"""one effective two-event ALD cycle, shared by mixed and spatial reactors."""

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

# ---- molar masses
# standard atomic weights [g/mol]
ATOMIC_MASS_ZN = 65.38
ATOMIC_MASS_C = 12.011
ATOMIC_MASS_H = 1.008
ATOMIC_MASS_O = 15.999
GRAMS_PER_KG = 1000

# formula-based molar masses [kg/mol]. both events together retain one ZnO:
# the A event keeps DEZ minus one ethane, the B event keeps water minus one ethane
M_DEZ = (ATOMIC_MASS_ZN + 4*ATOMIC_MASS_C + 10*ATOMIC_MASS_H) / GRAMS_PER_KG
M_WATER = (2*ATOMIC_MASS_H + ATOMIC_MASS_O) / GRAMS_PER_KG
M_ETHANE = (2*ATOMIC_MASS_C + 6*ATOMIC_MASS_H) / GRAMS_PER_KG
M_ZNO = (ATOMIC_MASS_ZN + ATOMIC_MASS_O) / GRAMS_PER_KG
M_RETAINED_A = M_DEZ - M_ETHANE
M_RETAINED_B = M_WATER - M_ETHANE

# ---- scaled state layout
# for n cells the state holds five fields of n values each, in this order:
#   xA/scale, xB/scale, theta, EA/Gamma, EB/Gamma
# followed by four cumulative ledger totals, divided by the inventory scale:
#   entered A, entered B, escaped A, escaped B
CELL_FIELDS = 5
LEDGER_SIZE = 4
GAS = slice(0, 2)
THETA = 2
EVENT_A = 3
EVENT_B = 4
EVENTS = slice(3, 5)
ENTERED = slice(-4, -2)
ESCAPED = slice(-2, None)

# ---- numerical acceptance limits
# gas and theta bounds may be missed by this much
BOUNDS_TOLERANCE = 1e-8
# largest relative gas ledger residual accepted in a recurring-cycle search
LEDGER_TOLERANCE = 1e-8
# largest ledger residual, over the inventory scale, where nothing entered
ZERO_INVENTORY_TOLERANCE = 1e-10
# largest mismatch between the two event counters and theta
EVENT_TOLERANCE = 1e-8

# ---- growth readout
ANGSTROM_PER_METER = 1e10
# the film density mapping is only set up at 150 C
GPC_TEMPERATURE_K = 423.15


# ---- chemistry and recipe inputs

@dataclass(frozen=True)
class CycleChemistry:
    """Gamma [mol/m²], kA and kB [m³/(mol s)] for the effective nu=1 loop."""

    capacity: float
    rate_a: float
    rate_b: float

    def __post_init__(self):
        """check the capacity is positive and both rates are nonnegative."""
        _positive(self.capacity, "capacity")
        _nonnegative(self.rate_a, "kA")
        _nonnegative(self.rate_b, "kB")

    def rates(self, concentration, theta):
        """return the A and B surface event rates [mol/(m² s)].

        A reacts with free sites (1 - theta) and B with covered sites theta.
        """
        rate_a = self.rate_a * concentration[0] * (1 - theta)
        rate_b = self.rate_b * concentration[1] * theta
        return self.capacity * np.array([rate_a, rate_b])


@dataclass(frozen=True)
class CycleSegment:
    """duration [s] and the two precursor inlet rates [mol/s]."""

    duration: float
    inlet_a: float
    inlet_b: float
    label: str = ""

    def __post_init__(self):
        """check the duration is positive and both inlet rates are nonnegative."""
        _positive(self.duration, "segment duration")
        _nonnegative(self.inlet_a, "A inlet")
        _nonnegative(self.inlet_b, "B inlet")


# ---- cycle result

