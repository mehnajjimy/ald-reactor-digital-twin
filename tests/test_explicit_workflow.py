"""exercise scientific gates, unchanged results, cli agreement and saved reads."""

import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from ald_twin.process_inputs import input_issues, inspect_process, load_process
from ald_twin.process_runner import DEFAULT_BASE, DEFAULT_PLAN, digest
from ald_twin.process_study import evaluate_case
from ald_twin.workflow import compare_runs, read_run, run_process, write_report


@pytest.mark.parametrize("process", ["synthetic-zno", "synthetic-ab"])
def test_packaged_inputs_are_explicit_and_inspection_does_not_solve(process, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Inspection started a solve")
    monkeypatch.setattr("ald_twin.workflow.periodic_cycle", unexpected)
    data = load_process(process)
    report = inspect_process(data)
    assert report["runnable"]
    assert report["physical_fit_ready"] is False
    assert report["flow"]["residence_s"] > 0
    assert report["flow"]["pressure_pa"][0] > report["flow"]["pressure_pa"][1]


@pytest.mark.parametrize("change", [
    lambda d: d.update(kind="experimental"),
    lambda d: d.update(physical_fit_ready=True),
    lambda d: d["diffusivity"]["a"].update(value=None),
    lambda d: d["diffusivity"]["a"].update(kind="physical"),
    lambda d: d["channel"].update(temperature=473.15),
    lambda d: d["chemistry"].update(capacity=None),
    lambda d: d["recipe"].update(a_pulse=0),
    lambda d: d["recipe"].update(a_pulse=float("nan")),
    lambda d: d.update(spatial_grids=[320, 640, 5120]),
    lambda d: d["units"].update({"channel.length": "cm"}),
    lambda d: d["provenance"].pop("chemistry"),
    lambda d: d.update(model="two-site-reversible"),
    lambda d: d.pop("reactive_interval"),
    lambda d: d.update(diffusivity=None),
    lambda d: d.update(temperature=423.15),
    lambda d: d.update(schema_version=True),
    lambda d: d.update(schema_version=1.0),
    lambda d: d["diffusivity"]["a"].update(temperature_exponent=2),
    lambda d: d["diffusivity"]["b"].update(source=123),
    lambda d: d["diffusivity"]["a"].update(source=" "),
    lambda d: d["diffusivity"]["b"].update(source_type="experimental"),
    lambda d: d.update(reactive_interval=[False, .05]),
    lambda d: d.update(reactive_interval={"start": 0, "end": .05}),
    lambda d: d["diffusivity"]["a"].update(uncertainty=float("nan")),
    lambda d: d["provenance"]["channel"].update(uncertainty=float("inf")),
    lambda d: d["channel"].update(outlet_pressure=1e300),
])
def test_invalid_or_unsupported_inputs_fail_before_creating_output(tmp_path, change):
    data = load_process("synthetic-ab")
    change(data)
    assert input_issues(data)
    with pytest.raises(ValueError):
        run_process(data, tmp_path/"rejected")
    assert not (tmp_path/"rejected").exists()


def test_missing_film_is_explicit_and_zno_mapping_cannot_transfer():
    data = load_process("synthetic-ab")
    assert data["film"] is None
    assert "turnover only" in inspect_process(data)["film_status"]
    data["film"] = load_process("synthetic-zno")["film"]
    assert any("cannot be transferred" in issue for issue in input_issues(data))


@pytest.fixture(scope="module")
def small_run(tmp_path_factory):
    folder = tmp_path_factory.mktemp("explicit-run")
    data = load_process("synthetic-ab")
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000  # near-mixed transport keeps this interface test small
    data["spatial_grids"] = [80, 160]
    stages = []
    def progress(row):
        stages.append(row["stage"])
        if row["stage"] == "Complete":
            assert read_run(folder/"api")["models"] == row["models"]
    result = run_process(data, folder/"api", progress=progress)
    assert result["status"] == "PASS", result.get("reason")
    return folder, data, result, stages


def test_cli_matches_api_and_unknown_film_stays_unavailable(small_run):
    folder, data, direct, stages = small_run
    path = folder/"example.json"
    path.write_text(json.dumps(data))
    child = subprocess.run([sys.executable, "-m", "ald_twin.cli", "simulate", str(path),
                            "--output", str(folder/"cli")], capture_output=True, text=True, check=True)
    saved = read_run(folder/"cli")
    assert json.loads(child.stdout)["models"] == direct["models"] == saved["models"]
    assert saved["profile"] == direct["profile"]
    assert saved["origin"] == "saved output"
    assert saved["models"]["spatial"]["metrics"]["mean_gpc_angstrom"] is None
    assert stages[0].startswith("Inputs validated") and stages[-1] == "Complete"
    assert any("time-repeat" in stage for stage in stages)


@pytest.mark.parametrize("recipe", [None, [], "missing"])
def test_cli_recipe_override_reports_missing_input_without_traceback(tmp_path, recipe):
    data = load_process("synthetic-ab")
    data["recipe"] = recipe
    path = tmp_path/"invalid.json"
    path.write_text(json.dumps(data))
    child = subprocess.run([sys.executable, "-m", "ald_twin.cli", "simulate", str(path),
                            "--a-pulse", "4", "--output", str(tmp_path/"rejected")],
                           capture_output=True, text=True)
    assert child.returncode == 2
    assert "recipe must be an input object" in child.stderr
    assert "Traceback" not in child.stderr
    assert not (tmp_path/"rejected").exists()


def test_report_distinguishes_uncleared_zero_and_unavailable(small_run, tmp_path):

    # exercise the saved-report boundary without running another calculation.

    record = json.loads(json.dumps(small_run[2]))
    summary = record["models"]["spatial"]["metrics"]
    summary["purge_crossing_s"] = [None, 0.]
    path = tmp_path/"report.md"
    write_report(record, path)
    report = path.read_text()
    assert "| A purge clearance (s) | Not cleared |" in report
    assert "| B purge clearance (s) | 0 |" in report
    assert "| Mean equivalent ZnO growth (Å/cycle) | Unavailable |" in report
    assert "Minimum A completion (%)" in report
    assert "precursor_consumption_fraction" not in report


def test_saved_comparison_never_solves_and_rejects_changed_data(small_run, tmp_path, monkeypatch):
    folder, data, result, stages = small_run
    def unexpected(*args, **kwargs):
        raise AssertionError("A saved comparison recalculated")
    monkeypatch.setattr("ald_twin.workflow.periodic_cycle", unexpected)
    comparison = compare_runs([folder/"api"])
    assert comparison["runs"][0]["models"] == result["models"]
    with pytest.raises(FileExistsError):
        run_process(data, folder/"api")
    copied = tmp_path/"altered"
    shutil.copytree(folder/"api", copied)
    (copied/"run.json").write_text((copied/"run.json").read_text()+"\n")
    with pytest.raises(ValueError, match="Saved run changed"):
        read_run(copied)


@pytest.mark.parametrize("artifact", ["sources/workflow.py", "mixed.json", "mixed.npz"])
def test_saved_run_requires_recorded_evidence(small_run, tmp_path, artifact):
    copied = tmp_path/"missing-evidence"
    shutil.copytree(small_run[0]/"api", copied)
    manifest = json.loads((copied/"manifest.json").read_text())
    del manifest[artifact]
    (copied/artifact).unlink()
    (copied/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest is incomplete"):
        read_run(copied)


@pytest.mark.parametrize("artifact", ["inputs.json", "sources/workflow.py", "mixed.json"])
def test_rebuilt_manifest_cannot_relabel_saved_calculation(small_run, tmp_path, artifact):
    copied = tmp_path/"mismatched-evidence"
    shutil.copytree(small_run[0]/"api", copied)
    path = copied/artifact
    if artifact == "inputs.json":
        data = json.loads(path.read_text())
        data["recipe"]["b_pulse"] = 4
        path.write_text(json.dumps(data))
    elif artifact == "mixed.json":
        data = json.loads(path.read_text())
        data["grid"]["parameters"]["recipe"]["b_pulse"] = 4
        path.write_text(json.dumps(data))
    else:
        path.write_text(path.read_text()+"\n# A different source snapshot\n")
    manifest = json.loads((copied/"manifest.json").read_text())
    manifest[artifact] = digest(path)
    (copied/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="do not match"):
        read_run(copied)


@pytest.mark.parametrize("change", [
    {"numerical_acceptance": False},
    {"status": "RUNNING"},
    {"status": []},
    {"recipe_feasibility": []},
    {"recipe": {"a_pulse": 100}},
    {"process_name": "A different process"},
])
def test_saved_result_must_match_its_status_and_inputs(small_run, tmp_path, change):
    copied = tmp_path/"inconsistent-result"
    shutil.copytree(small_run[0]/"api", copied)
    path = copied/"run.json"
    record = json.loads(path.read_text())
    record.update(change)
    path.write_text(json.dumps(record))
    manifest = json.loads((copied/"manifest.json").read_text())
    manifest["run.json"] = digest(path)
    (copied/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_run(copied)


def test_explicit_zno_path_preserves_original_numerical_results(tmp_path):
    base = json.loads(DEFAULT_BASE.read_text())
    plan = json.loads(DEFAULT_PLAN.read_text())
    plan.update(peclet=.002, spatial_grids=[80,160], selection_grid_ceiling=320,
                a_pulse_ratios=[3.], purge_ratios=[5.], scenarios=plan["scenarios"][:1])
    old = evaluate_case(base, plan, 3., 5., plan["scenarios"][0], tmp_path/"original")
    data = load_process("synthetic-zno")
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000
    data["spatial_grids"] = [80,160]
    current = run_process(data, tmp_path/"explicit")
    assert old["status"] == current["status"] == "PASS"
    assert old["accepted_cells"] == current["accepted_cells"]
    for name in ("mixed", "spatial"):
        assert old["models"][name]["feasible"] == current["models"][name]["feasible"]
        for key, value in old["models"][name]["metrics"].items():
            if key in current["models"][name]["metrics"]:
                np.testing.assert_allclose(current["models"][name]["metrics"][key], value, rtol=1e-10, atol=1e-12)


def test_spatial_failure_never_becomes_accepted(tmp_path):
    data = load_process("synthetic-ab")
    data["spatial_grids"] = [2,4]
    result = run_process(data, tmp_path/"failed")
    assert result["status"] == "UNVERIFIED"
    assert result["numerical_acceptance"] is False
    assert result["recipe_feasibility"] == "unverified"
    assert result["models"] == {}
    assert read_run(tmp_path/"failed")["status"] == "UNVERIFIED"
    assert len(result["attempts"]) == 3
