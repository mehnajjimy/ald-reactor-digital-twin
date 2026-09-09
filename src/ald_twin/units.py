"""Explicit SI conversions for the dilute-precursor model.

Standard volumetric flow has no meaning without its reference temperature and
pressure. No standard-flow convention is silently selected here.
"""

from __future__ import annotations

import math

K_B = 1.380649e-23  # J K^-1, exact SI definition
N_A = 6.02214076e23  # mol^-1, exact SI definition
R = K_B * N_A  # J mol^-1 K^-1
SCCM_TO_CUBIC_METRES_PER_SECOND = 1e-6 / 60.0


def _finite_scalar(value: float, name: str) -> float:
    """Reject missing/nonfinite scalar inputs before they reach an integrator."""
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
    converted = _finite_scalar(value, name)
    if converted <= 0:
        raise ValueError(f"{name} must be positive")
    return converted


def _nonnegative(value: float, name: str) -> float:
    converted = _finite_scalar(value, name)
    if converted < 0:
        raise ValueError(f"{name} must be nonnegative")
    return converted


def sccm_to_molar_flow(
    sccm: float, reference_temperature: float, reference_pressure: float
) -> float:
    """Convert sccm to mol/s using declared reference conditions [K, Pa]."""
    flow = _nonnegative(sccm, "sccm")
    temperature = _positive(reference_temperature, "reference_temperature [K]")
    pressure = _positive(reference_pressure, "reference_pressure [Pa]")
    return pressure * flow * SCCM_TO_CUBIC_METRES_PER_SECOND / (R * temperature)


def actual_volumetric_flow(
    molar_flow: float, temperature: float, pressure: float
) -> float:
    """Ideal-gas throughput [m³/s] at the specified chamber T [K] and P [Pa]."""
    flow = _nonnegative(molar_flow, "molar_flow [mol/s]")
    temperature = _positive(temperature, "temperature [K]")
    pressure = _positive(pressure, "pressure [Pa]")
    return flow * R * temperature / pressure


def celsius_to_kelvin(temperature_celsius: float) -> float:
    """Convert Celsius to an absolute temperature strictly above zero kelvin."""
    return _positive(
        _finite_scalar(temperature_celsius, "temperature_celsius") + 273.15,
        "temperature [K]",
    )


def angstrom_to_metre(length_angstrom: float) -> float:
    """Convert a nonnegative length [Å] to metres."""
    return _nonnegative(length_angstrom, "length [angstrom]") * 1e-10


def density_g_cm3_to_kg_m3(density: float) -> float:
    """Convert positive mass density [g/cm³] to kg/m³."""
    return _positive(density, "density [g/cm³]") * 1000.0


def molar_mass_g_mol_to_kg_mol(molar_mass: float) -> float:
    """Convert positive molar mass [g/mol] to kg/mol, not molecular mass."""
    return _positive(molar_mass, "molar_mass [g/mol]") * 1e-3


def precursor_partial_pressure(concentration: float, temperature: float) -> float:
    """Return only precursor partial pressure [Pa] from c [mol/m³], T [K]."""
    concentration = _nonnegative(concentration, "concentration [mol/m³]")
    temperature = _positive(temperature, "temperature [K]")
    return concentration * R * temperature
