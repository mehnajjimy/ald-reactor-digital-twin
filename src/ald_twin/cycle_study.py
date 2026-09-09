"""Small, explicit synthetic recipes and comparisons for the Phase 4–5 study."""

from copy import deepcopy

import numpy as np

from .cycle_transport import channel_grid
from .cycles import CycleChemistry, CycleSegment
from .numerics import SolverOptions
from .units import R


def case_parameters(config, peclet, damkohler):
    """Set mathematical Pe, Da and capacity scales without estimating DEZ data."""
    data = deepcopy(config)
    channel = data["channel"]
    concentration_out = channel["outlet_pressure"] / (R * channel["temperature"])
    area = channel["width"] * channel["height"]
    value = channel["molar_flow"] * channel["length"] / (area * concentration_out * peclet)
    prop = dict(kind="synthetic", source="Declared mathematical Peclet regime, not DEZ transport",
                value=value, temperature=channel["temperature"], pressure=channel["outlet_pressure"],
                source_type="synthetic_verification", uncertainty=None)
    data["diffusivity"] = {"a": prop, "b": prop | {"value": value * data["water_diffusivity_over_a"]}}
    mixed = channel_grid(data, 1)
    capacity = (data["capacity_over_carrier_trace_inventory"] * mixed.carrier_moles.sum()
                * data["fraction_scale"] / mixed.reactive_areas.sum())
    rate_a = damkohler * mixed.molar_flow / (capacity * mixed.carrier_concentration[0] * mixed.reactive_areas.sum())
    chemistry = CycleChemistry(float(capacity), float(rate_a), float(rate_a * data["rate_b_over_a"]))
    data["dimensionless"] = dict(peclet=float(peclet), damkohler=float(damkohler))
    return data, chemistry


def recipe(parameters, pulse_ratio, *, water_ratio=None):
    mixed = channel_grid(parameters, 1)
    residence = float(mixed.carrier_moles.sum() / mixed.molar_flow)
    flow = mixed.molar_flow * parameters["fraction_scale"]
    purge = parameters["purge_residence_ratio"] * residence
    water_ratio = parameters["water_pulse_residence_ratio"] if water_ratio is None else water_ratio
    return [CycleSegment(pulse_ratio*residence, flow, 0., "A pulse"),
            CycleSegment(purge, 0., 0., "A purge"),
            CycleSegment(water_ratio*residence, 0., flow, "B pulse"),
            CycleSegment(purge, 0., 0., "B purge")]


def study_options(segments):
    return SolverOptions("Radau", 1e-8, 1e-10, min(s.duration for s in segments) / 8)


def readout_times(segments, points=101):
    ends = np.r_[0., np.cumsum([s.duration for s in segments])]
    return np.unique(np.concatenate([np.linspace(a, b, points) for a, b in zip(ends[:-1], ends[1:])]))


def transient_fields(result):
    fields = result.fields.copy()
    # Startup takes different cycle counts on different grids. Compare events
    # within the last cycle, not the accumulated amount from unrelated startups.
    fields[3:5] -= fields[3:5, :1]
    return fields


def resolution_difference(coarse, fine):
    n = len(coarse.grid.z)
    if len(fine.grid.z) % n:
        raise ValueError("Fine cells must form equal groups within coarse cells")
    factor = len(fine.grid.z) // n
    values = transient_fields(fine)
    restricted = np.empty((5, values.shape[1], n))
    for field in range(5):
        weights = fine.grid.carrier_moles if field < 2 else fine.grid.reactive_areas
        numerator = (values[field] * weights).reshape(values.shape[1], n, factor).sum(axis=-1)
        denominator = weights.reshape(n, factor).sum(axis=-1)
        restricted[field] = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
    # Interpolate only retained output; the integrator still resolves every switch.
    aligned = np.array([[np.interp(coarse.integrated.t, fine.integrated.t, restricted[f, :, j])
                         for j in range(n)] for f in range(5)]).transpose(0, 2, 1)
    difference = np.abs(transient_fields(coarse) - aligned)
    return dict(gas=float(difference[:2].max()), coverage=float(difference[2].max()),
                events=float(difference[3:5].max()))


def purge_crossing(times, signal, threshold=.01):
    """Last downward crossing, so a later sampled resurgence is not hidden."""
    above = np.flatnonzero(signal > threshold)
    if not len(above):
        return 0.
    last = int(above[-1])
    if last == len(signal)-1:
        return None
    weight = (signal[last]-threshold) / (signal[last]-signal[last+1])
    return float(times[last] + weight*(times[last+1]-times[last]) - times[0])


