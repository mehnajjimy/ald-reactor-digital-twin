"""Preliminary synthetic 0D/1D comparison; no physical fit or full Phase 5 PASS."""

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ald_twin.configuration import ParameterRegistry
from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.reactor_1d import FluxBoundary, Reactor1D, TransportSegment, solve_1d
from ald_twin.surface import FiniteCapacity
from ald_twin.verification import restrict_uniform

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase5-preliminary"
COMPLETION = 0.9  # Illustrative synthetic threshold, declared in the plan.


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def run_pair(parameters, pulse, cells, options):
    """Match volume, reactive area, throughput, delivery and initial states."""
    reactor = Reactor1D(
        length=parameters["length"], area=parameters["area"],
        reactive_perimeter=parameters["reactive_perimeter"],
        velocity=parameters["velocity"], diffusivity=parameters["diffusivity"], cells=cells)
    surface = FiniteCapacity(parameters["capacity"], parameters["capture_velocity"])
    delivery = [(pulse, parameters["inlet_molar_flow"], "exposure"),
                (parameters["purge_duration"], 0., "purge")]
    common = dict(
        concentration_scale=parameters["concentration_scale"],
        initial_c=parameters["initial_c"], initial_theta=parameters["initial_theta"],
        options=options, provenance_id="phase5-preliminary-synthetic",
        output_times=np.linspace(0, pulse + parameters["purge_duration"], 201))
    lumped = solve_0d(
        WellMixedReactor(reactor.area * reactor.length,
                         reactor.reactive_perimeter * reactor.length,
                         reactor.velocity * reactor.area),
        surface, [FlowSegment(duration, flow, label) for duration, flow, label in delivery],
        **common)
    spatial = solve_1d(
        reactor, surface,
        [TransportSegment(duration, FluxBoundary(flow), label) for duration, flow, label in delivery],
        **common)
    return lumped, spatial


def resolution_difference(coarse, fine, concentration_scale):
    if not np.array_equal(coarse.t, fine.t):
        raise ValueError("Resolution comparisons require identical readout times")
    cells = len(coarse.z)
    return dict(
        coverage=float(np.max(np.abs(coarse.theta - restrict_uniform(fine.theta, cells)))),
        concentration=float(np.max(np.abs(coarse.c - restrict_uniform(fine.c, cells))) / concentration_scale),
        capture_fraction=float(np.max(np.abs(coarse.captured_moles - fine.captured_moles))
                               / fine.entered_moles[-1]))


def check_result(result, concentration_scale):
    inventory = result.metadata["initial_gas_moles"] + result.entered_moles
    positive = inventory > 0
    ledger = float(np.max(np.abs(result.ledger_error_moles[positive]) / inventory[positive]))
    zero_ledger = float(np.max(np.abs(result.ledger_error_moles[~positive]), initial=0.))
    bounds = max(0., -float(result.c.min()) / concentration_scale,
                 float(result.c.max()) / concentration_scale - 1,
                 -float(result.theta.min()), float(result.theta.max()) - 1)
    carryover = all(a["end_state"] == b["start_state"]
                    for a, b in zip(result.solver_status, result.solver_status[1:]))
    if ledger > 1e-8 or zero_ledger > 1e-10 or bounds > 1e-8 or not carryover:
        raise ValueError("Conservation, state bounds or switch-state check failed")
    return dict(relative_ledger=ledger, zero_inventory_residual=zero_ledger,
                bound_violation=bounds, exact_carryover=carryover)


