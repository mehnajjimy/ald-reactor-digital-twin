"""Diagnostic isothermal, no-slip parallel-plate flow; public inputs use SI.

This is a conditional flow reduction, not a validated Benchmark B reactor model.
It neglects axial inertia, side walls, slip, and changes in total molar flow.
"""

import numpy as np

from .units import R


def channel_flow(z, *, length, width, height, temperature, molar_flow,
                 viscosity, outlet_pressure):
    """Return pressure [Pa] and cross-section mean velocity [m/s] at z [m].

    The full plate separation is height. Integrating pressure-driven Poiseuille
    flow with Q=F*R*T/p gives p²=p_out²+24*mu*F*R*T*(length-z)/(width*height³).
    Required arguments prevent unresolved physical inputs from becoming defaults.
    """
    parameters = dict(length=length, width=width, height=height,
        temperature=temperature, molar_flow=molar_flow, viscosity=viscosity,
        outlet_pressure=outlet_pressure)
    for name, value in parameters.items():
        if isinstance(value, bool) or not np.isscalar(value) or not np.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    z = np.asarray(z, dtype=float)
    if not np.all(np.isfinite(z)) or np.any(z < 0) or np.any(z > length):
        raise ValueError("z must lie inside the channel")
    pressure = np.sqrt(outlet_pressure**2 +
        24*viscosity*molar_flow*R*temperature*(length-z)/(width*height**3))
    velocity = molar_flow*R*temperature/(width*height*pressure)
    return pressure, velocity