def metrics(result, segments):
    if result.settings.get("purge_readout", {}).get("scaled_threshold") != .01:
        raise ValueError("Study metrics require continuous readout at the declared 0.01 threshold")
    ends = np.cumsum([s.duration for s in segments])
    indices = [int(np.argmin(abs(result.integrated.t-t))) for t in ends]
    if not np.allclose(result.integrated.t[indices], ends, rtol=0, atol=1e-14):
        raise ValueError("All recipe boundaries must be retained")
    active = result.grid.reactive_areas > 0
    theta = result.fields[2][:, active]
    residual = result.fields[:2].sum(axis=0).max(axis=1)
    crossings = []
    for index in (1, 3):
        segment = result.integrated.segments[index]
        if "purge_clearance_s" not in segment:
            raise ValueError("This result needs a verified continuous purge readout; sampled histories are historical only")
        crossings.append(segment["purge_clearance_s"])
    input_moles = result.entered[:, -1] - result.entered[:, 0]
    escape_moles = result.escaped[:, -1] - result.escaped[:, 0]
    consumption = (result.events[:, -1] - result.events[:, 0]) @ result.grid.reactive_areas
    return dict(minimum_a_completion=float(theta[indices[0]].min()),
                mean_a_completion=float(np.average(theta[indices[0]], weights=result.grid.reactive_areas[active])),
                maximum_b_remaining=float(theta[indices[2]].max()),
                purge_a_residual=float(residual[indices[1]]), purge_b_residual=float(residual[indices[3]]),
                purge_crossing_s=crossings, minimum_turnover=float(result.turnover[active].min()),
                mean_turnover=float(np.average(result.turnover, weights=result.grid.reactive_areas)),
                precursor_consumption_fraction=(consumption/input_moles).tolist(),
                precursor_escape_fraction=(escape_moles/input_moles).tolist(),
                cycle_time_s=float(ends[-1]))


def decision(summary, uncertainty):
    """Return unresolved when a threshold is within measured numerical changes."""
    margins = np.array([summary["minimum_a_completion"]-.9, .1-summary["maximum_b_remaining"],
                        .01-summary["purge_a_residual"], .01-summary["purge_b_residual"]])
    if np.any(margins < -uncertainty):
        return False
    if np.any(margins <= uncertainty):
        return None
    return True


def metric_difference(coarse, fine, segments, residence):
    first, second = metrics(coarse, segments), metrics(fine, segments)
    names = ("minimum_a_completion", "maximum_b_remaining", "purge_a_residual", "purge_b_residual")
    change = max(abs(first[name]-second[name]) for name in names)
    crossing_change = 0.
    for a, b in zip(first["purge_crossing_s"], second["purge_crossing_s"]):
        if (a is None) != (b is None):
            return dict(decision_metrics=change, purge_time_over_residence=None)
        if a is not None:
            crossing_change = max(crossing_change, abs(a-b)/residence)
    return dict(decision_metrics=change, purge_time_over_residence=crossing_change)


def candidate_choice(rows):
    """A finite-list choice stays unresolved if a faster candidate is unresolved."""
    ordered = sorted(rows, key=lambda row: row["metrics"]["cycle_time_s"])
    for row in ordered:
        if row["feasible"] is None:
            return dict(status="unresolved", case=None)
        if row["feasible"]:
            return dict(status="selected", case=row["case"])
    return dict(status="no_feasible_candidate", case=None)


def wall_screen(parameters, chemistry):
    grid = channel_grid(parameters, 40)
    diffusion = np.asarray(grid.metadata["face_diffusivity_m2_s"])
    half_gap = parameters["channel"]["height"] / 2
    residence = float(grid.carrier_moles.sum()/grid.molar_flow)
    bi = chemistry.capacity * np.array([chemistry.rate_a, chemistry.rate_b]) * half_gap / diffusion.min(axis=1)
    mixing = half_gap**2 / diffusion.min(axis=1) / residence
    return dict(bi=bi.tolist(), transverse_time_over_residence=mixing.tolist(),
                passes_declared_screen=bool(np.max(bi) <= .1 and np.max(mixing) <= .1),
                interpretation="Synthetic screening ratios; not a certified physical error bound")
