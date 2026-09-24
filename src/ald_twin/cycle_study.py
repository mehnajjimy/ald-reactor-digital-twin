"""small, explicit synthetic recipes and comparisons for the Phase 4–5 study."""

from copy import deepcopy

import numpy as np

from .cycle_transport import channel_grid
from .cycles import CELL_FIELDS, EVENTS, GAS, THETA, CycleChemistry, CycleSegment
from .numerics import SolverOptions
from .units import R

# ---- recipe layout
# every recipe is four segments in this order
A_PULSE = 0
A_PURGE = 1
B_PULSE = 2
B_PURGE = 3

# ---- solver settings for study runs
STUDY_METHOD = "Radau"
STUDY_RTOL = 1e-8
STUDY_ATOL = 1e-10
# the largest step is the shortest segment divided by this
MAX_STEP_DIVISOR = 8

# ---- decision thresholds
# the A pulse must cover at least this fraction of sites in every reactive cell
MIN_A_COMPLETION = .9
# the B pulse must leave at most this fraction of sites covered
MAX_B_REMAINING = .1
# each purge must end with at most this scaled gas fraction
MAX_PURGE_RESIDUAL = .01
# the continuous purge readout threshold the study metrics expect
STUDY_PURGE_THRESHOLD = .01
# recipe boundaries must be retained to within this time [s]
BOUNDARY_TIME_TOLERANCE = 1e-14

# ---- wall screen
WALL_SCREEN_CELLS = 40
# largest accepted wall Biot number and transverse mixing time over residence time
WALL_SCREEN_LIMIT = .1


# ---- case setup

def case_parameters(config, peclet, damkohler):
    """set mathematical Pe, Da and capacity scales without estimating DEZ data."""
    data = deepcopy(config)
    channel = data["channel"]

    # diffusivity that gives the requested Peclet number at the outlet
    concentration_out = channel["outlet_pressure"] / (R * channel["temperature"])
    area = channel["width"] * channel["height"]
    value = channel["molar_flow"] * channel["length"] / (area * concentration_out * peclet)
    prop = dict(kind="synthetic", source="Declared mathematical Peclet regime, not DEZ transport",
                value=value, temperature=channel["temperature"], pressure=channel["outlet_pressure"],
                source_type="synthetic_verification", uncertainty=None)
    water_prop = dict(prop)
    water_prop["value"] = value * data["water_diffusivity_over_a"]
    data["diffusivity"] = {"a": prop, "b": water_prop}

    # capacity from the declared ratio to the trace gas inventory, then kA from
    # the requested Damkohler number on the matched well-mixed volume
    mixed = channel_grid(data, 1)
    capacity = (data["capacity_over_carrier_trace_inventory"] * mixed.carrier_moles.sum()
                * data["fraction_scale"] / mixed.reactive_areas.sum())
    rate_a = damkohler * mixed.molar_flow / (capacity * mixed.carrier_concentration[0] * mixed.reactive_areas.sum())
    chemistry = CycleChemistry(float(capacity), float(rate_a), float(rate_a * data["rate_b_over_a"]))
    data["dimensionless"] = dict(peclet=float(peclet), damkohler=float(damkohler))
    return data, chemistry


def recipe(parameters, pulse_ratio, *, water_ratio=None):
    """build the A pulse, purge, B pulse, purge recipe, timed in residence times."""
    mixed = channel_grid(parameters, 1)
    residence = float(mixed.carrier_moles.sum() / mixed.molar_flow)
    flow = mixed.molar_flow * parameters["fraction_scale"]
    purge = parameters["purge_residence_ratio"] * residence
    if water_ratio is None:
        water_ratio = parameters["water_pulse_residence_ratio"]
    return [CycleSegment(pulse_ratio*residence, flow, 0., "A pulse"),
            CycleSegment(purge, 0., 0., "A purge"),
            CycleSegment(water_ratio*residence, 0., flow, "B pulse"),
            CycleSegment(purge, 0., 0., "B purge")]


