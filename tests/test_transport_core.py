"""Phase 1A contract checks; this file alone is not the Phase 1 gate."""

from dataclasses import replace

import numpy as np
import pytest

from ald_twin.analytical import cell_averages, pulse_response, step_response
from ald_twin.numerics import SolverFailure, SolverOptions, integrate_segments
from ald_twin.reactor_1d import (AdvectiveBoundary, ConcentrationBoundary, FluxBoundary,
    Reactor1D, TransportSegment, face_fluxes, solve_1d)
from ald_twin.surface import FiniteCapacity


def reactor(**kw):
    return Reactor1D(**(dict(length=1., area=.01, reactive_perimeter=.2,
        velocity=.5, diffusivity=.1, cells=40) | kw))


def conservation_relative(result):
    denominator = result.metadata["initial_gas_moles"] + result.entered_moles
    nonzero = denominator > 0
    return float(np.max(np.abs(result.ledger_error_moles[nonzero]) / denominator[nonzero], initial=0.))


def test_dirichlet_half_cell_distances_and_signed_upwind():
    r = reactor(cells=2, velocity=2., diffusivity=.3)
    c = np.array([3., 5.])
    boundary = ConcentrationBoundary(7., 11.)
    assert np.allclose(face_fluxes(c, r, boundary), [18.8, 4.8, 2.8], atol=1e-14)
    assert np.allclose(face_fluxes(c, replace(r, velocity=-2.), boundary), [-1.2, -11.2, -29.2], atol=1e-14)


def test_flux_boundary_prescribes_total_flux_not_concentration():
    r = reactor()
    flux = face_fluxes(np.full(r.cells, 3.), r, FluxBoundary(.02))
    assert abs(flux[0] - .02 / r.area) <= 1e-12
    assert abs(flux[-1] - r.velocity * 3.) <= 1e-12


def test_hyperbolic_inflow_only_and_reverse_flow():
    r = reactor(cells=2, diffusivity=0., velocity=2.)
    with pytest.raises(ValueError, match="hyperbolic"):
        face_fluxes([3., 5.], r, ConcentrationBoundary(7., 11.))
    np.testing.assert_array_equal(face_fluxes([3., 5.], r, AdvectiveBoundary(7.)), [14., 6., 10.])
    np.testing.assert_array_equal(face_fluxes([3., 5.], replace(r, velocity=-2.), AdvectiveBoundary(7.)), [-6., -10., -14.])
    with pytest.raises(ValueError, match="forward"):
        face_fluxes([3., 5.], replace(r, velocity=-2.), FluxBoundary(1.))


def test_zero_input_preserves_nonfresh_surface():
    r = reactor()
    result = solve_1d(r, FiniteCapacity(.02, .01), [TransportSegment(1., FluxBoundary(0.))],
                      concentration_scale=.1, initial_theta=.3)
    assert np.max(np.abs(result.c)) / .1 <= 1e-10
    assert np.max(np.abs(result.theta-.3)) <= 1e-10
    assert np.max(np.abs(result.ledger_error_moles)) == 0


@pytest.mark.parametrize("velocity", [.5, -.5])
def test_constant_dirichlet_solution(velocity):
    r = reactor(velocity=velocity)
    result = solve_1d(r, FiniteCapacity(.02, 0.),
        [TransportSegment(1., ConcentrationBoundary(.1, .1))],
        concentration_scale=.1, initial_c=.1, initial_theta=.3)
    assert np.max(np.abs(result.c/.1-1)) <= 1e-10
    assert np.max(np.abs(result.theta-.3)) <= 1e-10
    assert conservation_relative(result) <= 1e-8


