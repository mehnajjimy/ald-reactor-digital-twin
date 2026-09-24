"""dilute-species composition transport in a prescribed carrier flow."""

from dataclasses import dataclass

import numpy as np

from .channel_flow import channel_flow
from .units import R, _nonnegative, _positive

# the two precursor species, in state order: a is the metal precursor, b is water
SPECIES = ("a", "b")


# ---- diffusivity input

def diffusivity(property_data, temperature, pressure):
    """evaluate the explicitly synthetic D(T,p) input [m²/s].

    a missing physical property cannot fall back to a test value. a future
    accepted physical relation belongs here, with its own range and source checks.
    """
    # only a labelled synthetic property is accepted for now
    if property_data.get("kind") != "synthetic" or not property_data.get("source"):
        raise ValueError("Physical diffusivity is not accepted; supply a labelled synthetic property")
    value = _positive(property_data.get("value"), "reference diffusivity [m²/s]")
    reference_pressure = _positive(property_data.get("pressure"), "reference pressure [Pa]")
    reference_temperature = _positive(property_data.get("temperature"), "reference temperature [K]")
    if temperature != reference_temperature:
        raise ValueError("This synthetic property defines one temperature only")

    # gas diffusivity scales as 1/p at fixed temperature
    pressure = np.asarray(pressure, dtype=float)
    if not np.all(np.isfinite(pressure)) or np.any(pressure <= 0):
        raise ValueError("Local pressure must be finite and positive")
    return value * reference_pressure / pressure


# ---- control-volume grid

@dataclass(frozen=True)
class CycleGrid:
    """cell inventories and interior diffusive conductances, all in SI."""

    z: np.ndarray
    volumes: np.ndarray
    reactive_areas: np.ndarray
    carrier_concentration: np.ndarray
    molar_flow: float
    conductance: np.ndarray
    metadata: dict

    def __post_init__(self):
        """check shapes and signs, and store private float copies of every array."""
        n = len(self.z)
        if n < 1:
            raise ValueError("At least one control volume is required")

        # the four per-cell arrays must be finite and n long
        for name in ("z", "volumes", "reactive_areas", "carrier_concentration"):
            values = np.asarray(getattr(self, name), dtype=float)
            if values.shape != (n,) or not np.isfinite(values).all():
                raise ValueError(f"Invalid cell array: {name}")
            object.__setattr__(self, name, values.copy())
        if (np.any(self.volumes <= 0) or np.any(self.carrier_concentration <= 0)
                or np.any(self.reactive_areas < 0)):
            raise ValueError("Cell volumes/concentrations must be positive; areas nonnegative")
        if n > 1 and np.any(np.diff(self.z) <= 0):
            raise ValueError("Cell centers must increase downstream")

        # one row of n-1 interior face conductances for each species
        conductance = np.asarray(self.conductance, dtype=float)
        if (conductance.shape != (2, n - 1) or not np.isfinite(conductance).all()
                or np.any(conductance < 0)):
            raise ValueError("Two nonnegative interior conductance arrays are required")
        object.__setattr__(self, "conductance", conductance.copy())

        _nonnegative(self.molar_flow, "carrier flow [mol/s]")
        if self.metadata.get("kind") != "synthetic":
            raise ValueError("The full-cycle implementation currently admits synthetic cases only")

    @property
    def carrier_moles(self):
        """carrier gas inventory of each cell [mol]."""
        return self.volumes * self.carrier_concentration


def channel_grid(parameters, cells):
    """build N spatial volumes, or one matched well-mixed volume.

    the square-root pressure profile is integrated over each cell exactly, so
    the total carrier inventory does not depend on the chosen grid.
    """
    if parameters.get("kind") != "synthetic":
        raise ValueError("Experimental cycle runs remain blocked")
    if isinstance(cells, bool) or not isinstance(cells, (int, np.integer)) or cells < 1:
        raise ValueError("cells must be a positive integer")

    # pressure and velocity on the cell faces
    channel = parameters["channel"]
    faces = np.linspace(0, channel["length"], cells + 1)
    pressure, velocity = channel_flow(faces, **channel)

    # the integral mean of sqrt(a + b*z) over a cell, written in its two face
    # pressures so it does not lose precision when b is small
    left = pressure[:-1]
    right = pressure[1:]
    mean_pressure = (2 / 3) * (left*left + left*right + right*right) / (left + right)
    concentration = mean_pressure / (R * channel["temperature"])
    area = channel["width"] * channel["height"]
    dz = channel["length"] / cells

    # reactive length inside each cell, from its overlap with the reactive interval
    start, end = parameters.get("reactive_interval", [0, channel["length"]])
    if not 0 <= start < end <= channel["length"]:
        raise ValueError("Reactive interval must lie inside the channel")
    overlap_start = np.maximum(faces[:-1], start)
    overlap_end = np.minimum(faces[1:], end)
    active_lengths = np.maximum(0, overlap_end - overlap_start)

    # face diffusivities and interior face conductances [mol/s], one row per species
    face_diffusivities = []
    for species in SPECIES:
        face_diffusivities.append(diffusivity(parameters["diffusivity"][species],
                                              channel["temperature"], pressure))
    diffusion = np.array(face_diffusivities)
    conductance = area * pressure[None, 1:-1] / (R * channel["temperature"]) * diffusion[:, 1:-1] / dz

    # upwind numerical diffusion u*dz/2 relative to the physical diffusivity
    if cells > 1:
        ratio = float(np.max(velocity[None, :] * dz / (2 * diffusion)))
    else:
        ratio = None

    metadata = dict(kind="synthetic", parameters=parameters, cells=int(cells),
                    face_pressure_pa=pressure.tolist(), face_diffusivity_m2_s=diffusion.tolist(),
                    numerical_diffusion_ratio=ratio, physical_fit_ready=False)
    centers = (faces[:-1] + faces[1:]) / 2
    volumes = np.full(cells, area * dz)
    # both plates react, so each cell has two walls of reactive area
    reactive_areas = 2 * channel["width"] * active_lengths
    return CycleGrid(centers, volumes, reactive_areas, concentration,
                     channel["molar_flow"], conductance, metadata)


# ---- face fluxes

def composition_fluxes(fractions, grid, inlet):
    """return the two species' actual face fluxes [mol/s], positive downstream.

    the inlet face carries the given inlet rates, interior faces carry upwind
    advection minus diffusion, and the outlet face carries advection only.
    """
    fractions = np.asarray(fractions)
    n = len(grid.z)
    if fractions.shape != (2, n):
        raise ValueError("Fractions must have shape (2, cells)")
    flux = np.empty((2, n + 1))
    flux[:, 0] = inlet
    flux[:, 1:-1] = grid.molar_flow * fractions[:, :-1] - grid.conductance * np.diff(fractions)
    flux[:, -1] = grid.molar_flow * fractions[:, -1]
    return flux
