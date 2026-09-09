"""Purge timing uses the solver trajectory, not spacing between saved samples."""

import numpy as np
import pytest

from ald_twin.cycle_transport import CycleGrid
from ald_twin.cycles import (CycleChemistry, CycleSegment, initial_state, purge_clearance,
                             purge_event, solve_cycle)
from ald_twin.numerics import SolverOptions, integrate_segments


@pytest.mark.parametrize("method", ["Radau", "BDF"])
def test_exponential_purge_time_is_exact_and_sample_independent(method):
    grid = CycleGrid(np.array([.5]), np.ones(1), np.ones(1), np.ones(1), 2.,
                     np.empty((2, 0)), {"kind": "synthetic"})
    state = initial_state(grid, fraction_scale=.01, fractions=np.array([[.01], [0.]]))
    options = SolverOptions(method, 1e-10, 1e-12, .05)
    times = []
    for output in (np.array([0., 5.]), np.linspace(0, 5, 101)):
        result = solve_cycle(grid, CycleChemistry(.01, 0., 0.), [CycleSegment(5., 0., 0.)],
                             fraction_scale=.01, state=state, options=options, output_times=output)
        times.append(result.integrated.segments[0]["purge_clearance_s"])
    np.testing.assert_allclose(times, np.log(100)/2, atol=2e-8, rtol=0)
    assert times[0] == times[1]


@pytest.mark.parametrize("fraction, expected", [(0., 0.), (.0001, 0.), (.001, None)])
def test_static_gas_is_already_clear_or_never_clear(fraction, expected):
    grid = CycleGrid(np.array([.5]), np.ones(1), np.ones(1), np.ones(1), 0.,
                     np.empty((2, 0)), {"kind": "synthetic"})
    state = initial_state(grid, fraction_scale=.01, fractions=np.array([[fraction], [0.]]))
    result = solve_cycle(grid, CycleChemistry(.01, 0., 0.), [CycleSegment(1., 0., 0.)],
                         fraction_scale=.01, state=state)
    assert result.integrated.segments[0]["purge_clearance_s"] == expected


def test_resurgence_retains_the_last_downward_crossing():
    event = purge_event(1, .01)
    # Prescribed smooth signal crosses down at 0.5 and 1.5, with resurgence between.
    rhs = lambda index: lambda time, state: [.005*2*np.pi*np.cos(2*np.pi*time), 0.]
    result = integrate_segments(np.array([.01, 0.]), [1.75], rhs,
                                SolverOptions("Radau", 1e-10, 1e-12, .025),
                                output_times=[0., 1.75], events_factory=lambda index: event)
    assert purge_clearance(event, result.segments[0], 1, .01) == pytest.approx(1.5, abs=1e-8)
