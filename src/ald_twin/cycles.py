"""One effective two-event ALD cycle, shared by mixed and spatial reactors."""

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json
import platform

import numpy as np
import scipy
from scipy.sparse import lil_matrix

from .cycle_transport import composition_fluxes
from .numerics import Integrated, SolverOptions, integrate_segments
from .results import json_native
from .units import _nonnegative, _positive

# Formula-based molar masses [kg/mol]; both events together retain one ZnO.
M_DEZ = (65.38 + 4*12.011 + 10*1.008) / 1000
M_WATER = (2*1.008 + 15.999) / 1000
M_ETHANE = (2*12.011 + 6*1.008) / 1000
M_ZNO = (65.38 + 15.999) / 1000
M_RETAINED_A = M_DEZ - M_ETHANE
M_RETAINED_B = M_WATER - M_ETHANE


@dataclass(frozen=True)
class CycleChemistry:
    """Gamma [mol/m²], kA and kB [m³/(mol s)] for the effective nu=1 loop."""

    capacity: float
    rate_a: float
    rate_b: float

    def __post_init__(self):
        _positive(self.capacity, "capacity")
        _nonnegative(self.rate_a, "kA")
        _nonnegative(self.rate_b, "kB")

    def rates(self, concentration, theta):
        return self.capacity * np.array([self.rate_a * concentration[0] * (1 - theta),
                                         self.rate_b * concentration[1] * theta])


@dataclass(frozen=True)
class CycleSegment:
    """Duration [s] and the two precursor inlet rates [mol/s]."""

    duration: float
    inlet_a: float
    inlet_b: float
    label: str = ""

    def __post_init__(self):
        _positive(self.duration, "segment duration")
        _nonnegative(self.inlet_a, "A inlet")
        _nonnegative(self.inlet_b, "B inlet")


@dataclass
class CycleResult:
    integrated: Integrated
    grid: object
    chemistry: CycleChemistry
    fraction_scale: float
    initial_state: np.ndarray
    history: list
    settings: dict
    periodic: bool = False

    @property
    def fields(self):
        # Five cell fields: xA/scale, xB/scale, theta, EA/Gamma, EB/Gamma.
        return self.integrated.y[:5 * len(self.grid.z)].reshape(5, len(self.grid.z), -1).transpose(0, 2, 1)

    @property
    def inventory_scale(self):
        return float(self.grid.carrier_moles.sum() * self.fraction_scale)

    @property
    def gas_moles(self):
        return (self.fields[:2] * self.fraction_scale) @ self.grid.carrier_moles

    @property
    def events(self):
        return self.fields[3:5] * self.chemistry.capacity

    @property
    def entered(self):
        return self.integrated.y[-4:-2] * self.inventory_scale

    @property
    def escaped(self):
        return self.integrated.y[-2:] * self.inventory_scale

    @property
    def turnover(self):
        return self.fields[4, -1] - self.fields[4, 0]

    def checks(self):
        n = len(self.grid.z)
        initial = self.initial_state[:5*n].reshape(5, n)
        initial_gas = initial[:2] * self.fraction_scale @ self.grid.carrier_moles
        entered = self.entered - self.initial_state[-4:-2, None] * self.inventory_scale
        escaped = self.escaped - self.initial_state[-2:, None] * self.inventory_scale
        consumed = ((self.fields[3:5] - initial[3:5, None]) * self.chemistry.capacity) @ self.grid.reactive_areas
        inventory = initial_gas[:, None] + entered
        residual = inventory - self.gas_moles - consumed - escaped
        positive = inventory > 0
        relative = float(np.max(np.abs(residual[positive]) / inventory[positive], initial=0))
        zero = float(np.max(np.abs(residual[~positive]), initial=0) / self.inventory_scale)
        event_error = self.fields[3] - initial[3] - self.fields[4] + initial[4] - self.fields[2] + initial[2]
        ceiling = np.asarray(self.settings["maximum_scaled_fraction"])
        bounds = max(0., float(-self.fields[:3].min()), float(self.fields[2].max() - 1),
                     float(np.max(self.fields[:2] - ceiling[:, None, None])))
        carryover = all(a["end_state"] == b["start_state"] for a, b in
                        zip(self.integrated.segments, self.integrated.segments[1:]))
        return dict(relative_ledger=relative, zero_inventory_residual=zero,
                    event_balance=float(np.max(np.abs(event_error))), bounds=bounds,
                    exact_segment_carryover=carryover,
                    maximum_trace_fraction=float((self.fields[:2].sum(axis=0) * self.fraction_scale).max()))

    def save(self, stem):
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(stem) + ".npz", t=self.integrated.t, z=self.grid.z,
                            scaled_state=self.integrated.y, initial_state=self.initial_state,
                            carrier_moles=self.grid.carrier_moles, reactive_areas=self.grid.reactive_areas)
        data = dict(kind="synthetic", physical_fit_performed=False, periodic=self.periodic,
                    chemistry=asdict(self.chemistry), grid=self.grid.metadata,
                    fraction_scale=self.fraction_scale, checks=self.checks(),
                    history=self.history, settings=self.settings, segments=self.integrated.segments,
                    units=dict(time="s", position="m", fraction="1", events="mol/m²",
                               gas_accounting="mol", retained_mass="kg/m²"))
        Path(str(stem) + ".json").write_text(json.dumps(json_native(data), indent=2, allow_nan=False) + "\n")


