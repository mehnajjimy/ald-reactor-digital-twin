"""process workflow: input gates, cli and api agreement, saved runs and reports."""

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


def forbid_solving(monkeypatch):
    """make any call to the cycle solver fail the test."""
    def unexpected(*args, **kwargs):
        """fail as soon as a solve starts."""
        raise AssertionError("A solve was started")
    monkeypatch.setattr("ald_twin.workflow.periodic_cycle", unexpected)


def fast_inputs(process):
    """packaged inputs with near-mixed transport and small grids, to keep runs quick."""
    data = load_process(process)
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000
    data["spatial_grids"] = [80, 160]
    return data


def test_packaged_inputs_inspect_without_solving(monkeypatch):
    """catches a packaged input file that no longer loads or an inspection that solves."""
    forbid_solving(monkeypatch)
    for process in ("synthetic-zno", "synthetic-ab"):
        report = inspect_process(load_process(process))
        assert report["runnable"]
        assert report["physical_fit_ready"] is False
        assert report["flow"]["residence_s"] > 0
        assert report["flow"]["pressure_pa"][0] > report["flow"]["pressure_pa"][1]


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


@pytest.fixture(scope="module")
def small_run(tmp_path_factory):
    """one real synthetic-ab run through the api, with its progress stages."""
    folder = tmp_path_factory.mktemp("explicit-run")
    data = fast_inputs("synthetic-ab")
    stages = []

    def progress(row):
        """keep each stage and check the saved run once it completes."""
        stages.append(row["stage"])
        if row["stage"] == "Complete":
            assert read_run(folder/"api")["models"] == row["models"]

    result = run_process(data, folder/"api", progress=progress)
    assert result["status"] == "PASS", result.get("reason")
    return folder, data, result, stages


def test_cli_and_api_give_the_same_saved_run(small_run):
    """catches the cli and the api disagreeing, or an unknown film given a growth rate."""
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
    assert stages[0].startswith("Inputs validated")
    assert stages[-1] == "Complete"
    assert any("time-repeat" in stage for stage in stages)


def test_report_separates_not_cleared_zero_and_unavailable(small_run, tmp_path):
    """catches a purge that never cleared being shown as zero, or a made-up growth rate."""
    record = json.loads(json.dumps(small_run[2]))
    record["models"]["spatial"]["metrics"]["purge_crossing_s"] = [None, 0.]
    path = tmp_path/"report.md"
    write_report(record, path)
    report = path.read_text()
    assert "| A purge clearance (s) | Not cleared |" in report
    assert "| B purge clearance (s) | 0 |" in report
    assert "| Mean equivalent ZnO growth (Å/cycle) | Unavailable |" in report
    assert "Minimum A completion (%)" in report


def test_saved_runs_compare_without_solving_and_reject_tampering(small_run, tmp_path, monkeypatch):
    """catches a saved run being recalculated, overwritten or relabelled after the fact."""
    folder, data, result, stages = small_run
    forbid_solving(monkeypatch)
    assert compare_runs([folder/"api"])["runs"][0]["models"] == result["models"]
    with pytest.raises(FileExistsError):
        run_process(data, folder/"api")

    def copy_run(name):
        """copy the saved api run to a new folder."""
        copied = tmp_path/name
        shutil.copytree(folder/"api", copied)
        return copied

    def update_json(path, changes):
        """merge changes into a saved json record."""
        record = json.loads(path.read_text())
        record.update(changes)
        path.write_text(json.dumps(record))

    def rehash(copied, artifact):
        """record the new hash of one file in the manifest."""
        manifest = json.loads((copied/"manifest.json").read_text())
        manifest[artifact] = digest(copied/artifact)
        (copied/"manifest.json").write_text(json.dumps(manifest))

    # an edited record without a new manifest hash
    copied = copy_run("edited")
    (copied/"run.json").write_text((copied/"run.json").read_text()+"\n")
    with pytest.raises(ValueError, match="Saved run changed"):
        read_run(copied)

    # a result file removed from both the folder and the manifest
    copied = copy_run("missing")
    manifest = json.loads((copied/"manifest.json").read_text())
    del manifest["mixed.npz"]
    (copied/"manifest.json").write_text(json.dumps(manifest))
    (copied/"mixed.npz").unlink()
    with pytest.raises(ValueError, match="manifest is incomplete"):
        read_run(copied)

    # changed inputs or source code with a rebuilt manifest
    copied = copy_run("relabelled-inputs")
    inputs = json.loads((copied/"inputs.json").read_text())
    inputs["recipe"]["b_pulse"] = 4
    (copied/"inputs.json").write_text(json.dumps(inputs))
    rehash(copied, "inputs.json")
    with pytest.raises(ValueError, match="do not match"):
        read_run(copied)
    copied = copy_run("relabelled-source")
    (copied/"sources/workflow.py").write_text("# a different source snapshot\n")
    rehash(copied, "sources/workflow.py")
    with pytest.raises(ValueError, match="do not match"):
        read_run(copied)

    # a status or recipe that does not match the saved calculation
    for number, changes in enumerate([{"status": "RUNNING"}, {"recipe": {"a_pulse": 100}}]):
        copied = copy_run(f"inconsistent-{number}")
        update_json(copied/"run.json", changes)
        rehash(copied, "run.json")
        with pytest.raises(ValueError):
            read_run(copied)


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


def test_unresolved_spatial_grid_is_saved_as_unverified(tmp_path):
    """catches a spatial run that never converged being reported as accepted."""
    data = load_process("synthetic-ab")
    data["spatial_grids"] = [2, 4]
    result = run_process(data, tmp_path/"failed")
    assert result["status"] == "UNVERIFIED"
    assert result["numerical_acceptance"] is False
    assert result["recipe_feasibility"] == "unverified"
    assert result["models"] == {}
    assert len(result["attempts"]) == 3
    assert read_run(tmp_path/"failed")["status"] == "UNVERIFIED"