def test_reacting_flux_pulse_purge_preserves_all_states():
    r = reactor()
    result = solve_1d(r, FiniteCapacity(.02, .05), [
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


def test_dirichlet_purge_accounts_for_inlet_escape():
    r = reactor(velocity=0.)
    result = solve_1d(r, FiniteCapacity(.02, 0.),
        [TransportSegment(.1, ConcentrationBoundary(0., 0.))],
        concentration_scale=.1, initial_c=.1)
    first_flux = face_fluxes(result.c[0], r, ConcentrationBoundary(0., 0.))
    assert first_flux[0] < 0 < first_flux[-1]
    assert result.entered_moles[-1] == 0
    assert result.escaped_moles[-1] > 0
    assert conservation_relative(result) <= 1e-8


def test_artificial_gas_and_surface_sources_enter_ledger():
    r = reactor(velocity=0., cells=12)
    result = solve_1d(r, FiniteCapacity(.02, 0.),
        [TransportSegment(.2, ConcentrationBoundary(0., 0.))], concentration_scale=.1,
        artificial_source=lambda t, z: (np.full_like(z, .01), np.full_like(z, .02)),
        source_id="synthetic-constant-source-plumbing")
    expected_source = .2*(r.area*r.length*.01 + r.reactive_perimeter*r.length*.02*.02)
    assert abs(result.source_moles[-1] / expected_source - 1) <= 1e-10
    assert np.max(np.abs(result.ledger_error_moles)) / expected_source <= 1e-8


def test_diffusion_reference_initial_acceptance():
    # Extended downstream boundary is negligible on this time interval.
    r = reactor(length=1., velocity=0., diffusivity=.1, cells=200)
    result = solve_1d(r, FiniteCapacity(.02, 0.),
        [TransportSegment(.1, ConcentrationBoundary(.1, 0.))], concentration_scale=.1)
    expected = cell_averages(lambda z: step_response(z, .1, 0., .1), np.linspace(0, 1, 201))
    error = np.sum(np.abs(result.c[-1]/.1-expected)) / np.sum(np.abs(expected))
    assert error <= 1e-3
    assert result.c.min()/.1 >= -1e-8
    assert result.c.max()/.1 <= 1+1e-8


def test_analytical_reference_avoids_exponential_overflow():
    z = np.array([0., 1., 2.])
    with np.errstate(over="raise", invalid="raise"):
        response = step_response(z, 1., 1., 1e-6)
        pulse = pulse_response(z, 1., .5, 1., 1e-6)
    assert np.all(np.isfinite(response)) and np.all(np.isfinite(pulse))
    assert response[0] == 1.
    assert abs(response[1] - .5) < .001


def test_failed_solver_is_not_reported_as_success(monkeypatch):
    from types import SimpleNamespace
    import ald_twin.numerics as module
    failed = SimpleNamespace(success=False, t=np.array([0., .1]),
        y=np.array([[1., 2.]]), message="test integration failure")
    monkeypatch.setattr(module, "solve_ivp", lambda *a, **kw: failed)
    with pytest.raises(SolverFailure, match="Segment 0 failed") as error:
        integrate_segments([1.], [1.], lambda i: lambda t, y: y, SolverOptions())
    assert error.value.result is failed


def test_scale_and_recipe_validation():
    with pytest.raises(ValueError, match="scale"):
        solve_1d(reactor(), FiniteCapacity(.02, .01), [], concentration_scale=0.)
    with pytest.raises(ValueError, match="duration"):
        solve_1d(reactor(), FiniteCapacity(.02, .01), [], concentration_scale=.1)


def test_result_persistence_handles_numpy_scalars_and_dotted_names(tmp_path):
    import json
    result = solve_1d(reactor(cells=np.int64(4)), FiniteCapacity(.02, 0.),
        [TransportSegment(.01, FluxBoundary(0.))], concentration_scale=.1)
    result.save(tmp_path / "run_0.1")
    result.save(tmp_path / "run_0.2")
    assert (tmp_path / "run_0.1.npz").is_file()
    assert (tmp_path / "run_0.2.npz").is_file()
    snapshot = json.loads((tmp_path / "run_0.1.json").read_text())
    assert snapshot["metadata"]["reactor"]["cells"] == 4
    assert "scipy" in snapshot["metadata"]["runtime"]
