"""verify the local gui boundary, real worker results and retained failures."""

from http.client import HTTPConnection
import json
from pathlib import Path
import signal
import threading
import time

import pytest

from ald_twin.gui import Workspace, create_server
from ald_twin import gui
from ald_twin.process_inputs import load_process
from ald_twin.process_study import write_json
from ald_twin.workflow import read_run


@pytest.fixture
def server(tmp_path):
    server = create_server(tmp_path/"runs", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.workspace.close()
    server.server_close()
    thread.join(timeout=5)


def request(server, path, data=None, **headers):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    defaults = {"X-Workspace-Token":server.token, "Content-Type":"application/json"}
    defaults.update(headers)
    connection.request("GET" if data is None else "POST", path,
                       body=None if data is None else json.dumps(data), headers=defaults)
    response = connection.getresponse()
    body = response.read()
    content_type = response.getheader("Content-Type")
    status = response.status
    connection.close()
    return status, json.loads(body) if content_type == "application/json" else body


def test_gui_serves_assets_and_only_the_simple_sound_toggle(server):
    status, html = request(server, "/")
    assert status == 200 and server.token.encode() in html
    assert b"Sounds off" in html and b"Sound preferences" not in html
    assert b"Preview run" not in html and b"Run simulation" in html
    for path in ("/workspace.css", "/workspace.js", "/audio/click.wav", "/audio/crystal.wav", "/audio/complete.wav"):
        assert request(server, path)[0] == 200
    assert request(server, "/../gui.py")[0] == 404


@pytest.mark.parametrize("headers", [
    {"X-Workspace-Token":""}, {"Origin":"https://unrelated.example"},
    {"Host":"unrelated.example"},
])
def test_other_pages_cannot_start_or_read_local_runs(server, headers):
    assert request(server, "/api/processes", **headers)[0] == 403
    assert request(server, "/api/start", load_process("synthetic-ab"), **headers)[0] == 403
    assert list(server.workspace.directory.iterdir()) == []


@pytest.mark.parametrize("change", [
    lambda data: data["diffusivity"]["a"].update(value=None),
    lambda data: data.update(physical_fit_ready=True),
    lambda data: data.update(film={"mapping":"invented", "density_kg_m3":5400}),
])
def test_inspection_and_invalid_runs_do_not_calculate(server, monkeypatch, change):
    def unexpected(*args, **kwargs):
        raise AssertionError("Inspection started a worker")
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", unexpected)
    data = load_process("synthetic-ab")
    status, inspection = request(server, "/api/inspect", data)
    assert status == 200 and inspection["runnable"]
    change(data)
    assert not request(server, "/api/inspect", data)[1]["runnable"]
    assert request(server, "/api/start", data)[0] == 400
    assert list(server.workspace.directory.iterdir()) == []


def test_worker_result_report_and_comparison_use_saved_shared_outputs(server, monkeypatch):
    data = load_process("synthetic-ab")
    data["spatial_grids"] = [80, 160]
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000
    status, state = request(server, "/api/start", data)
    assert status == 202 and state["active"]["running"]
    assert state["active"]["inputs"] == data  # a refreshed page can restore the running recipe
    name = state["active"]["id"]
    assert request(server, "/api/start", data)[0] == 409
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        state = request(server, "/api/state")[1]["active"]
        if not state["running"]:
            break
        time.sleep(.1)
    assert state["ready"] and state["record"]["status"] == "PASS", state
    saved = read_run(server.workspace.folder(name))
    status, result = request(server, "/api/run/"+name)
    assert status == 200 and result["inputs"] == data
    assert result["record"]["models"] == saved["models"]
    assert result["record"]["profile"] == saved["profile"]
    assert result["record"]["models"]["spatial"]["metrics"]["mean_gpc_angstrom"] is None
    def unexpected(*args, **kwargs):
        raise AssertionError("Saved inspection started a worker")
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", unexpected)
    assert request(server, "/api/compare", [name])[1]["runs"][0]["models"] == saved["models"]
    assert b"Unavailable" in request(server, "/api/report/"+name)[1]
    assert request(server, "/api/runs")[1][0]["ready"]
    path = server.workspace.folder(name)/"run.json"
    path.write_text(path.read_text()+"\n")
    assert request(server, "/api/run/"+name)[0] == 400
    assert request(server, "/api/compare", [name])[0] == 400


def test_stopping_retains_attempts_and_cannot_create_a_verified_comparison(tmp_path, monkeypatch):
    class Worker:
        code = None
        def poll(self): return self.code
        def send_signal(self, value):
            assert value == signal.SIGINT
            self.code = -2
        def terminate(self): self.code = -2
    worker = Worker()
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: worker)
    workspace = Workspace(tmp_path)
    state = workspace.start(load_process("synthetic-ab"))
    folder = workspace.folder(state["active"]["id"])
    folder.mkdir()
    attempt = dict(label="mixed", cells=1, status="PASS")
    write_json(folder/"run.json", dict(attempts=[attempt], status="RUNNING"))
    (folder/"mixed.npz").write_bytes(b"retained partial result")
    stopped = workspace.stop()["active"]
    assert stopped["record"]["status"] == "INTERRUPTED" and not stopped["ready"]
    assert json.loads((folder/"run.json").read_text())["attempts"] == [attempt]
    assert (folder/"mixed.npz").read_bytes() == b"retained partial result"
    assert not (folder/"manifest.json").exists()


