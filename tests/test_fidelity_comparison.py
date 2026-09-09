import importlib.util
from pathlib import Path

import numpy as np
import pytest

from ald_twin.numerics import SolverOptions


@pytest.fixture
def comparison():
    path = Path(__file__).resolve().parents[1] / "scripts/compare_fidelity.py"
    spec = importlib.util.spec_from_file_location("fidelity_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matched_models_share_geometry_dose_and_inventory(comparison):
    parameters = dict(length=3., area=2., reactive_perimeter=4., velocity=0.25,
        diffusivity=0.1, capacity=0.2, capture_velocity=0.04,
        concentration_scale=1., initial_c=0.1, initial_theta=0.25,
        purge_duration=0.05, inlet_molar_flow=0.08)
    lumped, spatial = comparison.run_pair(parameters, 0.1, 20, SolverOptions())
    assert lumped.metadata["reactor"] == dict(volume=6., reactive_area=12., throughput=0.5)
    assert spatial.metadata["segments"][0]["boundary_type"] == "FluxBoundary"
    np.testing.assert_array_equal(lumped.t, spatial.t)
    for result in [lumped, spatial]:
        assert result.metadata["initial_gas_moles"] == pytest.approx(0.6)
        assert result.entered_moles[-1] == pytest.approx(0.008, abs=1e-12)
        assert result.gas_moles[-1] + result.captured_moles[-1] + result.escaped_moles[-1] == pytest.approx(0.608, abs=1e-10)
        assert result.solver_status[0]["end_state"] == result.solver_status[1]["start_state"]


def test_threshold_inside_resolution_change_is_unresolved(comparison):
    assert comparison.completion_decision(0.895, 0.01) is None
    assert comparison.completion_decision(0.91, 0.001) is True
    assert comparison.completion_decision(0.89, 0.001) is False