def cycle_sparsity(cells):
    """Neighbor transport and local chemistry; cumulative ledgers do not feed back."""
    pattern = lil_matrix((5*cells + 4, 5*cells + 4), dtype=int)
    for j in range(cells):
        for species in range(2):
            row = species*cells + j
            pattern[row, species*cells + max(0, j-1):species*cells + min(cells, j+2)] = 1
            pattern[row, 2*cells+j] = 1
        for field in (2, 3, 4):
            pattern[field*cells+j, [j, cells+j, 2*cells+j]] = 1
    pattern[-2, cells-1] = 1
    pattern[-1, 2*cells-1] = 1
    return pattern.tocsr()


def initial_state(grid, *, fraction_scale, fractions=0., theta=0.):
    _positive(fraction_scale, "fraction scale")
    n = len(grid.z)
    fractions = np.broadcast_to(np.asarray(fractions, dtype=float), (2, n))
    theta = np.broadcast_to(np.asarray(theta, dtype=float), (n,))
    if not np.isfinite(fractions).all() or np.any(fractions < 0):
        raise ValueError("Initial precursor fractions must be finite and nonnegative")
    if not np.isfinite(theta).all() or np.any(theta < 0) or np.any(theta > 1):
        raise ValueError("Initial theta must be in [0,1]")
    return np.r_[fractions.ravel()/fraction_scale, theta, np.zeros(2*n + 4)]


def purge_event(cells, threshold):
    """Track downward crossings independently of the retained plot samples."""
    def event(_time, state):
        value = float(state[:2*cells].reshape(2, cells).sum(axis=0).max()) - threshold
        if value > 0:
            event.was_above = True
        return value
    event.direction = -1
    event.was_above = False
    return event


def purge_clearance(event, segment, cells, threshold):
    end = np.asarray(segment["end_state"][:2*cells]).reshape(2, cells).sum(axis=0).max()
    if end > threshold:
        return None
    if not event.was_above:
        return 0.
    if not segment["event_times"]:
        raise ValueError("Purge became clear without a recorded downward event")
    return float(segment["event_times"][-1] - segment["start"])


def solve_cycle(grid, chemistry, segments, *, fraction_scale, state=None,
                options=SolverOptions(), output_times=None, purge_threshold=.01):
    """Integrate one recipe, preserving every gas, surface and accounting state."""
    _positive(fraction_scale, "fraction scale")
    _positive(purge_threshold, "scaled purge threshold")
    segments = tuple(segments)
    if not segments or not all(isinstance(s, CycleSegment) for s in segments):
        raise ValueError("A nonempty sequence of CycleSegment is required")
    n = len(grid.z)
    start = initial_state(grid, fraction_scale=fraction_scale) if state is None else np.asarray(state, dtype=float).copy()
    if start.shape != (5*n + 4,) or not np.isfinite(start).all():
        raise ValueError("Invalid scaled cycle state")
    if np.min(start[:3*n]) < -1e-8 or np.max(start[2*n:3*n]) > 1+1e-8:
        raise ValueError("Initial gas/surface state violates its bounds")
    if grid.molar_flow == 0 and any(s.inlet_a or s.inlet_b for s in segments):
        raise ValueError("The closed-batch limit requires zero inlet")
    inventory = grid.carrier_moles * fraction_scale
    total_inventory = float(inventory.sum())

    def rhs_factory(index):
        inlet = np.array([segments[index].inlet_a, segments[index].inlet_b])

        def rhs(_time, y):
            fields = y[:5*n].reshape(5, n)
            fractions = fields[:2] * fraction_scale
            rates = chemistry.rates(fractions * grid.carrier_concentration, fields[2])
            flux = composition_fluxes(fractions, grid, inlet)
            change = np.empty_like(fields)
            change[:2] = (-np.diff(flux) - grid.reactive_areas * rates) / inventory
            # Inert cells carry no surface population or event inventory.
            events = rates / chemistry.capacity * (grid.reactive_areas > 0)
            change[2] = events[0] - events[1]
            change[3:5] = events
            entered = np.maximum(flux[:, 0], 0) + np.maximum(-flux[:, -1], 0)
            escaped = np.maximum(-flux[:, 0], 0) + np.maximum(flux[:, -1], 0)
            return np.r_[change.ravel(), entered/total_inventory, escaped/total_inventory]

        return rhs

    events = [purge_event(n, purge_threshold) if s.inlet_a == s.inlet_b == 0 else None for s in segments]
    integrated = integrate_segments(start, [s.duration for s in segments], rhs_factory, options,
                                    jac_sparsity=cycle_sparsity(n), output_times=output_times,
                                    events_factory=lambda index: events[index])
    for event, segment in zip(events, integrated.segments):
        if event is not None:
            segment["purge_clearance_s"] = purge_clearance(event, segment, n, purge_threshold)
    initial_fractions = start[:2*n].reshape(2, n).max(axis=1)
    inlet = np.array([[s.inlet_a, s.inlet_b] for s in segments]).max(axis=0)
    ceiling = initial_fractions if grid.molar_flow == 0 else np.maximum(
        initial_fractions, inlet / (grid.molar_flow * fraction_scale))
    settings = dict(recipe=[asdict(s) for s in segments], solver=asdict(options),
                    purge_readout=dict(method="continuous_solver_event", scaled_threshold=purge_threshold),
                    maximum_scaled_fraction=ceiling.tolist(),
                    runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__))
    if np.isinf(options.max_step):
        settings["solver"]["max_step"] = "unbounded"
    return CycleResult(integrated, grid, chemistry, fraction_scale, start, [], settings)


