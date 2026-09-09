import numpy as np
import pytest

from ald_twin.channel_flow import channel_flow
from ald_twin.units import R


CASE = dict(length=.055, width=.05, height=.002, temperature=423.15,
            molar_flow=3.7e-4, viscosity=2.25e-5, outlet_pressure=200.)


def test_outlet_and_molar_continuity():
    z = np.linspace(0, CASE["length"], 101)
    pressure, velocity = channel_flow(z, **CASE)
    assert pressure[-1] == 200.
    assert np.all(np.diff(pressure) < 0)
    assert np.all(np.diff(velocity) > 0)
    reconstructed_flow = CASE["width"]*CASE["height"]*pressure*velocity/(R*CASE["temperature"])
    np.testing.assert_allclose(reconstructed_flow, CASE["molar_flow"], rtol=1e-14)


def test_local_poiseuille_balance_from_numerical_gradient():
    z = np.linspace(0, CASE["length"], 10001)
    pressure, velocity = channel_flow(z, **CASE)
    pressure_gradient = np.gradient(pressure, z)
    from_momentum = -CASE["height"]**2*pressure_gradient/(12*CASE["viscosity"])
    np.testing.assert_allclose(velocity[1:-1], from_momentum[1:-1], rtol=1e-7)


@pytest.mark.parametrize("name", list(CASE))
def test_missing_physical_scale_cannot_be_zero(name):
    with pytest.raises(ValueError):
        channel_flow([0], **(CASE | {name: 0}))


@pytest.mark.parametrize("z", [[-.001], [.06], [float("nan")]])
def test_invalid_positions(z):
    with pytest.raises(ValueError, match="inside"):
        channel_flow(z, **CASE)
