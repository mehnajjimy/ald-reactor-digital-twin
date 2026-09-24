"""preliminary synthetic 0D/1D comparison, with no physical fit and no full Phase 5 PASS."""

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

# folders and the completion threshold
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase5-preliminary"
COMPLETION = 0.9  # illustrative synthetic threshold, declared in the plan

# case grid: multipliers on the reference diffusivity and pulse length
DIFFUSIVITY_MULTIPLIERS = [100, 10, 1]
PULSE_MULTIPLIERS = [0.5, 1, 2]

# spatial grids tried in order until two in a row agree and numerical diffusion is small
GRID_CELLS = [200, 400, 800, 1600, 3200]
OUTPUT_SAMPLES = 201

# acceptance limits
LEDGER_LIMIT = 1e-8                 # relative mole ledger
ZERO_LEDGER_LIMIT = 1e-10           # absolute ledger while no gas is present
BOUND_LIMIT = 1e-8                  # gas and coverage outside their bounds
GRID_LIMIT = 1e-3                   # change between successive grids
NUMERICAL_DIFFUSION_LIMIT = 0.05    # numerical / physical diffusivity
TIME_LIMIT = 1e-5                   # change from tightening the solver


def write_json(path, data):
    """write data as indented json with a trailing newline."""
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


# ---------------------------------------------------------------- matched 0D and 1D runs

def run_pair(parameters, pulse, cells, options):
    """solve the 0D and 1D models with matched geometry, throughput, delivery and initial states."""
    reactor = Reactor1D(
        length=parameters["length"], area=parameters["area"],
        reactive_perimeter=parameters["reactive_perimeter"],
        velocity=parameters["velocity"], diffusivity=parameters["diffusivity"], cells=cells)
    surface = FiniteCapacity(parameters["capacity"], parameters["capture_velocity"])

    # one exposure then one purge, as (duration, molar flow, label)
    delivery = [(pulse, parameters["inlet_molar_flow"], "exposure"),
                (parameters["purge_duration"], 0., "purge")]
    common = dict(
        concentration_scale=parameters["concentration_scale"],
        initial_c=parameters["initial_c"], initial_theta=parameters["initial_theta"],
        options=options, provenance_id="phase5-preliminary-synthetic",
        output_times=np.linspace(0, pulse + parameters["purge_duration"], OUTPUT_SAMPLES))

    # the well-mixed box has the channel's volume, reactive area and throughput
    volume = reactor.area * reactor.length
    reactive_area = reactor.reactive_perimeter * reactor.length
    throughput = reactor.velocity * reactor.area
    box = WellMixedReactor(volume, reactive_area, throughput)
    flow_segments = []
    for duration, flow, label in delivery:
        flow_segments.append(FlowSegment(duration, flow, label))
    lumped = solve_0d(box, surface, flow_segments, **common)

    # the channel gets the same molar flow through its inlet face
    transport_segments = []
    for duration, flow, label in delivery:
        transport_segments.append(TransportSegment(duration, FluxBoundary(flow), label))
    spatial = solve_1d(reactor, surface, transport_segments, **common)
    return lumped, spatial


def resolution_difference(coarse, fine, concentration_scale):
    """largest coverage, gas and capture change between two runs on the same readout times."""
    if not np.array_equal(coarse.t, fine.t):
        raise ValueError("Resolution comparisons require identical readout times")
    cells = len(coarse.z)
    coverage = float(np.max(np.abs(coarse.theta - restrict_uniform(fine.theta, cells))))
    concentration = float(np.max(np.abs(coarse.c - restrict_uniform(fine.c, cells))) / concentration_scale)
    capture_fraction = float(np.max(np.abs(coarse.captured_moles - fine.captured_moles))
                             / fine.entered_moles[-1])
    return dict(coverage=coverage, concentration=concentration, capture_fraction=capture_fraction)


