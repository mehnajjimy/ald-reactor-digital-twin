"""process study runs: cli agreement, resume and the html report."""

import json
import os
import subprocess
import sys

import pytest

from ald_twin.process_runner import DEFAULT_BASE, DEFAULT_PLAN, run_study
from ald_twin.process_study import evaluate_case
from ald_twin.process_report import build_report


def tiny_plan(tmp_path):
    """the packaged plan cut to one recipe and one scenario with near-mixed transport."""
    plan = json.loads(DEFAULT_PLAN.read_text())
    plan.update(peclet=.002, spatial_grids=[80, 160], selection_grid_ceiling=320,
                a_pulse_ratios=[3.], purge_ratios=[5.], scenarios=plan["scenarios"][:1])
    path = tmp_path/"plan.json"
    path.write_text(json.dumps(plan))
    return path, plan


def test_cli_case_matches_the_direct_api(tmp_path):
    """catches the cli case command solving a different problem from the api."""
    path, plan = tiny_plan(tmp_path)
    base = json.loads(DEFAULT_BASE.read_text())
    direct = evaluate_case(base, plan, 3., 5., plan["scenarios"][0], tmp_path/"direct")
    result = subprocess.run([sys.executable, "-m", "ald_twin.cli", "case", "--plan", str(path),
                             "--pulse", "3", "--purge", "5", "--output", str(tmp_path/"cli")],
                            text=True, capture_output=True, env=os.environ, check=True)
    saved = json.loads((tmp_path/"cli/case.json").read_text())
    assert result.stdout.strip() == "PASS"
    assert saved["models"] == direct["models"]
    assert saved["profile"] == direct["profile"]


def test_finished_study_resumes_without_solving_and_rejects_changed_records(tmp_path, monkeypatch):
    """catches a resume that recomputes, a report that drifts, or an edited case being trusted."""
    path, plan = tiny_plan(tmp_path)
    folder = tmp_path/"study"
    first = run_study(folder, path)
    assert first["status"] == "PASS"
    assert first["selections"]["nominal"]["status"] == "PASS"

    def unexpected(*args, **kwargs):
        """fail as soon as a trial is solved again."""
        raise AssertionError("A completed trial was recomputed")

    monkeypatch.setattr("ald_twin.process_runner.evaluate_case", unexpected)
    resumed = run_study(folder, path, resume=True)
    assert resumed["cases"] == first["cases"]
    assert resumed["selections"] == first["selections"]

    # the report carries the same numbers into its summary and html page
    build_report(folder, tmp_path/"report")
    summary = json.loads((tmp_path/"report/summary.json").read_text())
    assert summary["verified_pairs"] == 1
    assert summary["selections"] == first["selections"]
    html = (tmp_path/"report/index.html").read_text()
    payload = html.split('<script id="study-data" type="application/json">')[1].split('</script>')[0]
    view = json.loads(payload)
    assert view["cases"][0]["models"] == first["cases"][0]["models"]
    assert view["cases"][0]["state"] == "pass"

    # an edited case record stops the resume
    case = next((folder/"cases").glob("*/case.json"))
    case.write_text(case.read_text()+"\n")
    with pytest.raises(ValueError, match="record changed"):
        run_study(folder, path, resume=True)