@dataclass
class CycleResult:
    """an integrated recipe with its grid, chemistry and scaled start state."""

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
        """the five cell fields, shaped (field, time, cell)."""
        n = len(self.grid.z)
        cell_values = self.integrated.y[:CELL_FIELDS * n]
        return cell_values.reshape(CELL_FIELDS, n, -1).transpose(0, 2, 1)

    @property
    def inventory_scale(self):
        """total carrier moles times the fraction scale [mol]."""
        return float(self.grid.carrier_moles.sum() * self.fraction_scale)

    @property
    def gas_moles(self):
        """moles of A and B in the gas over time [mol]."""
        return (self.fields[GAS] * self.fraction_scale) @ self.grid.carrier_moles

    @property
    def events(self):
        """cumulative A and B events per area [mol/m²], shaped (event, time, cell)."""
        return self.fields[EVENTS] * self.chemistry.capacity

    @property
    def entered(self):
        """cumulative moles of A and B that entered the reactor [mol]."""
        return self.integrated.y[ENTERED] * self.inventory_scale

    @property
    def escaped(self):
        """cumulative moles of A and B that left the reactor [mol]."""
        return self.integrated.y[ESCAPED] * self.inventory_scale

    @property
    def turnover(self):
        """B events per site in each cell between the first and last output time."""
        return self.fields[EVENT_B, -1] - self.fields[EVENT_B, 0]

    def checks(self):
        """return the ledger, event balance and bounds checks of this run."""
        n = len(self.grid.z)
        fields = self.fields
        initial = self.initial_state[:CELL_FIELDS*n].reshape(CELL_FIELDS, n)

        # gas ledger: start + entered = now + consumed + escaped, per species
        initial_gas = initial[GAS] * self.fraction_scale @ self.grid.carrier_moles
        entered = self.entered - self.initial_state[ENTERED, None] * self.inventory_scale
        escaped = self.escaped - self.initial_state[ESCAPED, None] * self.inventory_scale
        consumed = ((fields[EVENTS] - initial[EVENTS, None]) * self.chemistry.capacity) @ self.grid.reactive_areas
        inventory = initial_gas[:, None] + entered
        residual = inventory - self.gas_moles - consumed - escaped

        # relative residual where something was present, absolute where nothing was
        positive = inventory > 0
        relative = float(np.max(np.abs(residual[positive]) / inventory[positive], initial=0))
        zero = float(np.max(np.abs(residual[~positive]), initial=0) / self.inventory_scale)

        # every A event covers a site and every B event frees one
        event_error = (fields[EVENT_A] - initial[EVENT_A] - fields[EVENT_B] + initial[EVENT_B]
                       - fields[THETA] + initial[THETA])

        # worst bound miss: negative gas or theta, theta above one, gas above its ceiling
        ceiling = np.asarray(self.settings["maximum_scaled_fraction"])
        below_zero = float(-fields[:THETA + 1].min())
        theta_above_one = float(fields[THETA].max() - 1)
        gas_above_ceiling = float(np.max(fields[GAS] - ceiling[:, None, None]))
        bounds = max(0., below_zero, theta_above_one, gas_above_ceiling)

        # each segment must start exactly where the previous one ended
        segments = self.integrated.segments
        carryover = True
        for before, after in zip(segments, segments[1:]):
            if not before["end_state"] == after["start_state"]:
                carryover = False
                break

        trace_fraction = fields[GAS].sum(axis=0) * self.fraction_scale
        return dict(relative_ledger=relative, zero_inventory_residual=zero,
                    event_balance=float(np.max(np.abs(event_error))), bounds=bounds,
                    exact_segment_carryover=carryover,
                    maximum_trace_fraction=float(trace_fraction.max()))

    def save(self, stem):
        """write the arrays to stem.npz and the metadata and checks to stem.json."""
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(stem) + ".npz", t=self.integrated.t, z=self.grid.z,
                            scaled_state=self.integrated.y, initial_state=self.initial_state,
                            carrier_moles=self.grid.carrier_moles, reactive_areas=self.grid.reactive_areas)
        data = dict(kind=self.grid.metadata["kind"], physical_fit_performed=False, periodic=self.periodic,
                    chemistry=asdict(self.chemistry), grid=self.grid.metadata,
                    fraction_scale=self.fraction_scale, checks=self.checks(),
                    history=self.history, settings=self.settings, segments=self.integrated.segments,
                    units=dict(time="s", position="m", fraction="1", events="mol/m²",
                               gas_accounting="mol", retained_mass="kg/m²"))
        Path(str(stem) + ".json").write_text(json.dumps(json_native(data), indent=2, allow_nan=False) + "\n")


# ---- solver helpers

def cycle_sparsity(cells):
    """jacobian pattern: neighbour transport and local chemistry.

    the cumulative ledgers never feed back into the other states.
    """
    size = CELL_FIELDS*cells + LEDGER_SIZE
    pattern = lil_matrix((size, size), dtype=int)
    for j in range(cells):
        # each gas fraction depends on its own species in the neighbouring cells
        # and on the local theta
        for species in range(2):
            row = species*cells + j
            first = species*cells + max(0, j-1)
            last = species*cells + min(cells, j+2)
            pattern[row, first:last] = 1
            pattern[row, THETA*cells + j] = 1
        # theta and both event counters depend on the local gases and theta
        for field in (THETA, EVENT_A, EVENT_B):
            pattern[field*cells + j, [j, cells + j, THETA*cells + j]] = 1
    # the escaped ledgers depend on the last cell's gas
    pattern[-2, cells-1] = 1
    pattern[-1, 2*cells-1] = 1
    return pattern.tocsr()


