"""Comparison norms and independent continuous manufactured references."""

from dataclasses import dataclass

import numpy as np


def normalized_l1(actual, reference):
    """Uniform-grid L1 ratio; do not fabricate a relative error near zero."""
    actual, reference = np.asarray(actual), np.asarray(reference)
    if actual.shape != reference.shape or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference)):
        raise ValueError("Comparison arrays must have equal shapes and finite values")
    scale = np.sum(np.abs(reference))
    if scale <= 0:
        raise ValueError("A zero reference requires an absolute error")
    return float(np.sum(np.abs(actual-reference))/scale)


def restrict_uniform(fine, coarse_cells):
    """Conservatively average aligned equal-width fine cells onto a coarse grid."""
    fine = np.asarray(fine)
    if coarse_cells <= 0 or fine.shape[-1] % coarse_cells:
        raise ValueError("Uniform grids must be nested by an integer ratio")
    return fine.reshape(*fine.shape[:-1], coarse_cells, fine.shape[-1]//coarse_cells).mean(axis=-1)


def front_position(z, theta, level=.5):
    """Unique monotone descending crossing, linearly interpolated at cell centers."""
    z, theta = np.asarray(z), np.asarray(theta)
    if z.ndim != 1 or z.shape != theta.shape or not np.all(np.isfinite(theta)) or np.any(np.diff(z) <= 0):
        raise ValueError("Invalid front coordinates/states")
    if np.any(np.diff(theta) > 1e-8):
        raise ValueError("Front is not monotonically descending")
    exact = np.flatnonzero(theta == level)
    crossing = np.flatnonzero((theta[:-1]-level)*(theta[1:]-level) < 0)
    if len(exact) == 1 and not len(crossing):
        return float(z[exact[0]])
    if len(exact) or len(crossing) != 1:
        raise ValueError("A unique resolved front crossing is required")
    j = crossing[0]
    return float(z[j]+(level-theta[j])*(z[j+1]-z[j])/(theta[j+1]-theta[j]))


def advection_pulse_average(faces, time, pulse_duration, velocity):
    """Exact rectangular overlap, not center sampling at discontinuities."""
    faces = np.asarray(faces)
    if velocity <= 0 or pulse_duration <= 0 or np.any(np.diff(faces) <= 0):
        raise ValueError("Forward flow, positive pulse, and increasing faces required")
    left, right = velocity*max(0., time-pulse_duration), velocity*max(0., time)
    return np.maximum(0., np.minimum(faces[1:], right)-np.maximum(faces[:-1], left))/np.diff(faces)


@dataclass(frozen=True)
class ManufacturedSolution:
    length: float = 1.
    concentration: float = 1.
    decay: float = .7
    theta_base: float = .2
    theta_amplitude: float = .2

    def spatial_averages(self, z, dz):
        w = np.pi/self.length
        sine = np.sinc(w*dz/(2*np.pi))*np.sin(w*z)
        cosine = np.sinc(w*dz/(2*np.pi))*np.cos(w*z)
        sine_squared = .5*(1-np.sinc(w*dz/np.pi)*np.cos(2*w*z))
        return sine, cosine, sine_squared

    def averages(self, time, z, dz):
        sine, _, _ = self.spatial_averages(z, dz)
        exponential = np.exp(-self.decay*time)
        return (self.concentration*exponential*sine,
                self.theta_base+self.theta_amplitude*(1-exponential)*sine)

    def derivatives(self, time, z, dz):
        sine, _, _ = self.spatial_averages(z, dz)
        exponential = np.exp(-self.decay*time)
        return (-self.decay*self.concentration*exponential*sine,
                self.theta_amplitude*self.decay*exponential*sine)

    def source_averages(self, time, z, dz, *, velocity, diffusivity, area_ratio,
                        capture_velocity, capacity):
        """Continuous PDE forcing averaged analytically, independent of face fluxes.

        c=C E sin(wz), theta=b+A(1-E)sin(wz), E=exp(-lambda*t).
        s_g=c_t+u*c_z-D*c_zz+a*r; s_theta=theta_t-r/Gamma.
        The exact average of the product uses <sin²>, not <sin>².
        """
        sine, cosine, sine_squared = self.spatial_averages(z, dz)
        E = np.exp(-self.decay*time)
        w = np.pi/self.length
        c = self.concentration*E*sine
        rate_average = capture_velocity*self.concentration*E*((1-self.theta_base)*sine
            - self.theta_amplitude*(1-E)*sine_squared)
        gas_source = (-self.decay+diffusivity*w*w)*c + velocity*self.concentration*E*w*cosine + area_ratio*rate_average
        theta_source = self.theta_amplitude*self.decay*E*sine-rate_average/capacity
        return gas_source, theta_source


def dimensional_checks():
    """Exact rational exponent checks: (kg, m, s, K, mol)."""
    from fractions import Fraction
    add = lambda *terms: tuple(sum(x) for x in zip(*terms))
    mul = lambda term, factor: tuple(Fraction(x)*factor for x in term)
    one = (0, 0, 0, 0, 0)
    length, time, temperature, amount = (0,1,0,0,0), (0,0,1,0,0), (0,0,0,1,0), (0,0,0,0,1)
    c, capacity = add(amount,mul(length,-3)), add(amount,mul(length,-2))
    speed, diffusion = add(length,mul(time,-1)), add(mul(length,2),mul(time,-1))
    rate = add(speed,c)
    pressure, gas_constant, molar_mass = (1,-1,-2,0,0), (1,2,-2,-1,-1), (1,0,0,0,-1)
    checks = {
        "collision speed sqrt(R*T/M)": mul(add(gas_constant,temperature,mul(molar_mass,-1)),Fraction(1,2)) == speed,
        "capture rate k*c": rate == (0,-2,-1,0,1),
        "advective equals diffusive flux": add(speed,c) == add(diffusion,c,mul(length,-1)),
        "gas accumulation equals flux divergence": add(c,mul(time,-1)) == add(rate,mul(length,-1)),
        "gas sink a*r": add(mul(length,-1),rate) == add(c,mul(time,-1)),
        "surface accumulation r/Gamma": add(rate,mul(capacity,-1)) == mul(time,-1),
        "0D accumulation equals molar flow": add(mul(length,3),c,mul(time,-1)) == add(amount,mul(time,-1)),
        "0D outlet Q*c": add(mul(length,3),mul(time,-1),c) == add(amount,mul(time,-1)),
        "surface ledger": add(mul(length,2),capacity) == amount,
        "partial pressure c*R*T": add(c,gas_constant,temperature) == pressure,
        "standard-volume to molar flow": add(pressure,mul(length,3),mul(time,-1),mul(gas_constant,-1),mul(temperature,-1)) == add(amount,mul(time,-1)),
        "Pe": add(speed,length,mul(diffusion,-1)) == one,
        "Da": add(mul(length,-1),speed,mul(length,2),mul(diffusion,-1)) == one,
        "gamma": add(c,length,mul(capacity,-1)) == one,
    }
    return checks
