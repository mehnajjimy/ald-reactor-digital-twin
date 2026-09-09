"""Validate, run, verify and report one synthetic recipe with the shared engine."""

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
from .process_inputs import prepare_inputs
from .process_runner import digest
from .process_study import converged, write_json


def output_metrics(result, segments, film):
    summary = metrics(result, segments)
    active = result.grid.reactive_areas > 0
    turnover = result.turnover[active]
    mean = summary["mean_turnover"]
    summary["relative_turnover_spread"] = float(np.ptp(turnover)/mean) if mean > 0 else None
    summary["mean_gpc_angstrom"] = None
    summary["film_status"] = "Unavailable; no supported film mapping"
    if film is not None:
        gpc = periodic_gpc(result, film["density_kg_m3"])[active]
        summary["mean_gpc_angstrom"] = float(np.average(gpc, weights=result.grid.reactive_areas[active]))
        summary["film_status"] = "Conditional synthetic ZnO equivalent at 150 C"
    return summary


def numerical_changes(first, second, segments, residence, film):
    change = resolution_difference(first, second) | metric_difference(first, second, segments, residence)
    summaries = [output_metrics(result, segments, film) for result in (first, second)]
    growth_change = 0.
    # Turnover is the normalized growth for fixed Gamma in a single trial.
    # Comparing this avoids transferring the ZnO mass mapping to fictional A/B.
    for name in ("mean_turnover", "relative_turnover_spread"):
        a, b = (summary[name] for summary in summaries)
        if (a is None) != (b is None):
            growth_change = None
            break
        if a is not None:
            growth_change = max(growth_change, abs(a-b))
    return change | {"growth_metrics": growth_change}


def run_process(data, output, *, progress=None):
    """Use a new folder; never resume or replace a historical study.

    Progress callbacks receive completed-attempt records. The atomic run.json
    also exposes the current stage for a GUI without a second calculation path.
    """
    parameters, chemistry, segments, residence = prepare_inputs(data)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = output/"sources"
    sources.mkdir()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        (sources/source.name).write_bytes(source.read_bytes())
    write_json(output/"inputs.json", parameters)
    record = dict(schema_version=1, kind="synthetic", physical_fit_ready=False,
                  process_id=parameters["id"], process_name=parameters["name"],
                  status="RUNNING", origin="new calculation",
                  started_at=datetime.now(timezone.utc).isoformat(),
                  recipe=parameters["recipe"], residence_s=residence,
                  input_sha256=digest(output/"inputs.json"),
                  source_sha256={p.name: digest(p) for p in sources.iterdir()},
                  wall_screen=wall_screen(parameters, chemistry), attempts=[], models={},
                  numerical_acceptance=None, recipe_feasibility="unverified")
    options = study_options(segments)

    def save_progress(stage):
        record["stage"] = stage
        write_json(output/"run.json", record)
        if progress is not None:
            progress(deepcopy(record))

    def solve(cells, label, solver=options, seed=None):
        save_progress(f"Solving {label} ({cells} cells)")
        started = time.perf_counter()
        try:
            result = periodic_cycle(channel_grid(parameters, cells), chemistry, segments,
                fraction_scale=parameters["fraction_scale"], options=solver,
                tolerance=1e-7, max_cycles=200,
                output_times=readout_times(segments, 101 if solver == options else 201),
                state=None if seed is None else seed.integrated.y[:, -1],
                accounting_origin=None if seed is None else seed.initial_state)
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
        return numerical_changes(a, b, segments, residence, parameters["film"])

    try:
        save_progress("Inputs validated; starting numerical verification")
        mixed = solve(1, "mixed")
        previous = None
        spatial = None
        for cells in parameters["spatial_grids"]:
            current = solve(cells, f"grid-{cells}")
            if previous is not None:
                change = difference(previous, current)
                record["attempts"][-1]["change"] = change
                if converged(change, .001) and current.grid.metadata["numerical_diffusion_ratio"] <= .05:
                    record["spatial_change"] = change
                    spatial = current
                    break
            previous = current
        if spatial is None:
            record.update(status="UNVERIFIED", numerical_acceptance=False,
                          reason=f"Spatial ceiling {parameters['spatial_grids'][-1]} reached")
        else:
            tighter = replace(options, rtol=options.rtol/10, atol=options.atol/10,
                              max_step=options.max_step/2)
            record["time_changes"] = {}
            for name, result in (("mixed", mixed), ("spatial", spatial)):
                repeat = solve(len(result.grid.z), f"{name}-time-repeat", tighter, result)
                change = difference(result, repeat)
                record["time_changes"][name] = change
                if not converged(change, 1e-5):
                    record.update(status="UNVERIFIED", numerical_acceptance=False,
                                  reason=f"{name} time refinement failed")
                    break
                error = max(change[key] + (record["spatial_change"][key] if name == "spatial" else 0.)
                            for key in ("gas", "coverage", "events", "decision_metrics"))
                summary = output_metrics(result, segments, parameters["film"])
                record["models"][name] = dict(metrics=summary, numerical_change=error,
                                               feasible=decision(summary, error))
            else:
                feasible = record["models"]["spatial"]["feasible"]
                state = "unresolved" if feasible is None else "pass" if feasible else "fail"
                if not record["wall_screen"]["passes_declared_screen"]:
                    state = "outside-screen"
                record.update(status="PASS", numerical_acceptance=True, recipe_feasibility=state,
                    accepted_cells=len(spatial.grid.z),
                    numerical_diffusion_ratio=spatial.grid.metadata["numerical_diffusion_ratio"],
                    profile=dict(z_m=spatial.grid.z.tolist(), turnover=spatial.turnover.tolist()),
                    objectives=dict(cycle_time_s=sum(s.duration for s in segments),
                                    precursor_moles=sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments)))
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
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["stage"] = "Complete"
    write_json(output/"run.json", record)
    write_report(record, output/"report.md")
    paths = sorted(p for p in output.rglob("*") if p.is_file())
    write_json(output/"manifest.json", {str(p.relative_to(output)): digest(p) for p in paths})
    if progress is not None:
        progress(deepcopy(record))
    return record


