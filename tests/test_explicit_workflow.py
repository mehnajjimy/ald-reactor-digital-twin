"""process workflow: the temperature gate and the original ZnO study."""

import json

import numpy as np
import pytest

from ald_twin.process_inputs import input_issues, load_process
from ald_twin.process_runner import DEFAULT_BASE, DEFAULT_PLAN
from ald_twin.process_study import evaluate_case
from ald_twin.workflow import run_process


def fast_inputs(process):
    """packaged inputs with near-mixed transport and small grids, to keep runs quick."""
    data = load_process(process)
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000
    data["spatial_grids"] = [80, 160]
    return data


def test_rejected_inputs_create_no_output_folder(tmp_path):
    """catches unsupported physics being run, or a rejected run leaving files behind."""
    changes = [
        lambda d: d.update(kind="experimental"),
        lambda d: d["diffusivity"]["a"].update(kind="physical"),
        lambda d: d["channel"].update(temperature=473.15),
        lambda d: d["units"].update({"channel.length": "cm"}),
        lambda d: d["provenance"].pop("chemistry"),
        lambda d: d.update(spatial_grids=[320, 640, 5120]),
        lambda d: d.update(film=load_process("synthetic-zno")["film"]),
    ]
    for change in changes:
        data = load_process("synthetic-ab")
        change(data)
        assert input_issues(data)
        with pytest.raises(ValueError):
            run_process(data, tmp_path/"rejected")
        assert not (tmp_path/"rejected").exists()

    # a hotter channel is refused for its temperature, not only for its diffusivity
    data = load_process("synthetic-ab")
    data["channel"]["temperature"] = 473.15
    assert "This input path is limited to 423.15 K; no temperature kinetics are defined" in input_issues(data)


def test_explicit_zno_inputs_reproduce_the_original_study(tmp_path):
    """catches the explicit input path giving different numbers from the study path."""
    base = json.loads(DEFAULT_BASE.read_text())
    plan = json.loads(DEFAULT_PLAN.read_text())
    plan.update(peclet=.002, spatial_grids=[80, 160], selection_grid_ceiling=320,
                a_pulse_ratios=[3.], purge_ratios=[5.], scenarios=plan["scenarios"][:1])
    old = evaluate_case(base, plan, 3., 5., plan["scenarios"][0], tmp_path/"original")
    current = run_process(fast_inputs("synthetic-zno"), tmp_path/"explicit")
    assert old["status"] == current["status"] == "PASS"
    assert old["accepted_cells"] == current["accepted_cells"]
    for name in ("mixed", "spatial"):
        assert old["models"][name]["feasible"] == current["models"][name]["feasible"]
        for key, value in old["models"][name]["metrics"].items():
            if key in current["models"][name]["metrics"]:
                np.testing.assert_allclose(current["models"][name]["metrics"][key], value, rtol=1e-10, atol=1e-12)
