"""well-mixed and spatial models compared on the same reactor and dose."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from ald_twin.numerics import SolverOptions


def load_comparison():
    """import scripts/compare_fidelity.py as a module."""
    path = Path(__file__).resolve().parents[1] / "scripts/compare_fidelity.py"
    spec = importlib.util.spec_from_file_location("fidelity_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matched_models_share_geometry_dose_and_inventory():
    """catches the two models being compared on different reactors or doses."""
    # a 3 m by 2 m² channel: volume 6 m³, reactive area 4*3 = 12 m², throughput 2*0.25 = 0.5 m³/s
    parameters = dict(length=3., area=2., reactive_perimeter=4., velocity=0.25,
        diffusivity=0.1, capacity=0.2, capture_velocity=0.04,
        concentration_scale=1., initial_c=0.1, initial_theta=0.25,
        purge_duration=0.05, inlet_molar_flow=0.08)
    lumped, spatial = load_comparison().run_pair(parameters, 0.1, 20, SolverOptions())
    assert lumped.metadata["reactor"] == dict(volume=6., reactive_area=12., throughput=0.5)
    assert spatial.metadata["segments"][0]["boundary_type"] == "FluxBoundary"
    np.testing.assert_array_equal(lumped.t, spatial.t)

    # both start with 6*0.1 = 0.6 mol gas, receive 0.08*0.1 = 0.008 mol and lose none
    for result in [lumped, spatial]:
        assert result.metadata["initial_gas_moles"] == pytest.approx(0.6)
        assert result.entered_moles[-1] == pytest.approx(0.008, abs=1e-12)
        total = result.gas_moles[-1] + result.captured_moles[-1] + result.escaped_moles[-1]
        assert total == pytest.approx(0.608, abs=1e-10)
        assert result.solver_status[0]["end_state"] == result.solver_status[1]["start_state"]
