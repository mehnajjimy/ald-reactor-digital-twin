"""The approved 5120-cell check, reusing the saved 2560-cell comparison."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np

from ald_twin.cycle_study import (case_parameters, channel_grid, decision, metrics,
                                 readout_times, recipe, study_options)
from ald_twin.cycles import CycleChemistry, CycleResult, periodic_cycle
from ald_twin.numerics import Integrated
from verify_phase45 import (DIFFUSION_RATIO_LIMIT, SPATIAL_LIMIT, TIGHT_READOUT_POINTS, TIME_LIMIT,
                            compare, file_hashes, model_errors, passes, source_hashes,
                            tighter_options, write_json)

ROOT = Path(__file__).resolve().parents[1]
CASE = "pe-20-da-1-pulse-0.75"
PRIOR = ROOT/"results/phase45-synthetic"

# ---- the approved case
CASE_PECLET = 20.
CASE_DAMKOHLER = 1.
CASE_PULSE_RATIO = .75
# the saved study stopped at 2560 cells. this check doubles it once.
FINE_CELLS = 5120
READOUT_POINTS = 101


# ---- reload a saved run

def load_result(stem):
    """read a recorded recurring cycle and verify its regenerated grid and ledger."""
    metadata = json.loads(Path(str(stem)+".json").read_text())
    if metadata["kind"] != "synthetic" or not metadata["periodic"]:
        raise ValueError("A saved synthetic recurring cycle is required")

    # rebuild the grid from its parameters and check it matches the saved arrays
    grid = channel_grid(metadata["grid"]["parameters"], metadata["grid"]["cells"])
    with np.load(str(stem)+".npz", allow_pickle=False) as raw:
        for name in ("z", "carrier_moles", "reactive_areas"):
            np.testing.assert_array_equal(raw[name], getattr(grid, name))
        integrated = Integrated(raw["t"], raw["scaled_state"], tuple(metadata["segments"]))
        result = CycleResult(integrated, grid, CycleChemistry(**metadata["chemistry"]),
                             metadata["fraction_scale"], raw["initial_state"], metadata["history"],
                             metadata["settings"], periodic=True)

    # the recomputed checks must match the saved ones exactly
    if result.checks() != metadata["checks"]:
        raise ValueError("Reloaded ledger/bounds differ from the saved result")
    return result


# ---- the grid check

def main():
    """run the 5120-cell grid and time checks for the approved case."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/phase45-grid-check")
    args = parser.parse_args()

    # the saved study must come from the same solver and configuration sources
    prior = json.loads((PRIOR/"study.json").read_text())
    if prior["source_hashes"] != source_hashes():
        raise ValueError("Previous solver/configuration hashes changed; reuse refused")

    # this script, its plan and the reused saved results are hashed before and after
    files =[Path(__file__), ROOT/"docs/phase45-grid-extension.md", PRIOR/"study.json", PRIOR/CASE/"case.json"]
    for label in ("grid-2560", "mixed"):
        for suffix in (".json", ".npz"):
            files.append(PRIOR/CASE/(label+suffix))

    # rebuild the approved case and check the saved runs used the same inputs
    config = prior["configuration"]
    parameters, chemistry = case_parameters(config, CASE_PECLET, CASE_DAMKOHLER)
    segments = recipe(parameters, CASE_PULSE_RATIO)
    options = study_options(segments)
    coarse = load_result(PRIOR/CASE/"grid-2560")
    mixed = load_result(PRIOR/CASE/"mixed")
    if parameters != coarse.grid.metadata["parameters"] or chemistry != coarse.chemistry:
        raise ValueError("Saved case does not match the approved inputs")
    if coarse.settings["recipe"] != [asdict(segment) for segment in segments]:
        raise ValueError("Saved recipe does not match the approved case")

    args.output.mkdir(parents=True, exist_ok=False)
    residence = float(mixed.grid.carrier_moles.sum()/mixed.grid.molar_flow)
    record = dict(case=CASE, kind="synthetic", status="RUNNING", physical_fit_ready=False,
                  peclet=CASE_PECLET, damkohler=CASE_DAMKOHLER, pulse_ratio=CASE_PULSE_RATIO,
                  residence_s=residence,
                  baseline_source_hashes=prior["source_hashes"], input_sha256=file_hashes(files),
                  wall_screen=json.loads((PRIOR/CASE/"case.json").read_text())["wall_screen"],
                  attempts=[], stage="spatial refinement", accepted_cells=None)
    write_json(args.output/"check.json", record)

    def solve(cells, label, solver, points):
        """find the recurring cycle on one grid, save it and log the attempt."""
        start = time.perf_counter()
        print(f"Running {label}: {cells} cells, {points} readout points per segment", flush=True)
        result = periodic_cycle(channel_grid(parameters, cells), chemistry, segments,
                                fraction_scale=config["fraction_scale"], options=solver,
                                output_times=readout_times(segments, points))
        result.save(args.output/label)
        record["attempts"].append(dict(label=label, cells=cells, seconds=time.perf_counter()-start,
                                       cycles=len(result.history), checks=result.checks()))
        write_json(args.output/"check.json", record)
        return result

    try:
        # one refinement step from the saved 2560-cell run
        fine = solve(FINE_CELLS, "grid-5120", options, READOUT_POINTS)
        spatial_change = compare(coarse, fine, segments, residence)
        record["spatial_change"] = spatial_change
        record["numerical_diffusion_ratio"] = fine.grid.metadata["numerical_diffusion_ratio"]
        write_json(args.output/"check.json", record)
        print(f"Spatial changes: {spatial_change}", flush=True)
        if (not passes(spatial_change, SPATIAL_LIMIT)
                or record["numerical_diffusion_ratio"] > DIFFUSION_RATIO_LIMIT):
            raise RuntimeError("Approved 5120-cell spatial check failed; no larger grid is authorized")
        del coarse

        # repeat both models with tighter solver settings and denser readout
        record["stage"] = "time and readout verification"
        write_json(args.output/"check.json", record)
        tighter = tighter_options(options)
        mixed_tight = solve(1, "mixed-time-repeat", tighter, TIGHT_READOUT_POINTS)
        time_mixed = compare(mixed, mixed_tight, segments, residence)
        del mixed_tight
        fine_tight = solve(FINE_CELLS, "spatial-time-repeat", tighter, TIGHT_READOUT_POINTS)
        time_spatial = compare(fine, fine_tight, segments, residence)
        del fine_tight
        record["time_changes"] = dict(mixed=time_mixed, spatial=time_spatial)
        write_json(args.output/"check.json", record)
        if not passes(time_mixed, TIME_LIMIT) or not passes(time_spatial, TIME_LIMIT):
            raise RuntimeError("Time/readout verification failed; the case is not accepted")

        # feasibility of each model, with its numerical change as the margin
        mixed_error, spatial_error = model_errors(time_mixed, spatial_change, time_spatial)
        errors = dict(mixed=mixed_error, spatial=spatial_error)
        record["models"] = {}
        for name, result in (("mixed", mixed), ("spatial", fine)):
            summary = metrics(result, segments)
            record["models"][name] = dict(case=CASE, metrics=summary, numerical_change=errors[name],
                                         feasible=decision(summary, errors[name]))

        # nothing the check relied on may have changed while it ran
        if record["input_sha256"] != file_hashes(files) or prior["source_hashes"] != source_hashes():
            raise RuntimeError("Input or solver hashes changed during the check")
        record.update(status="PASS", stage="complete", accepted_cells=FINE_CELLS)
    except Exception as error:
        record.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        write_json(args.output/"check.json", record)
        raise
    write_json(args.output/"check.json", record)
    print("PASS: approved case meets spatial, time/readout, periodic and ledger checks", flush=True)


if __name__ == "__main__":
    main()
