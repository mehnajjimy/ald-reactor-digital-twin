"""validate, run, verify and report one synthetic recipe with the shared engine."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from copy import deepcopy
import json
from pathlib import Path
import time

import numpy as np

from .cycle_study import (decision, metrics, metric_difference, readout_times,
                          resolution_difference, study_options, wall_screen)
from .cycle_transport import channel_grid
from .cycles import PeriodicFailure, periodic_cycle, periodic_gpc
from .process_inputs import PROCESS_KINDS, prepare_inputs
from .process_runner import digest
from .process_study import (converged, largest_change, numerical_error, recipe_objectives,
                            write_json)

# solver and acceptance settings for a single run

PERIODIC_TOLERANCE = 1e-7
MAX_CYCLES = 200
READOUT_POINTS = 101
REPEAT_READOUT_POINTS = 201
SPATIAL_CHANGE_LIMIT = .001
TIME_CHANGE_LIMIT = 1e-5
MAX_NUMERICAL_DIFFUSION_RATIO = .05

# saved-run checks and comparison fields

ACCEPTED_FEASIBILITY = ("pass", "fail", "unresolved", "outside-screen")
LABEL_FIELDS = (("process_id", "id"), ("process_name", "name"), ("recipe", "recipe"))
COMPARE_KEYS = ("process_id", "process_name", "origin", "kind", "status", "recipe",
                "numerical_acceptance", "recipe_feasibility", "models", "objectives")


# outputs of one solution

def output_metrics(result, segments, film):
    """cycle metrics plus turnover spread, and mean gpc when a film mapping exists."""

    summary = metrics(result, segments)
    active = result.grid.reactive_areas > 0
    turnover = result.turnover[active]
    mean = summary["mean_turnover"]
    if mean > 0:
        summary["relative_turnover_spread"] = float(np.ptp(turnover)/mean)
    else:
        summary["relative_turnover_spread"] = None
    summary["mean_gpc_angstrom"] = None
    summary["film_status"] = "Unavailable; no supported film mapping"
    if film is not None:
        gpc = periodic_gpc(result, film["density_kg_m3"])[active]
        summary["mean_gpc_angstrom"] = float(np.average(gpc, weights=result.grid.reactive_areas[active]))
        if result.grid.metadata["kind"] == "estimate":
            summary["film_status"] = "Estimated ZnO at 150 C from published values and assumptions"
        else:
            summary["film_status"] = "Conditional synthetic ZnO equivalent at 150 C"
    return summary


def numerical_changes(first, second, segments, residence, film):
    """all change measures between two solutions of the same run."""

    change = resolution_difference(first, second) | metric_difference(first, second, segments, residence)
    first_summary = output_metrics(first, segments, film)
    second_summary = output_metrics(second, segments, film)

    # compare turnover at fixed capacity, without applying the conditional
    # zno mass mapping to fictional a/b.

    growth_change = largest_change(first_summary, second_summary,
                                   ("mean_turnover", "relative_turnover_spread"))
    return change | {"growth_metrics": growth_change}


def _recipe_state(feasible, passes_screen):
    """pass, fail or unresolved from the spatial decision, unless outside the wall screen."""

    if feasible is None:
        state = "unresolved"
    elif feasible:
        state = "pass"
    else:
        state = "fail"
    if not passes_screen:
        state = "outside-screen"
    return state


# one full run

def run_process(data, output, *, progress=None):
    """use a new folder; never resume or replace a historical study.

    progress callbacks receive completed-attempt records. the atomic run.json
    also exposes the current stage for a gui without a second calculation path.
    """

    parameters, chemistry, segments, residence = prepare_inputs(data)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)

    # keep a copy of the code and inputs next to the results

    sources = output/"sources"
    sources.mkdir()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        (sources/source.name).write_bytes(source.read_bytes())
    write_json(output/"inputs.json", parameters)
    source_hashes = {}
    for path in sources.iterdir():
        source_hashes[path.name] = digest(path)
    record = dict(schema_version=1, kind=parameters["kind"], physical_fit_ready=False,
                  process_id=parameters["id"], process_name=parameters["name"],
                  status="RUNNING", origin="new calculation",
                  started_at=datetime.now(timezone.utc).isoformat(),
                  recipe=parameters["recipe"], residence_s=residence,
                  input_sha256=digest(output/"inputs.json"),
                  source_sha256=source_hashes,
                  wall_screen=wall_screen(parameters, chemistry), attempts=[], models={},
                  numerical_acceptance=None, recipe_feasibility="unverified")
    options = study_options(segments)

    def save_progress(stage):
        """save run.json with the current stage and tell the caller."""

        record["stage"] = stage
        write_json(output/"run.json", record)
        if progress is not None:
            progress(deepcopy(record))

    def solve(cells, label, solver=options, seed=None):
        """solve and save one attempt, recording it even when it does not recur."""

        save_progress(f"Solving {label} ({cells} cells)")
        started = time.perf_counter()
        try:
            grid = channel_grid(parameters, cells)
            if solver == options:
                points = READOUT_POINTS
            else:
                points = REPEAT_READOUT_POINTS
            output_times = readout_times(segments, points)

            # a time repeat starts from the end state of the solution it checks

            state = None
            accounting_origin = None
            if seed is not None:
                state = seed.integrated.y[:, -1]
                accounting_origin = seed.initial_state
            result = periodic_cycle(grid, chemistry, segments,
                                    fraction_scale=parameters["fraction_scale"], options=solver,
                                    tolerance=PERIODIC_TOLERANCE, max_cycles=MAX_CYCLES,
                                    output_times=output_times,
                                    state=state,
                                    accounting_origin=accounting_origin)
        except PeriodicFailure as error:
            error.result.save(output/label)
            record["attempts"].append(dict(label=label, cells=cells, status="UNVERIFIED",
                                           reason=str(error), checks=error.result.checks()))
            raise
        result.save(output/label)
        record["attempts"].append(dict(label=label, cells=cells, status="PASS",
                                       seconds=time.perf_counter()-started, cycles=len(result.history),
                                       checks=result.checks(), solver=asdict(solver)))
        save_progress(f"Completed {label}")
        return result

    def difference(a, b):
        """change measures between two solutions of this run."""

        return numerical_changes(a, b, segments, residence, parameters["film"])

    try:
        save_progress("Inputs validated; starting numerical verification")
        mixed = solve(1, "mixed")

        # refine the spatial grid until two grids agree

        previous = None
        spatial = None
        for cells in parameters["spatial_grids"]:
            current = solve(cells, f"grid-{cells}")
            if previous is not None:
                change = difference(previous, current)
                record["attempts"][-1]["change"] = change
                if (converged(change, SPATIAL_CHANGE_LIMIT)
                        and current.grid.metadata["numerical_diffusion_ratio"] <= MAX_NUMERICAL_DIFFUSION_RATIO):
                    record["spatial_change"] = change
                    spatial = current
                    break
            previous = current
        if spatial is None:
            record.update(status="UNVERIFIED", numerical_acceptance=False,
                          reason=f"Spatial ceiling {parameters['spatial_grids'][-1]} reached")
        else:

            # repeat each accepted solution with tighter time integration

            tighter = replace(options, rtol=options.rtol/10, atol=options.atol/10,
                              max_step=options.max_step/2)
            record["time_changes"] = {}
            time_converged = True
            for name, result in (("mixed", mixed), ("spatial", spatial)):
                repeat = solve(len(result.grid.z), f"{name}-time-repeat", tighter, result)
                change = difference(result, repeat)
                record["time_changes"][name] = change
                if not converged(change, TIME_CHANGE_LIMIT):
                    record.update(status="UNVERIFIED", numerical_acceptance=False,
                                  reason=f"{name} time refinement failed")
                    time_converged = False
                    break
                matching_spatial_change = None
                if name == "spatial":
                    matching_spatial_change = record["spatial_change"]
                error = numerical_error(change, matching_spatial_change)
                summary = output_metrics(result, segments, parameters["film"])
                record["models"][name] = dict(metrics=summary, numerical_change=error,
                                              feasible=decision(summary, error))
            if time_converged:
                feasibility_state = _recipe_state(record["models"]["spatial"]["feasible"],
                                                  record["wall_screen"]["passes_declared_screen"])
                record.update(status="PASS", numerical_acceptance=True, recipe_feasibility=feasibility_state,
                              accepted_cells=len(spatial.grid.z),
                              numerical_diffusion_ratio=spatial.grid.metadata["numerical_diffusion_ratio"],
                              profile=dict(z_m=spatial.grid.z.tolist(), turnover=spatial.turnover.tolist()),
                              objectives=recipe_objectives(segments))
    except PeriodicFailure as error:
        record.update(status="UNVERIFIED", numerical_acceptance=False, reason=str(error))
    except KeyboardInterrupt:
        record.update(status="INTERRUPTED", numerical_acceptance=False,
                      reason="Calculation interrupted; completed attempts retained")
        save_progress("Interrupted")
        raise
    except Exception as error:
        record.update(status="ERROR", numerical_acceptance=False, reason=f"{type(error).__name__}: {error}")
        save_progress("Stopped after an error; records retained")
        raise

    # finish: run.json, report.md and a manifest of every file

    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["stage"] = "Complete"
    write_json(output/"run.json", record)
    write_report(record, output/"report.md")
    paths = sorted(p for p in output.rglob("*") if p.is_file())
    manifest = {}
    for path in paths:
        manifest[str(path.relative_to(output))] = digest(path)
    write_json(output/"manifest.json", manifest)
    if progress is not None:
        progress(deepcopy(record))
    return record


# reading saved runs

def _check_run_status(record):
    """raise unless the saved record is a complete synthetic or estimate run with consistent status."""

    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("kind") not in PROCESS_KINDS
            or record.get("physical_fit_ready") is not False):
        raise ValueError("Unsupported saved run scientific status")
    accepted = record.get("status") == "PASS"
    if accepted:
        allowed_feasibility = ACCEPTED_FEASIBILITY
    else:
        allowed_feasibility = ("unverified",)
    if (record.get("status") not in ("PASS", "UNVERIFIED")
            or record.get("numerical_acceptance") is not accepted
            or record.get("stage") != "Complete"
            or record.get("recipe_feasibility") not in allowed_feasibility):
        raise ValueError("Saved run completion status is inconsistent")


def _required_files(sources, attempts):
    """every file a complete run must list in its manifest."""

    required = {"run.json", "inputs.json", "report.md"}
    for name in sources:
        if Path(name).name != name:
            raise ValueError("Invalid saved source name")
        required.add(f"sources/{name}")
    for attempt in attempts:
        label = None
        if isinstance(attempt, dict):
            label = attempt.get("label")
        if not isinstance(label, str) or not label or Path(label).name != label:
            raise ValueError("Invalid saved attempt label")
        required.update({label+".json", label+".npz"})
    return required


def _check_manifest_files(folder, manifest):
    """raise when a manifest path leaves the folder or a file's hash changed."""

    for name, expected in manifest.items():
        path = (folder/name).resolve()
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not path.is_relative_to(folder) or digest(path) != expected):
            raise ValueError(f"Saved run changed: {name}")


