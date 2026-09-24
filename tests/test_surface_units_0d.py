"""units, surface capture and the well-mixed reactor against exact answers."""

import math

import numpy as np
from scipy.integrate import solve_ivp

from ald_twin.gas_properties import H2O_MOLAR_MASS, N2_MOLAR_MASS
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


def test_unit_conversions_match_hand_arithmetic():
    """catches a wrong standard state, gas constant or flow conversion."""
    assert R == K_B * N_A
    assert math.isclose(R, 8.31446261815324, rel_tol=1e-15)
    assert celsius_to_kelvin(150.0) == 423.15
    assert angstrom_to_metre(10.0) == 1e-9
    assert density_g_cm3_to_kg_m3(5.4) == 5400.0
    assert math.isclose(molar_mass_g_mol_to_kg_mol(72.0), 0.072, rel_tol=1e-12)

    # 500 sccm at 0 °C and 1 atm, then the same gas at 150 °C and 200 Pa
    standard_molar_volume_cm3 = 8.31446261815324 * 273.15 / 101325 * 1e6
    flow = sccm_to_molar_flow(500.0, 273.15, 101325.0)
    assert math.isclose(flow, 500.0 / (60 * standard_molar_volume_cm3), rel_tol=1e-12)
    actual = actual_volumetric_flow(flow, 423.15, 200.0)
    expected = (500e-6 / 60) * (423.15 / 273.15) * (101325 / 200)
    assert math.isclose(actual, expected, rel_tol=1e-12)
    assert math.isclose(precursor_partial_pressure(0.02, 400), 0.02 * R * 400, rel_tol=1e-12)

    # frozen molar and mass flows for the nitrogen carrier, 11 sccm DEZ and 16 sccm water
    for sccm, mass, molar_reference, mass_reference in [
        (500, N2_MOLAR_MASS, 3.71792e-4, 1.04152e-5),
        (11, 0.12350, 8.17942e-6, 1.01016e-6),
        (16, H2O_MOLAR_MASS, 1.18973e-5, 2.14334e-7),
    ]:
        molar = sccm_to_molar_flow(sccm, 273.15, 101325)
        assert math.isclose(molar, molar_reference, rel_tol=5e-6)
        assert math.isclose(molar * mass, mass_reference, rel_tol=5e-6)


def test_capture_velocity_is_beta_times_the_kinetic_wall_flux():
    """catches a wrong kinetic-theory factor or a rate that sticks to full sites."""
    surface = FiniteCapacity.from_probability(capacity=2e-5, beta=1e-3, temperature=400.0, molar_mass=0.072)
    # wall flux per concentration is mean speed / 4, mean speed = sqrt(8 kT / (pi m))
    molecular_mass = 0.072 / N_A
    expected_velocity = 1e-3 * math.sqrt(8 * K_B * 400 / (math.pi * molecular_mass)) / 4
    assert math.isclose(surface.capture_velocity, expected_velocity, rel_tol=1e-12)
    actual = surface.rate(np.array([0.0, 0.02, 0.02]), np.array([0.0, 0.0, 1.0]))
    np.testing.assert_allclose(actual, [0.0, 0.02 * expected_velocity, 0.0], rtol=1e-14)
    # the rate is not clipped, so solver overshoot stays visible
    assert surface.rate(1.0, 1.1) < 0
    assert surface.rate(-1e-12, 0) < 0

    # at a fixed gas concentration coverage follows 1 - (1 - theta0) exp(-k t)
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


def test_purge_washes_out_over_ten_residence_times():
    """catches a missing or wrong outflow term in the well-mixed reactor."""
    reactor = WellMixedReactor(volume=2e-5, reactive_area=0.02, throughput=8e-6)
    initial_concentration = 0.03
    result = solve_0d(
        reactor, FiniteCapacity(2e-5, 0), [FlowSegment(10 * reactor.volume / reactor.throughput, 0)],
        concentration_scale=initial_concentration, initial_c=initial_concentration,
        initial_theta=0.2,
    )
    # c = c0 exp(-Q t / V)
    exact = initial_concentration * np.exp(-reactor.throughput / reactor.volume * result.t)
    assert np.max(np.abs(result.c[:, 0] - exact)) / initial_concentration <= 1e-7
    assert np.max(np.abs(result.theta[:, 0] - 0.2)) <= 1e-10
    assert np.max(np.abs(result.ledger_error_moles)) / (reactor.volume * initial_concentration) <= 1e-8


def test_closed_batch_is_limited_by_dose_or_by_capacity():
    """catches a closed reactor that captures more than its gas or its free sites allow."""
    reactor = WellMixedReactor(volume=2e-5, reactive_area=0.02, throughput=0)
    surface = FiniteCapacity(capacity=2e-5, capture_velocity=0.05)
    initial_theta = 0.2
    # 0.005 mol/m³ runs out of gas first, 0.05 mol/m³ fills every site
    for initial_concentration in (0.005, 0.05):
        result = solve_0d(
            reactor, surface, [FlowSegment(5, 0)], concentration_scale=initial_concentration,
            initial_c=initial_concentration, initial_theta=initial_theta,
        )
        inventory = reactor.volume * result.c[:, 0] + reactor.reactive_area * surface.capacity * result.theta[:, 0]
        assert np.max(np.abs(inventory - inventory[0])) / inventory[0] <= 1e-8
        dose_limit = initial_theta + reactor.volume * initial_concentration / (reactor.reactive_area * surface.capacity)
        assert abs(result.theta[-1, 0] - min(1.0, dose_limit)) <= 1e-6
        assert np.min(result.c[:, 0] / initial_concentration) >= -1e-8
        assert np.min(result.theta) >= -1e-8
        assert np.max(result.theta) <= 1 + 1e-8
