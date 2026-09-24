"""uniform-cell finite volumes for constant-coefficient transport over one half-cycle."""

from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
from scipy.sparse import lil_matrix

from .numerics import SolverOptions, integrate_segments
from .results import assemble_result
from .surface import FiniteCapacity
from .units import _finite_scalar, _nonnegative, _positive

# allowed labels for what the diffusivity stands for
DIFFUSIVITY_KINDS = ("molecular", "axial_dispersion", "synthetic_verification")

# ledger states after the n gas and n surface states: entered, escaped, source
LEDGER_STATES = 3


# channel geometry and transport


@dataclass(frozen=True)
class Reactor1D:
    """channel length [m], cross-section [m²], reactive perimeter [m], u [m/s], D [m²/s] and cell count."""

    length: float
    area: float
    reactive_perimeter: float
    velocity: float
    diffusivity: float
    cells: int
    diffusivity_kind: str = "synthetic_verification"

    def __post_init__(self):
        """check every input but keep the values as given (not converted to float)."""
        for name in ("length", "area"):
            _positive(getattr(self, name), name)
        for name in ("reactive_perimeter", "diffusivity"):
            _nonnegative(getattr(self, name), name)
        _finite_scalar(self.velocity, "velocity")
        if isinstance(self.cells, bool) or not isinstance(self.cells, (int, np.integer)):
            raise ValueError("cells must be an integer >= 2")
        if self.cells < 2:
            raise ValueError("cells must be an integer >= 2")
        if self.diffusivity_kind not in DIFFUSIVITY_KINDS:
            raise ValueError("Identify diffusivity as molecular, axial_dispersion, or synthetic_verification")

    @property
    def dz(self):
        """cell width [m]."""
        return self.length / self.cells

    @property
    def z(self):
        """cell-centre positions [m]."""
        return (np.arange(self.cells) + 0.5) * self.dz


# boundary conditions


@dataclass(frozen=True)
class ConcentrationBoundary:
    """fixed end concentrations [mol/m³]. needs D > 0."""

    left: float
    right: float = 0.0

    def __post_init__(self):
        """require both concentrations to be finite and nonnegative."""
        _nonnegative(self.left, "left concentration")
        _nonnegative(self.right, "right concentration")


@dataclass(frozen=True)
class FluxBoundary:
    """total inlet flow [mol/s], zero diffusive gradient at the outlet, forward flow only."""

    inlet_molar_flow: float

    def __post_init__(self):
        """require the inlet flow to be finite and nonnegative."""
        _nonnegative(self.inlet_molar_flow, "inlet molar flow")


@dataclass(frozen=True)
class AdvectiveBoundary:
    """inflow concentration at the upstream end for pure advection (D = 0), nothing set downstream."""

    inlet_concentration: float

    def __post_init__(self):
        """require the inflow concentration to be finite and nonnegative."""
        _nonnegative(self.inlet_concentration, "inflow concentration")


Boundary = ConcentrationBoundary | FluxBoundary | AdvectiveBoundary


# recipe segment


@dataclass(frozen=True)
class TransportSegment:
    """one boundary condition held for duration [s]."""

    duration: float
    boundary: Boundary
    label: str = ""

    def __post_init__(self):
        """require a positive duration and a string label."""
        _positive(self.duration, "segment duration")
        if not isinstance(self.label, str):
            raise ValueError("Segment label must be a string")


# face fluxes


def _validate_boundary(reactor, boundary):
    """check that the boundary type fits the reactor's velocity and diffusivity."""
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
    """total flux [mol/(m² s)] on all N+1 faces. positive flux points right (downstream)."""
    _validate_boundary(reactor, boundary)
    c = np.asarray(c)
    if c.shape != (reactor.cells,):
        raise ValueError("One concentration is required per cell")
    u = reactor.velocity
    D = reactor.diffusivity
    dz = reactor.dz
    flux = np.empty(reactor.cells + 1)

    # interior faces: first-order upwind advection plus central diffusion
    if u >= 0:
        upstream = c[:-1]
    else:
        upstream = c[1:]
    flux[1:-1] = u * upstream - D * np.diff(c) / dz

    # boundary faces
    if isinstance(boundary, ConcentrationBoundary):
        # upwind value at each end, then diffusion over the half cell (dz/2)
        # between the boundary face and the first or last cell centre
        if u >= 0:
            left_upwind = boundary.left
            right_upwind = c[-1]
        else:
            left_upwind = c[0]
            right_upwind = boundary.right
        flux[0] = u * left_upwind - 2 * D * (c[0] - boundary.left) / dz
        flux[-1] = u * right_upwind - 2 * D * (boundary.right - c[-1]) / dz
    elif isinstance(boundary, FluxBoundary):
        flux[0] = boundary.inlet_molar_flow / reactor.area
        flux[-1] = u * c[-1]
    else:
        # advective boundary: inflow at whichever end is upstream
        if u > 0:
            left_upwind = boundary.inlet_concentration
            right_upwind = c[-1]
        else:
            left_upwind = c[0]
            right_upwind = boundary.inlet_concentration
        flux[0] = u * left_upwind
        flux[-1] = u * right_upwind
    return flux


def jacobian_sparsity(cells):
    """sparsity of the rhs jacobian: neighbour transport, local reaction, ledger tied to the end cells."""
    size = 2 * cells + LEDGER_STATES
    pattern = lil_matrix((size, size), dtype=int)
    for j in range(cells):
        # gas in cell j depends on its neighbours and on its own surface state
        first_neighbour = max(0, j - 1)
        after_last_neighbour = min(cells, j + 2)
        pattern[j, first_neighbour:after_last_neighbour] = 1
        pattern[j, cells + j] = 1
        # surface in cell j depends only on cell j
        pattern[cells + j, j] = 1
        pattern[cells + j, cells + j] = 1
    # entered and escaped totals depend only on the two end cells
    pattern[2 * cells:2 * cells + 2, 0] = 1
    pattern[2 * cells:2 * cells + 2, cells - 1] = 1
    return pattern.tocsr()


