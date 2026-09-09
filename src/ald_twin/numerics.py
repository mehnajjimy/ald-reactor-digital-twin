"""Segmented integration of scaled states, with explicit solver failures."""

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(frozen=True)
class SolverOptions:
    method: str = "Radau"
    rtol: float = 1e-8
    atol: float = 1e-10
    max_step: float = np.inf

    def __post_init__(self):
        if self.method not in ("Radau", "BDF"):
            raise ValueError("Phase 1 supports Radau and BDF")
        if not (np.isfinite(self.rtol) and 0 < self.rtol < 1):
            raise ValueError("rtol must lie in (0, 1)")
        if not (np.isfinite(self.atol) and 0 < self.atol < 1):
            raise ValueError("atol must lie in (0, 1) for scaled states")
        if np.isnan(self.max_step) or self.max_step <= 0:
            raise ValueError("max_step must be positive seconds")


@dataclass(frozen=True)
class Integrated:
    t: np.ndarray
    y: np.ndarray
    segments: tuple[dict, ...]


class SolverFailure(RuntimeError):
    """A segment failed; partial solver output remains available for diagnosis."""

    def __init__(self, segment, result):
        super().__init__(f"Segment {segment} failed at t={result.t[-1]}: {result.message}")
        self.segment = segment
        self.result = result


def integrate_segments(initial, durations, rhs_factory: Callable, options, jac_sparsity=None,
                       output_times=None, events_factory=None):
    durations = np.asarray(durations, dtype=float)
    if durations.ndim != 1 or not len(durations) or not np.all(np.isfinite(durations)) or np.any(durations <= 0):
        raise ValueError("At least one finite positive segment duration is required")
    state = np.asarray(initial, dtype=float).copy()
    if state.ndim != 1 or not np.all(np.isfinite(state)):
        raise ValueError("Initial scaled state must be a finite vector")
    ends = np.cumsum(durations)
    if not np.all(np.isfinite(ends)) or np.any(np.diff(np.r_[0., ends]) <= 0):
        raise ValueError("Segment endpoints must be finite and distinguishable")
    if output_times is not None:
        output_times = np.asarray(output_times, dtype=float)
        if (output_times.ndim != 1 or not np.all(np.isfinite(output_times))
            or np.any(np.diff(output_times) <= 0) or np.any(output_times < 0)
            or np.any(output_times > ends[-1])):
            raise ValueError("output_times must be strictly increasing within the recipe")
    all_t, all_y, statuses = [], [], []
    start = 0.0
    for index, end in enumerate(ends):
        # Sampling changes retained output only. Every switch endpoint is always
        # retained so the full terminal state can initialize the next segment.
        sampled = None if output_times is None else np.unique(np.r_[start,
            output_times[(output_times > start) & (output_times < end)], end])
        # A separate constant-recipe RHS prevents endpoint evaluations from
        # leaking the next segment's inlet into the previous integration.
        events = None if events_factory is None else events_factory(index)
        result = solve_ivp(rhs_factory(index), (start, end), state,
                           method=options.method, rtol=options.rtol,
                           atol=options.atol, max_step=options.max_step,
                           jac_sparsity=jac_sparsity, t_eval=sampled, events=events)
        if not result.success or result.t[-1] != end or not np.all(np.isfinite(result.y)):
            raise SolverFailure(index, result)
        statuses.append(dict(index=index, start=float(start), end=float(end),
                             success=bool(result.success), message=result.message,
                             nfev=result.nfev, njev=result.njev, nlu=result.nlu,
                             start_state=state.tolist(), end_state=result.y[:, -1].tolist()))
        if events is not None:
            statuses[-1]["event_times"] = result.t_events[0].tolist()
        take = slice(None) if index == 0 else slice(1, None)
        all_t.append(result.t[take])
        all_y.append(result.y[:, take])
        # Preserve gas, surface, and all cumulative accounting states exactly.
        state = result.y[:, -1].copy()
        start = end
    return Integrated(np.concatenate(all_t), np.concatenate(all_y, axis=1), tuple(statuses))