def exact_carryover(solver_status):
    """true when every segment starts from the exact end state of the one before."""
    for before, after in zip(solver_status, solver_status[1:]):
        if before["end_state"] != after["start_state"]:
            return False
    return True


def check_result(result, concentration_scale):
    """raise unless the ledger, state bounds and segment carryover all pass, else return them."""
    # relative ledger where there is gas, absolute residual where there is none
    inventory = result.metadata["initial_gas_moles"] + result.entered_moles
    positive = inventory > 0
    ledger = float(np.max(np.abs(result.ledger_error_moles[positive]) / inventory[positive]))
    zero_ledger = float(np.max(np.abs(result.ledger_error_moles[~positive]), initial=0.))

    # gas must stay in [0, scale] and coverage in [0, 1]
    c_below = -float(result.c.min()) / concentration_scale
    c_above = float(result.c.max()) / concentration_scale - 1
    theta_below = -float(result.theta.min())
    theta_above = float(result.theta.max()) - 1
    bounds = max(0., c_below, c_above, theta_below, theta_above)

    carryover = exact_carryover(result.solver_status)
    if ledger > LEDGER_LIMIT or zero_ledger > ZERO_LEDGER_LIMIT or bounds > BOUND_LIMIT or not carryover:
        raise ValueError("Conservation, state bounds or switch-state check failed")
    return dict(relative_ledger=ledger, zero_inventory_residual=zero_ledger,
                bound_violation=bounds, exact_carryover=carryover)


def completion_decision(completion, resolution_change):
    """None when the threshold is inside the resolution change, else whether completion reaches it."""
    if abs(completion - COMPLETION) <= resolution_change:
        return None
    return bool(completion >= COMPLETION)


# ---------------------------------------------------------------- one case

def refine_grid(study, record, variant, pulse, options, concentration_scale):
    """refine the grid until two in a row agree, return (lumped, spatial, cells, last grid entry)."""
    previous = None
    for cells in GRID_CELLS:
        print(f"{record['name']}: {cells} cells", flush=True)
        lumped, spatial = run_pair(variant, pulse, cells, options)
        record["lumped_checks"] = check_result(lumped, concentration_scale)
        record["spatial_checks"] = check_result(spatial, concentration_scale)
        entry = dict(cells=cells, numerical_diffusion_ratio=spatial.metadata["numerical_diffusivity_ratio"])
        if previous is not None:
            entry["difference"] = resolution_difference(previous, spatial, concentration_scale)
        record["grids"].append(entry)
        write_json(OUT / "study.json", study)
        if (previous is not None and max(entry["difference"].values()) <= GRID_LIMIT
                and entry["numerical_diffusion_ratio"] <= NUMERICAL_DIFFUSION_LIMIT):
            return lumped, spatial, cells, entry
        previous = spatial
    raise ValueError(f"Grid refinement did not pass for {record['name']}")


def refine_time(record, variant, pulse, cells, tight, lumped, spatial, concentration_scale):
    """rerun on the final grid with tight tolerances and raise if the answer moves."""
    refined_lumped, refined_spatial = run_pair(variant, pulse, cells, tight)
    record["tight_lumped_checks"] = check_result(refined_lumped, concentration_scale)
    record["tight_spatial_checks"] = check_result(refined_spatial, concentration_scale)
    record["time_difference_0d"] = resolution_difference(lumped, refined_lumped, concentration_scale)
    record["time_difference_1d"] = resolution_difference(spatial, refined_spatial, concentration_scale)
    changes = list(record["time_difference_0d"].values()) + list(record["time_difference_1d"].values())
    if max(changes) > TIME_LIMIT:
        raise ValueError(f"Time refinement did not pass for {record['name']}")


