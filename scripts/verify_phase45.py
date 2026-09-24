"""Bounded full-cycle synthetic comparison; stops at the frozen numerical ceiling."""

import argparse
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import time

from ald_twin.cycle_study import (candidate_choice, case_parameters, channel_grid,
                                 decision, metric_difference, metrics, readout_times,
                                 recipe, resolution_difference, study_options, wall_screen)
from ald_twin.cycles import periodic_cycle
from ald_twin.results import json_native

ROOT = Path(__file__).resolve().parents[1]

# ---- study settings
# spatial grids tried in order until one refinement passes
GRIDS = (40, 80, 160, 320, 640, 1280, 2560)
# largest field change accepted between two grids
SPATIAL_LIMIT = .001
# largest upwind numerical diffusion ratio accepted on the chosen grid
DIFFUSION_RATIO_LIMIT = .05
# largest field change accepted when tightening the solver or changing method
TIME_LIMIT = 1e-5
# readout points per segment for the tightened time repeat
TIGHT_READOUT_POINTS = 201
# fields and metrics whose numerical change counts toward the decision margin
ERROR_KEYS = ("gas", "coverage", "decision_metrics")
# the (Pe, Da, pulse ratio) cases that also get a BDF comparison
BDF_CASES = ((.2, 1., .75), (2., 3., 1.5), (20., 10., 3.))


# ---- helpers shared with check_phase45_grid

def write_json(path, data):
    """write data as indented json with a trailing newline."""
    path.write_text(json.dumps(json_native(data), indent=2, allow_nan=False) + "\n")


def file_hashes(paths):
    """sha256 of each file, keyed by its path relative to the repo root."""
    hashes = {}
    for path in paths:
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def source_hashes():
    """hashes of this script, the study config, the plan and the solver sources."""
    paths = [Path(__file__), ROOT/"config/synthetic/phase45.json", ROOT/"docs/phase45-plan.md"]
    for name in ("cycles.py", "cycle_transport.py", "cycle_study.py", "numerics.py",
                 "results.py", "units.py", "channel_flow.py"):
        paths.append(ROOT/"src/ald_twin"/name)
    return file_hashes(paths)


def compare(first, second, segments, residence):
    """field differences and metric differences between two runs, in one dict."""
    return resolution_difference(first, second) | metric_difference(first, second, segments, residence)


def passes(change, field_limit, crossing_limit=.001):
    """true when every field change and the purge time change are within limits."""
    worst_field = max(change[name] for name in ("gas", "coverage", "events", "decision_metrics"))
    return (worst_field <= field_limit
            and change["purge_time_over_residence"] is not None
            and change["purge_time_over_residence"] <= crossing_limit)


def tighter_options(options):
    """the same solver with ten times tighter tolerances and half the largest step."""
    return replace(options, rtol=options.rtol/10, atol=options.atol/10, max_step=options.max_step/2)


def model_errors(time_mixed, spatial_change, time_spatial):
    """numerical change of the mixed and spatial models used as decision margins.

    the mixed model only has the time change. the spatial model adds the grid change.
    """
    mixed_error = max(time_mixed[key] for key in ERROR_KEYS)
    spatial_error = max(spatial_change[key] + time_spatial[key] for key in ERROR_KEYS)
    return mixed_error, spatial_error


# ---- one case

