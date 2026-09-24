"""time integration of scaled states over recipe segments, with clear solver failures."""

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp

# stiff solvers that phase 1 allows
SUPPORTED_METHODS = ("Radau", "BDF")


# solver settings


@dataclass(frozen=True)
class SolverOptions:
    """stiff solver name, tolerances for scaled states, and the largest step [s]."""

    method: str = "Radau"
    rtol: float = 1e-8
    atol: float = 1e-10
    max_step: float = np.inf

    def __post_init__(self):
        """check the method and that both tolerances lie in (0, 1)."""
        if self.method not in SUPPORTED_METHODS:
            raise ValueError("Phase 1 supports Radau and BDF")
        rtol_ok = np.isfinite(self.rtol) and 0 < self.rtol < 1
        if not rtol_ok:
            raise ValueError("rtol must lie in (0, 1)")
        atol_ok = np.isfinite(self.atol) and 0 < self.atol < 1
        if not atol_ok:
            raise ValueError("atol must lie in (0, 1) for scaled states")
        if np.isnan(self.max_step) or self.max_step <= 0:
            raise ValueError("max_step must be positive seconds")


# solver output


@dataclass(frozen=True)
class Integrated:
    """joined time points, states (one column per time) and per-segment diagnostics."""

    t: np.ndarray
    y: np.ndarray
    segments: tuple[dict, ...]


class SolverFailure(RuntimeError):
    """raised when a segment fails. the partial solver output stays attached for diagnosis."""

    def __init__(self, segment, result):
        """keep the failed segment index and the raw solve_ivp result."""
        super().__init__(f"Segment {segment} failed at t={result.t[-1]}: {result.message}")
        self.segment = segment
        self.result = result


# input checks


def _check_durations(durations):
    """require a nonempty 1D array of finite positive durations [s]."""
    message = "At least one finite positive segment duration is required"
    if durations.ndim != 1:
        raise ValueError(message)
    if len(durations) == 0:
        raise ValueError(message)
    if not np.all(np.isfinite(durations)):
        raise ValueError(message)
    if np.any(durations <= 0):
        raise ValueError(message)


def _check_output_times(output_times, final_time):
    """require output times to be finite, strictly increasing and inside the recipe."""
    message = "output_times must be strictly increasing within the recipe"
    if output_times.ndim != 1:
        raise ValueError(message)
    if not np.all(np.isfinite(output_times)):
        raise ValueError(message)
    if np.any(np.diff(output_times) <= 0):
        raise ValueError(message)
    if np.any(output_times < 0):
        raise ValueError(message)
    if np.any(output_times > final_time):
        raise ValueError(message)


# segment-by-segment integration


def integrate_segments(initial, durations, rhs_factory: Callable, options, jac_sparsity=None,
                       output_times=None, events_factory=None):
    """integrate each recipe segment in turn, carrying the full end state into the next one."""
    durations = np.asarray(durations, dtype=float)
    _check_durations(durations)
    state = np.asarray(initial, dtype=float).copy()
    if state.ndim != 1 or not np.all(np.isfinite(state)):
        raise ValueError("Initial scaled state must be a finite vector")

    # segment end times must stay distinct after summing
    ends = np.cumsum(durations)
    starts_and_ends = np.r_[0., ends]
    if not np.all(np.isfinite(ends)) or np.any(np.diff(starts_and_ends) <= 0):
        raise ValueError("Segment endpoints must be finite and distinguishable")
    if output_times is not None:
        output_times = np.asarray(output_times, dtype=float)
        _check_output_times(output_times, ends[-1])

    all_t = []
    all_y = []
    statuses = []
    start = 0.0
    for index, end in enumerate(ends):
        # sampling only changes which points are kept. both segment ends are
        # always kept so the full end state can start the next segment.
        if output_times is None:
            sampled = None
        else:
            inside = (output_times > start) & (output_times < end)
            sampled = np.unique(np.r_[start, output_times[inside], end])

        if events_factory is None:
            events = None
        else:
            events = events_factory(index)

        # each segment gets its own constant-recipe rhs, so evaluations at the
        # end point never see the next segment's inlet
        result = solve_ivp(rhs_factory(index), (start, end), state,
                           method=options.method, rtol=options.rtol,
                           atol=options.atol, max_step=options.max_step,
                           jac_sparsity=jac_sparsity, t_eval=sampled, events=events)
        if not result.success or result.t[-1] != end or not np.all(np.isfinite(result.y)):
            raise SolverFailure(index, result)

        # per-segment diagnostics
        status = {
            "index": index,
            "start": float(start),
            "end": float(end),
            "success": bool(result.success),
            "message": result.message,
            "nfev": result.nfev,
            "njev": result.njev,
            "nlu": result.nlu,
            "start_state": state.tolist(),
            "end_state": result.y[:, -1].tolist(),
        }
        if events is not None:
            status["event_times"] = result.t_events[0].tolist()
        statuses.append(status)

        # the first point of a later segment repeats the previous end point, so drop it
        if index == 0:
            take = slice(None)
        else:
            take = slice(1, None)
        all_t.append(result.t[take])
        all_y.append(result.y[:, take])

        # carry gas, surface and every running total forward unchanged
        state = result.y[:, -1].copy()
        start = end
    return Integrated(np.concatenate(all_t), np.concatenate(all_y, axis=1), tuple(statuses))
