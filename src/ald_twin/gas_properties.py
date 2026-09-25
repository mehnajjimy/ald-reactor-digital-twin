"""dilute-gas properties for N2 and H2O from traceable textbook formulas.

these replace Holmqvist's exact property inputs, they are not copies of them.
public arguments and results use SI. Poling 5e supplies the Chapman-Enskog,
Neufeld and Wilke expressions and Appendix B supplies the Svehla collision
inputs. see docs/phase3-property-audit.md. the DEZ collision inputs are
published estimates, not measurements, so DEZ-N2 diffusivity is an estimate too.
"""

import math

from .units import _finite_scalar, _positive

# molar masses and lennard-jones collision inputs for N2 and H2O
N2_MOLAR_MASS = 0.0280134  # kg/mol
H2O_MOLAR_MASS = 0.0180153  # kg/mol
N2_SIGMA = 3.798e-10  # m
H2O_SIGMA = 2.641e-10  # m
N2_EPSILON_OVER_K = 71.4  # K
H2O_EPSILON_OVER_K = 809.1  # K

# DEZ, Zn(C2H5)2: molar mass from atomic masses, collision inputs estimated in
# Zhuang et al. 2021, AIChE J, doi:10.1002/aic.17305, supporting Table S2
DEZ_MOLAR_MASS = 0.123504  # kg/mol
DEZ_SIGMA = 5.86e-10  # m
DEZ_EPSILON_OVER_K = 405.0  # K

# unit conversions between SI and the units the Poling formulas expect
_PA_PER_BAR = 1e5
_M_PER_ANGSTROM = 1e-10
_G_PER_KG = 1000
_M2_PER_CM2 = 1e-4
_PA_S_PER_MICROPOISE = 1e-7

# range of reduced temperature T* where the Neufeld fits are valid
_MIN_REDUCED_TEMPERATURE = 0.3
_MAX_REDUCED_TEMPERATURE = 100


def _reduced_temperature(temperature: float, epsilon_over_k: float) -> float:
    """reduced temperature T* = T / (epsilon/k), checked against the fit range."""
    reduced = _positive(temperature, "temperature [K]") / epsilon_over_k
    if not _MIN_REDUCED_TEMPERATURE <= reduced <= _MAX_REDUCED_TEMPERATURE:
        raise ValueError("Neufeld correlation requires 0.3 <= T* <= 100")
    return reduced


def _chapman_enskog_diffusivity(temperature, pressure, molar_masses, sigmas, epsilons_over_k):
    """binary diffusivity [m²/s] of a Lennard-Jones pair at T [K] and pressure [Pa].

    Poling Eqs. 11-3.2 and 11-3.4 to 11-3.6, with first-order correction f_D=1.
    each pair argument holds the two species' values in SI.
    """
    temperature = _positive(temperature, "temperature [K]")
    pressure_bar = _positive(pressure, "pressure [Pa]") / _PA_PER_BAR
    first_mass, second_mass = molar_masses
    first_sigma, second_sigma = sigmas
    first_epsilon, second_epsilon = epsilons_over_k

    # combining rules for the pair
    sigma_angstrom = (first_sigma + second_sigma) / 2 / _M_PER_ANGSTROM
    epsilon_over_k = math.sqrt(first_epsilon * second_epsilon)
    reduced = _reduced_temperature(temperature, epsilon_over_k)

    # Neufeld fit for the diffusion collision integral
    omega = (
        1.06036 / reduced**0.15610
        + 0.19300 * math.exp(-0.47635 * reduced)
        + 1.03587 * math.exp(-1.52996 * reduced)
        + 1.76474 * math.exp(-3.89411 * reduced)
    )

    # Chapman-Enskog in g/mol, bar and angstrom, giving cm²/s, then back to m²/s
    mass_g_per_mol = _G_PER_KG * 2 / (1 / first_mass + 1 / second_mass)
    diffusion_cm2_per_s = 0.00266 * temperature**1.5 / (
        pressure_bar * math.sqrt(mass_g_per_mol) * sigma_angstrom**2 * omega
    )
    return diffusion_cm2_per_s * _M2_PER_CM2


