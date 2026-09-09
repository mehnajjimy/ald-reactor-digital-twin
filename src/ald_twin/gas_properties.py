"""Traceable dilute-gas replacements, not Holmqvist's exact property inputs.

Public arguments and results use SI. Poling 5e supplies the Chapman-Enskog,
Neufeld and Wilke expressions; Appendix B supplies the Svehla collision inputs.
See docs/phase3-property-audit.md. No DEZ transport property is inferred here.
"""

import math

from .units import _finite_scalar, _positive

N2_MOLAR_MASS = 0.0280134  # kg/mol
H2O_MOLAR_MASS = 0.0180153  # kg/mol
N2_SIGMA = 3.798e-10  # m
H2O_SIGMA = 2.641e-10  # m
N2_EPSILON_OVER_K = 71.4  # K
H2O_EPSILON_OVER_K = 809.1  # K


def _reduced_temperature(temperature: float, epsilon_over_k: float) -> float:
    reduced = _positive(temperature, "temperature [K]") / epsilon_over_k
    if not 0.3 <= reduced <= 100:
        raise ValueError("Neufeld correlation requires 0.3 <= T* <= 100")
    return reduced


def water_nitrogen_diffusivity(temperature: float, pressure: float) -> float:
    """Binary H2O-N2 diffusivity [m²/s] at T [K] and local pressure [Pa].

    Poling Eqs. 11-3.2 and 11-3.4--6, with first-order correction f_D=1.
    The spherical Lennard-Jones approximation does not correct water polarity.
    """
    temperature = _positive(temperature, "temperature [K]")
    pressure_bar = _positive(pressure, "pressure [Pa]") / 1e5
    sigma_angstrom = (H2O_SIGMA + N2_SIGMA) / 2 / 1e-10
    epsilon_over_k = math.sqrt(H2O_EPSILON_OVER_K * N2_EPSILON_OVER_K)
    reduced = _reduced_temperature(temperature, epsilon_over_k)
    omega = (
        1.06036 / reduced**0.15610
        + 0.19300 * math.exp(-0.47635 * reduced)
        + 1.03587 * math.exp(-1.52996 * reduced)
        + 1.76474 * math.exp(-3.89411 * reduced)
    )
    mass_g_per_mol = 1000 * 2 / (1 / H2O_MOLAR_MASS + 1 / N2_MOLAR_MASS)
    diffusion_cm2_per_s = 0.00266 * temperature**1.5 / (
        pressure_bar * math.sqrt(mass_g_per_mol) * sigma_angstrom**2 * omega
    )
    return diffusion_cm2_per_s * 1e-4


def _gas_viscosity(
    temperature: float, molar_mass: float, sigma: float, epsilon_over_k: float
) -> float:
    # Poling Eqs. 9-3.9 and 9-4.3: g/mol, angstrom, micropoise.
    reduced = _reduced_temperature(temperature, epsilon_over_k)
    omega = (
        1.16145 / reduced**0.14874
        + 0.52487 * math.exp(-0.77320 * reduced)
        + 2.16178 * math.exp(-2.43787 * reduced)
    )
    micropoise = 26.69 * math.sqrt(molar_mass * 1000 * float(temperature)) / (
        (sigma / 1e-10)**2 * omega
    )
    return micropoise * 1e-7


def nitrogen_viscosity(temperature: float) -> float:
    """Dilute N2 viscosity [Pa·s] at temperature [K]."""
    return _gas_viscosity(temperature, N2_MOLAR_MASS, N2_SIGMA, N2_EPSILON_OVER_K)


def water_viscosity(temperature: float) -> float:
    """Dilute H2O viscosity [Pa·s] at T [K], without a polarity correction."""
    return _gas_viscosity(temperature, H2O_MOLAR_MASS, H2O_SIGMA, H2O_EPSILON_OVER_K)


def wilke_binary_viscosity(
    mole_fraction_a: float,
    viscosity_a: float,
    viscosity_b: float,
    molar_mass_a: float,
    molar_mass_b: float,
) -> float:
    """Binary-mixture viscosity [Pa·s]; viscosities [Pa·s], masses [kg/mol].

    Poling Eqs. 9-5.14--16. Composition is supplied explicitly; the inlet
    H2O fraction is not silently applied throughout the reacting chamber.
    """
    fraction = _finite_scalar(mole_fraction_a, "mole_fraction_a")
    if not 0 <= fraction <= 1:
        raise ValueError("mole_fraction_a must be between 0 and 1")
    viscosity_a = _positive(viscosity_a, "viscosity_a [Pa s]")
    viscosity_b = _positive(viscosity_b, "viscosity_b [Pa s]")
    molar_mass_a = _positive(molar_mass_a, "molar_mass_a [kg/mol]")
    molar_mass_b = _positive(molar_mass_b, "molar_mass_b [kg/mol]")
    phi_ab = (
        1 + math.sqrt(viscosity_a / viscosity_b) * (molar_mass_b / molar_mass_a)**0.25
    )**2 / math.sqrt(8 * (1 + molar_mass_a / molar_mass_b))
    phi_ba = phi_ab * viscosity_b * molar_mass_a / (viscosity_a * molar_mass_b)
    return (
        fraction * viscosity_a / (fraction + (1 - fraction) * phi_ab)
        + (1 - fraction) * viscosity_b / (1 - fraction + fraction * phi_ba)
    )
