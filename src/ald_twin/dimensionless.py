"""Dimensionless finite-capacity runs through the existing SI engine.

Representatives are arbitrary mathematical scales, not experimental parameters.
Reaction probability is already included in Da and is intentionally not an input.
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
    if isinstance(value, bool) or not np.isscalar(value) or not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class DimensionlessGroups:
    pe: float
    da: float
    gamma: float

    def __post_init__(self):
        for name in ("pe", "da", "gamma"):
            _positive(getattr(self, name), name)


@dataclass(frozen=True)
class MathematicalScales:
    """Positive arbitrary L*, D*, c0*, A*, a* in their respective SI units."""
    length: float = 1.
    diffusivity: float = 1.
    concentration: float = 1.
    area: float = 1.
    area_ratio: float = 1.

    def __post_init__(self):
        for name, value in asdict(self).items():
            _positive(value, name)

    @property
    def time(self):
        return self.length**2 / self.diffusivity

    @property
    def inventory(self):
        # Reference length L*, not the domain extension ell.
        return self.area * self.length * self.concentration


def representative(groups, scales, *, extent, cells):
    """Map groups into one member of an infinite mathematical equivalence class."""
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


@dataclass(frozen=True)
class DimensionlessResult:
    raw: object
    scales: MathematicalScales
    metadata: dict

    @property
    def tau(self):
        return self.raw.t / self.scales.time

    @property
    def xi(self):
        return self.raw.z / self.scales.length

    @property
    def x(self):
        return self.raw.c / self.scales.concentration

    @property
    def theta(self):
        return self.raw.theta

    def arrays(self):
        arrays = dict(tau=self.tau, xi=self.xi, x=self.x, theta=self.theta,
                      available_sites=1-self.theta)
        for name in ("gas", "captured", "entered", "escaped", "source", "ledger_error"):
            arrays[name] = getattr(self.raw, name+"_moles") / self.scales.inventory
        return arrays

    def save(self, stem):
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(stem)+".npz", **self.arrays())
        Path(str(stem)+".json").write_text(json.dumps(self.metadata, indent=2,
                                                   allow_nan=False)+"\n")
        self.raw.save(str(stem)+"-synthetic-representative")


def solve_dimensionless(groups, *, extent, cells, pulse_tau, purge_tau,
                        scales=MathematicalScales(), options=SolverOptions(),
                        output_tau=None, provenance_id="synthetic-dimensionless"):
    """Empty initial state; Dirichlet rectangular pulse followed by purge.

    SolverOptions.max_step is dimensionless delta-tau here and converted for solve_1d.
    The result's normalized inventories use A*L*c0*, hence captured=int(theta)/gamma.
    """
    _positive(pulse_tau, "pulse_tau")
    _positive(purge_tau, "purge_tau")
    reactor, surface = representative(groups, scales, extent=extent, cells=cells)
    segments = (
        TransportSegment(pulse_tau*scales.time,
                         ConcentrationBoundary(scales.concentration), "exposure"),
        TransportSegment(purge_tau*scales.time, ConcentrationBoundary(0.), "purge"))
    sample_times = None
    if output_tau is not None:
        sample_tau = np.asarray(output_tau, dtype=float)
        if (sample_tau.ndim != 1 or not np.all(np.isfinite(sample_tau))
                or np.any(np.diff(sample_tau) <= 0) or np.any(sample_tau < 0)
                or np.any(sample_tau > pulse_tau+purge_tau)):
            raise ValueError("output_tau must be strictly increasing within the recipe")
        sample_times = sample_tau*scales.time
        # Distributive floating-point rounding can otherwise retain a spurious
        # second endpoint or reject a valid final sample under a change of scale.
        for tau_end, time_end in zip(np.cumsum([pulse_tau, purge_tau]),
                                    np.cumsum([s.duration for s in segments])):
            sample_times[sample_tau == tau_end] = time_end
    raw = solve_1d(reactor, surface, segments,
        concentration_scale=scales.concentration,
        options=replace(options, max_step=options.max_step*scales.time),
        output_times=sample_times,
        provenance_id=provenance_id)
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
    metadata["configuration_sha256"] = hashlib.sha256(json.dumps(
        metadata, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return DimensionlessResult(raw, scales, metadata)