def summary_row(record, variant, pulse, cells, entry, lumped, spatial):
    """completion at pulse end, the proxy decisions and the final mole fractions for one case."""
    pulse_index = int(np.flatnonzero(spatial.t == pulse)[0])
    completion_0d = float(lumped.theta[pulse_index, 0])
    minimum_1d = float(spatial.theta[pulse_index].min())

    # a decision is None when the threshold sits inside the numerical uncertainty
    decision_0d = completion_decision(completion_0d, record["time_difference_0d"]["coverage"])
    change_1d = max(entry["difference"]["coverage"], record["time_difference_1d"]["coverage"])
    decision_1d = completion_decision(minimum_1d, change_1d)

    # false feasible: the 0D proxy says complete while the slowest 1D cell is not
    if decision_0d is not None and decision_1d is not None:
        false_feasible = decision_0d and not decision_1d
    else:
        false_feasible = None

    row = dict(
        name=record["name"], pe=variant["velocity"] * variant["length"] / variant["diffusivity"],
        pulse_residence_ratio=pulse * variant["velocity"] / variant["length"], cells=cells,
        completion_0d=completion_0d, mean_completion_1d=float(spatial.theta[pulse_index].mean()),
        minimum_completion_1d=minimum_1d, lumped_proxy_complete=decision_0d,
        spatial_minimum_complete=decision_1d, false_feasible_proxy=false_feasible)
    for label, result in [("0d", lumped), ("1d", spatial)]:
        metrics = [("captured", result.captured_moles), ("escaped", result.escaped_moles),
                   ("remaining_gas", result.gas_moles)]
        for metric, values in metrics:
            row[f"{metric}_fraction_{label}"] = float(values[-1] / result.entered_moles[-1])
        result.save(OUT / f"{record['name']}-{label}")
    return row


def run_case(study, name, variant, pulse, options, tight, concentration_scale):
    """grid and time refinement for one case, recorded in study, returning its summary row."""
    record = dict(name=name, parameters=variant | {"pulse_duration": pulse}, grids=[])
    study["cases"].append(record)
    start = time.perf_counter()
    lumped, spatial, cells, entry = refine_grid(study, record, variant, pulse, options, concentration_scale)
    refine_time(record, variant, pulse, cells, tight, lumped, spatial, concentration_scale)
    row = summary_row(record, variant, pulse, cells, entry, lumped, spatial)
    record["summary"] = row
    record["elapsed_seconds"] = time.perf_counter() - start
    write_json(OUT / "study.json", study)
    return row


# ---------------------------------------------------------------- whole study

def main():
    """run every case once, recording progress in study.json and a summary.csv at the end."""
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
    concentration_scale = parameters["concentration_scale"]

    # hashes of this script, its inputs, the plan and the engine source
    paths = [Path(__file__), registry_path, ROOT / "docs/phase5-preliminary-plan.md"]
    paths.extend(sorted((ROOT / "src/ald_twin").glob("*.py")))
    file_sha256 = {}
    for path in paths:
        file_sha256[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()

    study = dict(
        status="RUNNING", role="Preliminary synthetic fixed-parameter comparison",
        full_phase5_passed=False, physical_fit_performed=False,
        source_registry_sha256=registry.sha256, file_sha256=file_sha256,
        parameters=parameters, diffusivity_multipliers=DIFFUSIVITY_MULTIPLIERS,
        pulse_multipliers=PULSE_MULTIPLIERS, completion_threshold=COMPLETION, cases=[])
    write_json(OUT / "study.json", study)
    options = SolverOptions("Radau", 1e-9, 1e-11, 0.025)
    tight = replace(options, rtol=1e-10, atol=1e-12, max_step=0.0125)

    # any failure is recorded in study.json before it is raised
    rows = []
    try:
        for diffusion_factor in study["diffusivity_multipliers"]:
            variant = parameters | {"diffusivity": parameters["diffusivity"] * diffusion_factor}
            for pulse_factor in study["pulse_multipliers"]:
                pulse = parameters["pulse_duration"] * pulse_factor
                name = f"diffusion-{diffusion_factor}-pulse-{pulse_factor}"
                rows.append(run_case(study, name, variant, pulse, options, tight, concentration_scale))
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
