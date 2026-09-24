"""process study: scenarios, feasibility, envelopes and pareto selection."""

from copy import deepcopy
import json
from pathlib import Path

from ald_twin.process_runner import finish_selection
from ald_twin.process_study import feasibility, pareto_candidates, scenario_envelope, trial_inputs

ROOT = Path(__file__).resolve().parents[1]


def row(name, value, feasible=True):
    """a passing scenario result where every metric equals value."""
    names = ("mean_gpc_angstrom", "minimum_a_completion", "maximum_b_remaining",
             "purge_a_residual", "purge_b_residual", "relative_gpc_spread")
    metrics = {key: value for key in names}
    metrics["purge_crossing_s"] = [value, None]
    return dict(recipe="test", scenario={"name": name}, status="PASS",
                wall_screen={"passes_declared_screen": True},
                models={"spatial": dict(feasible=feasible, metrics=metrics)},
                objectives={"cycle_time_s": 1., "precursor_moles": 1.})


def test_diffusivity_scenario_changes_only_the_dez_diffusivity():
    """catches a scenario that also refits chemistry, water transport or the base inputs."""
    base = json.loads((ROOT/"config/synthetic/phase45.json").read_text())
    plan = json.loads((ROOT/"config/synthetic/process-study.json").read_text())
    before = deepcopy(base)
    reference = trial_inputs(base, plan, 3., 5., plan["scenarios"][0])
    changed = trial_inputs(base, plan, 3., 5., plan["scenarios"][5])
    assert changed[1:] == reference[1:]
    assert changed[0]["diffusivity"]["a"]["value"] == .8*reference[0]["diffusivity"]["a"]["value"]
    assert changed[0]["diffusivity"]["b"] == reference[0]["diffusivity"]["b"]
    assert base == before


def test_only_complete_passing_scenarios_give_a_pass_and_an_envelope():
    """catches missing, repeated or failed scenarios counting towards a pass."""
    a, b = row("a", 1.), row("b", 2.)
    assert feasibility([a, b], 2) == "pass"
    assert feasibility([a], 2) == "unverified"
    assert feasibility([a, a], 2) == "unverified"

    # the envelope is the min and max over scenarios, and a purge that never clears has none
    envelope = scenario_envelope([row("a", 3.), row("b", 1.)], 2)
    assert envelope["complete"]
    assert envelope["ranges"]["mean_gpc_angstrom"] == [1., 3.]
    assert envelope["ranges"]["a_clearance_s"] == [1., 3.]
    assert envelope["ranges"]["b_clearance_s"] is None

    b["status"] = "UNVERIFIED"
    assert feasibility([a, b], 2) == "unverified"
    assert scenario_envelope([a, b], 2)["complete"] is False
    assert scenario_envelope([a, b], 2)["ranges"] == {}


def test_pareto_keeps_ties_and_withdraws_a_failed_selection():
    """catches a hidden unknown competitor or a fallback to a failed recipe."""
    # fast and lean trade off, tie equals fast, dominated loses on both
    candidates = []
    for name, state, time, dose in [("fast", "pass", 1, 3), ("lean", "pass", 3, 1),
                                    ("tie", "pass", 1, 3), ("dominated", "pass", 4, 4),
                                    ("unknown", "unverified", 2, 2)]:
        candidates.append(dict(recipe=name, state=state,
                               objectives=dict(cycle_time_s=time, precursor_moles=dose)))
    result = pareto_candidates(candidates, "state")
    assert set(result["candidates"]) == {"fast", "lean", "tie"}
    assert not result["complete"]
    assert result["unresolved_competitors"] == ["unknown"]
    candidates[-1]["objectives"] = dict(cycle_time_s=5, precursor_moles=5)
    assert pareto_candidates(candidates, "state")["complete"]

    # a front whose refinement fails selects nothing
    front = dict(complete=True, candidates=["test"])
    selection = finish_selection(front, [row("reference", 1., False)], 1)
    assert selection["selected"] is None
    assert selection["status"] == "UNVERIFIED_SELECTION"
    assert finish_selection(dict(complete=True, candidates=[]), [], 1)["status"] == "NO_FEASIBLE_CANDIDATE"