def read_run(folder):
    """check a completed saved run against its manifest without calculating."""

    folder = Path(folder).resolve()
    manifest = json.loads((folder/"manifest.json").read_text())
    record = json.loads((folder/"run.json").read_text())
    if not isinstance(manifest, dict) or not isinstance(record, dict):
        raise ValueError("Saved run and manifest must be JSON objects")
    _check_run_status(record)
    sources = record.get("source_sha256")
    attempts = record.get("attempts")
    if not isinstance(sources, dict) or not sources or not isinstance(attempts, list) or not attempts:
        raise ValueError("Saved run source or attempt records are missing")
    required = _required_files(sources, attempts)
    if not required <= manifest.keys():
        raise ValueError("Saved run manifest is incomplete")
    _check_manifest_files(folder, manifest)

    # the run record must point at the same inputs and sources as the manifest

    hashes_match = record.get("input_sha256") == manifest["inputs.json"]
    if hashes_match:
        for name, expected in sources.items():
            if expected != manifest[f"sources/{name}"]:
                hashes_match = False
                break
    if not hashes_match:
        raise ValueError("Saved input or source hashes do not match the run")
    inputs = json.loads((folder/"inputs.json").read_text())
    if not isinstance(inputs, dict):
        raise ValueError("Saved run labels or recipe do not match its inputs")
    for saved, original in LABEL_FIELDS:
        if record.get(saved) != inputs.get(original):
            raise ValueError("Saved run labels or recipe do not match its inputs")

    # every saved attempt must have been solved from these inputs

    for attempt in attempts:
        metadata = json.loads((folder/(attempt["label"]+".json")).read_text())
        if (not isinstance(metadata, dict) or not isinstance(metadata.get("grid"), dict)
                or metadata["grid"].get("parameters") != inputs
                or metadata.get("chemistry") != inputs.get("chemistry")
                or metadata.get("fraction_scale") != inputs.get("fraction_scale")):
            raise ValueError(f"Saved attempt inputs do not match: {attempt['label']}")
    return record | {"origin": "saved output"}


