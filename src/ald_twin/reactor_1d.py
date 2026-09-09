"""Uniform-cell finite volumes for constant-coefficient single-half-cycle transport."""

from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
from scipy.sparse import lil_matrix

from .numerics import SolverOptions, integrate_segments
from .results import assemble_result
from .surface import FiniteCapacity
from .units import _finite_scalar, _nonnegative, _positive


@dataclass(frozen=True)
class Reactor1D:
    length: float
    area: float
    reactive_perimeter: float
    velocity: float
    diffusivity: float
    cells: int
    diffusivity_kind: str = "synthetic_verification"

    def __post_init__(self):
        for name in ("length", "area"):
            _positive(getattr(self, name), name)
        for name in ("reactive_perimeter", "diffusivity"):
            _nonnegative(getattr(self, name), name)
        _finite_scalar(self.velocity, "velocity")
        if isinstance(self.cells, bool) or not isinstance(self.cells, (int, np.integer)) or self.cells < 2:
            raise ValueError("cells must be an integer >= 2")
        if self.diffusivity_kind not in ("molecular", "axial_dispersion", "synthetic_verification"):
            raise ValueError("Identify diffusivity as molecular, axial_dispersion, or synthetic_verification")

    @property
    def dz(self):
        return self.length / self.cells

    @property
    def z(self):
        return (np.arange(self.cells) + 0.5) * self.dz


@dataclass(frozen=True)
class ConcentrationBoundary:
    """Fixed endpoint concentrations in mol/m3; D must be positive."""
    left: float
    right: float = 0.0

    def __post_init__(self):
        _nonnegative(self.left, "left concentration")
        _nonnegative(self.right, "right concentration")


@dataclass(frozen=True)
class FluxBoundary:
    """Total inlet mol/s; zero downstream diffusive gradient, forward flow."""
    inlet_molar_flow: float

    def __post_init__(self):
        _nonnegative(self.inlet_molar_flow, "inlet molar flow")


@dataclass(frozen=True)
class AdvectiveBoundary:
    """Hyperbolic inflow concentration at the upstream end; no downstream datum."""
    inlet_concentration: float

    def __post_init__(self):
        _nonnegative(self.inlet_concentration, "inflow concentration")


Boundary = ConcentrationBoundary | FluxBoundary | AdvectiveBoundary


@dataclass(frozen=True)
class TransportSegment:
    duration: float
    boundary: Boundary
    label: str = ""

    def __post_init__(self):
        _positive(self.duration, "segment duration")
        if not isinstance(self.label, str):
            raise ValueError("Segment label must be a string")


def _validate_boundary(reactor, boundary):
    if isinstance(boundary, ConcentrationBoundary):
        if reactor.diffusivity <= 0:
            raise ValueError("D=0 requires hyperbolic inflow/outflow, not two fixed concentrations")
    elif isinstance(boundary, FluxBoundary):
        if reactor.velocity <= 0:
            raise ValueError("The prescribed-flow reactor requires forward velocity > 0")
    elif isinstance(boundary, AdvectiveBoundary):
        if reactor.diffusivity != 0 or reactor.velocity == 0:
            raise ValueError("AdvectiveBoundary requires D=0 and nonzero velocity")
    else:
        raise TypeError("Unknown boundary formulation")


def face_fluxes(c, reactor: Reactor1D, boundary: Boundary):
    """Total mol/(m2 s) on all N+1 faces; positive flux points right."""
    _validate_boundary(reactor, boundary)
    c = np.asarray(c)
    if c.shape != (reactor.cells,):
        raise ValueError("One concentration is required per cell")
    u, D, dz = reactor.velocity, reactor.diffusivity, reactor.dz
    flux = np.empty(reactor.cells + 1)
    upstream = c[:-1] if u >= 0 else c[1:]
    flux[1:-1] = u * upstream - D * np.diff(c) / dz
    if isinstance(boundary, ConcentrationBoundary):
        # The diffusion distance from a boundary face to a cell center is dz/2.
        flux[0] = u * (boundary.left if u >= 0 else c[0]) - 2 * D * (c[0] - boundary.left) / dz
        flux[-1] = u * (c[-1] if u >= 0 else boundary.right) - 2 * D * (boundary.right - c[-1]) / dz
    elif isinstance(boundary, FluxBoundary):
        flux[0] = boundary.inlet_molar_flow / reactor.area
        flux[-1] = u * c[-1]
    else:
        flux[0] = u * (boundary.inlet_concentration if u > 0 else c[0])
        flux[-1] = u * (c[-1] if u > 0 else boundary.inlet_concentration)
    return flux


def jacobian_sparsity(cells):
    """Nearest-neighbor transport, local reaction, boundary-only ledger coupling."""
    pattern = lil_matrix((2 * cells + 3, 2 * cells + 3), dtype=int)
    for j in range(cells):
        pattern[j, max(0, j - 1):min(cells, j + 2)] = 1
        pattern[j, cells + j] = 1
        pattern[cells + j, j] = 1
        pattern[cells + j, cells + j] = 1
    pattern[2 * cells:2 * cells + 2, 0] = 1
    pattern[2 * cells:2 * cells + 2, cells - 1] = 1
    return pattern.tocsr()


