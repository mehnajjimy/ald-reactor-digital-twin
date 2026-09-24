"""purge clearance times come from the solver trajectory, not the saved samples."""

import numpy as np

from ald_twin.cycle_transport import CycleGrid
from ald_twin.cycles import CycleChemistry, CycleSegment, initial_state, solve_cycle
from ald_twin.numerics import SolverOptions


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