def compare_runs(folders):
    """side-by-side summary of several checked saved runs."""

    rows = []
    kinds = set()
    for folder in folders:
        record = read_run(folder)
        row = {}
        for key in COMPARE_KEYS:
            row[key] = record.get(key)
        rows.append(row)
        kinds.add(record["kind"])

    # the comparison is only as real as its least real run
    if "synthetic" in kinds:
        kind = "synthetic"
    else:
        kind = "estimate"
    return dict(kind=kind, physical_fit_ready=False, runs=rows,
                interpretation="Saved single-recipe comparisons; no optimization or uncertainty claim")


# report.md

def report_rows(summary):
    """human-readable labels and units; saved json retains unrounded si values."""

    clearance_a, clearance_b = summary["purge_crossing_s"]
    consumed_a, consumed_b = summary["precursor_consumption_fraction"]
    escaped_a, escaped_b = summary["precursor_escape_fraction"]
    if clearance_a is None:
        clearance_a = "Not cleared"
    if clearance_b is None:
        clearance_b = "Not cleared"
    rows = [
        ("Minimum A completion (%)", 100*summary["minimum_a_completion"]),
        ("Mean A completion (%)", 100*summary["mean_a_completion"]),
        ("Maximum B remaining (%)", 100*summary["maximum_b_remaining"]),
        ("A purge residual (scaled fraction)", summary["purge_a_residual"]),
        ("B purge residual (scaled fraction)", summary["purge_b_residual"]),
        ("A purge clearance (s)", clearance_a),
        ("B purge clearance (s)", clearance_b),
        ("Minimum surface turnover per cycle", summary["minimum_turnover"]),
        ("Mean surface turnover per cycle", summary["mean_turnover"]),
        ("Relative turnover spread (fraction)", summary["relative_turnover_spread"]),
        ("A consumed / delivered (fraction)", consumed_a),
        ("B consumed / delivered (fraction)", consumed_b),
        ("A escaped / delivered (fraction)", escaped_a),
        ("B escaped / delivered (fraction)", escaped_b),
        ("Cycle time (s)", summary["cycle_time_s"]),
        ("Mean equivalent ZnO growth (Å/cycle)", summary["mean_gpc_angstrom"]),
    ]
    return rows


