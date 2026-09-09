"""The approved 5120-cell check, reusing the saved 2560-cell comparison."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ald_twin.cycle_study import (case_parameters, channel_grid, decision, metrics,
                                 readout_times, recipe, study_options)
from ald_twin.cycles import CycleChemistry, CycleResult, periodic_cycle
from ald_twin.numerics import Integrated
from verify_phase45 import compare, passes, source_hashes, write_json

ROOT = Path(__file__).resolve().parents[1]
CASE = "pe-20-da-1-pulse-0.75"
PRIOR = ROOT/"results/phase45-synthetic"


def load_result(stem):
    """Read a recorded recurring cycle and verify its regenerated grid and ledger."""
    metadata = json.loads(Path(str(stem)+".json").read_text())
    if metadata["kind"] != "synthetic" or not metadata["periodic"]:
        raise ValueError("A saved synthetic recurring cycle is required")
    grid = channel_grid(metadata["grid"]["parameters"], metadata["grid"]["cells"])
    with np.load(str(stem)+".npz", allow_pickle=False) as raw:
        for name in ("z", "carrier_moles", "reactive_areas"):
            np.testing.assert_array_equal(raw[name], getattr(grid, name))
        integrated = Integrated(raw["t"], raw["scaled_state"], tuple(metadata["segments"]))
        result = CycleResult(integrated, grid, CycleChemistry(**metadata["chemistry"]),
                             metadata["fraction_scale"], raw["initial_state"], metadata["history"],
                             metadata["settings"], periodic=True)
    if result.checks() != metadata["checks"]:
        raise ValueError("Reloaded ledger/bounds differ from the saved result")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/phase45-grid-check")
    args = parser.parse_args()
    prior = json.loads((PRIOR/"study.json").read_text())
    if prior["source_hashes"] != source_hashes():
        raise ValueError("Previous solver/configuration hashes changed; reuse refused")
    files = [Path(__file__), ROOT/"docs/phase45-grid-extension.md", PRIOR/"study.json", PRIOR/CASE/"case.json"]
    files += [PRIOR/CASE/(label+suffix) for label in ("grid-2560", "mixed") for suffix in (".json", ".npz")]
    hashes = lambda: {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    config = prior["configuration"]
    parameters, chemistry = case_parameters(config, 20., 1.)
    segments = recipe(parameters, .75)
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
                  peclet=20., damkohler=1., pulse_ratio=.75, residence_s=residence,
                  baseline_source_hashes=prior["source_hashes"], input_sha256=hashes(),
                  wall_screen=json.loads((PRIOR/CASE/"case.json").read_text())["wall_screen"],
                  attempts=[], stage="spatial refinement", accepted_cells=None)
    write_json(args.output/"check.json", record)

    def solve(cells, label, solver, points):
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
        fine = solve(5120, "grid-5120", options, 101)
        spatial_change = compare(coarse, fine, segments, residence)
        record["spatial_change"] = spatial_change
        record["numerical_diffusion_ratio"] = fine.grid.metadata["numerical_diffusion_ratio"]
        write_json(args.output/"check.json", record)
        print(f"Spatial changes: {spatial_change}", flush=True)
        if not passes(spatial_change, .001) or record["numerical_diffusion_ratio"] > .05:
            raise RuntimeError("Approved 5120-cell spatial check failed; no larger grid is authorized")
        del coarse
        record["stage"] = "time and readout verification"
        write_json(args.output/"check.json", record)
        tighter = replace(options, rtol=options.rtol/10, atol=options.atol/10, max_step=options.max_step/2)
        mixed_tight = solve(1, "mixed-time-repeat", tighter, 201)
        time_mixed = compare(mixed, mixed_tight, segments, residence)
        del mixed_tight
        fine_tight = solve(5120, "spatial-time-repeat", tighter, 201)
        time_spatial = compare(fine, fine_tight, segments, residence)
        del fine_tight
        record["time_changes"] = dict(mixed=time_mixed, spatial=time_spatial)
        write_json(args.output/"check.json", record)
        if not passes(time_mixed, 1e-5) or not passes(time_spatial, 1e-5):
            raise RuntimeError("Time/readout verification failed; the case is not accepted")
        errors = dict(mixed=max(time_mixed[key] for key in ("gas", "coverage", "decision_metrics")),
                      spatial=max(spatial_change[key]+time_spatial[key]
                                  for key in ("gas", "coverage", "decision_metrics")))
        record["models"] = {}
        for name, result in (("mixed", mixed), ("spatial", fine)):
            summary = metrics(result, segments)
            record["models"][name] = dict(case=CASE, metrics=summary, numerical_change=errors[name],
                                         feasible=decision(summary, errors[name]))
        if record["input_sha256"] != hashes() or prior["source_hashes"] != source_hashes():
            raise RuntimeError("Input or solver hashes changed during the check")
        record.update(status="PASS", stage="complete", accepted_cells=5120)
    except Exception as error:
        record.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        write_json(args.output/"check.json", record)
        raise
    write_json(args.output/"check.json", record)
    print("PASS: approved case meets spatial, time/readout, periodic and ledger checks", flush=True)


if __name__ == "__main__":
    main()