def completion_decision(completion, resolution_change):
    if abs(completion - COMPLETION) <= resolution_change:
        return None
    return bool(completion >= COMPLETION)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "study.json").exists():
        raise SystemExit("A preliminary study is already recorded; review it before rerunning.")
    registry_path = ROOT / "config/synthetic/phase1-reacting-front.json"
    registry = ParameterRegistry.load(registry_path)
    if registry.kind != "synthetic":
        raise ValueError("This preliminary study requires explicitly synthetic inputs")
    parameters = registry.resolve(dict(
        length="m", area="m^2", reactive_perimeter="m", velocity="m s^-1",
        diffusivity="m^2 s^-1", capacity="mol m^-2", capture_velocity="m s^-1",
        concentration_scale="mol m^-3", initial_c="mol m^-3", initial_theta="1",
        pulse_duration="s", purge_duration="s", inlet_molar_flow="mol s^-1"))
    paths = [Path(__file__), registry_path, ROOT / "docs/phase5-preliminary-plan.md"]
    paths.extend(sorted((ROOT / "src/ald_twin").glob("*.py")))
    study = dict(
        status="RUNNING", role="Preliminary synthetic fixed-parameter comparison",
        full_phase5_passed=False, physical_fit_performed=False,
        source_registry_sha256=registry.sha256,
        file_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in paths},
        parameters=parameters, diffusivity_multipliers=[100, 10, 1],
        pulse_multipliers=[0.5, 1, 2], completion_threshold=COMPLETION, cases=[])
    write_json(OUT / "study.json", study)
    options = SolverOptions("Radau", 1e-9, 1e-11, 0.025)
    tight = replace(options, rtol=1e-10, atol=1e-12, max_step=0.0125)
    rows = []
    try:
        for diffusion_factor in study["diffusivity_multipliers"]:
            variant = parameters | {"diffusivity": parameters["diffusivity"] * diffusion_factor}
            for pulse_factor in study["pulse_multipliers"]:
                pulse = parameters["pulse_duration"] * pulse_factor
                name = f"diffusion-{diffusion_factor}-pulse-{pulse_factor}"
                record = dict(name=name, parameters=variant | {"pulse_duration": pulse}, grids=[])
                study["cases"].append(record)
                start = time.perf_counter()
                previous = None
                for cells in [200, 400, 800, 1600, 3200]:
                    print(f"{name}: {cells} cells", flush=True)
                    lumped, spatial = run_pair(variant, pulse, cells, options)
                    record["lumped_checks"] = check_result(lumped, parameters["concentration_scale"])
                    record["spatial_checks"] = check_result(spatial, parameters["concentration_scale"])
                    entry = dict(cells=cells, numerical_diffusion_ratio=spatial.metadata["numerical_diffusivity_ratio"])
                    if previous is not None:
                        entry["difference"] = resolution_difference(previous, spatial, parameters["concentration_scale"])
                    record["grids"].append(entry)
                    write_json(OUT / "study.json", study)
                    if (previous is not None and max(entry["difference"].values()) <= 1e-3
                            and entry["numerical_diffusion_ratio"] <= 0.05):
                        break
                    previous = spatial
                else:
                    raise ValueError(f"Grid refinement did not pass for {name}")
                refined_lumped, refined_spatial = run_pair(variant, pulse, cells, tight)
                record["tight_lumped_checks"] = check_result(refined_lumped, parameters["concentration_scale"])
                record["tight_spatial_checks"] = check_result(refined_spatial, parameters["concentration_scale"])
                record["time_difference_0d"] = resolution_difference(lumped, refined_lumped, parameters["concentration_scale"])
                record["time_difference_1d"] = resolution_difference(spatial, refined_spatial, parameters["concentration_scale"])
                if max(*record["time_difference_0d"].values(), *record["time_difference_1d"].values()) > 1e-5:
                    raise ValueError(f"Time refinement did not pass for {name}")
                pulse_index = int(np.flatnonzero(spatial.t == pulse)[0])
                completion_0d = float(lumped.theta[pulse_index, 0])
                minimum_1d = float(spatial.theta[pulse_index].min())
                decision_0d = completion_decision(completion_0d, record["time_difference_0d"]["coverage"])
                decision_1d = completion_decision(minimum_1d,
                    max(entry["difference"]["coverage"], record["time_difference_1d"]["coverage"]))
                row = dict(
                    name=name, pe=variant["velocity"] * variant["length"] / variant["diffusivity"],
                    pulse_residence_ratio=pulse * variant["velocity"] / variant["length"], cells=cells,
                    completion_0d=completion_0d, mean_completion_1d=float(spatial.theta[pulse_index].mean()),
                    minimum_completion_1d=minimum_1d, lumped_proxy_complete=decision_0d,
                    spatial_minimum_complete=decision_1d,
                    false_feasible_proxy=(decision_0d and not decision_1d)
                        if decision_0d is not None and decision_1d is not None else None)
                for label, result in [("0d", lumped), ("1d", spatial)]:
                    for metric, values in [("captured", result.captured_moles),
                                           ("escaped", result.escaped_moles), ("remaining_gas", result.gas_moles)]:
                        row[f"{metric}_fraction_{label}"] = float(values[-1] / result.entered_moles[-1])
                    result.save(OUT / f"{name}-{label}")
                record["summary"] = row
                record["elapsed_seconds"] = time.perf_counter() - start
                rows.append(row)
                write_json(OUT / "study.json", study)
        study["status"] = "PRELIMINARY_SYNTHETIC_CHECKS_PASSED"
    except Exception as error:
        study["status"] = "PRELIMINARY_STUDY_FAILED"
        study["error"] = str(error)
        write_json(OUT / "study.json", study)
        raise
    write_json(OUT / "study.json", study)
    with (OUT / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(dict(status=study["status"], cases=len(rows), full_phase5_passed=False)), flush=True)


if __name__ == "__main__":
    main()