class PeriodicFailure(RuntimeError):
    def __init__(self, result):
        super().__init__(f"No recurring cycle after {len(result.history)} cycles")
        self.result = result


def periodic_cycle(grid, chemistry, segments, *, fraction_scale, options=SolverOptions(),
                   max_cycles=200, tolerance=1e-7, output_times=None, state=None, accounting_origin=None):
    """Find repeating gas/surface states while cumulative growth keeps increasing."""
    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 2:
        raise ValueError("max_cycles must be an integer >= 2")
    _positive(tolerance, "periodic tolerance")
    if grid.reactive_areas.sum() <= 0:
        raise ValueError("Recurring growth requires positive reactive area")
    n = len(grid.z)
    first = initial_state(grid, fraction_scale=fraction_scale) if state is None else np.asarray(state).copy()
    # A continued run keeps its original ledger origin. Subtracting large old
    # counters from an almost-empty purge inventory otherwise loses precision.
    origin = first if accounting_origin is None else np.asarray(accounting_origin, dtype=float).copy()
    if origin.shape != first.shape or not np.isfinite(origin).all():
        raise ValueError("Invalid original accounting state")
    state = first.copy()
    history = []
    previous_turnover = None
    for cycle in range(1, max_cycles + 1):
        result = solve_cycle(grid, chemistry, segments, fraction_scale=fraction_scale,
                             state=state, options=options, output_times=output_times)
        finish = result.integrated.y[:, -1]
        state_error = float(np.max(np.abs(finish[:3*n] - state[:3*n])))
        growth_error = None if previous_turnover is None else float(np.max(np.abs(result.turnover - previous_turnover)))
        result = replace(result, initial_state=origin, history=history)
        checks = result.checks()
        if (checks["relative_ledger"] > 1e-8 or checks["zero_inventory_residual"] > 1e-10
                or checks["event_balance"] > 1e-8 or checks["bounds"] > 1e-8
                or not checks["exact_segment_carryover"]):
            raise ValueError(f"Cycle conservation/bounds check failed: {checks}")
        history.append(dict(cycle=cycle, state_error=state_error, growth_error=growth_error,
                            turnover_mean=float(np.average(result.turnover, weights=grid.reactive_areas)),
                            checks=checks))
        if growth_error is not None and state_error <= tolerance and growth_error <= tolerance:
            result.periodic = True
            return result
        previous_turnover = result.turnover.copy()
        state = finish.copy()
    raise PeriodicFailure(result)


def periodic_gpc(result, density):
    """Equivalent ZnO Å/cycle; this synthetic output is not experimental GPC."""
    _positive(density, "film density [kg/m³]")
    if not result.periodic:
        raise ValueError("Growth per recurring cycle requires periodic convergence")
    if result.grid.metadata["parameters"]["channel"]["temperature"] != 423.15:
        raise ValueError("The current density mapping is limited to 150 C")
    return 1e10 * M_ZNO / density * result.chemistry.capacity * result.turnover
