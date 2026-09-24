"""dimensionless finite-capacity runs through the existing SI engine.

representatives are arbitrary mathematical scales, not experimental parameters.
reaction probability is already included in Da and is on purpose not an input.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from .numerics import SolverOptions
from .reactor_1d import (ConcentrationBoundary, Reactor1D, TransportSegment,
                         solve_1d)
from .surface import FiniteCapacity


def _positive(value, name):
    """reject bools, non-scalars, non-finite values and values <= 0."""
    if isinstance(value, bool) or not np.isscalar(value):
        raise ValueError(f"{name} must be finite and positive")
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


# groups and scales

@dataclass(frozen=True)
class DimensionlessGroups:
    """Peclet, Damkohler and capacity ratio gamma for one benchmark case."""

    pe: float
    da: float
    gamma: float

    def __post_init__(self):
        """check every group is finite and positive."""
        for name in ("pe", "da", "gamma"):
            _positive(getattr(self, name), name)


@dataclass(frozen=True)
class MathematicalScales:
    """positive arbitrary L*, D*, c0*, A*, a* in their respective SI units."""

    length: float = 1.
    diffusivity: float = 1.
    concentration: float = 1.
    area: float = 1.
    area_ratio: float = 1.

    def __post_init__(self):
        """check every scale is finite and positive."""
        for name, value in asdict(self).items():
            _positive(value, name)

    @property
    def time(self):
        """diffusion time scale L*²/D* [s]."""
        return self.length**2 / self.diffusivity

    @property
    def inventory(self):
        """reference amount A* L* c0* [mol], using L* and not the domain extent."""
        return self.area * self.length * self.concentration


def representative(groups, scales, *, extent, cells):
    """map groups into one member of an infinite mathematical equivalence class."""
    _positive(extent, "extent")
    reactor = Reactor1D(
        length=extent*scales.length, area=scales.area,
        reactive_perimeter=scales.area_ratio*scales.area,
        velocity=groups.pe*scales.diffusivity/scales.length,
        diffusivity=scales.diffusivity, cells=cells,
        diffusivity_kind="synthetic_verification")
    surface = FiniteCapacity(
        capacity=scales.concentration/(scales.area_ratio*groups.gamma),
        capture_velocity=groups.da*scales.diffusivity/(scales.area_ratio*scales.length**2))
    return reactor, surface


# normalized result

@dataclass(frozen=True)
class DimensionlessResult:
    """an SI run seen through its mathematical scales."""

    raw: object
    scales: MathematicalScales
    metadata: dict

    @property
    def tau(self):
        """dimensionless time t/T*."""
        return self.raw.t / self.scales.time

    @property
    def xi(self):
        """dimensionless position z/L*."""
        return self.raw.z / self.scales.length

    @property
    def x(self):
        """normalized gas concentration c/c0*."""
        return self.raw.c / self.scales.concentration

    @property
    def theta(self):
        """occupied fraction of surface capacity."""
        return self.raw.theta

    def arrays(self):
        """all normalized arrays, with inventories divided by A* L* c0*."""
        arrays = dict(tau=self.tau, xi=self.xi, x=self.x, theta=self.theta,
                      available_sites=1-self.theta)
        for name in ("gas", "captured", "entered", "escaped", "source", "ledger_error"):
            arrays[name] = getattr(self.raw, name+"_moles") / self.scales.inventory
        return arrays

    def save(self, stem):
        """write stem.npz, stem.json and the raw SI run next to them."""
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(stem)+".npz", **self.arrays())
        metadata_text = json.dumps(self.metadata, indent=2, allow_nan=False)
        Path(str(stem)+".json").write_text(metadata_text+"\n")
        self.raw.save(str(stem)+"-synthetic-representative")


# solve

def _valid_output_tau(sample_tau, end_tau):
    """true when sample_tau is 1-d, finite, strictly increasing and inside [0, end_tau]."""
    if sample_tau.ndim != 1:
        return False
    if not np.all(np.isfinite(sample_tau)):
        return False
    if np.any(np.diff(sample_tau) <= 0):
        return False
    if np.any(sample_tau < 0):
        return False
    if np.any(sample_tau > end_tau):
        return False
    return True


def solve_dimensionless(groups, *, extent, cells, pulse_tau, purge_tau,
                        scales=MathematicalScales(), options=SolverOptions(),
                        output_tau=None, provenance_id="synthetic-dimensionless"):
    """empty initial state, then a Dirichlet rectangular pulse followed by purge.

    SolverOptions.max_step is dimensionless delta-tau here and converted for solve_1d.
    the result's normalized inventories use A*L*c0*, hence captured=int(theta)/gamma.
    """
    _positive(pulse_tau, "pulse_tau")
    _positive(purge_tau, "purge_tau")
    reactor, surface = representative(groups, scales, extent=extent, cells=cells)
    segments = (
        TransportSegment(pulse_tau*scales.time,
                         ConcentrationBoundary(scales.concentration), "exposure"),
        TransportSegment(purge_tau*scales.time, ConcentrationBoundary(0.), "purge"))

    # optional sample times, given in tau and converted to seconds
    sample_times = None
    if output_tau is not None:
        sample_tau = np.asarray(output_tau, dtype=float)
        if not _valid_output_tau(sample_tau, pulse_tau+purge_tau):
            raise ValueError("output_tau must be strictly increasing within the recipe")
        sample_times = sample_tau*scales.time
        # snap samples at segment ends to the exact segment end times. rounding
        # in tau*T* could otherwise keep a spurious second endpoint or reject a
        # valid final sample under a change of scale.
        tau_ends = np.cumsum([pulse_tau, purge_tau])
        time_ends = np.cumsum([segment.duration for segment in segments])
        for tau_end, time_end in zip(tau_ends, time_ends):
            sample_times[sample_tau == tau_end] = time_end

    raw = solve_1d(reactor, surface, segments,
        concentration_scale=scales.concentration,
        options=replace(options, max_step=options.max_step*scales.time),
        output_times=sample_times,
        provenance_id=provenance_id)

    # metadata, then a hash of it
    metadata = dict(
        role="dimensionless model reproduction with synthetic recipe",
        groups=asdict(groups), extent=extent, cells=cells,
        pulse_tau=pulse_tau, purge_tau=purge_tau,
        mathematical_scales=asdict(scales),
        units={"tau": "1", "xi": "1", "x": "1", "theta": "1",
               "available_sites": "1", "inventories": "N/(A* L* c0*)"},
        occupied_capacity_convention="theta_ours = 1 - theta_paper_available",
        reaction_probability="already inside Da; not applied again",
        exact_published_curve_reproduction=False,
        experimental_dimensional_mapping=False,
        provenance_id=provenance_id,
        raw_configuration_sha256=raw.metadata["configuration_sha256"])
    metadata_text = json.dumps(metadata, sort_keys=True, allow_nan=False)
    metadata["configuration_sha256"] = hashlib.sha256(metadata_text.encode()).hexdigest()
    return DimensionlessResult(raw, scales, metadata)
