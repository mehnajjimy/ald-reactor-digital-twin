"""Conservative well-mixed single-half-cycle reactor with piecewise delivery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

from .numerics import SolverOptions, integrate_segments
from .results import SimulationResult, assemble_result
from .surface import FiniteCapacity
from .units import _finite_scalar, _nonnegative, _positive


@dataclass(frozen=True, slots=True)
class WellMixedReactor:
    """Constant volume [m³], reactive area [m²], and actual throughput [m³/s]."""

    volume: float
    reactive_area: float
    throughput: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "volume", _positive(self.volume, "volume [m³]"))
        object.__setattr__(
            self, "reactive_area", _nonnegative(self.reactive_area, "reactive_area [m²]")
        )
        object.__setattr__(
            self, "throughput", _nonnegative(self.throughput, "throughput [m³/s]")
        )


@dataclass(frozen=True, slots=True)
class FlowSegment:
    """A constant nonnegative precursor inlet [mol/s] held for duration [s]."""

    duration: float
    inlet_molar_flow: float
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "duration", _positive(self.duration, "duration [s]"))
        object.__setattr__(
            self,
            "inlet_molar_flow",
            _nonnegative(self.inlet_molar_flow, "inlet_molar_flow [mol/s]"),
        )
        if not isinstance(self.label, str):
            raise ValueError("segment label must be a string")


def solve_0d(
    reactor: WellMixedReactor,
    surface: FiniteCapacity,
    segments: Sequence[FlowSegment],
    *,
    concentration_scale: float,
    initial_c: float = 0.0,
    initial_theta: float = 0.0,
    options: SolverOptions = SolverOptions(),
    provenance_id: str = "synthetic-unregistered",
    output_times=None,
) -> SimulationResult:
    """Integrate V dc/dt = F_in - Qc - A_r r and Gamma dtheta/dt = r.

    All dimensional arguments use SI. Concentration and cumulative boundary
    inventories are scaled by c_scale and V*c_scale before time integration.
    Recipe switches carry every state forward, including gas and surface state.
    """
    if not isinstance(reactor, WellMixedReactor):
        raise TypeError("reactor must be a WellMixedReactor")
    if not isinstance(surface, FiniteCapacity):
        raise TypeError("surface must be a FiniteCapacity")
    if not isinstance(options, SolverOptions):
        raise TypeError("options must be SolverOptions")
    segments = tuple(segments)
    if not segments or not all(isinstance(segment, FlowSegment) for segment in segments):
        raise ValueError("segments must contain at least one FlowSegment")
    if not isinstance(provenance_id, str) or not provenance_id.strip():
        raise ValueError("provenance_id must be a nonempty string")
    concentration_scale = _positive(concentration_scale, "concentration_scale [mol/m³]")
    initial_c = _nonnegative(initial_c, "initial_c [mol/m³]")
    initial_theta = _finite_scalar(initial_theta, "initial_theta")
    if not 0 <= initial_theta <= 1:
        raise ValueError("initial_theta must be in [0, 1]")
    inventory_scale = reactor.volume * concentration_scale
    if not np.isfinite(inventory_scale) or inventory_scale <= 0:
        raise ValueError("volume * concentration_scale must be finite and positive")
    initial = np.array([initial_c / concentration_scale, initial_theta, 0.0, 0.0])

    def rhs_factory(index: int):
        inlet = segments[index].inlet_molar_flow

        def rhs(_time: float, state: NDArray[np.float64]) -> NDArray[np.float64]:
            concentration = concentration_scale * state[0]
            rate = surface.rate(concentration, state[1])
            outlet = reactor.throughput * concentration
            # Reuse the actual inlet/outlet fluxes so conservation error measures
            # integration, rather than independent quadrature or bookkeeping.
            return np.array(
                [
                    (inlet - outlet - reactor.reactive_area * rate) / inventory_scale,
                    rate / surface.capacity,
                    (inlet + max(-outlet, 0.0)) / inventory_scale,
                    max(outlet, 0.0) / inventory_scale,
                ]
            )

        return rhs

    sparsity = np.array(
        [[True, True, False, False], [True, True, False, False],
         [True, False, False, False], [True, False, False, False]]
    )
    integrated = integrate_segments(
        initial,
        [segment.duration for segment in segments],
        rhs_factory,
        options,
        jac_sparsity=sparsity,
        output_times=output_times,
    )
    solver_settings = asdict(options)
    if np.isinf(options.max_step):
        solver_settings["max_step"] = "unbounded"
    metadata = {
        "model": "well_mixed_0d",
        "provenance_id": provenance_id,
        "reactor": asdict(reactor),
        "surface": asdict(surface),
        "recipe": [asdict(segment) for segment in segments],
        "initial_state": {"c": initial_c, "theta": initial_theta},
        "concentration_scale_mol_m3": concentration_scale,
        "inventory_scale_moles": inventory_scale,
        "solver_options": solver_settings,
        "output_times": np.asarray(output_times).tolist() if output_times is not None else "accepted steps",
    }
    return assemble_result(
        integrated=integrated,
        c=(concentration_scale * integrated.y[0])[:, None],
        theta=integrated.y[1, :, None],
        z=np.array([0.0]),
        cell_volumes=np.array([reactor.volume]),
        cell_areas=np.array([reactor.reactive_area]),
        capacity=surface.capacity,
        initial_c=np.array([initial_c]),
        initial_theta=np.array([initial_theta]),
        entered_moles=inventory_scale * integrated.y[2],
        escaped_moles=inventory_scale * integrated.y[3],
        metadata=metadata,
    )
