"""purge clearance times come from the solver trajectory, not the saved samples."""

import numpy as np
import pytest

from ald_twin.cycle_transport import CycleGrid
from ald_twin.cycles import (CycleChemistry, CycleSegment, initial_state, purge_clearance,
                             purge_event, solve_cycle)
from ald_twin.numerics import SolverOptions, integrate_segments


def one_cell(flow):
    """a single well-mixed cell of unit volume with the given carrier flow."""
    return CycleGrid(np.array([.5]), np.ones(1), np.ones(1), np.ones(1), flow,
                     np.empty((2, 0)), {"kind": "synthetic"})


def test_mixed_purge_decays_exponentially_and_clears_at_log_100_over_2():
    """catches a wrong washout rate or a clearance time that depends on output sampling."""
    grid = one_cell(2.)
    state = initial_state(grid, fraction_scale=.01, fractions=np.array([[.01], [0.]]))
    for method in ("Radau", "BDF"):
        options = SolverOptions(method, 1e-10, 1e-12, .05)
        times = []
        for output in (np.array([0., 5.]), np.linspace(0, 5, 101)):
            result = solve_cycle(grid, CycleChemistry(.01, 0., 0.), [CycleSegment(5., 0., 0.)],
                                 fraction_scale=.01, state=state, options=options, output_times=output)
            times.append(result.integrated.segments[0]["purge_clearance_s"])

        # with flow 2 per volume, x = exp(-2 t) and x reaches 1% at ln(100)/2 s
        np.testing.assert_allclose(result.fields[0, :, 0], np.exp(-2*result.integrated.t), atol=1e-9)
        np.testing.assert_allclose(times, np.log(100)/2, atol=2e-8, rtol=0)
        assert times[0] == times[1]


def test_static_gas_is_already_clear_or_never_clears():
    """catches a no-flow purge reporting a made-up clearance time."""
    grid = one_cell(0.)
    for fraction, expected in [(0., 0.), (.0001, 0.), (.001, None)]:
        state = initial_state(grid, fraction_scale=.01, fractions=np.array([[fraction], [0.]]))
        result = solve_cycle(grid, CycleChemistry(.01, 0., 0.), [CycleSegment(1., 0., 0.)],
                             fraction_scale=.01, state=state)
        assert result.integrated.segments[0]["purge_clearance_s"] == expected


def test_resurgence_keeps_the_last_downward_crossing():
    """catches a clearance time taken from the first crossing when the gas comes back."""
    event = purge_event(1, .01)

    # x = 0.01 + 0.005 sin(2 pi t) crosses 0.01 downward at 0.5 s and 1.5 s
    def rhs_factory(index):
        """return the rhs of the prescribed signal."""
        def rhs(time, state):
            """time derivative of the prescribed signal."""
            return [.005*2*np.pi*np.cos(2*np.pi*time), 0.]
        return rhs

    def events_factory(index):
        """use the same purge event in every segment."""
        return event

    result = integrate_segments(np.array([.01, 0.]), [1.75], rhs_factory,
                                SolverOptions("Radau", 1e-10, 1e-12, .025),
                                output_times=[0., 1.75], events_factory=events_factory)
    assert purge_clearance(event, result.segments[0], 1, .01) == pytest.approx(1.5, abs=1e-8)
