"""full-cycle equations against exact limits, older engines and mass balance."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from ald_twin.cycle_study import candidate_choice, decision, purge_crossing
from ald_twin.cycle_transport import CycleGrid, channel_grid, diffusivity
from ald_twin.cycles import (CycleChemistry, CycleSegment, M_DEZ, M_WATER, M_ETHANE,
                             M_ZNO, M_RETAINED_A, M_RETAINED_B, initial_state, solve_cycle)
from ald_twin.numerics import SolverOptions

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
