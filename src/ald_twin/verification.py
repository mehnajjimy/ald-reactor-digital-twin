"""error norms and exact manufactured solutions used to verify the solvers."""

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

# largest rise between neighbouring theta values still treated as descending
MONOTONE_TOLERANCE = 1e-8


# comparing arrays


def normalized_l1(actual, reference):
    """sum |actual - reference| / sum |reference| on a uniform grid. a zero reference is refused."""
    actual = np.asarray(actual)
    reference = np.asarray(reference)
    message = "Comparison arrays must have equal shapes and finite values"
    if actual.shape != reference.shape:
        raise ValueError(message)
    if not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference)):
        raise ValueError(message)
    scale = np.sum(np.abs(reference))
    if scale <= 0:
        raise ValueError("A zero reference requires an absolute error")
    return float(np.sum(np.abs(actual-reference))/scale)


def restrict_uniform(fine, coarse_cells):
    """average groups of equal fine cells onto a coarser grid that lines up with them."""
    fine = np.asarray(fine)
    if coarse_cells <= 0 or fine.shape[-1] % coarse_cells:
        raise ValueError("Uniform grids must be nested by an integer ratio")
    fine_per_coarse = fine.shape[-1]//coarse_cells
    grouped = fine.reshape(*fine.shape[:-1], coarse_cells, fine_per_coarse)
    return grouped.mean(axis=-1)


# front position


def front_position(z, theta, level=.5):
    """where a descending theta profile crosses level, by linear interpolation between cell centres."""
    z = np.asarray(z)
    theta = np.asarray(theta)
    shape_ok = z.ndim == 1 and z.shape == theta.shape
    if not shape_ok or not np.all(np.isfinite(theta)) or np.any(np.diff(z) <= 0):
        raise ValueError("Invalid front coordinates/states")
    if np.any(np.diff(theta) > MONOTONE_TOLERANCE):
        raise ValueError("Front is not monotonically descending")

    # cells that hit the level exactly, and neighbour pairs that straddle it
    exact = np.flatnonzero(theta == level)
    crossing = np.flatnonzero((theta[:-1]-level)*(theta[1:]-level) < 0)
    if len(exact) == 1 and len(crossing) == 0:
        return float(z[exact[0]])
    if len(exact) > 0 or len(crossing) != 1:
        raise ValueError("A unique resolved front crossing is required")
    j = crossing[0]
    return float(z[j]+(level-theta[j])*(z[j+1]-z[j])/(theta[j+1]-theta[j]))


# exact references


def advection_pulse_average(faces, time, pulse_duration, velocity):
    """exact cell averages of a unit square pulse moved by pure advection (overlap, not centre sampling)."""
    faces = np.asarray(faces)
    if velocity <= 0 or pulse_duration <= 0 or np.any(np.diff(faces) <= 0):
        raise ValueError("Forward flow, positive pulse, and increasing faces required")
    # the pulse occupies [left, right] at this time
    left = velocity*max(0., time-pulse_duration)
    right = velocity*max(0., time)
    overlap = np.minimum(faces[1:], right)-np.maximum(faces[:-1], left)
    return np.maximum(0., overlap)/np.diff(faces)


@dataclass(frozen=True)
class ManufacturedSolution:
    """c = C E sin(wz) and theta = b + A (1 - E) sin(wz), with E = exp(-lambda t) and w = pi / L."""

    length: float = 1.
    concentration: float = 1.
    decay: float = .7
    theta_base: float = .2
    theta_amplitude: float = .2

    def spatial_averages(self, z, dz):
        """exact cell averages of sin(wz), cos(wz) and sin²(wz) for cells of width dz centred at z."""
        w = np.pi/self.length
        # averaging sin or cos over a cell multiplies it by sinc(w dz / 2)
        cell_factor = np.sinc(w*dz/(2*np.pi))
        sine = cell_factor*np.sin(w*z)
        cosine = cell_factor*np.cos(w*z)
        sine_squared = .5*(1-np.sinc(w*dz/np.pi)*np.cos(2*w*z))
        return sine, cosine, sine_squared

    def averages(self, time, z, dz):
        """exact cell averages of c and theta at time."""
        sine, _, _ = self.spatial_averages(z, dz)
        exponential = np.exp(-self.decay*time)
        c_average = self.concentration*exponential*sine
        theta_average = self.theta_base+self.theta_amplitude*(1-exponential)*sine
        return c_average, theta_average

    def derivatives(self, time, z, dz):
        """exact time derivatives of the cell-averaged c and theta."""
        sine, _, _ = self.spatial_averages(z, dz)
        exponential = np.exp(-self.decay*time)
        c_rate = -self.decay*self.concentration*exponential*sine
        theta_rate = self.theta_amplitude*self.decay*exponential*sine
        return c_rate, theta_rate

    def source_averages(self, time, z, dz, *, velocity, diffusivity, area_ratio,
                        capture_velocity, capacity):
        """cell averages of the forcing that makes this solution exact, worked out from the pde.

        s_g = c_t + u c_z - D c_zz + a r and s_theta = theta_t - r / Gamma.
        the average of the rate uses <sin²>, not <sin>².
        """
        sine, cosine, sine_squared = self.spatial_averages(z, dz)
        E = np.exp(-self.decay*time)
        w = np.pi/self.length
        c = self.concentration*E*sine
        rate_average = capture_velocity*self.concentration*E*((1-self.theta_base)*sine
            - self.theta_amplitude*(1-E)*sine_squared)
        # gas forcing: decay and diffusion, then advection, then reaction
        decay_and_diffusion = (-self.decay+diffusivity*w*w)*c
        advection = velocity*self.concentration*E*w*cosine
        reaction = area_ratio*rate_average
        gas_source = decay_and_diffusion + advection + reaction
        theta_source = self.theta_amplitude*self.decay*E*sine-rate_average/capacity
        return gas_source, theta_source


# dimensional analysis


def _add_units(*terms):
    """multiply quantities by adding their unit exponents."""
    return tuple(sum(exponents) for exponents in zip(*terms))


def _power_units(term, factor):
    """raise a quantity to a power by scaling its unit exponents."""
    return tuple(Fraction(exponent)*factor for exponent in term)


def dimensional_checks():
    """check that each model equation balances, using exact exponents of (kg, m, s, K, mol)."""
    # short local names keep each check below on one line
    add = _add_units
    mul = _power_units

    # base and derived units as exponents of (kg, m, s, K, mol)
    one = (0, 0, 0, 0, 0)
    length = (0, 1, 0, 0, 0)
    time = (0, 0, 1, 0, 0)
    temperature = (0, 0, 0, 1, 0)
    amount = (0, 0, 0, 0, 1)
    c = add(amount, mul(length, -3))
    capacity = add(amount, mul(length, -2))
    speed = add(length, mul(time, -1))
    diffusion = add(mul(length, 2), mul(time, -1))
    rate = add(speed, c)
    pressure = (1, -1, -2, 0, 0)
    gas_constant = (1, 2, -2, -1, -1)
    molar_mass = (1, 0, 0, 0, -1)

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
