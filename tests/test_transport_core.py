"""spatial transport: face fluxes, conservation and an exact diffusion answer."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import ald_twin.numerics as numerics
from ald_twin.analytical import cell_averages, pulse_response, step_response
from ald_twin.numerics import SolverFailure, SolverOptions, integrate_segments
from ald_twin.reactor_1d import (AdvectiveBoundary, ConcentrationBoundary, FluxBoundary,
    Reactor1D, TransportSegment, face_fluxes, solve_1d)
from ald_twin.surface import FiniteCapacity


def reactor(**changes):
    """a 1 m channel with 40 cells, with any field changed."""
    fields = dict(length=1., area=.01, reactive_perimeter=.2, velocity=.5, diffusivity=.1, cells=40)
    fields.update(changes)
    return Reactor1D(**fields)


def conservation_relative(result):
    """largest ledger error relative to the gas that was present or entered."""
    denominator = result.metadata["initial_gas_moles"] + result.entered_moles
    nonzero = denominator > 0
    return float(np.max(np.abs(result.ledger_error_moles[nonzero]) / denominator[nonzero], initial=0.))


def test_face_fluxes_match_hand_worked_values():
    """catches a wrong boundary distance, upwind direction or boundary type."""
    # two cells of 0.5 m, u = 2, D = 0.3, c = [3, 5], walls held at 7 and 11.
    # the wall is half a cell away, so the inlet flux is 2*7 - 2*0.3*(3 - 7)/0.5 = 18.8
    r = reactor(cells=2, velocity=2., diffusivity=.3)
    c = np.array([3., 5.])
    boundary = ConcentrationBoundary(7., 11.)
    np.testing.assert_allclose(face_fluxes(c, r, boundary), [18.8, 4.8, 2.8], atol=1e-14)
    np.testing.assert_allclose(face_fluxes(c, replace(r, velocity=-2.), boundary),
                               [-1.2, -11.2, -29.2], atol=1e-14)

    # without diffusion only the upstream inflow value is used
    r = reactor(cells=2, diffusivity=0., velocity=2.)
    with pytest.raises(ValueError, match="hyperbolic"):
        face_fluxes(c, r, ConcentrationBoundary(7., 11.))
    np.testing.assert_array_equal(face_fluxes(c, r, AdvectiveBoundary(7.)), [14., 6., 10.])
    np.testing.assert_array_equal(face_fluxes(c, replace(r, velocity=-2.), AdvectiveBoundary(7.)),
                                  [-6., -10., -14.])

    # a flux boundary sets the total inlet flux, and the outlet only advects
    r = reactor()
    flux = face_fluxes(np.full(r.cells, 3.), r, FluxBoundary(.02))
    assert abs(flux[0] - .02 / r.area) <= 1e-12
    assert abs(flux[-1] - r.velocity * 3.) <= 1e-12


def test_steady_states_stay_put():
    """catches spurious gas, coverage or ledger drift in a state that should not change."""
    # nothing enters an empty channel
    empty = solve_1d(reactor(), FiniteCapacity(.02, .01), [TransportSegment(1., FluxBoundary(0.))],
                     concentration_scale=.1, initial_theta=.3)
    assert np.max(np.abs(empty.c)) / .1 <= 1e-10
    assert np.max(np.abs(empty.theta-.3)) <= 1e-10
    assert np.max(np.abs(empty.ledger_error_moles)) == 0

    # equal walls and an equal inside stay equal whichever way the gas flows
    for velocity in (.5, -.5):
        result = solve_1d(reactor(velocity=velocity), FiniteCapacity(.02, 0.),
                          [TransportSegment(1., ConcentrationBoundary(.1, .1))],
                          concentration_scale=.1, initial_c=.1, initial_theta=.3)
        assert np.max(np.abs(result.c/.1-1)) <= 1e-10
        assert np.max(np.abs(result.theta-.3)) <= 1e-10
        assert conservation_relative(result) <= 1e-8


def test_ledger_closes_through_pulses_purges_and_sources():
    """catches moles lost at a segment switch, an inlet wall or an added source."""
    result = solve_1d(reactor(), FiniteCapacity(.02, .05), [
        TransportSegment(.6, FluxBoundary(.0005), "exposure"),
        TransportSegment(1., FluxBoundary(0.), "purge")], concentration_scale=.1)
    assert result.solver_status[0]["end_state"] == result.solver_status[1]["start_state"]
    switch = np.flatnonzero(result.t == .6)
    assert len(switch) == 1
    assert result.gas_moles[switch[0]] > 0
    assert result.captured_moles[-1] > result.captured_moles[switch[0]] > 0
    assert conservation_relative(result) <= 1e-8
    assert result.c.min() / .1 >= -1e-8
    assert result.theta.min() >= -1e-8
    assert result.theta.max() <= 1+1e-8

    # with both walls at zero, gas leaves through the inlet as well as the outlet
    still = reactor(velocity=0.)
    result = solve_1d(still, FiniteCapacity(.02, 0.),
                      [TransportSegment(.1, ConcentrationBoundary(0., 0.))],
                      concentration_scale=.1, initial_c=.1)
    first_flux = face_fluxes(result.c[0], still, ConcentrationBoundary(0., 0.))
    assert first_flux[0] < 0 < first_flux[-1]
    assert result.entered_moles[-1] == 0
    assert result.escaped_moles[-1] > 0
    assert conservation_relative(result) <= 1e-8

    # constant sources of 0.01 mol/(m³ s) in gas and 0.02*0.02 mol/(m² s) on the wall for 0.2 s
    still = reactor(velocity=0., cells=12)
    result = solve_1d(still, FiniteCapacity(.02, 0.),
        [TransportSegment(.2, ConcentrationBoundary(0., 0.))], concentration_scale=.1,
        artificial_source=lambda t, z: (np.full_like(z, .01), np.full_like(z, .02)),
        source_id="synthetic-constant-source-plumbing")
    expected_source = .2*(still.area*still.length*.01 + still.reactive_perimeter*still.length*.02*.02)
    assert abs(result.source_moles[-1] / expected_source - 1) <= 1e-10
    assert np.max(np.abs(result.ledger_error_moles)) / expected_source <= 1e-8


def test_diffusion_matches_the_exact_step_response():
    """catches a wrong diffusion discretisation or an overflowing analytical answer."""
    # a long channel, so the far wall does not matter over 0.1 s
    r = reactor(length=1., velocity=0., diffusivity=.1, cells=200)
    result = solve_1d(r, FiniteCapacity(.02, 0.),
        [TransportSegment(.1, ConcentrationBoundary(.1, 0.))], concentration_scale=.1)
    expected = cell_averages(lambda z: step_response(z, .1, 0., .1), np.linspace(0, 1, 201))
    error = np.sum(np.abs(result.c[-1]/.1-expected)) / np.sum(np.abs(expected))
    assert error <= 1e-3
    assert result.c.min()/.1 >= -1e-8
    assert result.c.max()/.1 <= 1+1e-8

    # the reference stays finite at high Peclet number
    z = np.array([0., 1., 2.])
    with np.errstate(over="raise", invalid="raise"):
        response = step_response(z, 1., 1., 1e-6)
        pulse = pulse_response(z, 1., .5, 1., 1e-6)
    assert np.all(np.isfinite(response))
    assert np.all(np.isfinite(pulse))
    assert response[0] == 1.
    assert abs(response[1] - .5) < .001


def test_failed_solver_is_not_reported_as_success(monkeypatch):
    """catches a failed integration being passed on as a result."""
    failed = SimpleNamespace(success=False, t=np.array([0., .1]),
        y=np.array([[1., 2.]]), message="test integration failure")
    monkeypatch.setattr(numerics, "solve_ivp", lambda *a, **kw: failed)
    with pytest.raises(SolverFailure, match="Segment 0 failed") as error:
        integrate_segments([1.], [1.], lambda i: lambda t, y: y, SolverOptions())
    assert error.value.result is failed