def initial_state(grid, *, fraction_scale, fractions=0., theta=0.):
    """build a scaled start state with zero event counters and zero ledgers."""
    _positive(fraction_scale, "fraction scale")
    n = len(grid.z)
    fractions = np.broadcast_to(np.asarray(fractions, dtype=float), (2, n))
    theta = np.broadcast_to(np.asarray(theta, dtype=float), (n,))
    if not np.isfinite(fractions).all() or np.any(fractions < 0):
        raise ValueError("Initial precursor fractions must be finite and nonnegative")
    if not np.isfinite(theta).all() or np.any(theta < 0) or np.any(theta > 1):
        raise ValueError("Initial theta must be in [0,1]")
    # the two event fields and the ledgers all start at zero
    zeros = np.zeros(2*n + LEDGER_SIZE)
    return np.concatenate([fractions.ravel()/fraction_scale, theta, zeros])


def purge_event(cells, threshold):
    """solver event that tracks downward crossings of the purge threshold.

    it works on the solver's own steps, not on the retained plot samples.
    was_above records whether the summed gas fraction was ever above threshold.
    """
    def event(_time, state):
        """summed scaled gas fraction in the worst cell, minus the threshold."""
        value = float(state[:2*cells].reshape(2, cells).sum(axis=0).max()) - threshold
        if value > 0:
            event.was_above = True
        return value

    # solve_ivp reads direction from the function: only count downward crossings
    event.direction = -1
    event.was_above = False
    return event


def purge_clearance(event, segment, cells, threshold):
    """time [s] into a purge segment when it last fell below the threshold.

    returns None when the purge ends above the threshold, and 0 when it never
    rose above it.
    """
    end = np.asarray(segment["end_state"][:2*cells]).reshape(2, cells).sum(axis=0).max()
    if end > threshold:
        return None
    if not event.was_above:
        return 0.
    if not segment["event_times"]:
        raise ValueError("Purge became clear without a recorded downward event")
    return float(segment["event_times"][-1] - segment["start"])


# ---- one recipe

def solve_cycle(grid, chemistry, segments, *, fraction_scale, state=None,
                options=SolverOptions(), output_times=None, purge_threshold=.01):
    """integrate one recipe, keeping every gas, surface and accounting state."""
    # check the inputs and the start state
    _positive(fraction_scale, "fraction scale")
    _positive(purge_threshold, "scaled purge threshold")
    segments = tuple(segments)
    if not segments or not all(isinstance(s, CycleSegment) for s in segments):
        raise ValueError("A nonempty sequence of CycleSegment is required")
    n = len(grid.z)
    if state is None:
        start = initial_state(grid, fraction_scale=fraction_scale)
    else:
        start = np.asarray(state, dtype=float).copy()
    if start.shape != (CELL_FIELDS*n + LEDGER_SIZE,) or not np.isfinite(start).all():
        raise ValueError("Invalid scaled cycle state")
    # gas and theta must be nonnegative and theta at most one
    if np.min(start[:3*n]) < -BOUNDS_TOLERANCE or np.max(start[2*n:3*n]) > 1+BOUNDS_TOLERANCE:
        raise ValueError("Initial gas/surface state violates its bounds")
    if grid.molar_flow == 0 and any(s.inlet_a or s.inlet_b for s in segments):
        raise ValueError("The closed-batch limit requires zero inlet")
    inventory = grid.carrier_moles * fraction_scale
    total_inventory = float(inventory.sum())

    def rhs_factory(index):
        """right-hand side for one segment, with that segment's inlet rates."""
        inlet = np.array([segments[index].inlet_a, segments[index].inlet_b])

        def rhs(_time, y):
            """time derivative of the full scaled state."""
            fields = y[:CELL_FIELDS*n].reshape(CELL_FIELDS, n)
            fractions = fields[GAS] * fraction_scale
            rates = chemistry.rates(fractions * grid.carrier_concentration, fields[THETA])
            flux = composition_fluxes(fractions, grid, inlet)
            change = np.empty_like(fields)

            # gas: net face flux in, minus surface uptake
            change[GAS] = (-np.diff(flux) - grid.reactive_areas * rates) / inventory

            # surface: inert cells carry no surface population or event inventory
            events = rates / chemistry.capacity * (grid.reactive_areas > 0)
            change[THETA] = events[0] - events[1]
            change[EVENTS] = events

            # ledgers: count flow into and out of both ends of the reactor
            entered = np.maximum(flux[:, 0], 0) + np.maximum(-flux[:, -1], 0)
            escaped = np.maximum(-flux[:, 0], 0) + np.maximum(flux[:, -1], 0)
            return np.concatenate([change.ravel(), entered/total_inventory, escaped/total_inventory])

        return rhs

    # purge segments (no inlet at all) get a clearance event
    events = []
    for s in segments:
        if s.inlet_a == 0 and s.inlet_b == 0:
            events.append(purge_event(n, purge_threshold))
        else:
            events.append(None)

    integrated = integrate_segments(start, [s.duration for s in segments], rhs_factory, options,
                                    jac_sparsity=cycle_sparsity(n), output_times=output_times,
                                    events_factory=lambda index: events[index])
    for event, segment in zip(events, integrated.segments):
        if event is not None:
            segment["purge_clearance_s"] = purge_clearance(event, segment, n, purge_threshold)

    # the largest scaled fraction each species can reach: its start value, or
    # its pure inlet fraction when there is flow
    initial_fractions = start[:2*n].reshape(2, n).max(axis=1)
    inlet = np.array([[s.inlet_a, s.inlet_b] for s in segments]).max(axis=0)
    if grid.molar_flow == 0:
        ceiling = initial_fractions
    else:
        ceiling = np.maximum(initial_fractions, inlet / (grid.molar_flow * fraction_scale))

    settings = dict(recipe=[asdict(s) for s in segments], solver=asdict(options),
                    purge_readout=dict(method="continuous_solver_event", scaled_threshold=purge_threshold),
                    maximum_scaled_fraction=ceiling.tolist(),
                    runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__))
    if np.isinf(options.max_step):
        settings["solver"]["max_step"] = "unbounded"
    return CycleResult(integrated, grid, chemistry, fraction_scale, start, [], settings)


