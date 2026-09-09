"""Finite synthetic scenarios, verified recipe trials and candidate comparisons."""

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


def write_json(path, data):
    """Replace a small record atomically, including while a study is running."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(json_native(data), indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_plan(plan):
    if plan.get("kind") != "synthetic" or plan.get("physical_fit_ready") is not False:
        raise ValueError("Only an explicitly synthetic process study is admitted")
    if plan.get("physical_dez_diffusivity") is not None:
        raise ValueError("Physical DEZ transport has not been accepted")
    if plan.get("factor_order") != ["Gamma", "kA", "kB", "D_A"]:
        raise ValueError("Scenario factors must be Gamma, kA, kB, D_A")
    for name in ("a_pulse_ratios", "purge_ratios"):
        values = np.asarray(plan[name], dtype=float)
        if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError(f"Positive finite {name} are required")
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate {name}")
    for name in ("peclet", "damkohler", "b_pulse_ratio", "periodic_tolerance"):
        if not np.isfinite(plan[name]) or plan[name] <= 0:
            raise ValueError(f"Positive finite {name} is required")
    if plan["periodic_tolerance"] > 1e-7:
        raise ValueError("The recurring-state tolerance cannot exceed 1e-7")
    names = [row["name"] for row in plan["scenarios"]]
    if not names or len(names) != len(set(names)) or "reference" not in names:
        raise ValueError("Distinct scenario names including reference are required")
    for row in plan["scenarios"]:
        if not row["name"] or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in row["name"]):
            raise ValueError("Use simple lowercase scenario names")
        factors = np.asarray(row["factors"], dtype=float)
        if factors.shape != (4,) or not np.isfinite(factors).all() or np.any(factors <= 0):
            raise ValueError("Four positive finite scenario factors are required")
        if row["name"] == "reference" and not np.array_equal(factors, np.ones(4)):
            raise ValueError("The reference scenario must preserve all four inputs")
    grids = plan["spatial_grids"]
    if len(grids) < 2 or any(type(n) is not int or n < 2 for n in grids):
        raise ValueError("At least two positive spatial grids are required")
    if any(b != 2*a for a, b in zip(grids, grids[1:])):
        raise ValueError("Each spatial refinement must double the cells")
    if plan["selection_grid_ceiling"] < grids[-1]:
        raise ValueError("The selection ceiling cannot be below the study ceiling")


def trial_inputs(base, plan, pulse, purge, scenario):
    validate_plan(plan)
    if (base.get("kind") != "synthetic" or base.get("physical_fit_ready") is not False
            or base.get("physical_dez_diffusivity") is not None):
        raise ValueError("The base configuration must retain its synthetic physical-input gate")
    if pulse not in plan["a_pulse_ratios"] or purge not in plan["purge_ratios"]:
        raise ValueError("Recipe is outside the declared candidate list")
    if scenario not in plan["scenarios"]:
        raise ValueError("Scenario is outside the declared set")
    parameters, nominal = case_parameters(base, plan["peclet"], plan["damkohler"])
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
    scale = 1e10*M_ZNO*nominal.capacity/base["density_kg_m3"]
    return parameters, chemistry, segments, scale


def observations(result, segments, density, scale):
    summary = metrics(result, segments)
    active = result.grid.reactive_areas > 0
    gpc = periodic_gpc(result, density)[active]
    mean = float(np.average(gpc, weights=result.grid.reactive_areas[active]))
    spread = float(np.ptp(gpc)/mean) if mean > 0 else None
    return summary | dict(mean_gpc_angstrom=mean, mean_gpc_normalized=mean/scale,
                          relative_gpc_spread=spread)


def changes(first, second, segments, residence, density, scale):
    change = resolution_difference(first, second) | metric_difference(first, second, segments, residence)
    a, b = (observations(result, segments, density, scale) for result in (first, second))
    extra = 0.
    for name in ("mean_gpc_normalized", "relative_gpc_spread"):
        if (a[name] is None) != (b[name] is None):
            extra = None
            break
        if a[name] is not None:
            extra = max(extra, abs(a[name]-b[name]))
    change["growth_metrics"] = extra
    return change


def converged(change, limit):
    return (all(change[name] is not None and change[name] <= limit
                for name in ("gas", "coverage", "events", "decision_metrics", "growth_metrics"))
            and change["purge_time_over_residence"] is not None
            and change["purge_time_over_residence"] <= .001)


def load_cycle(stem):
    """Reload a complete cycle and check the reconstructed grid and ledger."""
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


def evaluate_case(base, plan, pulse, purge, scenario, folder, *, grids=None, include_mixed=True):
    """Verify one declared trial; keep every numerical attempt for resuming."""
    parameters, chemistry, segments, scale = trial_inputs(base, plan, pulse, purge, scenario)
    grids = plan["spatial_grids"] if grids is None else grids
    if (len(grids) < 2 or any(type(n) is not int or n < 2 for n in grids)
            or any(b != 2*a for a, b in zip(grids, grids[1:]))
            or grids[-1] > plan["selection_grid_ceiling"]):
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
        start = time.perf_counter()
        stem = folder/label
        reused = Path(str(stem)+".json").exists() and Path(str(stem)+".npz").exists()
        if reused:
            result = load_cycle(stem)
            if (result.grid.metadata["parameters"] != parameters or result.chemistry != chemistry
                    or len(result.grid.z) != cells
                    or result.settings["solver"] != asdict(solver)
                    or result.settings["recipe"] != [asdict(s) for s in segments]):
                raise ValueError("Saved attempt does not match the requested inputs")
        else:
            if Path(str(stem)+".npz").exists() or Path(str(stem)+".json").exists():
                raise ValueError("Incomplete saved artifact retained; use a new output directory")
            result = periodic_cycle(channel_grid(parameters, cells), chemistry, segments,
                        fraction_scale=parameters["fraction_scale"], options=solver,
                        tolerance=plan["periodic_tolerance"],
                        output_times=readout_times(segments, 101 if solver == options else 201),
                        state=None if seed is None else seed.integrated.y[:, -1],
                        accounting_origin=None if seed is None else seed.initial_state)
            result.save(stem)
        record["attempts"].append(dict(label=label, cells=cells, seconds=time.perf_counter()-start,
                           reused=reused, cycles=len(result.history), checks=result.checks(),
                           last_cycle=result.history[-1], solver=asdict(solver)))
        write_json(folder/"case.json", record)
        return result

    def difference(a, b):
        return changes(a, b, segments, residence, base["density_kg_m3"], scale)

    try:
        mixed = solve(1, "mixed") if include_mixed else None
        previous = None
        for cells in grids:
            spatial = solve(cells, f"grid-{cells}")
            if previous is not None:
                spatial_change = difference(previous, spatial)
                record["spatial_change"] = spatial_change
                record["attempts"][-1]["change"] = spatial_change
                write_json(folder/"case.json", record)
                if converged(spatial_change, .001) and spatial.grid.metadata["numerical_diffusion_ratio"] <= .05:
                    break
            previous = spatial
        else:
            record.update(status="UNVERIFIED", reason=f"Spatial ceiling {grids[-1]} reached")
            write_json(folder/"case.json", record)
            return record
        tighter = replace(options, rtol=options.rtol/10, atol=options.atol/10, max_step=options.max_step/2)
        records = {}
        for name, result in (("mixed", mixed), ("spatial", spatial)):
            if result is None:
                continue
            repeat = solve(len(result.grid.z), f"{name}-time-repeat", tighter, result)
            time_change = difference(result, repeat)
            record.setdefault("time_changes", {})[name] = time_change
            if not converged(time_change, 1e-5):
                record.update(status="UNVERIFIED", reason=f"{name} time refinement failed")
                write_json(folder/"case.json", record)
                return record
            error = max(time_change[k] + (spatial_change[k] if name == "spatial" else 0.)
                        for k in ("gas", "coverage", "events", "decision_metrics"))
            summary = observations(result, segments, base["density_kg_m3"], scale)
            records[name] = dict(metrics=summary, numerical_change=error, feasible=decision(summary, error))
        endpoint = int(np.argmin(abs(spatial.integrated.t-segments[0].duration)))
        record.update(status="PASS", accepted_cells=cells, models=records,
            numerical_diffusion_ratio=spatial.grid.metadata["numerical_diffusion_ratio"],
            objectives=dict(cycle_time_s=sum(s.duration for s in segments),
                            precursor_moles=sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments)),
            profile=dict(z_m=spatial.grid.z.tolist(), a_completion=spatial.fields[2, endpoint].tolist(),
                         gpc_angstrom=periodic_gpc(spatial, base["density_kg_m3"]).tolist()))
    except Exception as error:
        record.update(status="ERROR", reason=f"{type(error).__name__}: {error}")
        write_json(folder/"case.json", record)
        raise
    write_json(folder/"case.json", record)
    return record


def feasibility(rows, expected, model="spatial"):
    """Unknown and unsupported cases never become an all-scenario pass."""
    if (len(rows) != expected or len({row["scenario"]["name"] for row in rows}) != expected
            or any(row["status"] != "PASS" for row in rows)):
        return "unverified"
    if any(not row["wall_screen"]["passes_declared_screen"] for row in rows):
        return "outside-screen"
    values = [row["models"][model]["feasible"] for row in rows]
    if any(value is False for value in values):
        return "fail"
    return "pass" if all(value is True for value in values) else "unresolved"


def scenario_envelope(rows, expected, model="spatial"):
    complete = (len(rows) == expected and len({row["scenario"]["name"] for row in rows}) == expected
                and all(row["status"] == "PASS" for row in rows))
    names = ("mean_gpc_angstrom", "minimum_a_completion", "maximum_b_remaining",
             "purge_a_residual", "purge_b_residual", "relative_gpc_spread")
    ranges = {}
    if complete:
        for name in names:
            values = [row["models"][model]["metrics"][name] for row in rows]
            ranges[name] = None if any(v is None for v in values) else [min(values), max(values)]
        for index, name in enumerate(("a_clearance_s", "b_clearance_s")):
            values = [row["models"][model]["metrics"]["purge_crossing_s"][index] for row in rows]
            ranges[name] = None if any(v is None for v in values) else [min(values), max(values)]
    return dict(complete=complete, ranges=ranges,
                interpretation="Range over the declared finite scenarios; not a confidence interval")


def pareto_candidates(recipes, status_key):
    """Exact finite-list objectives; retain ties and possible unknown competitors."""
    feasible = [row for row in recipes if row[status_key] == "pass"]

    def dominates(a, b):
        names = ("cycle_time_s", "precursor_moles")
        return (all(a["objectives"][k] <= b["objectives"][k] for k in names)
                and any(a["objectives"][k] < b["objectives"][k] for k in names))

    front = [row for row in feasible if not any(dominates(other, row) for other in feasible)]
    unknown = [row for row in recipes if row[status_key] in ("unverified", "unresolved", "outside-screen")]
    competitors = [row["recipe"] for row in unknown if not any(dominates(known, row) for known in feasible)]
    return dict(candidates=[row["recipe"] for row in front], complete=not competitors,
                unresolved_competitors=competitors,
                interpretation="Pareto candidates over the declared finite recipe list only")


def summarize_cases(base, plan, cases):
    recipes = []
    for pulse in plan["a_pulse_ratios"]:
        for purge in plan["purge_ratios"]:
            name = f"a-{pulse:g}-purge-{purge:g}"
            rows = [row for row in cases if row["recipe"] == name]
            reference = [row for row in rows if row["scenario"]["name"] == "reference"]
            _, _, segments, _ = trial_inputs(base, plan, pulse, purge, plan["scenarios"][0])
            recipes.append(dict(recipe=name, pulse_ratio=pulse, purge_ratio=purge,
                nominal=feasibility(reference, 1), all_scenarios=feasibility(rows, len(plan["scenarios"])),
                nominal_mixed=feasibility(reference, 1, "mixed"),
                envelope=scenario_envelope(rows, len(plan["scenarios"])),
                objectives=dict(cycle_time_s=sum(s.duration for s in segments),
                                precursor_moles=sum(s.duration*(s.inlet_a+s.inlet_b) for s in segments))))
    return dict(kind="synthetic", physical_fit_ready=False, recipes=recipes,
                nominal_front=pareto_candidates(recipes, "nominal"),
                scenario_front=pareto_candidates(recipes, "all_scenarios"))
