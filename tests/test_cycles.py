"""full-cycle equations against exact limits, older engines and mass balance."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from ald_twin.cycle_study import candidate_choice, decision, purge_crossing
from ald_twin.cycle_transport import CycleGrid, channel_grid, composition_fluxes, diffusivity
from ald_twin.cycles import (CycleChemistry, CycleSegment, M_DEZ, M_WATER, M_ETHANE,
                             M_ZNO, M_RETAINED_A, M_RETAINED_B, PeriodicFailure,
                             initial_state, solve_cycle, periodic_cycle, periodic_gpc)
from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import WellMixedReactor, FlowSegment, solve_0d
from ald_twin.reactor_1d import Reactor1D, TransportSegment, FluxBoundary, solve_1d
from ald_twin.surface import FiniteCapacity

OPTIONS = SolverOptions("Radau", 1e-10, 1e-12, 0.05)


def mixed_grid(flow=1., area=1.):
    """a single well-mixed cell with unit volume."""
    return CycleGrid(np.array([0.5]), np.array([1.]), np.array([area]),
                     np.array([1.]), flow, np.empty((2, 0)), {"kind": "synthetic"})


def parameters():
    """the synthetic channel with a 0.01 m²/s diffusivity for both precursors."""
    data = json.loads((Path(__file__).parents[1] / "config/synthetic/phase45.json").read_text())
    prop = dict(kind="synthetic", source="unit test", value=0.01, temperature=423.15, pressure=200.)
    return data | {"diffusivity": {"a": prop, "b": prop.copy()}}


def test_diffusivity_scales_as_one_over_pressure_and_refuses_physical_values():
    """catches a wrong pressure scaling or a missing value replaced by a default."""
    prop = parameters()["diffusivity"]["a"]
    np.testing.assert_allclose(diffusivity(prop, 423.15, np.array([200., 400.])), [.01, .005])
    with pytest.raises(ValueError, match="not accepted"):
        diffusivity(dict(kind="physical", value=None), 423.15, 200.)
    with pytest.raises(ValueError, match="temperature"):
        diffusivity(prop, 473.15, 200.)


def test_channel_grid_keeps_inventory_and_passes_uniform_composition():
    """catches grid refinement that changes gas or area totals, or a spurious flux."""
    grids = [channel_grid(parameters(), n) for n in (1, 20, 40)]
    np.testing.assert_allclose([g.carrier_moles.sum() for g in grids], grids[0].carrier_moles.sum(), rtol=1e-14)
    np.testing.assert_allclose([g.reactive_areas.sum() for g in grids], grids[0].reactive_areas.sum(), rtol=1e-14)

    # a uniform mole fraction is carried unchanged even though pressure varies
    grid = grids[1]
    x = np.broadcast_to(np.array([[0.01], [0.02]]), (2, len(grid.z)))
    inlet = grid.molar_flow * x[:, 0]
    flux = composition_fluxes(x, grid, inlet)
    np.testing.assert_allclose(flux, np.broadcast_to(inlet[:, None], flux.shape), rtol=1e-14)


def test_advection_front_converges_to_carrier_mole_characteristics():
    """catches an advection scheme that moves the front at the wrong speed."""
    errors = []
    for cells in (40, 80, 160):
        # with no diffusion the front advances by F*t carrier moles
        grid = channel_grid(parameters(), cells)
        grid = replace(grid, conductance=np.zeros_like(grid.conductance))
        time = .5*grid.carrier_moles.sum()/grid.molar_flow
        result = solve_cycle(grid, CycleChemistry(1e-6, 0., 0.),
                             [CycleSegment(time, .01*grid.molar_flow, 0.)],
                             fraction_scale=.01, options=OPTIONS)
        before = np.r_[0., np.cumsum(grid.carrier_moles)[:-1]]
        exact = np.minimum(1., np.maximum(0., (grid.molar_flow*time-before)/grid.carrier_moles))
        errors.append(np.average(abs(result.fields[0, -1]-exact), weights=grid.carrier_moles))
        assert result.checks()["relative_ledger"] < 1e-8
    assert errors[1] < .8*errors[0]
    assert errors[2] < .8*errors[1]


def test_closed_diffusion_converges_to_cosine_decay():
    """catches a wrong diffusive conductance or boundary leak in a closed tube."""
    errors = []
    for cells in (20, 40, 80):
        dz = 1/cells
        grid = CycleGrid((np.arange(cells)+.5)*dz, np.full(cells, dz), np.zeros(cells),
                         np.ones(cells), 0., np.full((2, cells-1), .2/dz), {"kind": "synthetic"})
        # cell averages of cos(pi z) decay as exp(-D pi² t) with D = 0.2
        cell_cosine = np.sinc(.5/cells)*np.cos(np.pi*grid.z)
        fractions = np.array([.01*(1+.2*cell_cosine), np.zeros(cells)])
        start = initial_state(grid, fraction_scale=.01, fractions=fractions)
        result = solve_cycle(grid, CycleChemistry(.01, 0., 0.), [CycleSegment(1., 0., 0.)],
                             fraction_scale=.01, state=start, options=OPTIONS)
        exact = 1+.2*cell_cosine*np.exp(-.2*np.pi**2)
        errors.append(np.max(abs(result.fields[0, -1]-exact)))
        np.testing.assert_allclose(result.gas_moles[0], .01, atol=1e-12)
    assert errors[1] < .3*errors[0]
    assert errors[2] < .3*errors[1]


def test_surface_coverage_matches_exact_two_precursor_solution():
    """catches A or B reacting on the wrong sites, or events that do not balance coverage."""
    chemistry = CycleChemistry(.02, 3., 5.)
    initial = .37
    for concentration in ([.03, 0.], [0., .04], [.03, .04]):
        # d(theta)/dt = a (1 - theta) - b theta relaxes to a / (a + b)
        a = chemistry.rate_a*concentration[0]
        b = chemistry.rate_b*concentration[1]

        def exact(t):
            """exact coverage at time t."""
            return a/(a+b) + (initial-a/(a+b))*np.exp(-(a+b)*t)

        def rhs(_t, y):
            """coverage and the two event counts from the production rates."""
            events = chemistry.rates(concentration, y[0]) / chemistry.capacity
            return [events[0]-events[1], events[0], events[1]]

        result = solve_ivp(rhs, [0, 50], [initial, 0, 0], method="Radau", rtol=1e-10, atol=1e-12)
        np.testing.assert_allclose(result.y[0], exact(result.t), atol=1e-9)
        np.testing.assert_allclose(result.y[1]-result.y[2], result.y[0]-initial, atol=1e-12)


def test_half_cycle_matches_the_older_0d_and_spatial_engines():
    """catches the shared cycle equations drifting from the two verified engines."""
    chemistry = CycleChemistry(.01, 1000., 0.)

    # one mixed cell against the well-mixed engine
    recipe = [CycleSegment(1.5, .01, 0.), CycleSegment(3., 0., 0.)]
    times = np.linspace(0, 4.5, 91)
    result = solve_cycle(mixed_grid(), chemistry, recipe, fraction_scale=.01,
                         options=OPTIONS, output_times=times)
    old = solve_0d(WellMixedReactor(1., 1., 1.), FiniteCapacity(.01, 10.),
                   [FlowSegment(1.5, .01), FlowSegment(3., 0.)], concentration_scale=.01,
                   options=OPTIONS, output_times=times)
    np.testing.assert_allclose(result.fields[0, :, 0], old.c[:, 0]/.01, atol=2e-8)
    np.testing.assert_allclose(result.fields[2, :, 0], old.theta[:, 0], atol=2e-8)
    assert result.checks()["relative_ledger"] < 1e-8
    assert result.checks()["exact_segment_carryover"]

    # twenty cells against the spatial engine
    n = 20
    dz = 1/n
    grid = CycleGrid((np.arange(n)+.5)*dz, np.full(n, dz), np.full(n, dz),
                     np.ones(n), 1., np.full((2, n-1), .2/dz), {"kind": "synthetic"})
    segments = [CycleSegment(1., .01, 0.), CycleSegment(2., 0., 0.)]
    times = np.linspace(0, 3, 61)
    result = solve_cycle(grid, chemistry, segments, fraction_scale=.01, options=OPTIONS, output_times=times)
    old = solve_1d(Reactor1D(1., 1., 1., 1., .2, n), FiniteCapacity(.01, 10.),
                   [TransportSegment(s.duration, FluxBoundary(s.inlet_a)) for s in segments],
                   concentration_scale=.01, options=OPTIONS, output_times=times)
    np.testing.assert_allclose(result.fields[0], old.c/.01, atol=2e-8)
    np.testing.assert_allclose(result.fields[2], old.theta, atol=2e-8)


def test_closed_batch_conserves_atoms_and_mass():
    """catches wrong molar masses or a batch that makes film from nothing."""
    # element counts Zn, C, H, O: DEZ + H2O - 2 C2H6 leaves one ZnO
    dez, water, ethane = np.array([1, 4, 10, 0]), np.array([0, 0, 2, 1]), np.array([0, 2, 6, 0])
    np.testing.assert_array_equal(dez + water - 2*ethane, [1, 0, 0, 1])
    assert M_RETAINED_B < 0
    assert M_RETAINED_A + M_RETAINED_B == pytest.approx(M_ZNO)
    assert M_DEZ + M_WATER - 2*M_ETHANE == pytest.approx(M_ZNO)

    # a closed cell can use no more precursor than it holds and keeps its mass
    grid = mixed_grid(flow=0.)
    state = initial_state(grid, fraction_scale=.01, fractions=np.array([[.006], [.003]]), theta=.2)
    result = solve_cycle(grid, CycleChemistry(.01, 1000., 1200.), [CycleSegment(20., 0., 0.)],
                         fraction_scale=.01, state=state, options=OPTIONS)
    consumption = result.events[:, :, 0]
    assert consumption[0, -1] <= .006 + 1e-10
    assert consumption[1, -1] <= .003 + 1e-10
    retained = M_RETAINED_A*consumption[0] + M_RETAINED_B*consumption[1]
    gas_mass = M_DEZ*result.gas_moles[0] + M_WATER*result.gas_moles[1]
    ethane_mass = M_ETHANE*consumption.sum(axis=0)
    np.testing.assert_allclose(gas_mass + ethane_mass + retained, gas_mass[0], atol=1e-12)
    assert result.checks()["relative_ledger"] < 1e-8
    assert result.checks()["event_balance"] < 1e-9


def test_decisions_keep_ambiguous_and_missing_candidates_unresolved():
    """catches a pass or fail declared inside the numerical uncertainty."""
    summary = dict(minimum_a_completion=.95, maximum_b_remaining=.05,
                   purge_a_residual=.0099, purge_b_residual=.002)
    assert decision(summary, .001) is None
    assert decision(summary, .00001) is True
    assert decision(summary | {"minimum_a_completion": .8}, .001) is False

    rows = [dict(case="short", feasible=None, metrics=dict(cycle_time_s=1.)),
            dict(case="long", feasible=True, metrics=dict(cycle_time_s=2.))]
    assert candidate_choice(rows)["status"] == "unresolved"
    rows[0]["feasible"] = False
    assert candidate_choice(rows)["case"] == "long"
    rows[1]["feasible"] = False
    assert candidate_choice(rows)["status"] == "no_feasible_candidate"

    # the last downward crossing of 0.01 is at 2.5 s, and a signal that never falls has none
    assert purge_crossing(np.array([0., 1., 2., 3.]), np.array([.02, 0., .02, 0.])) == 2.5
    assert purge_crossing(np.array([0., 1.]), np.array([.02, .02])) is None


def test_periodic_cycle_converges_and_a_short_run_fails_openly():
    """catches a non-repeating cycle reported as periodic or growth from a failed run."""
    recipe = [CycleSegment(3., .01, 0.), CycleSegment(5., 0., 0.),
              CycleSegment(3., 0., .01), CycleSegment(5., 0., 0.)]
    result = periodic_cycle(mixed_grid(), CycleChemistry(.01, 1000., 1200.), recipe,
                            fraction_scale=.01, options=OPTIONS, output_times=np.linspace(0, 16, 65))
    assert result.periodic
    assert result.fields[4, -1, 0] > result.turnover[0] > .9
    assert result.history[-1]["state_error"] <= 1e-7
    assert result.history[-1]["growth_error"] <= 1e-7

    # every B event completes one ZnO unit
    events = result.events[:, -1] - result.events[:, 0]
    retained = M_RETAINED_A*events[0] + M_RETAINED_B*events[1]
    np.testing.assert_allclose(retained, M_ZNO*events[1], atol=1e-9)

    # two very short cycles cannot repeat, so no growth per cycle is given
    short = [CycleSegment(.01, .01, 0.), CycleSegment(.01, 0., .01)]
    with pytest.raises(PeriodicFailure) as caught:
        periodic_cycle(mixed_grid(), CycleChemistry(.01, 1., 1.), short,
                       fraction_scale=.01, max_cycles=2, options=OPTIONS)
    assert len(caught.value.result.history) == 2
    assert not caught.value.result.periodic
    with pytest.raises(ValueError, match="periodic"):
        periodic_gpc(caught.value.result, 5400.)
