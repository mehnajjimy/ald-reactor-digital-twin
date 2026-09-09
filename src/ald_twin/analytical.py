"""Independent nonreacting semi-infinite transport references from the freeze."""

import numpy as np
from scipy.special import erfc, erfcx


def step_response(z, t, velocity, diffusivity):
    """Unit Dirichlet step, z>=0, u>=0, D>0; initial interior gas is zero."""
    z = np.asarray(z, dtype=float)
    if (not np.all(np.isfinite(z)) or np.any(z < 0) or not np.isfinite(t)
        or not np.isfinite(velocity) or velocity < 0
        or not np.isfinite(diffusivity) or diffusivity <= 0):
        raise ValueError("Invalid semi-infinite reference inputs")
    if t <= 0:
        return np.zeros_like(z)
    denominator = 2 * np.sqrt(diffusivity * t)
    a, b = (z - velocity*t)/denominator, (z + velocity*t)/denominator
    # exp(u*z/D)*erfc(b) = exp(-a*a)*erfcx(b); b>=0 prevents
    # erfcx overflow and the exponential never exceeds one.
    return 0.5 * erfc(a) + 0.5 * np.exp(-a*a) * erfcx(b)


def pulse_response(z, t, pulse_duration, velocity, diffusivity):
    if not np.isfinite(pulse_duration) or pulse_duration <= 0:
        raise ValueError("Pulse duration must be positive seconds")
    return (step_response(z, t, velocity, diffusivity)
            - step_response(z, t-pulse_duration, velocity, diffusivity))


def cell_averages(function, faces, order=8):
    """Gauss-Legendre reference averages for comparison with finite-volume states."""
    faces = np.asarray(faces, dtype=float)
    if faces.ndim != 1 or len(faces) < 2 or np.any(np.diff(faces) <= 0):
        raise ValueError("Strictly increasing cell faces required")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    mid = (faces[:-1] + faces[1:]) / 2
    half = np.diff(faces) / 2
    values = function(mid[:, None] + half[:, None] * nodes)
    return np.asarray(values) @ weights / 2