def test_unverified_worker_exit_is_retained_as_unverified(server):
    data = load_process("synthetic-ab")
    data["spatial_grids"] = [2, 4]
    name = request(server, "/api/start", data)[1]["active"]["id"]
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        state = request(server, "/api/state")[1]["active"]
        if not state["running"]:
            break
        time.sleep(.1)
    assert state["ready"] and state["record"]["status"] == "UNVERIFIED"
    result = request(server, "/api/run/"+name)[1]
    assert not result["record"]["numerical_acceptance"]
    assert len(result["record"]["attempts"]) == 3


def test_run_paths_cannot_escape_the_workspace(tmp_path):
    workspace = Workspace(tmp_path/"runs")
    for name in ("../elsewhere", "/tmp/elsewhere", ".", "a/b"):
        with pytest.raises(ValueError):
            workspace.folder(name)
    outside = tmp_path/"outside"
    outside.mkdir()
    (workspace.directory/"linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        workspace.folder("linked")


def test_closed_workspace_rejects_late_start(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    workspace.close()
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: pytest.fail("Started after close"))
    with pytest.raises(RuntimeError, match="closed"):
        workspace.start(load_process("synthetic-ab"))
    assert not list(tmp_path.iterdir())


def test_incomplete_saved_result_cannot_display_acceptance(tmp_path):
    workspace = Workspace(tmp_path)
    folder = workspace.folder("incomplete")
    folder.mkdir()
    record = dict(kind="synthetic", physical_fit_ready=False, status="PASS",
                  numerical_acceptance=True, recipe_feasibility="pass", accepted_cells=160)
    write_json(folder/"run.json", record)
    write_json(folder/"inputs.json", load_process("synthetic-ab"))
    result = workspace.result("incomplete")
    assert not result["ready"] and not result["record"]["numerical_acceptance"]
    assert result["record"]["status"] == "UNVERIFIED"
    assert result["record"]["recipe_feasibility"] == "unverified"
    assert result["record"]["accepted_cells"] is None
    assert json.loads((folder/"run.json").read_text()) == record


def test_damaged_worker_progress_is_retained_on_exit(tmp_path, monkeypatch):
    class Worker:
        code = None
        def poll(self): return self.code
    worker = Worker()
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: worker)
    workspace = Workspace(tmp_path)
    name = workspace.start(load_process("synthetic-ab"))["active"]["id"]
    folder = workspace.folder(name)
    folder.mkdir()
    (folder/"run.json").write_text("broken JSON")
    worker.code = 2
    active = workspace.state()["active"]
    assert active["record"]["status"] == "ERROR" and not active["ready"]
    assert (folder/"run-damaged.json").read_text() == "broken JSON"
    assert workspace.result(name)["record"]["status"] == "ERROR"


def test_quitting_waits_for_live_worker_with_malformed_progress(tmp_path, monkeypatch):
    class Worker:
        code = None
        stopped = False
        waited = False
        def poll(self): return self.code
        def send_signal(self, value):
            assert value == signal.SIGINT
            self.stopped = True
        def terminate(self): self.stopped = True
        def wait(self, timeout):
            assert self.stopped and timeout == 10
            self.waited = True
            self.code = -2
            return self.code
    worker = Worker()
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: worker)
    workspace = Workspace(tmp_path)
    name = workspace.start(load_process("synthetic-ab"))["active"]["id"]
    folder = workspace.folder(name)
    folder.mkdir()
    (folder/"run.json").write_text("broken live progress")
    assert workspace.state()["active"]["record"]["stage"] == "Worker progress unavailable"
    workspace.close()
    assert worker.waited and workspace.closed
    assert (folder/"run-damaged.json").read_text() == "broken live progress"
    assert workspace.state()["active"]["record"]["status"] == "INTERRUPTED"
    assert not workspace.state()["active"]["ready"]


def test_browser_start_failure_closes_server(tmp_path, monkeypatch):
    servers = []
    original = gui.create_server
    def create_server(*args):
        server = original(*args)
        servers.append(server)
        return server
    def fail(url):
        raise OSError("Browser startup test failure")
    monkeypatch.setattr(gui, "create_server", create_server)
    monkeypatch.setattr(gui.webbrowser, "open", fail)
    with pytest.raises(OSError, match="Browser startup test failure"):
        gui.serve(tmp_path, port=0)
    assert len(servers) == 1
    assert servers[0].fileno() == -1 and servers[0].workspace.closed
