"""Run the frozen Phase 1 mathematical acceptance studies, individually or together."""

import argparse
import csv
from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from scipy.integrate import solve_ivp

from ald_twin.analytical import cell_averages, pulse_response
from ald_twin.configuration import ParameterRegistry
from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.reactor_1d import (AdvectiveBoundary, ConcentrationBoundary, FluxBoundary,
    Reactor1D, TransportSegment, face_fluxes, solve_1d)
from ald_twin.surface import FiniteCapacity
from ald_twin.units import (actual_volumetric_flow, angstrom_to_metre, celsius_to_kelvin,
    density_g_cm3_to_kg_m3, molar_mass_g_mol_to_kg_mol, sccm_to_molar_flow)
from ald_twin.verification import (ManufacturedSolution, advection_pulse_average,
    dimensional_checks, front_position, normalized_l1, restrict_uniform)


# folders, gate categories and study groups
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase1"
FIGURES = ROOT / "figures/phase1"
GATE_CATEGORIES = ["units", "analytical cases", "conservation", "state bounds",
    "temporal convergence", "spatial convergence", "independent solver comparison",
    "boundary conditions", "domain truncation", "numerical diffusion"]
GROUPS = ["basic", "transport", "temporal", "spatial", "manufactured", "truncation"]

# SI units every synthetic case parameter must be declared in
PARAMETER_UNITS = dict(length="m", area="m^2", reactive_perimeter="m", velocity="m s^-1",
    diffusivity="m^2 s^-1", capacity="mol m^-2", capture_velocity="m s^-1",
    concentration_scale="mol m^-3", inlet_concentration="mol m^-3", initial_c="mol m^-3",
    initial_theta="1", pulse_duration="s", purge_duration="s", duration="s", volume="m^3",
    reactive_area="m^2", throughput="m^3 s^-1", inlet_molar_flow="mol s^-1", decay="s^-1",
    theta_amplitude="1", base_theta="1", base_length="m")

# acceptance tolerances
ROUNDOFF = 1e-12            # exact arithmetic up to floating point
EXACT = 1e-10               # cases whose exact answer is known
LEDGER = 1e-8               # relative mole ledger and state bounds
TIME_REFINEMENT = 1e-5      # base versus tight solver tolerances
GRID_REFINEMENT = 1e-3      # last two spatial grids
NUMERICAL_DIFFUSION = .05   # allowed numerical / physical diffusivity
TRUNCATION = 1e-4           # 10L versus 20L coverage on [0, L]

# cell count for the small reacting-front checks in the basic group
BASIC_CELLS = 32

# fixed time where the manufactured operator residual is evaluated (s)
RESIDUAL_TIME = .2


