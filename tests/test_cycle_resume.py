"""A saved cycle may be reused only with its original grid and accounting."""

import json
from pathlib import Path

import numpy as np
import pytest

from ald_twin.cycle_study import case_parameters, channel_grid, recipe, study_options
from ald_twin.cycles import periodic_cycle


def test_saved_cycle_reloads_exactly_and_detects_changed_inventory(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/"scripts"))
    from check_phase45_grid import load_result
    config = json.loads((root/"config/synthetic/phase45.json").read_text())
    parameters, chemistry = case_parameters(config, 2., 3.)
    segments = recipe(parameters, 1.5)
    original = periodic_cycle(channel_grid(parameters, 1), chemistry, segments,
                              fraction_scale=config["fraction_scale"], options=study_options(segments))
    stem = tmp_path/"cycle"
    original.save(stem)
    restored = load_result(stem)
    np.testing.assert_array_equal(restored.integrated.y, original.integrated.y)
    np.testing.assert_array_equal(restored.initial_state, original.initial_state)
    assert restored.checks() == original.checks()
    continued = periodic_cycle(restored.grid, chemistry, segments, fraction_scale=config["fraction_scale"],
                               options=study_options(segments), state=restored.integrated.y[:, -1],
                               accounting_origin=restored.initial_state)
    np.testing.assert_array_equal(continued.initial_state, original.initial_state)
    assert continued.checks()["relative_ledger"] < 1e-8
    assert continued.integrated.y[-4, -1] > restored.integrated.y[-4, -1]
    with np.load(str(stem)+".npz") as raw:
        arrays = dict(raw)
    arrays["carrier_moles"] *= 2
    np.savez_compressed(str(stem)+".npz", **arrays)
    with pytest.raises(AssertionError):
        load_result(stem)
