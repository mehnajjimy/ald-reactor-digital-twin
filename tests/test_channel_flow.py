"""parallel-plate channel flow: pressure drop and molar continuity."""

import numpy as np

from ald_twin.channel_flow import channel_flow
from ald_twin.units import R

# a 5.5 cm by 5 cm channel with a 2 mm gap at 150 °C and a 200 Pa outlet
CASE = dict(length=.055, width=.05, height=.002, temperature=423.15,
            molar_flow=3.7e-4, viscosity=2.25e-5, outlet_pressure=200.)


def test_channel_flow_obeys_poiseuille_and_molar_continuity():
    """catches a wrong pressure-drop factor or a velocity that loses gas."""
    z = np.linspace(0, CASE["length"], 10001)
    pressure, velocity = channel_flow(z, **CASE)
    assert pressure[-1] == 200.
    assert np.all(np.diff(pressure) < 0)
    assert np.all(np.diff(velocity) > 0)

    # the same molar flow passes every position: F = w h p u / (R T)
    carried = CASE["width"]*CASE["height"]*pressure*velocity/(R*CASE["temperature"])
    np.testing.assert_allclose(carried, CASE["molar_flow"], rtol=1e-14)

    # local plane poiseuille flow: u = -h² (dp/dz) / (12 mu)
    gradient = np.gradient(pressure, z)
    from_momentum = -CASE["height"]**2*gradient/(12*CASE["viscosity"])
    np.testing.assert_allclose(velocity[1:-1], from_momentum[1:-1], rtol=1e-7)