def read_run(folder):
    """Check a completed saved run against its manifest without calculating."""
    folder = Path(folder).resolve()
    manifest = json.loads((folder/"manifest.json").read_text())
    record = json.loads((folder/"run.json").read_text())
    if not isinstance(manifest, dict) or not isinstance(record, dict):
        raise ValueError("Saved run and manifest must be JSON objects")
    if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("kind") != "synthetic"
            or record.get("physical_fit_ready") is not False):
        raise ValueError("Unsupported saved run scientific status")
    accepted = record.get("status") == "PASS"
    if (record.get("status") not in ("PASS", "UNVERIFIED")
            or record.get("numerical_acceptance") is not accepted
            or record.get("stage") != "Complete"
            or record.get("recipe_feasibility") not in (
                ("pass", "fail", "unresolved", "outside-screen") if accepted else ("unverified",))):
        raise ValueError("Saved run completion status is inconsistent")
    sources = record.get("source_sha256")
    attempts = record.get("attempts")
    if not isinstance(sources, dict) or not sources or not isinstance(attempts, list) or not attempts:
        raise ValueError("Saved run source or attempt records are missing")
    required = {"run.json", "inputs.json", "report.md"}
    for name in sources:
        if Path(name).name != name:
            raise ValueError("Invalid saved source name")
        required.add(f"sources/{name}")
    for attempt in attempts:
        label = attempt.get("label") if isinstance(attempt, dict) else None
        if not isinstance(label, str) or not label or Path(label).name != label:
            raise ValueError("Invalid saved attempt label")
        required.update({label+".json", label+".npz"})
    if not required <= manifest.keys():
        raise ValueError("Saved run manifest is incomplete")
    for name, expected in manifest.items():
        path = (folder/name).resolve()
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not path.is_relative_to(folder) or digest(path) != expected):
            raise ValueError(f"Saved run changed: {name}")
    if record.get("input_sha256") != manifest["inputs.json"] or any(
            expected != manifest[f"sources/{name}"] for name, expected in sources.items()):
        raise ValueError("Saved input or source hashes do not match the run")
    inputs = json.loads((folder/"inputs.json").read_text())
    if not isinstance(inputs, dict) or any(record.get(saved) != inputs.get(original)
            for saved, original in (("process_id", "id"), ("process_name", "name"), ("recipe", "recipe"))):
        raise ValueError("Saved run labels or recipe do not match its inputs")
    for attempt in attempts:
        metadata = json.loads((folder/(attempt["label"]+".json")).read_text())
        if (not isinstance(metadata, dict) or not isinstance(metadata.get("grid"), dict)
                or metadata["grid"].get("parameters") != inputs
                or metadata.get("chemistry") != inputs.get("chemistry")
                or metadata.get("fraction_scale") != inputs.get("fraction_scale")):
            raise ValueError(f"Saved attempt inputs do not match: {attempt['label']}")
    return record | {"origin": "saved output"}


