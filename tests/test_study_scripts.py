"""verification runner metrics keep problems visible."""

import importlib.util
from pathlib import Path

import numpy as np


def load_phase2():
    """import scripts/verify_phase2.py as a module."""
    path = Path(__file__).resolve().parents[1] / "scripts/verify_phase2.py"
    spec = importlib.util.spec_from_file_location("phase2_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_case_metrics_keep_zero_inventory_and_bound_violations_visible():
    """catches a ledger error hidden at zero inventory or a negative state that is ignored."""
    arrays = dict(
        xi=np.array([0.25, 0.75]), theta=np.array([[0., 0.], [0.75, 0.25]]),
        x=np.array([[-0.1, 0.], [0.5, 0.2]]), entered=np.array([0., 1.]),
        ledger_error=np.array([0.125, 0.0625]), captured=np.array([0., 0.25]),
        escaped=np.array([0., 0.25]), gas=np.array([0., 0.5]),
    )
    status = [{"end_state": [0.], "nfev": 2}, {"start_state": [1.], "nfev": 3}]
    metrics = load_phase2().case_metrics(arrays, status)
    # the first row has no inventory, so its 0.125 error is reported on its own
    assert metrics["zero_inventory_residual"] == 0.125
    assert metrics["ledger_relative"] == 0.0625
    assert metrics["bound_violation"] == 0.1
    assert not metrics["state_carryover_exact"]
    # theta falls through 0.5 halfway between xi = 0.25 and 0.75
    assert metrics["front_final"] == 0.5
    assert metrics["solver_nfev"] == 5