def water_nitrogen_diffusivity(temperature: float, pressure: float) -> float:
    """binary H2O-N2 diffusivity [m²/s] at T [K] and local pressure [Pa].

    the spherical Lennard-Jones approximation does not correct water polarity.
    """
    return _chapman_enskog_diffusivity(temperature, pressure,
                                       (H2O_MOLAR_MASS, N2_MOLAR_MASS),
                                       (H2O_SIGMA, N2_SIGMA),
                                       (H2O_EPSILON_OVER_K, N2_EPSILON_OVER_K))


def dez_nitrogen_diffusivity(temperature: float, pressure: float) -> float:
    """estimated binary DEZ-N2 diffusivity [m²/s] at T [K] and local pressure [Pa].

    the DEZ collision inputs are estimates, and a nonspherical molecule is
    treated as a Lennard-Jones sphere, so this is not a measured value.
    """
    return _chapman_enskog_diffusivity(temperature, pressure,
                                       (DEZ_MOLAR_MASS, N2_MOLAR_MASS),
                                       (DEZ_SIGMA, N2_SIGMA),
                                       (DEZ_EPSILON_OVER_K, N2_EPSILON_OVER_K))


def _gas_viscosity(
    temperature: float, molar_mass: float, sigma: float, epsilon_over_k: float
) -> float:
    """dilute pure-gas viscosity [Pa·s] from Poling Eqs. 9-3.9 and 9-4.3."""
    reduced = _reduced_temperature(temperature, epsilon_over_k)

    # Neufeld fit for the viscosity collision integral
    omega = (
        1.16145 / reduced**0.14874
        + 0.52487 * math.exp(-0.77320 * reduced)
        + 2.16178 * math.exp(-2.43787 * reduced)
    )

    # the formula works in g/mol, angstrom and micropoise
    micropoise = 26.69 * math.sqrt(molar_mass * _G_PER_KG * float(temperature)) / (
        (sigma / _M_PER_ANGSTROM)**2 * omega
    )
    return micropoise * _PA_S_PER_MICROPOISE


def nitrogen_viscosity(temperature: float) -> float:
    """dilute N2 viscosity [Pa·s] at temperature [K]."""
    return _gas_viscosity(temperature, N2_MOLAR_MASS, N2_SIGMA, N2_EPSILON_OVER_K)


def water_viscosity(temperature: float) -> float:
    """dilute H2O viscosity [Pa·s] at T [K], without a polarity correction."""
    return _gas_viscosity(temperature, H2O_MOLAR_MASS, H2O_SIGMA, H2O_EPSILON_OVER_K)


def wilke_binary_viscosity(
    mole_fraction_a: float,
    viscosity_a: float,
    viscosity_b: float,
    molar_mass_a: float,
    molar_mass_b: float,
) -> float:
    """binary-mixture viscosity [Pa·s]. viscosities in Pa·s, masses in kg/mol.

    Poling Eqs. 9-5.14 to 9-5.16. composition is passed in explicitly, so the
    inlet H2O fraction is never silently applied to the whole reacting chamber.
    """
    # check inputs
    fraction = _finite_scalar(mole_fraction_a, "mole_fraction_a")
    if not 0 <= fraction <= 1:
        raise ValueError("mole_fraction_a must be between 0 and 1")
    viscosity_a = _positive(viscosity_a, "viscosity_a [Pa s]")
    viscosity_b = _positive(viscosity_b, "viscosity_b [Pa s]")
    molar_mass_a = _positive(molar_mass_a, "molar_mass_a [kg/mol]")
    molar_mass_b = _positive(molar_mass_b, "molar_mass_b [kg/mol]")

    # Wilke interaction factors
    phi_ab = (
        1 + math.sqrt(viscosity_a / viscosity_b) * (molar_mass_b / molar_mass_a)**0.25
    )**2 / math.sqrt(8 * (1 + molar_mass_a / molar_mass_b))
    phi_ba = phi_ab * viscosity_b * molar_mass_a / (viscosity_a * molar_mass_b)

    # mole-fraction weighted mixing rule
    fraction_b = 1 - fraction
    return (
        fraction * viscosity_a / (fraction + fraction_b * phi_ab)
        + fraction_b * viscosity_b / (fraction_b + fraction * phi_ba)
    )
