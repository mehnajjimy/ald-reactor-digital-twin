"""Dilute-species composition transport in a prescribed carrier flow."""

from dataclasses import dataclass

import numpy as np

from .channel_flow import channel_flow
from .units import R, _nonnegative, _positive


def diffusivity(property_data, temperature, pressure):
    """Evaluate the explicitly synthetic D(T,p) input [m²/s].

    A missing physical property cannot fall back to a test value. A future
    accepted physical relation belongs here, with its own range/source checks.
    """
    if property_data.get("kind") != "synthetic" or not property_data.get("source"):
        raise ValueError("Physical diffusivity is not accepted; supply a labelled synthetic property")
    value = _positive(property_data.get("value"), "reference diffusivity [m²/s]")
    reference_pressure = _positive(property_data.get("pressure"), "reference pressure [Pa]")
    reference_temperature = _positive(property_data.get("temperature"), "reference temperature [K]")
    if temperature != reference_temperature:
        raise ValueError("This synthetic property defines one temperature only")
    pressure = np.asarray(pressure, dtype=float)
    if not np.all(np.isfinite(pressure)) or np.any(pressure <= 0):
        raise ValueError("Local pressure must be finite and positive")
    return value * reference_pressure / pressure


@dataclass(frozen=True)
class CycleGrid:
    """Cell inventories and interior diffusive conductances, all in SI."""

    z: np.ndarray
    volumes: np.ndarray
    reactive_areas: np.ndarray
    carrier_concentration: np.ndarray
    molar_flow: float
    conductance: np.ndarray
    metadata: dict

    def __post_init__(self):
        n = len(self.z)
        if n < 1:
            raise ValueError("At least one control volume is required")
        for name in ("z", "volumes", "reactive_areas", "carrier_concentration"):
            values = np.asarray(getattr(self, name), dtype=float)
            if values.shape != (n,) or not np.isfinite(values).all():
                raise ValueError(f"Invalid cell array: {name}")
            object.__setattr__(self, name, values.copy())
        if np.any(self.volumes <= 0) or np.any(self.carrier_concentration <= 0) or np.any(self.reactive_areas < 0):
            raise ValueError("Cell volumes/concentrations must be positive; areas nonnegative")
        if n > 1 and np.any(np.diff(self.z) <= 0):
            raise ValueError("Cell centers must increase downstream")
        conductance = np.asarray(self.conductance, dtype=float)
        if conductance.shape != (2, n - 1) or not np.isfinite(conductance).all() or np.any(conductance < 0):
            raise ValueError("Two nonnegative interior conductance arrays are required")
        object.__setattr__(self, "conductance", conductance.copy())
        _nonnegative(self.molar_flow, "carrier flow [mol/s]")
        if self.metadata.get("kind") != "synthetic":
            raise ValueError("The full-cycle implementation currently admits synthetic cases only")

    @property
    def carrier_moles(self):
        return self.volumes * self.carrier_concentration


def channel_grid(parameters, cells):
    """Build N spatial volumes, or one matched well-mixed volume.

    Integrate the square-root pressure profile over each cell exactly. This
    keeps the total carrier inventory independent of the chosen grid.
    """
    if parameters.get("kind") != "synthetic":
        raise ValueError("Experimental cycle runs remain blocked")
    if isinstance(cells, bool) or not isinstance(cells, (int, np.integer)) or cells < 1:
        raise ValueError("cells must be a positive integer")
    channel = parameters["channel"]
    faces = np.linspace(0, channel["length"], cells + 1)
    pressure, velocity = channel_flow(faces, **channel)
    # Integral mean of sqrt(a+b*z), factored to avoid cancellation at small b.
    left, right = pressure[:-1], pressure[1:]
    mean_pressure = (2 / 3) * (left*left + left*right + right*right) / (left + right)
    concentration = mean_pressure / (R * channel["temperature"])
    area = channel["width"] * channel["height"]
    dz = channel["length"] / cells
    start, end = parameters.get("reactive_interval", [0, channel["length"]])
    if not 0 <= start < end <= channel["length"]:
        raise ValueError("Reactive interval must lie inside the channel")
    active_lengths = np.maximum(0, np.minimum(faces[1:], end) - np.maximum(faces[:-1], start))
    diffusion = np.array([diffusivity(parameters["diffusivity"][species],
                                     channel["temperature"], pressure) for species in ("a", "b")])
    conductance = area * pressure[None, 1:-1] / (R * channel["temperature"]) * diffusion[:, 1:-1] / dz
    ratio = float(np.max(velocity[None, :] * dz / (2 * diffusion))) if cells > 1 else None
    metadata = dict(kind="synthetic", parameters=parameters, cells=int(cells),
                    face_pressure_pa=pressure.tolist(), face_diffusivity_m2_s=diffusion.tolist(),
                    numerical_diffusion_ratio=ratio, physical_fit_ready=False)
    return CycleGrid((faces[:-1] + faces[1:]) / 2, np.full(cells, area * dz),
                     2 * channel["width"] * active_lengths, concentration,
                     channel["molar_flow"], conductance, metadata)


def composition_fluxes(fractions, grid, inlet):
    """Return the two species' actual face fluxes [mol/s], positive downstream."""
    fractions = np.asarray(fractions)
    n = len(grid.z)
    if fractions.shape != (2, n):
        raise ValueError("Fractions must have shape (2, cells)")
    flux = np.empty((2, n + 1))
    flux[:, 0] = inlet
    flux[:, 1:-1] = grid.molar_flow * fractions[:, :-1] - grid.conductance * np.diff(fractions)
    flux[:, -1] = grid.molar_flow * fractions[:, -1]
    return flux