def run_case(config, pe, da, pulse, folder, bdf=False):
    """run one Pe, Da, pulse case through grid, time and method checks."""
    parameters, chemistry = case_parameters(config, pe, da)
    segments = recipe(parameters, pulse)
    options = study_options(segments)
    times = readout_times(segments)
    mixed_grid = channel_grid(parameters, 1)
    residence = float(mixed_grid.carrier_moles.sum()/mixed_grid.molar_flow)
    name = folder.name
    folder.mkdir()
    record = dict(case=name, kind="synthetic", status="RUNNING", peclet=pe,
                  damkohler=da, pulse_ratio=pulse, residence_s=residence,
                  wall_screen=wall_screen(parameters, chemistry), attempts=[])
    write_json(folder/"case.json", record)

    def solve(cells, label, solver=options, readouts=times):
        """find the recurring cycle on one grid, save it and log the attempt."""
        start = time.perf_counter()
        result = periodic_cycle(channel_grid(parameters, cells), chemistry, segments,
                                fraction_scale=parameters["fraction_scale"],
                                options=solver, output_times=readouts)
        result.save(folder/label)
        attempt = dict(label=label, cells=cells, seconds=time.perf_counter()-start,
                       cycles=len(result.history), checks=result.checks())
        record["attempts"].append(attempt)
        write_json(folder/"case.json", record)
        return result

    try:
        # refine the spatial grid until two neighbouring grids agree
        mixed = solve(1, "mixed")
        previous = None
        spatial_change = None
        refined = False
        for cells in GRIDS:
            spatial = solve(cells, f"grid-{cells}")
            if previous is not None:
                spatial_change = compare(previous, spatial, segments, residence)
                record["attempts"][-1]["refinement_change"] = spatial_change
                write_json(folder/"case.json", record)
                ratio = spatial.grid.metadata["numerical_diffusion_ratio"]
                if passes(spatial_change, SPATIAL_LIMIT) and ratio <= DIFFUSION_RATIO_LIMIT:
                    refined = True
                    break
            previous = spatial
        if not refined:
            raise RuntimeError(f"{name}: spatial refinement failed at {GRIDS[-1]} cells")

        # repeat both models with tighter solver settings and denser readout
        tighter = tighter_options(options)
        mixed_tight = solve(1, "mixed-time-repeat", tighter, readout_times(segments, TIGHT_READOUT_POINTS))
        time_mixed = compare(mixed, mixed_tight, segments, residence)
        del mixed_tight
        spatial_tight = solve(cells, "spatial-time-repeat", tighter, readout_times(segments, TIGHT_READOUT_POINTS))
        time_spatial = compare(spatial, spatial_tight, segments, residence)
        del spatial_tight
        if not passes(time_mixed, TIME_LIMIT) or not passes(time_spatial, TIME_LIMIT):
            record["time_changes"] = dict(mixed=time_mixed, spatial=time_spatial)
            raise RuntimeError(f"{name}: time/readout refinement failed")

        # some cases also check the spatial result against BDF
        method_change = None
        if bdf:
            other = solve(cells, "spatial-bdf", replace(tighter, method="BDF"))
            method_change = compare(spatial, other, segments, residence)
            del other
            if not passes(method_change, TIME_LIMIT):
                record["method_change"] = method_change
                raise RuntimeError(f"{name}: BDF comparison failed")

        # feasibility of each model, with its numerical change as the margin
        mixed_error, spatial_error = model_errors(time_mixed, spatial_change, time_spatial)
        summaries = {}
        for model, result, error in (("mixed", mixed, mixed_error), ("spatial", spatial, spatial_error)):
            summary = metrics(result, segments)
            summaries[model] = dict(case=name, metrics=summary, numerical_change=error,
                                    feasible=decision(summary, error))
        record.update(status="PASS", accepted_cells=cells,
                      numerical_diffusion_ratio=spatial.grid.metadata["numerical_diffusion_ratio"],
                      spatial_change=spatial_change, time_changes=dict(mixed=time_mixed, spatial=time_spatial),
                      method_change=method_change, models=summaries)
    except Exception as error:
        record.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        write_json(folder/"case.json", record)
        raise
    write_json(folder/"case.json", record)
    return record


# ---- recipe choice per regime

def _case_row(group, case):
    """the first row in group for the named case."""
    return next(row for row in group if row["case"] == case)


def choices(records):
    """compare the mixed and spatial recipe choices for every Pe, Da regime."""
    comparisons = []
    regimes = sorted({(row["peclet"], row["damkohler"]) for row in records})
    for pe, da in regimes:
        group = []
        for row in records:
            if row["peclet"] == pe and row["damkohler"] == da:
                group.append(row)
        mixed = candidate_choice([row["models"]["mixed"] for row in group])
        spatial = candidate_choice([row["models"]["spatial"] for row in group])
        comparison = dict(peclet=pe, damkohler=da, mixed_choice=mixed, spatial_choice=spatial,
                          mixed_choice_spatial_feasibility=None, false_feasible=None,
                          excess_time_fraction=None)

        # check the mixed model's pick against the spatial model
        if mixed["case"] is not None:
            selected = _case_row(group, mixed["case"])
            feasible = selected["models"]["spatial"]["feasible"]
            comparison["mixed_choice_spatial_feasibility"] = feasible
            if feasible is None:
                comparison["false_feasible"] = None
            else:
                comparison["false_feasible"] = not feasible
            # how much longer the mixed pick is than the spatial pick
            if feasible and spatial["case"] is not None:
                best = _case_row(group, spatial["case"])
                comparison["excess_time_fraction"] = (selected["models"]["spatial"]["metrics"]["cycle_time_s"]
                    / best["models"]["spatial"]["metrics"]["cycle_time_s"] - 1)
        comparisons.append(comparison)
    return comparisons


# ---- full study

def main():
    """run every configured case and write study.json with the recipe choices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/phase45-synthetic")
    args = parser.parse_args()
    # keep every attempted study. reuse requires a deliberate, separately checked run.
    args.output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT/"config/synthetic/phase45.json").read_text())
    study = dict(kind="synthetic", status="RUNNING", physical_fit_ready=False,
                 source_hashes=source_hashes(), configuration=config, cases=[])
    write_json(args.output/"study.json", study)
    try:
        combinations = itertools.product(config["peclet_numbers"], config["damkohler_numbers"],
                                         config["pulse_residence_ratios"])
        for pe, da, pulse in combinations:
            name = f"pe-{pe:g}-da-{da:g}-pulse-{pulse:g}"
            bdf = (pe, da, pulse) in BDF_CASES
            print(f"Running {name}", flush=True)
            record = run_case(config, pe, da, pulse, args.output/name, bdf)
            study["cases"].append(record)
            write_json(args.output/"study.json", study)
            print(f"PASS {name}: {record['accepted_cells']} cells", flush=True)
        if study["source_hashes"] != source_hashes():
            raise RuntimeError("Study input/solver hashes changed during the run")
        study.update(status="PASS", choices=choices(study["cases"]))
    except Exception as error:
        study.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        write_json(args.output/"study.json", study)
        raise
    write_json(args.output/"study.json", study)
    print(f"PASS: {len(study['cases'])} synthetic cases", flush=True)


if __name__ == "__main__":
    main()
