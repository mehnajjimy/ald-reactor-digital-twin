"""diagnostic isothermal, no-slip parallel-plate flow. public inputs use SI.

this is a conditional flow reduction, not a validated Benchmark B reactor model.
it neglects axial inertia, side walls, slip and changes in total molar flow.
"""

import numpy as np

from .units import R

# plane Poiseuille flow in a full gap h gives dp/dz = -12*mu*Q/(w*h³).
# integrating p*dp along the channel doubles the 12 into this factor of 24.
POISEUILLE_SQUARED_PRESSURE_FACTOR = 24


def channel_flow(z, *, length, width, height, temperature, molar_flow,
                 viscosity, outlet_pressure):
    """return pressure [Pa] and cross-section mean velocity [m/s] at z [m].

    height is the full plate separation. with Q = F*R*T/p the pressure is
    p² = p_out² + 24*mu*F*R*T*(length - z)/(width*height³).
    every input is required so an unresolved physical value never gets a default.
    """
    # every physical input must be a finite positive scalar
    parameters = dict(length=length, width=width, height=height,
        temperature=temperature, molar_flow=molar_flow, viscosity=viscosity,
        outlet_pressure=outlet_pressure)
    for name, value in parameters.items():
        if (isinstance(value, bool) or not np.isscalar(value)
                or not np.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be finite and positive")

    # positions must lie between the inlet (z = 0) and the outlet (z = length)
    z = np.asarray(z, dtype=float)
    if not np.all(np.isfinite(z)) or np.any(z < 0) or np.any(z > length):
        raise ValueError("z must lie inside the channel")

    # pressure from the squared-pressure profile, then velocity from Q = F*R*T/p
    pressure_drop_term = (POISEUILLE_SQUARED_PRESSURE_FACTOR*viscosity*molar_flow*R*temperature
                          * (length-z) / (width*height**3))
    pressure = np.sqrt(outlet_pressure**2 + pressure_drop_term)
    velocity = molar_flow*R*temperature/(width*height*pressure)
    return pressure, velocity