def hashes():
    """sha256 of every engine source file, keyed by path relative to the repo."""
    result = {}
    for path in sorted(ROOT.glob("src/ald_twin/*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


# ---------------------------------------------------------------- study record

class Study:
    """collects checks, run summaries, arrays and configs for one study group."""

    def __init__(self, group):
        """start an empty record for this group and start its clock."""
        self.group = group
        self.rows = []
        self.runs = []
        self.data = {}
        self.configs = {}
        self.start = time.perf_counter()

    def case(self, name):
        """load a synthetic case config and return (values in SI, settings, identifier)."""
        path = ROOT / f"config/synthetic/phase1-{name}.json"
        document = json.loads(path.read_text())
        registry = ParameterRegistry.load(path)
        self.configs[name] = document
        units = {}
        for parameter in registry.parameters:
            units[parameter.name] = PARAMETER_UNITS[parameter.name]
        values = registry.resolve(units)
        return values, document["settings"], registry.identifier + ":" + registry.sha256

    def check(self, name, category, error, tolerance, **details):
        """record one pass/fail row, failing on any non-finite error."""
        error = float(error)
        passed = bool(np.isfinite(error) and error <= tolerance)
        self.rows.append(dict(name=name, category=category, error=error,
            tolerance=float(tolerance), passed=passed, details=details))

    def record(self, name, result, scale, *, upper_bound=False, source=False):
        """check ledger and state bounds of one solve and keep its summary and arrays."""
        # relative ledger where there is gas, absolute residual where there is none
        denominator = result.metadata["initial_gas_moles"] + result.entered_moles
        if source:
            denominator = denominator + np.abs(result.source_moles)
        mask = denominator > 0
        ledger = float(np.max(np.abs(result.ledger_error_moles[mask]) / denominator[mask], initial=0.))
        if np.any(~mask):
            zero_residual = float(np.max(np.abs(result.ledger_error_moles[~mask]), initial=0.))
            self.check(name + " zero-inventory ledger", "conservation", zero_residual, 0.)
        self.check(name + " relative ledger", "conservation", ledger, LEDGER)

        # gas must stay non-negative and coverage must stay in [0, 1]
        c_below = max(0., -float(result.c.min()) / scale)
        self.check(name + " c lower bound", "state bounds", c_below, LEDGER)
        theta_outside = max(0., -float(result.theta.min()), float(result.theta.max()) - 1)
        self.check(name + " theta bounds", "state bounds", theta_outside, LEDGER)
        if upper_bound:
            c_above = max(0., float(result.c.max()) / scale - 1)
            self.check(name + " c upper bound", "state bounds", c_above, LEDGER)

        # run summary without the bulky start and end states
        status = []
        for entry in result.solver_status:
            kept = {}
            for key, value in entry.items():
                if key not in ("start_state", "end_state"):
                    kept[key] = value
            status.append(kept)
        self.runs.append(dict(name=name, metadata=result.metadata,
            solver_status=status,
            exact_segment_carryover=exact_carryover(result.solver_status),
            max_relative_ledger=ledger, final_capture=float(result.captured_moles[-1]),
            max_absolute_ledger=float(np.max(np.abs(result.ledger_error_moles))),
            final_entered=float(result.entered_moles[-1]), final_escaped=float(result.escaped_moles[-1])))

        # arrays for the figures
        self.data[name + "_z"] = result.z
        self.data[name + "_c"] = result.c[-1]
        self.data[name + "_theta"] = result.theta[-1]
        self.data[name + "_t"] = result.t
        self.data[name + "_ledger"] = result.ledger_error_moles

    def save(self, extra=None):
        """write <group>.json and <group>.npz, print a summary and return True if all passed."""
        OUT.mkdir(parents=True, exist_ok=True)
        if not extra:
            extra = {}
        payload = dict(group=self.group, checks=self.rows, runs=self.runs, case_configs=self.configs,
            code_sha256=hashes(), runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            elapsed_seconds=time.perf_counter() - self.start, extra=extra)
        (OUT / f"{self.group}.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        np.savez_compressed(OUT / f"{self.group}.npz", **self.data)
        failures = []
        for row in self.rows:
            if not row["passed"]:
                failures.append(row)
        print(json.dumps(dict(group=self.group, checks=len(self.rows), failures=failures,
                              elapsed_seconds=payload["elapsed_seconds"])), flush=True)
        return not failures


def exact_carryover(solver_status):
    """true when every segment starts from the exact end state of the one before."""
    for before, after in zip(solver_status, solver_status[1:]):
        if before["end_state"] != after["start_state"]:
            return False
    return True


# ---------------------------------------------------------------- shared solver setup

def options(settings, *, tight=False, method="Radau"):
    """solver options from a case's settings, using the refinement_ ones when tight."""
    prefix = ""
    if tight:
        prefix = "refinement_"
    return SolverOptions(method=method, rtol=settings[prefix + "rtol"], atol=settings[prefix + "atol"],
                         max_step=settings[prefix + "max_step"])


def geometry(parameters, cells):
    """1D channel from case parameters with the given number of cells."""
    return Reactor1D(
        length=parameters["length"], area=parameters["area"],
        reactive_perimeter=parameters["reactive_perimeter"],
        velocity=parameters["velocity"], diffusivity=parameters["diffusivity"], cells=cells)


def pulse_boundaries(parameters, boundary):
    """(exposure, purge) inlet boundaries for a concentration, flux or advective inlet."""
    if boundary == "concentration":
        exposure = ConcentrationBoundary(parameters["inlet_concentration"], 0.)
        purge = ConcentrationBoundary(0., 0.)
    elif boundary == "flux":
        exposure = FluxBoundary(parameters["inlet_molar_flow"])
        purge = FluxBoundary(0.)
    else:
        exposure = AdvectiveBoundary(parameters["inlet_concentration"])
        purge = AdvectiveBoundary(0.)
    return exposure, purge


def pulse_run(parameters, settings, identifier, cells, *,
              boundary="concentration", tight=True, method="Radau"):
    """solve one exposure pulse followed by one purge in the 1D channel."""
    reactor = geometry(parameters, cells)
    surface = FiniteCapacity(parameters["capacity"], parameters["capture_velocity"])
    exposure, purge = pulse_boundaries(parameters, boundary)
    segments = [
        TransportSegment(parameters["pulse_duration"], exposure, "exposure"),
        TransportSegment(parameters["purge_duration"], purge, "purge"),
    ]
    end_time = parameters["pulse_duration"] + parameters["purge_duration"]
    return solve_1d(
        reactor, surface, segments,
        concentration_scale=parameters["concentration_scale"],
        initial_c=parameters.get("initial_c", 0.),
        initial_theta=parameters.get("initial_theta", 0.),
        options=options(settings, tight=tight, method=method),
        provenance_id=identifier,
        output_times=np.linspace(0, end_time, settings["output_samples"]),
    )


# ---------------------------------------------------------------- basic group

def check_units(study):
    """check equation dimensions and each unit conversion against hand-worked values."""
    dimensions = dimensional_checks()
    wrong = sum(not x for x in dimensions.values())
    study.check("exact equation dimensions", "units", wrong, 0., equations=dimensions)

    # 500 sccm at 0 C and 1 atm, worked in 50-digit Decimal with the exact SI constants
    with localcontext() as ctx:
        ctx.prec = 50
        pressure = Decimal("101325")
        volume_flow = Decimal("500") * Decimal("1e-6") / Decimal("60")
        gas_constant_times_t = Decimal("8.31446261815324") * Decimal("273.15")
        expected = float(pressure * volume_flow / gas_constant_times_t)
    flow = sccm_to_molar_flow(500., 273.15, 101325.)

    # the same flow at 150 C and 200 Pa, from the ideal gas ratios
    actual_volume = actual_volumetric_flow(flow, 423.15, 200.)
    expected_volume = (500e-6 / 60) * (423.15 / 273.15) * (101325 / 200)

    conversion_errors = {"sccm_to_mol_s": abs(flow / expected - 1),
        "actual_volume": abs(actual_volume / expected_volume - 1),
        "C_to_K": abs(celsius_to_kelvin(150.) / 423.15 - 1),
        "angstrom": abs(angstrom_to_metre(10.) / 1e-9 - 1),
        "density": abs(density_g_cm3_to_kg_m3(5.4) / 5400. - 1),
        "molar_mass": abs(molar_mass_g_mol_to_kg_mol(72.) / .072 - 1)}
    for name, error in conversion_errors.items():
        study.check(name, "units", error, ROUNDOFF)


def check_well_mixed_cases(study):
    """0D zero-input, purge decay, closed batch and pulse cases against exact answers."""
    for case_name in ("zero-0d", "purge-0d", "closed-batch", "pulse-0d"):
        p, s, identifier = study.case(case_name)
        surface = FiniteCapacity(p["capacity"], p["capture_velocity"])
        reactor = WellMixedReactor(p["volume"], p["reactive_area"], p["throughput"])
        initials = s.get("initial_concentrations", [p["initial_c"]])
        for i, c0 in enumerate(initials):
            label = f"{case_name}_{i}"
            if case_name == "pulse-0d":
                segments = [FlowSegment(p["pulse_duration"], p["inlet_molar_flow"]),
                            FlowSegment(p["purge_duration"], 0.)]
            else:
                segments = [FlowSegment(p["duration"], 0.)]
            duration = sum(x.duration for x in segments)
            result = solve_0d(reactor, surface, segments, concentration_scale=p["concentration_scale"],
                initial_c=c0, initial_theta=p["initial_theta"], options=options(s), provenance_id=identifier,
                output_times=np.linspace(0, duration, s["output_samples"]))
            study.record(label, result, p["concentration_scale"])

            if case_name == "zero-0d":
                # no gas in and none present, so nothing may change
                study.check("0D zero gas", "analytical cases",
                    np.max(np.abs(result.c)) / p["concentration_scale"], EXACT)
                study.check("0D zero-input theta change", "analytical cases",
                    np.max(np.abs(result.theta - p["initial_theta"])), EXACT)
            elif case_name == "purge-0d":
                # a nonreacting purge decays as c0 exp(-Q t / V)
                exact = c0 * np.exp(-reactor.throughput / reactor.volume * result.t)
                study.check("0D purge over ten residence times", "analytical cases",
                    np.max(np.abs(result.c[:, 0] - exact)) / c0, 1e-7)
                study.data["purge_exact"] = exact
                study.data["purge_actual"] = result.c[:, 0]
            elif case_name == "closed-batch":
                # closed box: gas plus surface moles stay constant, coverage ends at dose / capacity
                gas = reactor.volume * result.c[:, 0]
                bound = reactor.reactive_area * surface.capacity * result.theta[:, 0]
                inventory = gas + bound
                target = min(1., p["initial_theta"] + reactor.volume * c0 / (reactor.reactive_area * surface.capacity))
                study.check(label + " total inventory", "conservation",
                    np.max(np.abs(inventory - inventory[0])) / inventory[0], LEDGER)
                study.check(label + " dose/capacity endpoint", "analytical cases",
                    abs(result.theta[-1, 0] - target), 1e-6)


def check_surface_saturation(study):
    """fixed-exposure coverage against 1 - (1 - theta0) exp(-lambda t)."""
    p, s, identifier = study.case("surface-saturation")
    surface = FiniteCapacity(p["capacity"], p["capture_velocity"])
    lam = surface.capture_velocity * p["inlet_concentration"] / surface.capacity
    duration = s["e_folding_times"] / lam
    t = np.linspace(0, duration, s["output_samples"])

    def coverage_rate(t, y):
        """dtheta/dt at the fixed inlet concentration."""
        return surface.rate(p["inlet_concentration"], y) / surface.capacity

    result = solve_ivp(coverage_rate, (0, duration), [p["initial_theta"]], method="Radau",
        rtol=s["rtol"], atol=s["atol"], t_eval=t)
    if not result.success:
        raise RuntimeError(result.message)
    exact = 1 - (1 - p["initial_theta"]) * np.exp(-lam * t)
    study.check("prescribed-exposure saturation", "analytical cases", np.max(np.abs(result.y[0] - exact)), 1e-7)
    study.data.update(saturation_t=t, saturation_actual=result.y[0], saturation_exact=exact)


def check_zero_input_1d(study, reactor, p, s, identifier):
    """1D channel with no gas in: gas and coverage must not move."""
    empty = solve_1d(reactor, FiniteCapacity(p["capacity"], p["capture_velocity"]),
        [TransportSegment(1., FluxBoundary(0.))], concentration_scale=1., initial_theta=.3,
        options=options(s), provenance_id=identifier)
    study.record("zero_1d", empty, 1.)
    change = max(np.max(np.abs(empty.c)), np.max(np.abs(empty.theta - .3)))
    study.check("1D zero input", "analytical cases", change, EXACT)


def check_constant_solution(study, reactor, s, identifier):
    """equal fixed boundaries keep a uniform gas field uniform for any flow direction."""
    boundary_errors = []
    for u in (1., -1., 0.):
        flowing = replace(reactor, velocity=u)
        uniform = solve_1d(flowing, FiniteCapacity(1., 0.), [TransportSegment(.3, ConcentrationBoundary(1., 1.))],
            concentration_scale=1., initial_c=1., initial_theta=.3, options=options(s), provenance_id=identifier)
        study.record(f"constant_u{u:g}", uniform, 1., upper_bound=True)
        boundary_errors.append(float(np.max(np.abs(uniform.c - 1.))))
    study.check("equal fixed boundaries preserve constant solution", "boundary conditions",
        max(boundary_errors), EXACT)


def check_boundary_faces(study, reactor):
    """face fluxes at the inlet and outlet match the imposed boundary values."""
    c = np.linspace(.2, .8, reactor.cells)

    # a flux inlet sets the total inlet face flux, the outlet carries advection only
    flux = face_fluxes(c, reactor, FluxBoundary(.7))
    study.check("prescribed total inlet face flux", "boundary conditions",
        abs(flux[0] - .7 / reactor.area), ROUNDOFF)
    study.check("zero downstream diffusive flux", "boundary conditions",
        abs(flux[-1] - reactor.velocity * c[-1]), ROUNDOFF)

    # rebuild the imposed face concentrations from the diffusive part of each face flux.
    # this checks the half-cell distance and the signed advective donor independently.
    for u in (1., -1.):
        flowing = replace(reactor, velocity=u)
        bc = ConcentrationBoundary(.7, .1)
        flux = face_fluxes(c, flowing, bc)
        if u > 0:
            adv_l = u * bc.left
            adv_r = u * c[-1]
        else:
            adv_l = u * c[0]
            adv_r = u * bc.right
        left = c[0] + (flux[0] - adv_l) * flowing.dz / (2 * flowing.diffusivity)
        right = c[-1] - (flux[-1] - adv_r) * flowing.dz / (2 * flowing.diffusivity)
        study.check(f"fixed face concentrations u={u:g}", "boundary conditions",
            max(abs(left - bc.left), abs(right - bc.right)), ROUNDOFF)


def check_saturated_recapture(study, reactor, identifier):
    """a fully covered surface takes up nothing over repeated exposures."""
    segments = [TransportSegment(.2, FluxBoundary(1.)), TransportSegment(.2, FluxBoundary(0.)),
                TransportSegment(.2, FluxBoundary(1.))]
    saturated = solve_1d(reactor, FiniteCapacity(1., 10.), segments,
        concentration_scale=1., initial_theta=1., provenance_id=identifier)
    study.record("repeated_saturated_exposure", saturated, 1.)
    study.check("same precursor cannot recapture saturated capacity", "analytical cases",
        np.max(np.abs(saturated.theta - 1.)), EXACT)


def basic():
    """units, 0D exact cases, surface saturation and 1D boundary checks."""
    study = Study("basic")
    check_units(study)
    check_well_mixed_cases(study)
    check_surface_saturation(study)
    p, s, identifier = study.case("reacting-front")
    reactor = geometry(p, BASIC_CELLS)
    check_zero_input_1d(study, reactor, p, s, identifier)
    check_constant_solution(study, reactor, s, identifier)
    check_boundary_faces(study, reactor)
    check_saturated_recapture(study, reactor, identifier)
    return study.save(extra={"unit_reference_convention": {"T_ref_K": 273.15, "P_ref_Pa": 101325.,
        "status": "assumed arithmetic convention, not author-exact experimental input"}})


# ---------------------------------------------------------------- transport group

def without_grids(settings):
    """copy of a settings dict without its grids entry."""
    kept = {}
    for key, value in settings.items():
        if key != "grids":
            kept[key] = value
    return kept


def load_transport(study):
    """reload a previous transport run into study, return (histories, prior acceptance, elapsed)."""
    old = json.loads((OUT / "transport.json").read_text())
    if old["code_sha256"] != hashes():
        raise ValueError("Cannot reuse transport results after an engine change")

    # the final L1 acceptance rows are recomputed, so move the old ones aside
    old_acceptance = []
    for row in old["checks"]:
        if row["name"].endswith(" analytical pulse L1"):
            old_acceptance.append(row)
    kept_rows = []
    for row in old["checks"]:
        if row not in old_acceptance:
            kept_rows.append(row)
    prior_acceptance = old["extra"].get("prior_acceptance", []) + old_acceptance

    study.rows = kept_rows
    study.runs = old["runs"]
    study.configs = old["case_configs"].copy()
    data = {}
    with np.load(OUT / "transport.npz") as archive:
        for name in archive.files:
            data[name] = archive[name]
    study.data = data
    return old["extra"]["histories"], prior_acceptance, old["elapsed_seconds"]


def check_resumable(current, previous_config, s, entries):
    """a resumed case may only append grids, never change inputs or reorder old grids."""
    # settings are only compared when the parameters already match
    changed = current["parameters"] != previous_config["parameters"]
    if not changed:
        changed = without_grids(current["settings"]) != without_grids(previous_config["settings"])
    if changed:
        raise ValueError("Resumption permits grid extension only, not changed physical or numerical settings")
    old_grids = [e["cells"] for e in entries]
    if s["grids"][:len(old_grids)] != old_grids:
        raise ValueError("Existing grid history must be retained in order")


def has_grid(entries, cells):
    """true when the history already holds a run with this many cells."""
    for entry in entries:
        if entry["cells"] == cells:
            return True
    return False


def exact_pulse(p, faces, end_time):
    """exact cell-averaged nonreacting pulse, pure advection or with diffusion."""
    if p["diffusivity"] == 0:
        return advection_pulse_average(faces, end_time, p["pulse_duration"], p["velocity"])

    def profile(z):
        """analytical advection-diffusion pulse at position z."""
        return pulse_response(z, end_time, p["pulse_duration"], p["velocity"], p["diffusivity"])

    return cell_averages(profile, faces)


def transport(resume=False):
    """nonreacting pulses on refining grids against exact solutions."""
    study = Study("transport")
    histories = {}
    prior_acceptance = []
    previous_elapsed = 0.
    if resume:
        histories, prior_acceptance, previous_elapsed = load_transport(study)
    for case_name in ("transport-pulse", "diffusion-pulse", "advection-pulse"):
        previous_config = study.configs.get(case_name)
        p, s, identifier = study.case(case_name)
        entries = histories.get(case_name, [])
        if previous_config is not None:
            check_resumable(study.configs[case_name], previous_config, s, entries)
        for n in s["grids"]:
            # grids already in the history are not run again
            if has_grid(entries, n):
                continue
            print(f"{case_name}: {n} cells", flush=True)
            result = pulse_run(p, s, identifier, n, boundary=s["boundary"])
            faces = np.linspace(0, p["length"], n + 1)
            exact = exact_pulse(p, faces, result.t[-1])
            error = normalized_l1(result.c[-1] / p["inlet_concentration"], exact)
            name = f"{case_name}_{n}"
            study.record(name, result, p["concentration_scale"], upper_bound=True)
            study.check(name + " zero reaction theta", "analytical cases",
                np.max(np.abs(result.theta - p["initial_theta"])), EXACT)
            if p["diffusivity"] > 0:
                study.check(name + " Dnum/D", "numerical diffusion",
                    result.metadata["numerical_diffusivity_ratio"], NUMERICAL_DIFFUSION)
            study.data[name + "_exact"] = exact
            entries.append(dict(cells=n, dz=p["length"] / n, error=error))
            print(f"  normalized L1 = {error:.6g}", flush=True)
        study.check(case_name + " analytical pulse L1", "analytical cases",
            entries[-1]["error"], s["final_l1_tolerance"])
        histories[case_name] = entries
    return study.save(extra={"histories": histories, "prior_acceptance": prior_acceptance,
                             "reused_elapsed_seconds": previous_elapsed})


# ---------------------------------------------------------------- temporal group

def temporal():
    """reacting front with base and tight tolerances for Radau and BDF."""
    study = Study("temporal")
    p, s, identifier = study.case("reacting-front")
    results = {}
    for method in ("Radau", "BDF"):
        for tight in (False, True):
            if tight:
                name = f"{method}_tight"
            else:
                name = f"{method}_base"
            print("Temporal " + name, flush=True)
            result = pulse_run(p, s, identifier, s["temporal_cells"], boundary="flux", tight=tight, method=method)
            study.record(name, result, 1.)
            results[name] = result
        base = results[f"{method}_base"]
        tight = results[f"{method}_tight"]
        study.check(method + " temporal theta", "temporal convergence",
            np.max(np.abs(base.theta[-1] - tight.theta[-1])), TIME_REFINEMENT)
        study.check(method + " temporal uptake", "temporal convergence",
            abs(base.captured_moles[-1] / tight.captured_moles[-1] - 1), TIME_REFINEMENT)
    study.check("temporally refined Radau/BDF theta", "independent solver comparison",
        np.max(np.abs(results["Radau_tight"].theta[-1] - results["BDF_tight"].theta[-1])), TIME_REFINEMENT)
    return study.save()


# ---------------------------------------------------------------- spatial group

def spatial():
    """reacting front on refining grids, then a time check on the finest grid."""
    study = Study("spatial")
    p, s, identifier = study.case("reacting-front")
    previous = None
    history = []
    for n in s["grids"]:
        print(f"Reacting spatial grid: {n}", flush=True)
        result = pulse_run(p, s, identifier, n, boundary="flux", tight=True)
        study.record(f"reacting_{n}", result, 1.)
        front = front_position(result.z, result.theta[-1], s["front_theta"])
        entry = dict(cells=n, dz=p["length"] / n, front=front, uptake=float(result.captured_moles[-1]))
        study.check(f"reacting {n} Dnum/D", "numerical diffusion",
            result.metadata["numerical_diffusivity_ratio"], NUMERICAL_DIFFUSION)
        if previous is not None:
            # compare with the grid before, with this grid restricted onto that one
            restricted = restrict_uniform(result.theta[-1], len(previous.z))
            theta_difference = float(np.max(np.abs(restricted - previous.theta[-1])))
            uptake_difference = float(abs(previous.captured_moles[-1] / result.captured_moles[-1] - 1))
            front_difference = abs(front - front_position(previous.z, previous.theta[-1])) / p["length"]
            entry.update(theta_difference=theta_difference, relative_uptake_difference=uptake_difference,
                front_difference=front_difference)
        history.append(entry)
        previous = result
    last = history[-1]
    study.check("last two reacting grids theta", "spatial convergence",
        last["theta_difference"], GRID_REFINEMENT)
    study.check("last two reacting grids uptake", "spatial convergence",
        last["relative_uptake_difference"], GRID_REFINEMENT)
    study.check("last two reacting grids front/L", "spatial convergence",
        last["front_difference"], GRID_REFINEMENT)

    # the finest grid again with the base tolerances
    base = pulse_run(p, s, identifier, s["grids"][-1], boundary="flux", tight=False)
    study.record("finest_grid_time_base", base, 1.)
    study.check("finest grid temporal theta", "temporal convergence",
        np.max(np.abs(base.theta[-1] - previous.theta[-1])), TIME_REFINEMENT)
    study.check("finest grid temporal uptake", "temporal convergence",
        abs(base.captured_moles[-1] / previous.captured_moles[-1] - 1), TIME_REFINEMENT)
    return study.save(extra={"history": history})


# ---------------------------------------------------------------- manufactured group

def operator_errors(reference, forcing, reactor, surface):
    """discrete operator residuals on exact cell averages at RESIDUAL_TIME, boundary cells kept."""
    cc, th = reference.averages(RESIDUAL_TIME, reactor.z, reactor.dz)
    dc, dt = reference.derivatives(RESIDUAL_TIME, reactor.z, reactor.dz)
    sg, st = forcing(RESIDUAL_TIME, reactor.z)
    rate = surface.rate(cc, th)
    residual = (-np.diff(face_fluxes(cc, reactor, ConcentrationBoundary(0., 0.))) / reactor.dz
        - reactor.reactive_perimeter / reactor.area * rate + sg - dc)
    residual_theta = rate / surface.capacity + st - dt
    return dict(operator_l1=float(np.mean(np.abs(residual))),
        operator_interior_l1=float(np.mean(np.abs(residual[1:-1]))),
        operator_boundary_max=float(np.max(np.abs(residual[[0, -1]]))),
        surface_operator_l1=float(np.mean(np.abs(residual_theta))))


def manufactured():
    """manufactured sine solution: observed convergence order against the expected one."""
    study = Study("manufactured")
    p, s, identifier = study.case("manufactured")
    reference = ManufacturedSolution(p["length"], p["concentration_scale"], p["decay"],
        p["base_theta"], p["theta_amplitude"])
    histories = {}
    for u in s["velocities"]:
        entries = []
        for n in s["grids"]:
            print(f"MMS u={u}, N={n}", flush=True)
            r = geometry(p | {"velocity": u}, n)
            surface = FiniteCapacity(p["capacity"], p["capture_velocity"])

            def forcing(t, z):
                """cell-averaged source that makes the sine solution exact."""
                return reference.source_averages(t, z, r.dz, velocity=u, diffusivity=r.diffusivity,
                    area_ratio=r.reactive_perimeter / r.area, capture_velocity=surface.capture_velocity,
                    capacity=surface.capacity)

            c0, theta0 = reference.averages(0., r.z, r.dz)
            result = solve_1d(r, surface, [TransportSegment(p["duration"], ConcentrationBoundary(0., 0.))],
                concentration_scale=p["concentration_scale"], initial_c=c0, initial_theta=theta0,
                artificial_source=forcing, source_id="continuous-sine-MMS-analytic-cell-averages-v1",
                options=options(s, tight=True), provenance_id=identifier,
                output_times=np.linspace(0, p["duration"], s["output_samples"]))
            name = f"mms_u{u:g}_{n}"
            study.record(name, result, p["concentration_scale"], source=True)
            cexact, thexact = reference.averages(p["duration"], r.z, r.dz)
            operator = operator_errors(reference, forcing, r, surface)
            entry = dict(cells=n, dz=r.dz, c_error=normalized_l1(result.c[-1], cexact),
                theta_error=float(np.mean(np.abs(result.theta[-1] - thexact))), **operator)

            # observed order from the error ratio with the grid before (each grid halves dz)
            if entries:
                for key in ("c_error", "theta_error", "operator_l1"):
                    entry[key + "_order"] = float(np.log2(entries[-1][key] / entry[key]))
            entries.append(entry)
            study.data[name + "_exact_c"] = cexact
            study.data[name + "_exact_theta"] = thexact

        # first order with advection, second order for pure diffusion
        if u:
            expected = s["expected_order_advection"]
        else:
            expected = s["expected_order_diffusion"]
        for key in ("c_error", "theta_error", "operator_l1"):
            observed = entries[-1][key + "_order"]
            study.check(f"MMS u={u:g} {key} order", "spatial convergence", abs(observed - expected),
                s["order_tolerance"], observed=observed, expected=expected)
        histories[str(u)] = entries
    return study.save(extra={"histories": histories})


# ---------------------------------------------------------------- truncation group

def truncation():
    """a 10L and a 20L domain must agree on [0, L] while a front is still moving."""
    study = Study("truncation")
    p, s, identifier = study.case("domain-truncation")
    base_cells = s["cells_per_base_length"]
    results = []
    for extension in s["extensions"]:
        values = p | {"length": p["base_length"] * extension}
        n = base_cells * extension
        print(f"Truncation {extension}L, {n} cells", flush=True)
        result = pulse_run(values, s, identifier, n)
        study.record(f"domain_{extension}L", result, 1., upper_bound=True)
        results.append(result)
    a, b = results
    if not np.array_equal(a.t, b.t) or not np.array_equal(a.z[:base_cells], b.z[:base_cells]):
        raise ValueError("Truncation comparison requires matched physical times and cells")
    theta_diff = float(np.max(np.abs(a.theta[:, :base_cells] - b.theta[:, :base_cells])))
    study.check("10L versus 20L theta on [0,L]", "domain truncation", theta_diff, TRUNCATION)

    # the comparison must contain a reacting, partially completed front
    front = front_position(a.z[:base_cells], a.theta[-1, :base_cells])
    if a.captured_moles[-1] > 0:
        no_uptake = 0.
    else:
        no_uptake = 1.
    study.check("truncation case has nonzero uptake", "domain truncation", no_uptake, 0., front=front)
    study.data["truncation_t"] = a.t
    study.data["truncation_theta_difference"] = a.theta[:, :base_cells] - b.theta[:, :base_cells]
    return study.save(extra={"max_theta_difference": theta_diff, "front": front})


# ---------------------------------------------------------------- gate report

# fixed text of the gate report
LIMITATIONS = ["Synthetic mathematical verification only; no experimental validity.",
    "Constant coefficients and one finite-capacity half-cycle; no full-cycle/GPC/QCM closure.",
    "Bounds and ledger errors are checked at stored output times, not proven for every continuous time.",
    "Radau/BDF share the same spatial discretization; independent analytical/MMS evidence checks spatial accuracy.",
    "The full planned studies remain separate from any dimensional benchmark."]
EVIDENCE_COMMANDS = [".venv/bin/python -m pytest -q",
    "OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group all",
    "OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group transport --resume",
    "PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group report"]
GROUP_NOTE = ("The same studies may be run independently with --group basic, transport, temporal, spatial, "
    "manufactured, or truncation, followed by --group report.")
REFINEMENT_NOTE = ("The initial 4,000-cell advection-diffusion pulse error was 1.502977e-3, above the 1e-3 "
    "criterion. The same case was extended to 8,000 cells. The original failed attempt and runner are "
    "preserved under attempt-1/; no physical input or tolerance was changed.")
CONSERVATION_COLUMNS = ["study", "run", "max_relative_ledger", "max_absolute_ledger", "final_entered",
    "final_escaped", "final_capture"]


def pass_word(passed):
    """PASS or FAIL."""
    if passed:
        return "PASS"
    return "FAIL"


def load_documents():
    """read every group's json and refuse any that is stale against the source or configs."""
    documents = {}
    for group in GROUPS:
        documents[group] = json.loads((OUT / f"{group}.json").read_text())
    current = hashes()
    for group, data in documents.items():
        if data["code_sha256"] != current:
            raise ValueError(f"Stale engine source for {group}; rerun affected study")
        for name, config in data["case_configs"].items():
            if config != json.loads((ROOT / f"config/synthetic/phase1-{name}.json").read_text()):
                raise ValueError(f"Changed case configuration for {group}/{name}")
    return documents, current


def gate_categories(documents, rows):
    """each gate category passes only if it has checks and all of them pass."""
    categories = {}
    for category in GATE_CATEGORIES:
        matching = [r for r in rows if r["category"] == category]
        categories[category] = bool(matching) and all(r["passed"] for r in matching)

    # a segment that did not start from the exact previous end state fails boundary conditions
    if not all_carried_over(documents):
        categories["boundary conditions"] = False
    return categories


def all_carried_over(documents):
    """true when every run in every group had exact segment carryover, stopping at the first that did not."""
    for data in documents.values():
        for run in data["runs"]:
            if not run["exact_segment_carryover"]:
                return False
    return True


def gate_markdown(gate, categories, rows):
    """lines of gate.md."""
    lines = ["# Phase 1 gate", "", "```text", "PHASE 1 GATE", ""]
    for category, passed in categories.items():
        lines.append(f"[{pass_word(passed)}] {category}")
    lines += ["", f"Decision: {gate}", "```", "", "All cases use explicitly synthetic inputs.", "",
        "## Evidence", "", "Commands executed from the project directory:", "", "```sh"]
    lines += EVIDENCE_COMMANDS
    lines += ["```", "", GROUP_NOTE, "",
        "| Check | Error or deviation | Criterion | Result |", "|---|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['error']:.6e} | {r['tolerance']:.2e} | {pass_word(r['passed'])} |")
    lines += ["", "## Refinement diagnosis", "", REFINEMENT_NOTE, "", "## Material limitations", ""]
    for x in LIMITATIONS:
        lines.append(f"- {x}")

    failures = [r["name"] for r in rows if not r["passed"]]
    if failures:
        blocking = "\n".join(f"- {x}" for x in failures)
    else:
        blocking = "None for this mathematical gate."
    lines += ["", "## Blocking issues", "", blocking, "",
              "Phase 2 has not started. Stop here for the next phase instruction.", ""]
    return lines


def write_conservation(documents):
    """one conservation.csv row per run across every group."""
    with (OUT / "conservation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CONSERVATION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for group, data in documents.items():
            for run in data["runs"]:
                row = dict(study=group, run=run["name"])
                for key in CONSERVATION_COLUMNS[2:]:
                    row[key] = run[key]
                writer.writerow(row)


def report():
    """combine every group into gate.json, gate.md, conservation.csv and the figures."""
    documents, current = load_documents()
    rows = []
    for data in documents.values():
        rows.extend(data["checks"])
    categories = gate_categories(documents, rows)
    if all(categories.values()):
        gate = "PASS"
    else:
        gate = "FAIL"
    total_elapsed = 0
    for d in documents.values():
        total_elapsed += d["elapsed_seconds"] + d["extra"].get("reused_elapsed_seconds", 0.)
    payload = dict(decision=gate, categories=categories, checks=rows, code_sha256=current,
        limitations=LIMITATIONS, total_elapsed_seconds=total_elapsed)
    (OUT / "gate.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT / "gate.md").write_text("\n".join(gate_markdown(gate, categories, rows)))
    write_conservation(documents)
    figures(documents)
    print(json.dumps(dict(decision=gate, categories=categories, checks=len(rows))), flush=True)
    return gate == "PASS"


# ---------------------------------------------------------------- figures

def analytical_figure(plt, NullFormatter, documents):
    """L1 error against cells for the three nonreacting pulses."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), layout="constrained")
    transport_history = documents["transport"]["extra"]["histories"]
    for ax, (name, entries) in zip(axes, transport_history.items()):
        cells = [x["cells"] for x in entries]
        ax.loglog(cells, [x["error"] for x in entries], "o-", label="Measured spatial L1")
        if name == "advection-pulse":
            tol = 1e-2
        else:
            tol = 1e-3
        ax.axhline(tol, color="firebrick", ls="--", label="Acceptance criterion")
        ax.set(title=name.replace("-", " "), xlabel="Cells", ylabel="Normalized L1 error")
        ax.set_xticks(cells, labels=[f"{x['cells']:,}" for x in entries])
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.legend(fontsize=8)
    fig.suptitle("Nonreacting analytical pulse verification — synthetic cases")
    fig.savefig(FIGURES / "analytical-convergence.png")
    plt.close(fig)


def manufactured_figure(plt, NullFormatter, documents):
    """gas and coverage error against cell width for each manufactured velocity."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for u, entries in documents["manufactured"]["extra"]["histories"].items():
        widths = [e["dz"] for e in entries]
        for ax, key, label in zip(axes, ["c_error", "theta_error"], ["Gas normalized L1", "Coverage absolute L1"]):
            ax.loglog(widths, [e[key] for e in entries], "o-", label=f"u={u} m/s")
            ax.set(xlabel="Cell width (m)", ylabel=label)
            ax.set_xticks(widths, labels=[f"{e['dz']:.6g}" for e in entries])
            ax.xaxis.set_minor_formatter(NullFormatter())
            ax.legend()
    fig.suptitle("Continuous manufactured solution — first-order advection / second-order diffusion")
    fig.savefig(FIGURES / "manufactured-convergence.png")
    plt.close(fig)


def reacting_figure(plt, NullFormatter, documents):
    """final coverage on each grid and the differences between successive grids."""
    arrays = np.load(OUT / "spatial.npz")
    history = documents["spatial"]["extra"]["history"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    fig.suptitle("Synthetic single-half-cycle spatial convergence")
    for entry in history:
        name = f"reacting_{entry['cells']}"
        axes[0].plot(arrays[name + "_z"], arrays[name + "_theta"], label=f"N={entry['cells']}")
    axes[0].axhline(.5, color="grey", ls="--", lw=.8)
    axes[0].set(xlabel="z (m)", ylabel="Occupied capacity", title="Reacting pulse/purge at 1.75 s")
    axes[0].legend()

    # differences exist from the second grid on
    refined = history[1:]
    fine_cells = [h["cells"] for h in refined]
    differences = [("theta_difference", "Max coverage"), ("relative_uptake_difference", "Relative uptake"),
        ("front_difference", "Front / L")]
    for key, label in differences:
        axes[1].loglog(fine_cells, [h[key] for h in refined], "o-", label=label)
    axes[1].axhline(GRID_REFINEMENT, color="firebrick", ls="--", label="Criterion")
    axes[1].set(xlabel="Fine-grid cells", ylabel="Difference between successive grids",
        title="Actual spatial convergence")
    axes[1].set_xticks(fine_cells, labels=[f"{h['cells']:,}" for h in refined])
    axes[1].xaxis.set_minor_formatter(NullFormatter())
    axes[1].legend(fontsize=8)
    fig.savefig(FIGURES / "reacting-convergence.png")
    plt.close(fig)


def time_and_truncation_figure(plt, documents):
    """temporal and solver-comparison errors, and the truncation difference over time."""
    temporal_rows = []
    for x in documents["temporal"]["checks"]:
        if x["category"] in ("temporal convergence", "independent solver comparison"):
            temporal_rows.append(x)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")

    # errors are floored so an exact zero still shows on the log axis
    axes[0].barh([x["name"] for x in temporal_rows], [max(x["error"], 1e-16) for x in temporal_rows])
    axes[0].axvline(TIME_REFINEMENT, color="firebrick", ls="--")
    axes[0].set(xscale="log", xlabel="Error (absolute coverage / relative uptake)",
        title="Temporal refinement and solver comparison")

    trunc = np.load(OUT / "truncation.npz")
    axes[1].plot(trunc["truncation_t"], np.max(np.abs(trunc["truncation_theta_difference"]), axis=1))
    axes[1].axhline(TRUNCATION, color="firebrick", ls="--", label="Criterion")
    axes[1].set(xlabel="Time (s)", ylabel="Max |theta_10L - theta_20L| on [0,L]",
        title="Nontrivial reacting domain truncation")
    axes[1].set_yscale("symlog", linthresh=1e-12)
    axes[1].legend()
    fig.savefig(FIGURES / "time-and-truncation.png")
    plt.close(fig)


def figures(documents):
    """draw the four phase 1 figures from the saved group results."""
    # matplotlib is imported here so the study groups never need it
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "work/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": .2, "figure.dpi": 160})
    analytical_figure(plt, NullFormatter, documents)
    manufactured_figure(plt, NullFormatter, documents)
    reacting_figure(plt, NullFormatter, documents)
    time_and_truncation_figure(plt, documents)


# ---------------------------------------------------------------- command line

def main():
    """run the chosen group, or every group then the report, and exit 1 on any failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=[*GROUPS, "report", "all"], default="all")
    parser.add_argument("--resume", action="store_true",
        help="For transport only: reuse unchanged levels and compute appended grids")
    args = parser.parse_args()
    if args.resume and args.group != "transport":
        parser.error("--resume applies only to --group transport")
    functions = {"basic": basic, "transport": transport, "temporal": temporal, "spatial": spatial,
                 "manufactured": manufactured, "truncation": truncation, "report": report}
    if args.group == "all":
        selected = [*GROUPS, "report"]
    else:
        selected = [args.group]

    # every selected group runs, even after an earlier one fails
    succeeded = True
    for group in selected:
        if args.resume:
            passed = transport(resume=True)
        else:
            passed = functions[group]()
        succeeded = passed and succeeded
    if succeeded:
        raise SystemExit(0)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
