"""explicit SI unit conversions for the dilute-precursor model.

standard volume flow means nothing without its reference temperature and
pressure, so no standard-flow convention is picked silently here.
"""

from __future__ import annotations

import math

# exact SI constants
K_B = 1.380649e-23  # J K^-1, exact SI definition
N_A = 6.02214076e23  # mol^-1, exact SI definition
R = K_B * N_A  # J mol^-1 K^-1

# unit conversion factors
SCCM_TO_CUBIC_METRES_PER_SECOND = 1e-6 / 60.0
ZERO_CELSIUS_IN_KELVIN = 273.15
METRES_PER_ANGSTROM = 1e-10
KG_M3_PER_G_CM3 = 1000.0
KG_PER_GRAM = 1e-3


# input checks shared by the whole model


def _finite_scalar(value: float, name: str) -> float:
    """turn a real number into a float, or raise ValueError if it is missing or not finite."""
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{name} must be a finite real scalar")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite real scalar") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _positive(value: float, name: str) -> float:
    """return value as a float, or raise ValueError unless it is finite and above zero."""
    converted = _finite_scalar(value, name)
    if converted <= 0:
        raise ValueError(f"{name} must be positive")
    return converted


def _nonnegative(value: float, name: str) -> float:
    """return value as a float, or raise ValueError unless it is finite and not negative."""
    converted = _finite_scalar(value, name)
    if converted < 0:
        raise ValueError(f"{name} must be nonnegative")
    return converted


# flow conversions


def sccm_to_molar_flow(
    sccm: float, reference_temperature: float, reference_pressure: float
) -> float:
    """convert sccm to mol/s using the stated reference T [K] and P [Pa]."""
    flow = _nonnegative(sccm, "sccm")
    temperature = _positive(reference_temperature, "reference_temperature [K]")
    pressure = _positive(reference_pressure, "reference_pressure [Pa]")
    return pressure * flow * SCCM_TO_CUBIC_METRES_PER_SECOND / (R * temperature)


def actual_volumetric_flow(
    molar_flow: float, temperature: float, pressure: float
) -> float:
    """ideal-gas volume flow [m³/s] at the chamber T [K] and P [Pa]."""
    flow = _nonnegative(molar_flow, "molar_flow [mol/s]")
    temperature = _positive(temperature, "temperature [K]")
    pressure = _positive(pressure, "pressure [Pa]")
    return flow * R * temperature / pressure


# simple unit conversions


def celsius_to_kelvin(temperature_celsius: float) -> float:
    """convert °C to K, and require the result to be above zero kelvin."""
    celsius = _finite_scalar(temperature_celsius, "temperature_celsius")
    return _positive(celsius + ZERO_CELSIUS_IN_KELVIN, "temperature [K]")


def angstrom_to_metre(length_angstrom: float) -> float:
    """convert a nonnegative length [Å] to metres."""
    return _nonnegative(length_angstrom, "length [angstrom]") * METRES_PER_ANGSTROM


def density_g_cm3_to_kg_m3(density: float) -> float:
    """convert a positive density [g/cm³] to kg/m³."""
    return _positive(density, "density [g/cm³]") * KG_M3_PER_G_CM3


def molar_mass_g_mol_to_kg_mol(molar_mass: float) -> float:
    """convert a positive molar mass [g/mol] to kg/mol (not the mass of one molecule)."""
    return _positive(molar_mass, "molar_mass [g/mol]") * KG_PER_GRAM


# gas pressure


def precursor_partial_pressure(concentration: float, temperature: float) -> float:
    """precursor partial pressure [Pa] from c [mol/m³] and T [K], using p = c R T."""
    concentration = _nonnegative(concentration, "concentration [mol/m³]")
    temperature = _positive(temperature, "temperature [K]")
    return concentration * R * temperature