def study_options(segments):
    """solver settings with the largest step tied to the shortest segment."""
    shortest = min(s.duration for s in segments)
    return SolverOptions(method=STUDY_METHOD, rtol=STUDY_RTOL, atol=STUDY_ATOL,
                         max_step=shortest / MAX_STEP_DIVISOR)


def readout_times(segments, points=101):
    """evenly spaced output times inside every segment, including each switch."""
    ends = np.r_[0., np.cumsum([s.duration for s in segments])]
    pieces = []
    for start, stop in zip(ends[:-1], ends[1:]):
        pieces.append(np.linspace(start, stop, points))
    return np.unique(np.concatenate(pieces))


# ---- grid comparisons

def transient_fields(result):
    """cell fields with event counters measured from the start of the run."""
    fields = result.fields.copy()
    # startup takes different cycle counts on different grids. compare events
    # within the last cycle, not the accumulated amount from unrelated startups.
    fields[EVENTS] -= fields[EVENTS, :1]
    return fields


def resolution_difference(coarse, fine):
    """largest gas, coverage and event differences after averaging fine onto coarse."""
    n = len(coarse.grid.z)
    if len(fine.grid.z) % n:
        raise ValueError("Fine cells must form equal groups within coarse cells")
    factor = len(fine.grid.z) // n
    values = transient_fields(fine)

    # average each group of fine cells: gas by carrier moles, surface by area
    restricted = np.empty((CELL_FIELDS, values.shape[1], n))
    for field in range(CELL_FIELDS):
        # the first two fields are the gas fractions
        if field < THETA:
            weights = fine.grid.carrier_moles
        else:
            weights = fine.grid.reactive_areas
        numerator = (values[field] * weights).reshape(values.shape[1], n, factor).sum(axis=-1)
        denominator = weights.reshape(n, factor).sum(axis=-1)
        # a group with no reactive area gets zero instead of 0/0
        restricted[field] = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)

    # interpolate only retained output onto the coarse times. the integrator
    # still resolves every switch.
    aligned = np.empty((CELL_FIELDS, len(coarse.integrated.t), n))
    for field in range(CELL_FIELDS):
        for j in range(n):
            aligned[field, :, j] = np.interp(coarse.integrated.t, fine.integrated.t, restricted[field, :, j])

    difference = np.abs(transient_fields(coarse) - aligned)
    return dict(gas=float(difference[GAS].max()), coverage=float(difference[THETA].max()),
                events=float(difference[EVENTS].max()))


# ---- cycle metrics

def purge_crossing(times, signal, threshold=.01):
    """last downward crossing, so a later sampled resurgence is not hidden.

    returns 0 when the signal never exceeds the threshold, and None when it
    is still above at the last sample.
    """
    above = np.flatnonzero(signal > threshold)
    if len(above) == 0:
        return 0.
    last = int(above[-1])
    if last == len(signal)-1:
        return None
    # linear interpolation between the last sample above and the next one
    weight = (signal[last]-threshold) / (signal[last]-signal[last+1])
    return float(times[last] + weight*(times[last+1]-times[last]) - times[0])