def solve_1d(reactor: Reactor1D, surface: FiniteCapacity, segments, *,
             concentration_scale: float, initial_c=0., initial_theta=0.,
             options=SolverOptions(), provenance_id="synthetic-unregistered",
             artificial_source: Callable | None = None, source_id: str | None = None,
             output_times=None):
    """Solve exposure/purge without resetting state.

    An optional manufactured source returns prescribed cell-average gas source
    [mol/m3/s] and theta source [1/s] at (t,z). It may not depend on numerical
    state. Both artificial contributions enter the explicit source ledger.
    """
    _positive(concentration_scale, "concentration scale")
    if not isinstance(provenance_id, str) or not provenance_id.strip():
        raise ValueError("provenance_id must be nonempty")
    if artificial_source is not None and not source_id:
        raise ValueError("Manufactured sources require an explicit source_id")
    segments = tuple(segments)
    for segment in segments:
        _validate_boundary(reactor, segment.boundary)
    n = reactor.cells
    c0 = np.broadcast_to(np.asarray(initial_c, dtype=float), (n,)).copy()
    theta0 = np.broadcast_to(np.asarray(initial_theta, dtype=float), (n,)).copy()
    if not np.all(np.isfinite(c0)) or np.any(c0 < 0):
        raise ValueError("Initial gas must be finite and nonnegative")
    if not np.all(np.isfinite(theta0)) or np.any((theta0 < 0) | (theta0 > 1)):
        raise ValueError("Initial theta must lie in [0,1]")
    inventory_scale = reactor.area * reactor.length * concentration_scale
    _positive(inventory_scale, "inventory scale")
    area_ratio = reactor.reactive_perimeter / reactor.area
    initial = np.r_[c0 / concentration_scale, theta0, 0., 0., 0.]

    def rhs_factory(index):
        boundary = segments[index].boundary

        def rhs(t, y):
            c, theta = y[:n] * concentration_scale, y[n:2*n]
            flux = face_fluxes(c, reactor, boundary)
            rate = surface.rate(c, theta)
            dc = -np.diff(flux) / reactor.dz - area_ratio * rate
            dtheta = rate / surface.capacity
            source_rate = 0.
            if artificial_source is not None:
                gas_source, surface_source = artificial_source(t, reactor.z)
                gas_source = np.broadcast_to(np.asarray(gas_source, dtype=float), (n,))
                surface_source = np.broadcast_to(np.asarray(surface_source, dtype=float), (n,))
                if not np.all(np.isfinite(gas_source)) or not np.all(np.isfinite(surface_source)):
                    raise ValueError("Artificial sources must be finite")
                dc = dc + gas_source
                dtheta = dtheta + surface_source
                source_rate = reactor.dz * (
                    reactor.area * np.sum(gas_source)
                    + reactor.reactive_perimeter * surface.capacity * np.sum(surface_source)
                )
            # Reuse the PDE's boundary fluxes; diffusive inlet escape during
            # purge contributes to escape even though its location is upstream.
            left_inflow = reactor.area * flux[0]
            right_inflow = -reactor.area * flux[-1]
            entering = max(left_inflow, 0.) + max(right_inflow, 0.)
            escaping = max(-left_inflow, 0.) + max(-right_inflow, 0.)
            return np.r_[dc / concentration_scale, dtheta, entering / inventory_scale,
                         escaping / inventory_scale, source_rate / inventory_scale]
        return rhs

    integrated = integrate_segments(initial, [s.duration for s in segments],
                                    rhs_factory, options, jacobian_sparsity(n), output_times)
    snapshot = dict(model="constant-coefficient single-half-cycle 1D",
                    reactor=asdict(reactor), surface=asdict(surface),
                    segments=[dict(duration=s.duration, label=s.label,
                        boundary_type=type(s.boundary).__name__, boundary=asdict(s.boundary)) for s in segments],
                    concentration_scale=concentration_scale, inventory_scale=inventory_scale,
                    initial_c=c0.tolist(), initial_theta=theta0.tolist(),
                    solver=dict(method=options.method, rtol=options.rtol, atol=options.atol,
                                max_step=options.max_step if np.isfinite(options.max_step) else "unbounded"),
                    provenance_id=provenance_id, artificial_source_id=source_id,
                    output_times=(np.asarray(output_times).tolist() if output_times is not None else "accepted steps"),
                    numerical_diffusivity=abs(reactor.velocity)*reactor.dz/2,
                    numerical_diffusivity_ratio=(abs(reactor.velocity)*reactor.dz/(2*reactor.diffusivity)
                        if reactor.diffusivity > 0 else None))
    return assemble_result(integrated=integrated, c=integrated.y[:n].T*concentration_scale,
        theta=integrated.y[n:2*n].T, z=reactor.z,
        cell_volumes=np.full(n, reactor.area*reactor.dz),
        cell_areas=np.full(n, reactor.reactive_perimeter*reactor.dz),
        capacity=surface.capacity, initial_c=c0, initial_theta=theta0,
        entered_moles=integrated.y[2*n]*inventory_scale,
        escaped_moles=integrated.y[2*n+1]*inventory_scale,
        source_moles=integrated.y[2*n+2]*inventory_scale, metadata=snapshot)