# channel solver


def solve_1d(reactor: Reactor1D, surface: FiniteCapacity, segments, *,
             concentration_scale: float, initial_c=0., initial_theta=0.,
             options=SolverOptions(), provenance_id="synthetic-unregistered",
             artificial_source: Callable | None = None, source_id: str | None = None,
             output_times=None):
    """solve exposure and purge segments in turn without resetting state.

    an optional manufactured source returns prescribed cell-average gas source
    [mol/m³/s] and theta source [1/s] at (t, z). it must not depend on the
    solver state. both parts are added to the source ledger.
    """
    # check inputs
    _positive(concentration_scale, "concentration scale")
    if not isinstance(provenance_id, str) or not provenance_id.strip():
        raise ValueError("provenance_id must be nonempty")
    if artificial_source is not None and not source_id:
        raise ValueError("Manufactured sources require an explicit source_id")
    segments = tuple(segments)
    for segment in segments:
        _validate_boundary(reactor, segment.boundary)

    # initial gas and surface in every cell
    n = reactor.cells
    c0 = np.broadcast_to(np.asarray(initial_c, dtype=float), (n,)).copy()
    theta0 = np.broadcast_to(np.asarray(initial_theta, dtype=float), (n,)).copy()
    if not np.all(np.isfinite(c0)) or np.any(c0 < 0):
        raise ValueError("Initial gas must be finite and nonnegative")
    if not np.all(np.isfinite(theta0)) or np.any((theta0 < 0) | (theta0 > 1)):
        raise ValueError("Initial theta must lie in [0,1]")

    # scaled states: c / c_scale per cell, theta per cell, then the
    # entered, escaped and source totals / (channel volume * c_scale)
    inventory_scale = reactor.area * reactor.length * concentration_scale
    _positive(inventory_scale, "inventory scale")
    area_ratio = reactor.reactive_perimeter / reactor.area
    initial = np.r_[c0 / concentration_scale, theta0, 0., 0., 0.]

    def rhs_factory(index):
        """return the rhs for recipe segment index, with its boundary held constant."""
        boundary = segments[index].boundary

        def rhs(t, y):
            """time derivatives of all scaled states."""
            c = y[:n] * concentration_scale
            theta = y[n:2*n]
            flux = face_fluxes(c, reactor, boundary)
            rate = surface.rate(c, theta)
            dc = -np.diff(flux) / reactor.dz - area_ratio * rate
            dtheta = rate / surface.capacity

            # optional manufactured source, also counted in the source ledger
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

            # the ledger reuses the pde's boundary fluxes. gas diffusing back out
            # of the inlet during purge counts as escaped, even though it leaves upstream.
            left_inflow = reactor.area * flux[0]
            right_inflow = -reactor.area * flux[-1]
            entering = max(left_inflow, 0.) + max(right_inflow, 0.)
            escaping = max(-left_inflow, 0.) + max(-right_inflow, 0.)
            return np.r_[dc / concentration_scale, dtheta, entering / inventory_scale,
                         escaping / inventory_scale, source_rate / inventory_scale]
        return rhs

    integrated = integrate_segments(initial, [s.duration for s in segments],
                                    rhs_factory, options, jacobian_sparsity(n), output_times)

    # metadata snapshot of the run
    segment_records = []
    for s in segments:
        segment_records.append(dict(duration=s.duration, label=s.label,
                                    boundary_type=type(s.boundary).__name__,
                                    boundary=asdict(s.boundary)))
    if np.isfinite(options.max_step):
        max_step_record = options.max_step
    else:
        max_step_record = "unbounded"
    if output_times is not None:
        output_times_record = np.asarray(output_times).tolist()
    else:
        output_times_record = "accepted steps"
    # upwind advection adds numerical diffusion of about |u| dz / 2
    numerical_diffusivity = abs(reactor.velocity)*reactor.dz/2
    if reactor.diffusivity > 0:
        numerical_diffusivity_ratio = abs(reactor.velocity)*reactor.dz/(2*reactor.diffusivity)
    else:
        numerical_diffusivity_ratio = None
    snapshot = dict(model="constant-coefficient single-half-cycle 1D",
                    reactor=asdict(reactor), surface=asdict(surface),
                    segments=segment_records,
                    concentration_scale=concentration_scale, inventory_scale=inventory_scale,
                    initial_c=c0.tolist(), initial_theta=theta0.tolist(),
                    solver=dict(method=options.method, rtol=options.rtol, atol=options.atol,
                                max_step=max_step_record),
                    provenance_id=provenance_id, artificial_source_id=source_id,
                    output_times=output_times_record,
                    numerical_diffusivity=numerical_diffusivity,
                    numerical_diffusivity_ratio=numerical_diffusivity_ratio)

    # unscale the states and build the result
    return assemble_result(integrated=integrated, c=integrated.y[:n].T*concentration_scale,
        theta=integrated.y[n:2*n].T, z=reactor.z,
        cell_volumes=np.full(n, reactor.area*reactor.dz),
        cell_areas=np.full(n, reactor.reactive_perimeter*reactor.dz),
        capacity=surface.capacity, initial_c=c0, initial_theta=theta0,
        entered_moles=integrated.y[2*n]*inventory_scale,
        escaped_moles=integrated.y[2*n+1]*inventory_scale,
        source_moles=integrated.y[2*n+2]*inventory_scale, metadata=snapshot)
