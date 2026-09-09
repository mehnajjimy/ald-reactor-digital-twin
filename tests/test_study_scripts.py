"""Protect the verification runner's reuse and diagnostic checks."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def phase2():
    path = Path(__file__).resolve().parents[1] / "scripts/verify_phase2.py"
    spec = importlib.util.spec_from_file_location("phase2_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cached_case(tmp_path, phase2):
    stem = tmp_path / "case"
    np.savez(tmp_path / "case.npz", xi=[0.25, 0.75])
    (tmp_path / "case.json").write_text('{"source": "synthetic"}')
    summary = dict(cache_key="original", artifact_sha256={
        name: phase2.sha(tmp_path / name) for name in ("case.npz", "case.json")})
    (tmp_path / "case-metrics.json").write_text(json.dumps(summary))
    return stem


def test_reuse_requires_matching_configuration(tmp_path, phase2, cached_case):
    assert phase2.load_cached_case(tmp_path / "missing", "original") is None
    assert phase2.load_cached_case(cached_case, "changed-inputs") is None
    arrays, summary = phase2.load_cached_case(cached_case, "original")
    np.testing.assert_array_equal(arrays["xi"], [0.25, 0.75])
    assert summary["cache_key"] == "original"


@pytest.mark.parametrize("filename", ["case.npz", "case.json"])
def test_reuse_rejects_changed_artifacts(phase2, cached_case, filename):
    (cached_case.parent / filename).write_bytes(b"changed after the recorded run")
    with pytest.raises(ValueError, match="Cached artifact changed"):
        phase2.load_cached_case(cached_case, "original")


def test_metrics_keep_zero_inventory_and_state_violations_visible(phase2):
    arrays = dict(
        xi=np.array([0.25, 0.75]), theta=np.array([[0., 0.], [0.75, 0.25]]),
        x=np.array([[-0.1, 0.], [0.5, 0.2]]), entered=np.array([0., 1.]),
        ledger_error=np.array([0.125, 0.0625]), captured=np.array([0., 0.25]),
        escaped=np.array([0., 0.25]), gas=np.array([0., 0.5]),
    )
    status = [{"end_state": [0.], "nfev": 2}, {"start_state": [1.], "nfev": 3}]
    metrics = phase2.case_metrics(arrays, status)
    assert metrics["zero_inventory_residual"] == 0.125
    assert metrics["ledger_relative"] == 0.0625
    assert metrics["bound_violation"] == 0.1
    assert not metrics["state_carryover_exact"]
    assert metrics["front_final"] == 0.5
    assert metrics["solver_nfev"] == 5
