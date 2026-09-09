"""Synthetic unit, analytical, and conservation checks for the lumped engine."""

import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.surface import FiniteCapacity
from ald_twin.units import (
    K_B,
    N_A,
    R,
    actual_volumetric_flow,
    angstrom_to_metre,
    celsius_to_kelvin,
    density_g_cm3_to_kg_m3,
    molar_mass_g_mol_to_kg_mol,
    precursor_partial_pressure,
    sccm_to_molar_flow,
)


def test_explicit_si_and_standard_flow_conversions():
    assert R == K_B * N_A
    assert math.isclose(R, 8.31446261815324, rel_tol=1e-15)
    assert celsius_to_kelvin(150.0) == 423.15
    assert angstrom_to_metre(10.0) == 1e-9
    assert density_g_cm3_to_kg_m3(5.4) == 5400.0
    assert math.isclose(molar_mass_g_mol_to_kg_mol(72.0), 0.072, rel_tol=1e-12)
    # Independent arithmetic uses the declared ideal-gas standard molar volume.
    standard_molar_volume_cm3 = 8.31446261815324 * 273.15 / 101325 * 1e6
    flow = sccm_to_molar_flow(500.0, 273.15, 101325.0)
    assert math.isclose(flow, 500.0 / (60 * standard_molar_volume_cm3), rel_tol=1e-12)
    actual = actual_volumetric_flow(flow, 423.15, 200.0)
    expected = (500e-6 / 60) * (423.15 / 273.15) * (101325 / 200)
    assert math.isclose(actual, expected, rel_tol=1e-12)
    assert math.isclose(precursor_partial_pressure(0.02, 400), 0.02 * R * 400, rel_tol=1e-12)
    assert sccm_to_molar_flow(0, 273.15, 101325) == 0


def test_probability_uses_molar_mass_and_rate_broadcasts_without_clipping():
    surface = FiniteCapacity.from_probability(
        capacity=2e-5, beta=1e-3, temperature=400.0, molar_mass=0.072
    )
    molecular_mass = 0.072 / N_A
    expected_velocity = 1e-3 * math.sqrt(8 * K_B * 400 / (math.pi * molecular_mass)) / 4
    assert math.isclose(surface.capture_velocity, expected_velocity, rel_tol=1e-12)
    actual = surface.rate(np.array([0.0, 0.02, 0.02]), np.array([0.0, 0.0, 1.0]))
    np.testing.assert_allclose(actual, [0.0, 0.02 * expected_velocity, 0.0], rtol=1e-14)
    assert surface.rate(1.0, 1.1) < 0
    assert surface.rate(-1e-12, 0) < 0


def test_prescribed_concentration_surface_saturation():
    surface = FiniteCapacity(capacity=2e-5, capture_velocity=0.004)
    concentration, theta_initial = 0.015, 0.17
    rate_constant = surface.capture_velocity * concentration / surface.capacity
    solution = solve_ivp(
        lambda _time, theta: surface.rate(concentration, theta) / surface.capacity,
        (0, 10 / rate_constant), [theta_initial], method="Radau", rtol=1e-9, atol=1e-11,
    )
    assert solution.success
    exact = 1 - (1 - theta_initial) * np.exp(-rate_constant * solution.t)
    assert np.max(np.abs(solution.y[0] - exact)) <= 1e-7


def test_zero_input_preserves_exact_zero_and_initial_capacity():
    result = solve_0d(
        WellMixedReactor(2e-5, 0.02, 2e-5), FiniteCapacity(2e-5, 0.002),
        [FlowSegment(10, 0, "zero")], concentration_scale=0.01, initial_theta=0.3,
    )
    assert np.max(np.abs(result.c / 0.01)) <= 1e-10
    assert np.max(np.abs(result.theta - 0.3)) <= 1e-10
    assert np.all(result.entered_moles == 0)
    assert np.all(result.escaped_moles == 0)
    assert np.all(result.ledger_error_moles == 0)


def test_nonreacting_purge_matches_ten_residence_times():
    reactor = WellMixedReactor(volume=2e-5, reactive_area=0.02, throughput=8e-6)
    initial_concentration = 0.03
    result = solve_0d(
        reactor, FiniteCapacity(2e-5, 0), [FlowSegment(10 * reactor.volume / reactor.throughput, 0)],
        concentration_scale=initial_concentration, initial_c=initial_concentration,
        initial_theta=0.2,
    )
    exact = initial_concentration * np.exp(-reactor.throughput / reactor.volume * result.t)
    assert np.max(np.abs(result.c[:, 0] - exact)) / initial_concentration <= 1e-7
    assert np.max(np.abs(result.theta[:, 0] - 0.2)) <= 1e-10
    assert np.max(np.abs(result.ledger_error_moles)) / (reactor.volume * initial_concentration) <= 1e-8


