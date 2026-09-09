"""Verify the adapter against transformed coefficients and an available-site RHS."""

from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from ald_twin.configuration import ParameterRegistry
from ald_twin.dimensionless import (DimensionlessGroups, MathematicalScales,
    representative, solve_dimensionless)
from ald_twin.numerics import SolverOptions


GROUPS = DimensionlessGroups(65., 1550., 2.5)
CONFIG = Path(__file__).resolve().parents[1]/"config/benchmarks/benchmark-a.json"


@pytest.mark.parametrize("scales", [MathematicalScales(),
    MathematicalScales(.13, .004, .7, .002, 17.)])
def test_group_recovery(scales):
    reactor, surface = representative(GROUPS, scales, extent=10, cells=100)
    a = reactor.reactive_perimeter/reactor.area
    assert reactor.velocity*scales.length/reactor.diffusivity == pytest.approx(65, rel=1e-14)
    assert a*surface.capture_velocity*scales.length**2/reactor.diffusivity == pytest.approx(1550, rel=1e-14)
    assert scales.concentration/(a*surface.capacity) == pytest.approx(2.5, rel=1e-14)
    # Local gas and occupied-capacity reaction derivatives in tau.
    rate = surface.rate(scales.concentration*.6, .3)
    assert a*rate*scales.time/scales.concentration == pytest.approx(1550*.6*.7)
    assert rate*scales.time/surface.capacity == pytest.approx(2.5*1550*.6*.7)


def test_arbitrary_representatives_preserve_normalized_solution_and_ledger():
    args = dict(extent=2., cells=80, pulse_tau=.002, purge_tau=.003,
        options=SolverOptions(max_step=.0005), output_tau=[0., .001, .002, .003, .005])
    first = solve_dimensionless(GROUPS, **args)
    second = solve_dimensionless(GROUPS,
        scales=MathematicalScales(.13, .004, .7, .002, 17.), **args)
    for name, array in first.arrays().items():
        np.testing.assert_allclose(array, second.arrays()[name], atol=1e-7, rtol=0)
    assert second.raw.solver_status[0]["end_state"] == second.raw.solver_status[1]["start_state"]
    assert first.arrays()["captured"][-1] == pytest.approx(
        np.sum(first.theta[-1])*(2/80)/GROUPS.gamma, rel=1e-13)


def test_independent_available_site_formulation():
    # Test-only formulation writes group coefficients directly. No SI adapter,
    # surface.rate, or production face_fluxes enters this independent RHS.
    n, extent, pulse, purge = 32, 2., .002, .003
    h = extent/n
    state = np.r_[np.zeros(n), np.ones(n)]
    for duration, inlet in [(pulse, 1.), (purge, 0.)]:
        def rhs(t, y):
            x, available = y[:n], y[n:]
            f = np.r_[65*inlet-2*(x[0]-inlet)/h,
                       65*x[:-1]-np.diff(x)/h,
                       65*x[-1]+2*x[-1]/h]
            reaction = 1550*x*available
            return np.r_[-np.diff(f)/h-reaction, -2.5*reaction]
        ref = solve_ivp(rhs, (0, duration), state, method="Radau",
                        rtol=1e-10, atol=1e-12)
        assert ref.success
        state = ref.y[:, -1]
    result = solve_dimensionless(GROUPS, extent=extent, cells=n,
        pulse_tau=pulse, purge_tau=purge, output_tau=[0., pulse, pulse+purge])
    np.testing.assert_allclose(result.x[-1], state[:n], atol=1e-7, rtol=0)
    np.testing.assert_allclose(result.theta[-1], 1-state[n:], atol=1e-7, rtol=0)


def test_benchmark_config_retains_unresolved_metadata_and_beta_is_not_a_solver_input():
    registry = ParameterRegistry.load(CONFIG)
    assert registry.resolve({"pe": "1", "da": "1", "gamma": "1", "beta0": "1"}) == dict(
        pe=65., da=1550., gamma=2.5, beta0=.01)
    for field, unit in [("published_pulse_tau", "1"), ("published_readout_tau", "1"),
                         ("seconds_per_tau", "s"), ("experimental_u", "m s^-1"),
                         ("experimental_D", "m^2 s^-1")]:
        with pytest.raises(ValueError, match="Blocked dependent run"):
            registry.resolve({field: unit})
    with pytest.raises(TypeError):
        DimensionlessGroups(pe=65., da=1550., gamma=2.5, beta0=.01)


def test_saved_normalized_units_are_separate_from_synthetic_si(tmp_path):
    import json
    result = solve_dimensionless(GROUPS, extent=2, cells=20,
        pulse_tau=.001, purge_tau=.001, output_tau=[0., .001, .002])
    stem = tmp_path/"pulse.001"
    result.save(stem)
    snapshot = json.loads(Path(str(stem)+".json").read_text())
    arrays = np.load(str(stem)+".npz")
    assert snapshot["units"]["tau"] == "1"
    assert not snapshot["experimental_dimensional_mapping"]
    assert not snapshot["exact_published_curve_reproduction"]
    np.testing.assert_array_equal(arrays["available_sites"], 1-arrays["theta"])
    assert Path(str(stem)+"-synthetic-representative.json").exists()


@pytest.mark.parametrize("kwargs", [{"pe": 0}, {"da": -1}, {"gamma": float("nan")}, {"pe": True}])
def test_invalid_groups(kwargs):
    with pytest.raises(ValueError):
        DimensionlessGroups(**(dict(pe=65, da=1550, gamma=2.5) | kwargs))


@pytest.mark.parametrize("field", ["length", "diffusivity", "concentration", "area", "area_ratio"])
def test_invalid_scales(field):
    with pytest.raises(ValueError):
        MathematicalScales(**{field: 0})