# ---- recurring cycle

class PeriodicFailure(RuntimeError):
    """no recurring cycle was found. the last result is kept on the error."""

    def __init__(self, result):
        """store the last cycle result with the error."""
        super().__init__(f"No recurring cycle after {len(result.history)} cycles")
        self.result = result


def _checks_fail(checks):
    """true when a cycle's ledger, event or bounds check is outside its limit."""
    return (checks["relative_ledger"] > LEDGER_TOLERANCE
            or checks["zero_inventory_residual"] > ZERO_INVENTORY_TOLERANCE
            or checks["event_balance"] > EVENT_TOLERANCE
            or checks["bounds"] > BOUNDS_TOLERANCE
            or not checks["exact_segment_carryover"])


def periodic_cycle(grid, chemistry, segments, *, fraction_scale, options=SolverOptions(),
                   max_cycles=200, tolerance=1e-7, output_times=None, state=None, accounting_origin=None):
    """repeat the recipe until gas and surface states recur.

    cumulative growth keeps rising, so only the gas and theta states must
    repeat, and the per-cycle turnover must stop changing.
    """
    if isinstance(max_cycles, bool) or not isinstance(max_cycles, int) or max_cycles < 2:
        raise ValueError("max_cycles must be an integer >= 2")
    _positive(tolerance, "periodic tolerance")
    if grid.reactive_areas.sum() <= 0:
        raise ValueError("Recurring growth requires positive reactive area")
    n = len(grid.z)
    if state is None:
        first = initial_state(grid, fraction_scale=fraction_scale)
    else:
        first = np.asarray(state).copy()

    # a continued run keeps its original ledger origin. subtracting large old
    # counters from an almost-empty purge inventory otherwise loses precision.
    if accounting_origin is None:
        origin = first
    else:
        origin = np.asarray(accounting_origin, dtype=float).copy()
    if origin.shape != first.shape or not np.isfinite(origin).all():
        raise ValueError("Invalid original accounting state")

    # run one cycle at a time until the state and the turnover both repeat
    state = first.copy()
    history = []
    previous_turnover = None
    for cycle in range(1, max_cycles + 1):
        result = solve_cycle(grid, chemistry, segments, fraction_scale=fraction_scale,
                             state=state, options=options, output_times=output_times)
        finish = result.integrated.y[:, -1]
        state_error = float(np.max(np.abs(finish[:3*n] - state[:3*n])))
        if previous_turnover is None:
            growth_error = None
        else:
            growth_error = float(np.max(np.abs(result.turnover - previous_turnover)))
        result = replace(result, initial_state=origin, history=history)
        checks = result.checks()
        if _checks_fail(checks):
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
    """equivalent ZnO Å/cycle from capacity, turnover and density. not measured GPC."""
    _positive(density, "film density [kg/m³]")
    if not result.periodic:
        raise ValueError("Growth per recurring cycle requires periodic convergence")
    if result.grid.metadata["parameters"]["channel"]["temperature"] != GPC_TEMPERATURE_K:
        raise ValueError("The current density mapping is limited to 150 C")
    return ANGSTROM_PER_METER * M_ZNO / density * result.chemistry.capacity * result.turnover
