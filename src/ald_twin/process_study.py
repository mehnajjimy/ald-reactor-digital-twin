"""finite synthetic scenarios, verified recipe trials and candidate comparisons."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import time

import numpy as np

from .cycle_study import (case_parameters, channel_grid, decision, metric_difference,
                          metrics, readout_times, recipe, resolution_difference,
                          study_options, wall_screen)
from .cycles import CycleChemistry, CycleResult, M_ZNO, periodic_cycle, periodic_gpc
from .numerics import Integrated
from .results import json_native

# fixed study settings

FACTOR_ORDER = ["Gamma", "kA", "kB", "D_A"]
SCENARIO_NAME_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789-"
MAX_PERIODIC_TOLERANCE = 1e-7
ANGSTROM_PER_METRE = 1e10
READOUT_POINTS = 101
REPEAT_READOUT_POINTS = 201
SPATIAL_CHANGE_LIMIT = .001
TIME_CHANGE_LIMIT = 1e-5
PURGE_CHANGE_LIMIT = .001
MAX_NUMERICAL_DIFFUSION_RATIO = .05

# names of the change measures compared between two solutions

CHANGE_KEYS = ("gas", "coverage", "events", "decision_metrics", "growth_metrics")
ERROR_KEYS = ("gas", "coverage", "events", "decision_metrics")
OBJECTIVE_NAMES = ("cycle_time_s", "precursor_moles")
ENVELOPE_METRICS = ("mean_gpc_angstrom", "minimum_a_completion", "maximum_b_remaining",
                    "purge_a_residual", "purge_b_residual", "relative_gpc_spread")
UNKNOWN_STATES = ("unverified", "unresolved", "outside-screen")


# saving records

def write_json(path, data):
    """replace a small record atomically, including while a study is running."""

    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(json_native(data), indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


# checking the study plan

def _each_doubles(grids):
    """true when every grid has twice the cells of the one before it."""

    for smaller, larger in zip(grids, grids[1:]):
        if larger != 2*smaller:
            return False
    return True


def _whole_cells(grids):
    """true when every grid is an int with at least two cells."""

    for cells in grids:
        if type(cells) is not int or cells < 2:
            return False
    return True


def _simple_name(name):
    """true for a nonempty name made only of lowercase letters, digits and dashes."""

    if not name:
        return False
    for character in name:
        if character not in SCENARIO_NAME_CHARACTERS:
            return False
    return True


def _check_ratios(plan, name):
    """raise unless plan[name] is a nonempty list of distinct positive finite ratios."""

    values = np.asarray(plan[name], dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError(f"Positive finite {name} are required")
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {name}")


def _check_scenarios(scenarios):
    """raise unless scenarios have distinct simple names, a reference and four factors each."""

    names = [row["name"] for row in scenarios]
    if not names or len(names) != len(set(names)) or "reference" not in names:
        raise ValueError("Distinct scenario names including reference are required")
    for row in scenarios:
        if not _simple_name(row["name"]):
            raise ValueError("Use simple lowercase scenario names")
        factors = np.asarray(row["factors"], dtype=float)
        if factors.shape != (4,) or not np.isfinite(factors).all() or np.any(factors <= 0):
            raise ValueError("Four positive finite scenario factors are required")
        if row["name"] == "reference" and not np.array_equal(factors, np.ones(4)):
            raise ValueError("The reference scenario must preserve all four inputs")


def validate_plan(plan):
    """raise ValueError unless the plan is an explicit, bounded synthetic study."""

    if plan.get("kind") != "synthetic" or plan.get("physical_fit_ready") is not False:
        raise ValueError("Only an explicitly synthetic process study is admitted")
    if plan.get("physical_dez_diffusivity") is not None:
        raise ValueError("Physical DEZ transport has not been accepted")
    if plan.get("factor_order") != FACTOR_ORDER:
        raise ValueError("Scenario factors must be Gamma, kA, kB, D_A")
    for name in ("a_pulse_ratios", "purge_ratios"):
        _check_ratios(plan, name)
    for name in ("peclet", "damkohler", "b_pulse_ratio", "periodic_tolerance"):
        if not np.isfinite(plan[name]) or plan[name] <= 0:
            raise ValueError(f"Positive finite {name} is required")
    if plan["periodic_tolerance"] > MAX_PERIODIC_TOLERANCE:
        raise ValueError("The recurring-state tolerance cannot exceed 1e-7")
    _check_scenarios(plan["scenarios"])
    grids = plan["spatial_grids"]
    if len(grids) < 2 or not _whole_cells(grids):
        raise ValueError("At least two positive spatial grids are required")
    if not _each_doubles(grids):
        raise ValueError("Each spatial refinement must double the cells")
    if plan["selection_grid_ceiling"] < grids[-1]:
        raise ValueError("The selection ceiling cannot be below the study ceiling")


# building one trial

def trial_inputs(base, plan, pulse, purge, scenario):
    """return parameters, chemistry, recipe segments and gpc scale for one declared trial."""

    validate_plan(plan)
    if (base.get("kind") != "synthetic" or base.get("physical_fit_ready") is not False
            or base.get("physical_dez_diffusivity") is not None):
        raise ValueError("The base configuration must retain its synthetic physical-input gate")
    if pulse not in plan["a_pulse_ratios"] or purge not in plan["purge_ratios"]:
        raise ValueError("Recipe is outside the declared candidate list")
    if scenario not in plan["scenarios"]:
        raise ValueError("Scenario is outside the declared set")
    parameters, nominal = case_parameters(base, plan["peclet"], plan["damkohler"])

    # factors scale Gamma, kA, kB and D_A in that order

    factors = scenario["factors"]
    chemistry = CycleChemistry(nominal.capacity*factors[0], nominal.rate_a*factors[1], nominal.rate_b*factors[2])
    parameters["diffusivity"]["a"]["value"] *= factors[3]
    parameters["diffusivity"]["a"]["scenario_factor"] = factors[3]
    parameters["dimensionless"] = dict(nominal_peclet=plan["peclet"], nominal_damkohler=plan["damkohler"],
                                       peclet=plan["peclet"]/factors[3],
                                       damkohler=plan["damkohler"]*factors[0]*factors[1])
    parameters["scenario"] = scenario
    parameters["purge_residence_ratio"] = purge
    segments = recipe(parameters, pulse, water_ratio=plan["b_pulse_ratio"])

    # growth per cycle (Å) of one full nominal monolayer, used to normalize gpc

    scale = ANGSTROM_PER_METRE*M_ZNO*nominal.capacity/base["density_kg_m3"]
    return parameters, chemistry, segments, scale


def recipe_objectives(segments):
    """cycle time (s) and precursor delivered (mol) for one cycle."""

    return dict(cycle_time_s=sum(s.duration for s in segments),
                precursor_moles=sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments))


# comparing two solutions

def observations(result, segments, density, scale):
    """cycle metrics plus the area-weighted mean gpc and its spread over the reactive wall."""

    summary = metrics(result, segments)
    active = result.grid.reactive_areas > 0
    gpc = periodic_gpc(result, density)[active]
    mean = float(np.average(gpc, weights=result.grid.reactive_areas[active]))
    if mean > 0:
        spread = float(np.ptp(gpc)/mean)
    else:
        spread = None
    return summary | dict(mean_gpc_angstrom=mean, mean_gpc_normalized=mean/scale,
                          relative_gpc_spread=spread)


def largest_change(first, second, names):
    """largest absolute change over names, or None when only one side is defined."""

    largest = 0.
    for name in names:
        a = first[name]
        b = second[name]
        if (a is None) != (b is None):
            return None
        if a is not None:
            largest = max(largest, abs(a-b))
    return largest


def changes(first, second, segments, residence, density, scale):
    """all change measures between two solutions of the same trial."""

    change = resolution_difference(first, second) | metric_difference(first, second, segments, residence)
    a = observations(first, segments, density, scale)
    b = observations(second, segments, density, scale)
    change["growth_metrics"] = largest_change(a, b, ("mean_gpc_normalized", "relative_gpc_spread"))
    return change


def converged(change, limit):
    """true when every change is defined and within limit, and purge clearance moved at most 0.001 residence times."""

    for name in CHANGE_KEYS:
        value = change[name]
        if value is None or not (value <= limit):
            return False
    purge = change["purge_time_over_residence"]
    if purge is None:
        return False
    return purge <= PURGE_CHANGE_LIMIT


def numerical_error(time_change, spatial_change):
    """largest per-measure sum of time change and spatial change (no spatial part for the 0D model)."""

    errors = []
    for key in ERROR_KEYS:
        extra = 0.
        if spatial_change is not None:
            extra = spatial_change[key]
        errors.append(time_change[key] + extra)
    return max(errors)


# saved cycles

def load_cycle(stem):
    """reload a complete cycle and check the reconstructed grid and ledger."""

    data = json.loads(Path(str(stem)+".json").read_text())
    if data["kind"] != "synthetic" or not data["periodic"]:
        raise ValueError("A saved synthetic recurring cycle is required")
    grid = channel_grid(data["grid"]["parameters"], data["grid"]["cells"])
    with np.load(str(stem)+".npz", allow_pickle=False) as raw:
        for name in ("z", "carrier_moles", "reactive_areas"):
            np.testing.assert_array_equal(raw[name], getattr(grid, name))
        result = CycleResult(Integrated(raw["t"], raw["scaled_state"], tuple(data["segments"])),
                             grid, CycleChemistry(**data["chemistry"]), data["fraction_scale"],
                             raw["initial_state"], data["history"], data["settings"], periodic=True)
    if result.checks() != data["checks"]:
        raise ValueError("Saved cycle accounting changed")
    return result


def _grids_in_bounds(grids, ceiling):
    """true for at least two whole-cell grids that double and stay under the ceiling."""

    if len(grids) < 2 or not _whole_cells(grids) or not _each_doubles(grids):
        return False
    if grids[-1] > ceiling:
        return False
    return True


# one verified trial

def evaluate_case(base, plan, pulse, purge, scenario, folder, *, grids=None, include_mixed=True):
    """verify one declared trial; keep every numerical attempt for resuming."""

    parameters, chemistry, segments, scale = trial_inputs(base, plan, pulse, purge, scenario)
    if grids is None:
        grids = plan["spatial_grids"]
    if not _grids_in_bounds(grids, plan["selection_grid_ceiling"]):
        raise ValueError("Invalid bounded refinement grids")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    options = study_options(segments)
    mixed_grid = channel_grid(parameters, 1)
    residence = float(mixed_grid.carrier_moles.sum()/mixed_grid.molar_flow)
    record = dict(kind="synthetic", status="RUNNING", physical_fit_ready=False,
                  recipe=f"a-{pulse:g}-purge-{purge:g}", pulse_ratio=pulse, purge_ratio=purge,
                  scenario=scenario, parameters=parameters, chemistry=asdict(chemistry),
                  residence_s=residence, gpc_scale_angstrom=scale,
                  wall_screen=wall_screen(parameters, chemistry), attempts=[])

    def solve(cells, label, solver=options, seed=None):
        """solve one attempt, or reload it when both saved files match the inputs."""

        start = time.perf_counter()
        stem = folder/label
        json_path = Path(str(stem)+".json")
        npz_path = Path(str(stem)+".npz")
        reused = json_path.exists() and npz_path.exists()
        if reused:
            result = load_cycle(stem)
            if (result.grid.metadata["parameters"] != parameters or result.chemistry != chemistry
                    or len(result.grid.z) != cells
                    or result.settings["solver"] != asdict(solver)
                    or result.settings["recipe"] != [asdict(s) for s in segments]):
                raise ValueError("Saved attempt does not match the requested inputs")
        else:
            if npz_path.exists() or json_path.exists():
                raise ValueError("Incomplete saved artifact retained; use a new output directory")
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
                                    tolerance=plan["periodic_tolerance"],
                                    output_times=output_times,
                                    state=state,
                                    accounting_origin=accounting_origin)
            result.save(stem)
        record["attempts"].append(dict(label=label, cells=cells, seconds=time.perf_counter()-start,
                                       reused=reused, cycles=len(result.history), checks=result.checks(),
                                       last_cycle=result.history[-1], solver=asdict(solver)))
        write_json(folder/"case.json", record)
        return result

    def difference(a, b):
        """change measures between two solutions of this trial."""

        return changes(a, b, segments, residence, base["density_kg_m3"], scale)

    try:
        mixed = None
        if include_mixed:
            mixed = solve(1, "mixed")

        # refine the spatial grid until two grids agree

        previous = None
        accepted = False
        for cells in grids:
            spatial = solve(cells, f"grid-{cells}")
            if previous is not None:
                spatial_change = difference(previous, spatial)
                record["spatial_change"] = spatial_change
                record["attempts"][-1]["change"] = spatial_change
                write_json(folder/"case.json", record)
                if (converged(spatial_change, SPATIAL_CHANGE_LIMIT)
                        and spatial.grid.metadata["numerical_diffusion_ratio"] <= MAX_NUMERICAL_DIFFUSION_RATIO):
                    accepted = True
                    break
            previous = spatial
        if not accepted:
            record.update(status="UNVERIFIED", reason=f"Spatial ceiling {grids[-1]} reached")
            write_json(folder/"case.json", record)
            return record

        # repeat each accepted solution with tighter time integration

        tighter = replace(options, rtol=options.rtol/10, atol=options.atol/10, max_step=options.max_step/2)
        records = {}
        for name, result in (("mixed", mixed), ("spatial", spatial)):
            if result is None:
                continue
            repeat = solve(len(result.grid.z), f"{name}-time-repeat", tighter, result)
            time_change = difference(result, repeat)
            if "time_changes" not in record:
                record["time_changes"] = {}
            record["time_changes"][name] = time_change
            if not converged(time_change, TIME_CHANGE_LIMIT):
                record.update(status="UNVERIFIED", reason=f"{name} time refinement failed")
                write_json(folder/"case.json", record)
                return record
            matching_spatial_change = None
            if name == "spatial":
                matching_spatial_change = spatial_change
            error = numerical_error(time_change, matching_spatial_change)
            summary = observations(result, segments, base["density_kg_m3"], scale)
            records[name] = dict(metrics=summary, numerical_change=error, feasible=decision(summary, error))

        # the profile is read at the readout nearest the end of the A pulse

        endpoint = int(np.argmin(abs(spatial.integrated.t-segments[0].duration)))
        record.update(status="PASS", accepted_cells=cells, models=records,
                      numerical_diffusion_ratio=spatial.grid.metadata["numerical_diffusion_ratio"],
                      objectives=recipe_objectives(segments),
                      profile=dict(z_m=spatial.grid.z.tolist(), a_completion=spatial.fields[2, endpoint].tolist(),
                                   gpc_angstrom=periodic_gpc(spatial, base["density_kg_m3"]).tolist()))
    except Exception as error:
        record.update(status="ERROR", reason=f"{type(error).__name__}: {error}")
        write_json(folder/"case.json", record)
        raise
    write_json(folder/"case.json", record)
    return record


# judging and comparing trials

def _complete_set(rows, expected):
    """true when rows cover expected distinct scenarios and all passed."""

    if len(rows) != expected:
        return False
    if len({row["scenario"]["name"] for row in rows}) != expected:
        return False
    for row in rows:
        if row["status"] != "PASS":
            return False
    return True


def feasibility(rows, expected, model="spatial"):
    """unknown and unsupported cases never become an all-scenario pass."""

    if not _complete_set(rows, expected):
        return "unverified"
    for row in rows:
        if not row["wall_screen"]["passes_declared_screen"]:
            return "outside-screen"
    values = [row["models"][model]["feasible"] for row in rows]
    if any(value is False for value in values):
        return "fail"
    if all(value is True for value in values):
        return "pass"
    return "unresolved"


def _value_range(values):
    """[min, max] of values, or None when any value is missing."""

    if any(value is None for value in values):
        return None
    return [min(values), max(values)]


def scenario_envelope(rows, expected, model="spatial"):
    """range of each metric over the declared scenarios, only when every scenario passed."""

    complete = _complete_set(rows, expected)
    ranges = {}
    if complete:
        for name in ENVELOPE_METRICS:
            values = [row["models"][model]["metrics"][name] for row in rows]
            ranges[name] = _value_range(values)
        for index, name in enumerate(("a_clearance_s", "b_clearance_s")):
            values = [row["models"][model]["metrics"]["purge_crossing_s"][index] for row in rows]
            ranges[name] = _value_range(values)
    return dict(complete=complete, ranges=ranges,
                interpretation="Range over the declared finite scenarios; not a confidence interval")


def _dominates(first, second):
    """true when first is no worse in both objectives and better in at least one."""

    for name in OBJECTIVE_NAMES:
        if not first["objectives"][name] <= second["objectives"][name]:
            return False
    for name in OBJECTIVE_NAMES:
        if first["objectives"][name] < second["objectives"][name]:
            return True
    return False


def _dominated(row, others):
    """true when any of others dominates row."""

    for other in others:
        if _dominates(other, row):
            return True
    return False


def pareto_candidates(recipes, status_key):
    """exact finite-list objectives; retain ties and possible unknown competitors."""

    feasible = [row for row in recipes if row[status_key] == "pass"]
    front = [row for row in feasible if not _dominated(row, feasible)]

    # an unknown recipe that no feasible one beats could still belong on the front

    unknown = [row for row in recipes if row[status_key] in UNKNOWN_STATES]
    competitors = [row["recipe"] for row in unknown if not _dominated(row, feasible)]
    return dict(candidates=[row["recipe"] for row in front], complete=not competitors,
                unresolved_competitors=competitors,
                interpretation="Pareto candidates over the declared finite recipe list only")


def summarize_cases(base, plan, cases):
    """feasibility, scenario ranges and objectives per recipe, plus both pareto fronts."""

    recipes = []
    for pulse in plan["a_pulse_ratios"]:
        for purge in plan["purge_ratios"]:
            name = f"a-{pulse:g}-purge-{purge:g}"
            rows = [row for row in cases if row["recipe"] == name]
            reference = [row for row in rows if row["scenario"]["name"] == "reference"]
            _, _, segments, _ = trial_inputs(base, plan, pulse, purge, plan["scenarios"][0])
            count = len(plan["scenarios"])
            recipes.append(dict(recipe=name, pulse_ratio=pulse, purge_ratio=purge,
                                nominal=feasibility(reference, 1), all_scenarios=feasibility(rows, count),
                                nominal_mixed=feasibility(reference, 1, "mixed"),
                                envelope=scenario_envelope(rows, count),
                                objectives=recipe_objectives(segments)))
    return dict(kind="synthetic", physical_fit_ready=False, recipes=recipes,
                nominal_front=pareto_candidates(recipes, "nominal"),
                scenario_front=pareto_candidates(recipes, "all_scenarios"))
