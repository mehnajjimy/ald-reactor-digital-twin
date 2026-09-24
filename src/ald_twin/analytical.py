"""exact semi-infinite transport answers without reaction, used to check the solver."""

import numpy as np
from scipy.special import erfc, erfcx

# gauss-legendre points used for cell averages by default
DEFAULT_QUADRATURE_ORDER = 8


# step and pulse responses


def step_response(z, t, velocity, diffusivity):
    """gas response to a unit inlet step (z >= 0, u >= 0, D > 0), starting from an empty channel."""
    z = np.asarray(z, dtype=float)
    message = "Invalid semi-infinite reference inputs"
    if not np.all(np.isfinite(z)) or np.any(z < 0):
        raise ValueError(message)
    if not np.isfinite(t):
        raise ValueError(message)
    if not np.isfinite(velocity) or velocity < 0:
        raise ValueError(message)
    if not np.isfinite(diffusivity) or diffusivity <= 0:
        raise ValueError(message)
    if t <= 0:
        return np.zeros_like(z)
    denominator = 2 * np.sqrt(diffusivity * t)
    a = (z - velocity*t)/denominator
    b = (z + velocity*t)/denominator
    # exp(u*z/D)*erfc(b) is written as exp(-a*a)*erfcx(b). since b >= 0, erfcx
    # cannot overflow and the exponential never goes above one.
    return 0.5 * erfc(a) + 0.5 * np.exp(-a*a) * erfcx(b)


def pulse_response(z, t, pulse_duration, velocity, diffusivity):
    """gas response to a unit inlet pulse, as a step minus a delayed step."""
    if not np.isfinite(pulse_duration) or pulse_duration <= 0:
        raise ValueError("Pulse duration must be positive seconds")
    return (step_response(z, t, velocity, diffusivity)
            - step_response(z, t-pulse_duration, velocity, diffusivity))


# cell averages


def cell_averages(function, faces, order=DEFAULT_QUADRATURE_ORDER):
    """gauss-legendre average of function over each cell, to compare with finite-volume states."""
    faces = np.asarray(faces, dtype=float)
    if faces.ndim != 1 or len(faces) < 2 or np.any(np.diff(faces) <= 0):
        raise ValueError("Strictly increasing cell faces required")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    mid = (faces[:-1] + faces[1:]) / 2
    half = np.diff(faces) / 2
    values = function(mid[:, None] + half[:, None] * nodes)
    return np.asarray(values) @ weights / 2
