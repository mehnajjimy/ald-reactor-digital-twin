"""gas properties against frozen values and a textbook example."""

import pytest

from ald_twin.gas_properties import (
    H2O_MOLAR_MASS,
    N2_MOLAR_MASS,
    nitrogen_viscosity,
    water_nitrogen_diffusivity,
    water_viscosity,
    wilke_binary_viscosity,
)

# values frozen before the code was written, with 16 sccm water in 500 sccm nitrogen.
# columns: T [K], D water-N2 at 200 Pa [m²/s], mu N2, mu H2O, mu mixture [Pa s]
FROZEN = [
    (373.15, 0.01670, 2.0620e-5, 1.3222e-5, 2.03995e-5),
    (423.15, 0.02118, 2.2465e-5, 1.4959e-5, 2.22471e-5),
    (473.15, 0.02608, 2.4212e-5, 1.6732e-5, 2.40010e-5),
]


def test_gas_properties_reproduce_frozen_values():
    """catches a changed lennard-jones constant, collision integral or mixing rule."""
    for temperature, diffusion, nitrogen, water, mixture in FROZEN:
        # tolerances are half of the last printed digit
        actual_nitrogen = nitrogen_viscosity(temperature)
        actual_water = water_viscosity(temperature)
        assert water_nitrogen_diffusivity(temperature, 200) == pytest.approx(diffusion, abs=5e-6, rel=0)
        assert actual_nitrogen == pytest.approx(nitrogen, abs=5e-10, rel=0)
        assert actual_water == pytest.approx(water, abs=5e-10, rel=0)
        actual_mixture = wilke_binary_viscosity(
            16 / 516, actual_water, actual_nitrogen, H2O_MOLAR_MASS, N2_MOLAR_MASS
        )
        assert actual_mixture == pytest.approx(mixture, abs=5e-11, rel=0)


def test_wilke_matches_the_poling_example_and_pure_limits():
    """catches a wrong wilke phi factor or a mixture rule that depends on species order."""
    # Poling example 9-5, methane and n-butane at 293 K. the book rounds its
    # intermediate values, hence the 0.03 micropoise tolerance
    result = wilke_binary_viscosity(0.697, 109.4e-7, 72.74e-7, 0.016043, 0.058123)
    assert result == pytest.approx(92.26e-7, abs=0.03e-7, rel=0)
    reverse = wilke_binary_viscosity(0.303, 72.74e-7, 109.4e-7, 0.058123, 0.016043)
    assert result == pytest.approx(reverse, rel=1e-14)

    # a pure gas has its own viscosity
    assert wilke_binary_viscosity(0, 1e-5, 3e-5, 0.018, 0.028) == 3e-5
    assert wilke_binary_viscosity(1, 1e-5, 3e-5, 0.018, 0.028) == 1e-5