def _display(value):
    """table text for a report value: Unavailable, the text itself, or 8 significant digits."""

    if value is None:
        return "Unavailable"
    if isinstance(value, str):
        return value
    return f"{value:.8g}"


def write_report(record, path):
    """write a short markdown report of one run's decisions and outputs."""

    if record["kind"] == "estimate":
        basis = "Estimated inputs from published values and labelled assumptions; not fitted or validated."
    else:
        basis = "Synthetic inputs; physical fitting remains blocked."
    lines = [f"# {record['process_name']}", "", basis, "",
             f"Numerical acceptance: {record['status']}",
             f"Recipe constraints and wall screen: {record['recipe_feasibility']}", "",
             "These are separate decisions. A numerical PASS does not validate a physical process.", ""]
    if record.get("reason"):
        lines += [record["reason"], ""]
    for name, model in record["models"].items():
        if name == "mixed":
            title = "0D well-mixed reactor"
        else:
            title = "1D spatial reactor"
        lines += [f"## {title}", "", model["metrics"]["film_status"], "",
                  "| Output | Value |", "|---|---:|"]
        for label, value in report_rows(model["metrics"]):
            lines.append(f"| {label} | {_display(value)} |")
        lines.append("")
    lines += ["Not cleared means the purge ended above the clearance threshold. Zero means already clear.",
              "Unavailable means the output is undefined or has no supported mapping; it is not zero.",
              "Values in this report are rounded for reading. run.json retains the full reported precision.",
              "All attempts, input and source snapshots, and their hashes are retained alongside this report.", ""]
    Path(path).write_text("\n".join(lines))
