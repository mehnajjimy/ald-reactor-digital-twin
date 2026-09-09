from copy import deepcopy
import json
from pathlib import Path

import pytest

from ald_twin.process_runner import finish_selection
from ald_twin.process_study import (feasibility, pareto_candidates, scenario_envelope,
                                    trial_inputs, validate_plan)

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    return (json.loads((ROOT/"config/synthetic/phase45.json").read_text()),
            json.loads((ROOT/"config/synthetic/process-study.json").read_text()))


def row(name, value, feasible=True):
    metrics = {key: value for key in ("mean_gpc_angstrom", "minimum_a_completion",
                 "maximum_b_remaining", "purge_a_residual", "purge_b_residual", "relative_gpc_spread")}
    metrics["purge_crossing_s"] = [value, None]
    return dict(recipe="test", scenario={"name": name}, status="PASS",
                wall_screen={"passes_declared_screen": True},
                models={"spatial": dict(feasible=feasible, metrics=metrics)},
                objectives={"cycle_time_s": 1., "precursor_moles": 1.})


def test_diffusivity_scenario_does_not_refit_chemistry_or_water_transport():
    base, plan = inputs()
    before = deepcopy(base)
    reference = trial_inputs(base, plan, 3., 5., plan["scenarios"][0])
    changed = trial_inputs(base, plan, 3., 5., plan["scenarios"][5])
    assert changed[1:] == reference[1:]
    assert changed[0]["diffusivity"]["a"]["value"] == .8*reference[0]["diffusivity"]["a"]["value"]
    assert changed[0]["diffusivity"]["b"] == reference[0]["diffusivity"]["b"]
    assert base == before


@pytest.mark.parametrize("field,value", [("kind", "physical"), ("physical_dez_diffusivity", .1),
                                        ("physical_fit_ready", True), ("periodic_tolerance", .01)])
def test_physical_or_weakened_configuration_is_rejected(field, value):
    _, plan = inputs()
    plan[field] = value
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_incomplete_duplicate_and_failed_scenarios_cannot_pass():
    a, b = row("a", 1.), row("b", 2.)
    assert feasibility([a, b], 2) == "pass"
    assert feasibility([a], 2) == "unverified"
    assert feasibility([a, a], 2) == "unverified"
    b["status"] = "UNVERIFIED"
    assert feasibility([a, b], 2) == "unverified"
    assert scenario_envelope([a, b], 2) == dict(complete=False, ranges={},
                        interpretation="Range over the declared finite scenarios; not a confidence interval")


def test_finite_scenario_envelope_and_undefined_clearance():
    envelope = scenario_envelope([row("a", 3.), row("b", 1.)], 2)
    assert envelope["complete"]
    assert envelope["ranges"]["mean_gpc_angstrom"] == [1., 3.]
    assert envelope["ranges"]["a_clearance_s"] == [1., 3.]
    assert envelope["ranges"]["b_clearance_s"] is None


def test_pareto_keeps_ties_and_does_not_hide_unknown_competitors():
    candidates = [dict(recipe=name, state=state, objectives=dict(cycle_time_s=t, precursor_moles=d))
                  for name, state, t, d in [("fast", "pass", 1, 3), ("lean", "pass", 3, 1),
                        ("tie", "pass", 1, 3), ("dominated", "pass", 4, 4), ("unknown", "unverified", 2, 2)]]
    result = pareto_candidates(candidates, "state")
    assert set(result["candidates"]) == {"fast", "lean", "tie"}
    assert not result["complete"]
    assert result["unresolved_competitors"] == ["unknown"]
    candidates[-1]["objectives"] = dict(cycle_time_s=5, precursor_moles=5)
    assert pareto_candidates(candidates, "state")["complete"]


def test_failed_refinement_withdraws_selection_without_falling_back():
    front = dict(complete=True, candidates=["test"])
    assert finish_selection(front, [row("reference", 1., False)], 1)["selected"] is None
    assert finish_selection(front, [row("reference", 1., False)], 1)["status"] == "UNVERIFIED_SELECTION"
    assert finish_selection(dict(complete=True, candidates=[]), [], 1)["status"] == "NO_FEASIBLE_CANDIDATE"