def compare_runs(folders):
    rows = []
    for folder in folders:
        record = read_run(folder)
        rows.append({key: record.get(key) for key in
                     ("process_id", "process_name", "origin", "kind", "status", "recipe",
                      "numerical_acceptance", "recipe_feasibility", "models", "objectives")})
    return dict(kind="synthetic", physical_fit_ready=False, runs=rows,
                interpretation="Saved single-recipe comparisons; no optimization or uncertainty claim")


def report_rows(summary):
    """Human-readable labels and units; saved JSON retains unrounded SI values."""
    clearance_a, clearance_b = summary["purge_crossing_s"]
    consumed_a, consumed_b = summary["precursor_consumption_fraction"]
    escaped_a, escaped_b = summary["precursor_escape_fraction"]
    rows = [
        ("Minimum A completion (%)", 100*summary["minimum_a_completion"]),
        ("Mean A completion (%)", 100*summary["mean_a_completion"]),
        ("Maximum B remaining (%)", 100*summary["maximum_b_remaining"]),
        ("A purge residual (scaled fraction)", summary["purge_a_residual"]),
        ("B purge residual (scaled fraction)", summary["purge_b_residual"]),
        ("A purge clearance (s)", "Not cleared" if clearance_a is None else clearance_a),
        ("B purge clearance (s)", "Not cleared" if clearance_b is None else clearance_b),
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


def write_report(record, path):
    lines = [f"# {record['process_name']}", "", "Synthetic inputs; physical fitting remains blocked.", "",
             f"Numerical acceptance: {record['status']}",
             f"Recipe constraints and wall screen: {record['recipe_feasibility']}", "",
             "These are separate decisions. A numerical PASS does not validate a physical process.", ""]
    if record.get("reason"):
        lines += [record["reason"], ""]
    for name, model in record["models"].items():
        title = "0D well-mixed reactor" if name == "mixed" else "1D spatial reactor"
        lines += [f"## {title}", "", model["metrics"]["film_status"], "",
                  "| Output | Value |", "|---|---:|"]
        for label, value in report_rows(model["metrics"]):
            if value is None:
                display = "Unavailable"
            elif isinstance(value, str):
                display = value
            else:
                display = f"{value:.8g}"
            lines.append(f"| {label} | {display} |")
        lines.append("")
    lines += ["Not cleared means the purge ended above the clearance threshold. Zero means already clear.",
              "Unavailable means the output is undefined or has no supported mapping; it is not zero.",
              "Values in this report are rounded for reading. run.json retains the full reported precision.",
              "All attempts, input and source snapshots, and their hashes are retained alongside this report.", ""]
    Path(path).write_text("\n".join(lines))
