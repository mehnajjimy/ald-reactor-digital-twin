"""Irreversible capture into one effective precursor-equivalent capacity pool."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .units import R, _nonnegative, _positive


@dataclass(frozen=True, slots=True)
class FiniteCapacity:
    """Capacity [mol/m²] and capture velocity [m/s], independent of transport.

    Theta measures consumed effective capacity. It is not automatically literal
    site coverage, deposited thickness, or an experimental mass observable.
    """

    capacity: float
    capture_velocity: float

    def __post_init__(self) -> None:
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
        """Use k_cap = beta sqrt(8 R T / (pi M)) / 4, with T [K], M [kg/mol].

        Capacity remains an independent input; collision theory does not supply
        an effective saturated surface inventory.
        """
        beta = _nonnegative(beta, "effective capture probability")
        if beta > 1:
            raise ValueError("effective capture probability must be no greater than one")
        temperature = _positive(temperature, "temperature [K]")
        molar_mass = _positive(molar_mass, "molar_mass [kg/mol]")
        mean_speed = math.sqrt(8 * R * temperature / (math.pi * molar_mass))
        return cls(capacity=capacity, capture_velocity=beta * mean_speed / 4)

    def rate(self, concentration: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        """Return capture rate [mol/m²/s], broadcasting concentration and theta.

        No clipping is applied: any integrator state-bound violation must remain
        visible in the returned solution and its diagnostics.
        """
        return (
            self.capture_velocity
            * np.asarray(concentration, dtype=float)
            * (1.0 - np.asarray(theta, dtype=float))
        )
