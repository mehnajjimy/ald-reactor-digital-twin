"""dimensionless model: group recovery, scale independence and an independent solve."""

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from ald_twin.dimensionless import (DimensionlessGroups, MathematicalScales,
    representative, solve_dimensionless)
from ald_twin.numerics import SolverOptions

# Pe = 65, Da = 1550, gamma = 2.5
GROUPS = DimensionlessGroups(65., 1550., 2.5)
ODD_SCALES = MathematicalScales(.13, .004, .7, .002, 17.)


def test_representative_si_values_recover_the_groups():
    """catches an si adapter that changes Pe, Da or gamma."""
    for scales in (MathematicalScales(), ODD_SCALES):
        reactor, surface = representative(GROUPS, scales, extent=10, cells=100)
        a = reactor.reactive_perimeter/reactor.area
        assert reactor.velocity*scales.length/reactor.diffusivity == pytest.approx(65, rel=1e-14)
        assert a*surface.capture_velocity*scales.length**2/reactor.diffusivity == pytest.approx(1550, rel=1e-14)
        assert scales.concentration/(a*surface.capacity) == pytest.approx(2.5, rel=1e-14)

        # at x = 0.6 and theta = 0.3 the scaled gas and surface rates are Da*0.6*0.7 and gamma times that
        rate = surface.rate(scales.concentration*.6, .3)
        assert a*rate*scales.time/scales.concentration == pytest.approx(1550*.6*.7)
        assert rate*scales.time/surface.capacity == pytest.approx(2.5*1550*.6*.7)


def test_solution_does_not_depend_on_the_chosen_scales():
    """catches a scaled answer that changes with the representative si values."""
    args = dict(extent=2., cells=80, pulse_tau=.002, purge_tau=.003,
                options=SolverOptions(max_step=.0005), output_tau=[0., .001, .002, .003, .005])
    first = solve_dimensionless(GROUPS, **args)
    second = solve_dimensionless(GROUPS, scales=ODD_SCALES, **args)
    for name, array in first.arrays().items():
        np.testing.assert_allclose(array, second.arrays()[name], atol=1e-7, rtol=0)
    assert second.raw.solver_status[0]["end_state"] == second.raw.solver_status[1]["start_state"]

    # captured amount equals the integral of theta over the extent divided by gamma
    assert first.arrays()["captured"][-1] == pytest.approx(
        np.sum(first.theta[-1])*(2/80)/GROUPS.gamma, rel=1e-13)


def test_solver_matches_an_independent_available_site_model():
    """catches a wrong flux, boundary or reaction term in the production solver."""
    # this reference writes the group equations directly with free sites s = 1 - theta
    n, extent, pulse, purge = 32, 2., .002, .003
    h = extent/n
    state = np.r_[np.zeros(n), np.ones(n)]
    for duration, inlet in [(pulse, 1.), (purge, 0.)]:
        def rhs(t, y):
            """gas and free-site equations written straight from the groups."""
            x, available = y[:n], y[n:]
            flux = np.r_[65*inlet-2*(x[0]-inlet)/h,
                         65*x[:-1]-np.diff(x)/h,
                         65*x[-1]+2*x[-1]/h]
            reaction = 1550*x*available
            return np.r_[-np.diff(flux)/h-reaction, -2.5*reaction]

        reference = solve_ivp(rhs, (0, duration), state, method="Radau", rtol=1e-10, atol=1e-12)
        assert reference.success
        state = reference.y[:, -1]
    result = solve_dimensionless(GROUPS, extent=extent, cells=n,
        pulse_tau=pulse, purge_tau=purge, output_tau=[0., pulse, pulse+purge])
    np.testing.assert_allclose(result.x[-1], state[:n], atol=1e-7, rtol=0)
    np.testing.assert_allclose(result.theta[-1], 1-state[n:], atol=1e-7, rtol=0)
