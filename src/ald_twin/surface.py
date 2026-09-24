"""irreversible capture into one effective precursor-equivalent capacity pool."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .units import R, _nonnegative, _positive


# finite-capacity surface


@dataclass(frozen=True, slots=True)
class FiniteCapacity:
    """capacity [mol/m²] and capture velocity [m/s], independent of transport.

    theta is the used fraction of the effective capacity. it is not automatically
    real site coverage, film thickness or a measured mass.
    """

    capacity: float
    capture_velocity: float

    def __post_init__(self) -> None:
        """check both inputs and store them as floats."""
        object.__setattr__(self, "capacity", _positive(self.capacity, "capacity [mol/m²]"))
        object.__setattr__(
            self,
            "capture_velocity",
            _nonnegative(self.capture_velocity, "capture_velocity [m/s]"),
        )

    @classmethod
    def from_probability(
        cls,
        *,
        capacity: float,
        beta: float,
        temperature: float,
        molar_mass: float,
    ) -> FiniteCapacity:
        """build from a capture probability: k_cap = beta sqrt(8 R T / (pi M)) / 4, T [K], M [kg/mol].

        capacity stays a separate input, since collision theory says nothing
        about the saturated surface inventory.
        """
        beta = _nonnegative(beta, "effective capture probability")
        if beta > 1:
            raise ValueError("effective capture probability must be no greater than one")
        temperature = _positive(temperature, "temperature [K]")
        molar_mass = _positive(molar_mass, "molar_mass [kg/mol]")
        # mean molecular speed, and the wall flux is a quarter of n times that speed
        mean_speed = math.sqrt(8 * R * temperature / (math.pi * molar_mass))
        return cls(capacity=capacity, capture_velocity=beta * mean_speed / 4)

    def rate(self, concentration: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        """capture rate [mol/m²/s] = k_cap c (1 - theta), broadcasting c and theta.

        nothing is clipped, so any state that leaves its bounds stays visible in
        the solution and its diagnostics.
        """
        return (
            self.capture_velocity
            * np.asarray(concentration, dtype=float)
            * (1.0 - np.asarray(theta, dtype=float))
        )