def metrics(result, segments):
    """completion, purge and precursor-use metrics of one recurring cycle."""
    if result.settings.get("purge_readout", {}).get("scaled_threshold") != STUDY_PURGE_THRESHOLD:
        raise ValueError("Study metrics require continuous readout at the declared 0.01 threshold")

    # output index at the end of each segment
    ends = np.cumsum([s.duration for s in segments])
    indices = []
    for t in ends:
        indices.append(int(np.argmin(abs(result.integrated.t-t))))
    if not np.allclose(result.integrated.t[indices], ends, rtol=0, atol=BOUNDARY_TIME_TOLERANCE):
        raise ValueError("All recipe boundaries must be retained")

    active = result.grid.reactive_areas > 0
    theta = result.fields[THETA][:, active]
    # worst-cell summed gas fraction at each output time
    residual = result.fields[GAS].sum(axis=0).max(axis=1)

    # purge clearance times from the continuous solver events
    crossings = []
    for index in (A_PURGE, B_PURGE):
        segment = result.integrated.segments[index]
        if "purge_clearance_s" not in segment:
            raise ValueError("This result needs a verified continuous purge readout; sampled histories are historical only")
        crossings.append(segment["purge_clearance_s"])

    # precursor that entered, escaped and reacted over the cycle [mol]
    input_moles = result.entered[:, -1] - result.entered[:, 0]
    escape_moles = result.escaped[:, -1] - result.escaped[:, 0]
    consumption = (result.events[:, -1] - result.events[:, 0]) @ result.grid.reactive_areas

    a_pulse_theta = theta[indices[A_PULSE]]
    return dict(minimum_a_completion=float(a_pulse_theta.min()),
                mean_a_completion=float(np.average(a_pulse_theta, weights=result.grid.reactive_areas[active])),
                maximum_b_remaining=float(theta[indices[B_PULSE]].max()),
                purge_a_residual=float(residual[indices[A_PURGE]]),
                purge_b_residual=float(residual[indices[B_PURGE]]),
                purge_crossing_s=crossings, minimum_turnover=float(result.turnover[active].min()),
                mean_turnover=float(np.average(result.turnover, weights=result.grid.reactive_areas)),
                precursor_consumption_fraction=(consumption/input_moles).tolist(),
                precursor_escape_fraction=(escape_moles/input_moles).tolist(),
                cycle_time_s=float(ends[-1]))


def decision(summary, uncertainty):
    """return unresolved (None) when a threshold is within measured numerical changes."""
    margins = np.array([summary["minimum_a_completion"]-MIN_A_COMPLETION,
                        MAX_B_REMAINING-summary["maximum_b_remaining"],
                        MAX_PURGE_RESIDUAL-summary["purge_a_residual"],
                        MAX_PURGE_RESIDUAL-summary["purge_b_residual"]])
    if np.any(margins < -uncertainty):
        return False
    if np.any(margins <= uncertainty):
        return None
    return True


def metric_difference(coarse, fine, segments, residence):
    """largest change in the decision metrics and in purge time over residence."""
    first = metrics(coarse, segments)
    second = metrics(fine, segments)
    names = ("minimum_a_completion", "maximum_b_remaining", "purge_a_residual", "purge_b_residual")
    change = max(abs(first[name]-second[name]) for name in names)

    # a purge that clears on one run but not the other has no finite change
    crossing_change = 0.
    for a, b in zip(first["purge_crossing_s"], second["purge_crossing_s"]):
        if (a is None) != (b is None):
            return dict(decision_metrics=change, purge_time_over_residence=None)
        if a is not None:
            crossing_change = max(crossing_change, abs(a-b)/residence)
    return dict(decision_metrics=change, purge_time_over_residence=crossing_change)


def candidate_choice(rows):
    """a finite-list choice stays unresolved if a faster candidate is unresolved."""
    ordered = sorted(rows, key=lambda row: row["metrics"]["cycle_time_s"])
    for row in ordered:
        if row["feasible"] is None:
            return dict(status="unresolved", case=None)
        if row["feasible"]:
            return dict(status="selected", case=row["case"])
    return dict(status="no_feasible_candidate", case=None)


# ---- wall screen

def wall_screen(parameters, chemistry):
    """synthetic checks that the gap is thin enough to treat as well mixed across."""
    grid = channel_grid(parameters, WALL_SCREEN_CELLS)
    diffusion = np.asarray(grid.metadata["face_diffusivity_m2_s"])
    half_gap = parameters["channel"]["height"] / 2
    residence = float(grid.carrier_moles.sum()/grid.molar_flow)
    # wall reaction against cross-gap diffusion, and cross-gap time against residence
    bi = chemistry.capacity * np.array([chemistry.rate_a, chemistry.rate_b]) * half_gap / diffusion.min(axis=1)
    mixing = half_gap**2 / diffusion.min(axis=1) / residence
    passes = bool(np.max(bi) <= WALL_SCREEN_LIMIT and np.max(mixing) <= WALL_SCREEN_LIMIT)
    return dict(bi=bi.tolist(), transverse_time_over_residence=mixing.tolist(),
                passes_declared_screen=passes,
                interpretation="Synthetic screening ratios; not a certified physical error bound")