@pytest.mark.parametrize("initial_concentration", [0.005, 0.05])
def test_closed_batch_dose_limited_and_capacity_limited(initial_concentration):
    reactor = WellMixedReactor(volume=2e-5, reactive_area=0.02, throughput=0)
    surface = FiniteCapacity(capacity=2e-5, capture_velocity=0.05)
    initial_theta = 0.2
    result = solve_0d(
        reactor, surface, [FlowSegment(5, 0)], concentration_scale=initial_concentration,
        initial_c=initial_concentration, initial_theta=initial_theta,
    )
    inventory = reactor.volume * result.c[:, 0] + reactor.reactive_area * surface.capacity * result.theta[:, 0]
    assert np.max(np.abs(inventory - inventory[0])) / inventory[0] <= 1e-8
    expected = min(1.0, initial_theta + reactor.volume * initial_concentration / (reactor.reactive_area * surface.capacity))
    assert abs(result.theta[-1, 0] - expected) <= 1e-6
    assert np.min(result.c[:, 0] / initial_concentration) >= -1e-8
    assert np.min(result.theta) >= -1e-8
    assert np.max(result.theta) <= 1 + 1e-8


def test_reacting_pulse_purge_conservation_and_state_carryover():
    reactor = WellMixedReactor(2e-5, 0.02, 2e-5)
    surface = FiniteCapacity(2e-5, 0.002)
    pulse, purge = FlowSegment(2, 2e-7, "pulse"), FlowSegment(5, 0, "purge")
    combined = solve_0d(
        reactor, surface, [pulse, purge], concentration_scale=0.01, initial_theta=0.15,
    )
    first = solve_0d(reactor, surface, [pulse], concentration_scale=0.01, initial_theta=0.15)
    second = solve_0d(
        reactor, surface, [purge], concentration_scale=0.01,
        initial_c=first.c[-1, 0], initial_theta=first.theta[-1, 0],
    )
    switch_index = np.flatnonzero(combined.t == pulse.duration)
    assert len(switch_index) == 1
    np.testing.assert_array_equal(combined.c[switch_index[0]], first.c[-1])
    np.testing.assert_array_equal(combined.theta[switch_index[0]], first.theta[-1])
    np.testing.assert_allclose(combined.c[-1], second.c[-1], rtol=1e-7, atol=1e-10)
    np.testing.assert_allclose(combined.theta[-1], second.theta[-1], rtol=0, atol=1e-8)
    assert combined.theta[-1, 0] > combined.theta[switch_index[0], 0]
    assert combined.c[switch_index[0], 0] > 0
    dose = pulse.duration * pulse.inlet_molar_flow
    assert abs(combined.entered_moles[-1] - dose) / dose <= 1e-8
    assert np.max(np.abs(combined.ledger_error_moles)) / dose <= 1e-8
    assert np.min(combined.c / 0.01) >= -1e-8
    assert np.min(combined.theta) >= -1e-8
    assert np.max(combined.theta) <= 1 + 1e-8


def test_same_precursor_cannot_recapture_saturated_capacity():
    result = solve_0d(
        WellMixedReactor(2e-5, 0.02, 2e-5), FiniteCapacity(2e-5, 0.002),
        [FlowSegment(2, 2e-7), FlowSegment(5, 0), FlowSegment(2, 2e-7)],
        concentration_scale=0.01, initial_theta=1,
    )
    assert np.max(np.abs(result.theta - 1)) <= 1e-10
    assert np.max(np.abs(result.captured_moles)) <= 1e-16


@pytest.mark.parametrize("kwargs", [{"capacity": 0}, {"capacity": None}, {"capture_velocity": -1}, {"capture_velocity": np.nan}])
def test_invalid_surface_parameters(kwargs):
    values = {"capacity": 1e-5, "capture_velocity": 0.01} | kwargs
    with pytest.raises(ValueError):
        FiniteCapacity(**values)


@pytest.mark.parametrize("kwargs", [{"volume": 0}, {"reactive_area": -1}, {"throughput": np.inf}])
def test_invalid_reactor_parameters(kwargs):
    values = {"volume": 1e-5, "reactive_area": 0.01, "throughput": 1e-5} | kwargs
    with pytest.raises(ValueError):
        WellMixedReactor(**values)


@pytest.mark.parametrize("duration,flow", [(0, 0), (-1, 0), (1, -1), (np.inf, 0)])
def test_invalid_segments(duration, flow):
    with pytest.raises(ValueError):
        FlowSegment(duration, flow)


@pytest.mark.parametrize(
    "kwargs",
    [{"concentration_scale": 0}, {"concentration_scale": np.nan}, {"initial_c": -1},
     {"initial_theta": -0.1}, {"initial_theta": 1.1}, {"initial_theta": None},
     {"segments": []}, {"provenance_id": ""}],
)
def test_invalid_solve_inputs(kwargs):
    values = {"segments": [FlowSegment(1, 0)], "concentration_scale": 0.01} | kwargs
    with pytest.raises(ValueError):
        solve_0d(WellMixedReactor(1e-5, 0.01, 1e-5), FiniteCapacity(1e-5, 0.01), **values)


def test_invalid_conversion_inputs():
    with pytest.raises(ValueError):
        sccm_to_molar_flow(1, 0, 101325)
    with pytest.raises(ValueError):
        actual_volumetric_flow(1e-6, 400, 0)
    with pytest.raises(ValueError):
        celsius_to_kelvin(-273.15)
    with pytest.raises(ValueError):
        FiniteCapacity.from_probability(capacity=1e-5, beta=1.1, temperature=400, molar_mass=0.072)
