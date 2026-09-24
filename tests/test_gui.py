"""local web workspace: access control, real worker runs, stops and failures."""

from http.client import HTTPConnection
import json
import signal
import threading
import time

import pytest

from ald_twin import gui
from ald_twin.gui import Workspace, create_server
from ald_twin.process_inputs import load_process
from ald_twin.process_study import write_json
from ald_twin.workflow import read_run


@pytest.fixture
def server(tmp_path):
    """a running workspace server on a free port, shut down after the test."""
    server = create_server(tmp_path/"runs", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.workspace.close()
    server.server_close()
    thread.join(timeout=5)


def request(server, path, data=None, **headers):
    """send a get (or a post when data is given) and return the status and body."""
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    defaults = {"X-Workspace-Token": server.token, "Content-Type": "application/json"}
    defaults.update(headers)
    if data is None:
        connection.request("GET", path, headers=defaults)
    else:
        connection.request("POST", path, body=json.dumps(data), headers=defaults)
    response = connection.getresponse()
    body = response.read()
    content_type = response.getheader("Content-Type")
    status = response.status
    connection.close()
    if content_type == "application/json":
        return status, json.loads(body)
    return status, body


def fake_worker(monkeypatch, worker):
    """make the workspace start this fake worker instead of a real process."""
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: worker)


def wait_until_done(server, seconds):
    """poll the active run until it stops or the time runs out."""
    deadline = time.monotonic()+seconds
    state = request(server, "/api/state")[1]["active"]
    while state["running"] and time.monotonic() < deadline:
        time.sleep(.1)
        state = request(server, "/api/state")[1]["active"]
    return state


def test_page_is_served_but_other_sites_cannot_use_the_api(server):
    """catches a missing token, origin or host check, or a path that leaves the ui folder."""
    status, html = request(server, "/")
    assert status == 200
    assert server.token.encode() in html
    assert request(server, "/workspace.js")[0] == 200
    assert request(server, "/../gui.py")[0] == 404
    for headers in ({"X-Workspace-Token": ""}, {"Origin": "https://unrelated.example"},
                    {"Host": "unrelated.example"}):
        assert request(server, "/api/processes", **headers)[0] == 403
        assert request(server, "/api/start", load_process("synthetic-ab"), **headers)[0] == 403
    assert list(server.workspace.directory.iterdir()) == []


def test_invalid_inputs_are_refused_without_starting_a_worker(server, monkeypatch):
    """catches inspection or a bad input starting a calculation."""
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: pytest.fail("Worker started"))
    data = load_process("synthetic-ab")
    status, inspection = request(server, "/api/inspect", data)
    assert status == 200
    assert inspection["runnable"]
    data["diffusivity"]["a"]["value"] = None
    assert not request(server, "/api/inspect", data)[1]["runnable"]
    assert request(server, "/api/start", data)[0] == 400
    assert list(server.workspace.directory.iterdir()) == []


def test_worker_run_is_shown_from_its_saved_files(server, monkeypatch):
    """catches the page showing numbers that differ from the saved, verified run."""
    data = load_process("synthetic-ab")
    data["spatial_grids"] = [80, 160]
    for prop in data["diffusivity"].values():
        prop["value"] *= 1000
    status, state = request(server, "/api/start", data)
    assert status == 202
    assert state["active"]["running"]
    # a refreshed page can restore the running recipe, and a second start is refused
    assert state["active"]["inputs"] == data
    name = state["active"]["id"]
    assert request(server, "/api/start", data)[0] == 409

    state = wait_until_done(server, 60)
    assert state["ready"], state
    assert state["record"]["status"] == "PASS", state
    saved = read_run(server.workspace.folder(name))
    status, result = request(server, "/api/run/"+name)
    assert status == 200
    assert result["inputs"] == data
    assert result["record"]["models"] == saved["models"]
    assert result["record"]["profile"] == saved["profile"]
    assert result["record"]["models"]["spatial"]["metrics"]["mean_gpc_angstrom"] is None

    # comparing and reporting a saved run never starts a worker
    monkeypatch.setattr("ald_twin.gui.subprocess.Popen", lambda *a, **kw: pytest.fail("Worker started"))
    assert request(server, "/api/compare", [name])[1]["runs"][0]["models"] == saved["models"]
    assert b"Unavailable" in request(server, "/api/report/"+name)[1]

    # an edited saved run is refused
    path = server.workspace.folder(name)/"run.json"
    path.write_text(path.read_text()+"\n")
    assert request(server, "/api/run/"+name)[0] == 400
    assert request(server, "/api/compare", [name])[0] == 400


def test_stop_keeps_partial_attempts_as_interrupted(tmp_path, monkeypatch):
    """catches a stopped run losing its attempts or looking verified."""
    class Worker:
        code = None

        def poll(self):
            """return the exit code, or None while running."""
            return self.code

        def send_signal(self, value):
            """stop on SIGINT like the real worker."""
            assert value == signal.SIGINT
            self.code = -2

        def terminate(self):
            """stop at once."""
            self.code = -2

    fake_worker(monkeypatch, Worker())
    workspace = Workspace(tmp_path)
    state = workspace.start(load_process("synthetic-ab"))
    folder = workspace.folder(state["active"]["id"])
    folder.mkdir()
    attempt = dict(label="mixed", cells=1, status="PASS")
    write_json(folder/"run.json", dict(attempts=[attempt], status="RUNNING"))
    (folder/"mixed.npz").write_bytes(b"retained partial result")
    stopped = workspace.stop()["active"]
    assert stopped["record"]["status"] == "INTERRUPTED"
    assert not stopped["ready"]
    assert json.loads((folder/"run.json").read_text())["attempts"] == [attempt]
    assert (folder/"mixed.npz").read_bytes() == b"retained partial result"
    assert not (folder/"manifest.json").exists()


def test_damaged_progress_is_kept_and_quitting_waits_for_the_worker(tmp_path, monkeypatch):
    """catches broken progress being lost, or quit returning before the worker stops."""
    class Worker:
        code = None
        stopped = False
        waited = False

        def poll(self):
            """return the exit code, or None while running."""
            return self.code

        def send_signal(self, value):
            """note a SIGINT stop request."""
            assert value == signal.SIGINT
            self.stopped = True

        def terminate(self):
            """note a terminate request."""
            self.stopped = True

        def wait(self, timeout):
            """finish only after a stop was requested."""
            assert self.stopped and timeout == 10
            self.waited = True
            self.code = -2
            return self.code

    # a worker that exits with broken progress is saved as an error
    exited = Worker()
    fake_worker(monkeypatch, exited)
    workspace = Workspace(tmp_path/"exited")
    name = workspace.start(load_process("synthetic-ab"))["active"]["id"]
    folder = workspace.folder(name)
    folder.mkdir()
    (folder/"run.json").write_text("broken JSON")
    exited.code = 2
    active = workspace.state()["active"]
    assert active["record"]["status"] == "ERROR"
    assert not active["ready"]
    assert (folder/"run-damaged.json").read_text() == "broken JSON"
    assert workspace.result(name)["record"]["status"] == "ERROR"

    # a live worker with broken progress is stopped and waited for on quit
    live = Worker()
    fake_worker(monkeypatch, live)
    workspace = Workspace(tmp_path/"live")
    name = workspace.start(load_process("synthetic-ab"))["active"]["id"]
    folder = workspace.folder(name)
    folder.mkdir()
    (folder/"run.json").write_text("broken live progress")
    assert workspace.state()["active"]["record"]["stage"] == "Worker progress unavailable"
    workspace.close()
    assert live.waited
    assert workspace.closed
    assert (folder/"run-damaged.json").read_text() == "broken live progress"
    assert workspace.state()["active"]["record"]["status"] == "INTERRUPTED"
    assert not workspace.state()["active"]["ready"]


def test_incomplete_saved_run_cannot_show_acceptance(tmp_path):
    """catches a run folder without a manifest being displayed as verified."""
    workspace = Workspace(tmp_path)
    folder = workspace.folder("incomplete")
    folder.mkdir()
    record = dict(kind="synthetic", physical_fit_ready=False, status="PASS",
                  numerical_acceptance=True, recipe_feasibility="pass", accepted_cells=160)
    write_json(folder/"run.json", record)
    write_json(folder/"inputs.json", load_process("synthetic-ab"))
    result = workspace.result("incomplete")
    assert not result["ready"]
    assert not result["record"]["numerical_acceptance"]
    assert result["record"]["status"] == "UNVERIFIED"
    assert result["record"]["recipe_feasibility"] == "unverified"
    assert result["record"]["accepted_cells"] is None
    assert json.loads((folder/"run.json").read_text()) == record


def test_run_names_cannot_leave_the_workspace(tmp_path):
    """catches a run name or symlink that reads or writes outside the runs folder."""
    workspace = Workspace(tmp_path/"runs")
    for name in ("../elsewhere", "/tmp/elsewhere", ".", "a/b"):
        with pytest.raises(ValueError):
            workspace.folder(name)
    outside = tmp_path/"outside"
    outside.mkdir()
    (workspace.directory/"linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        workspace.folder("linked")


def test_browser_start_failure_closes_the_server(tmp_path, monkeypatch):
    """catches a failed browser launch that leaves the server and workspace open."""
    servers = []
    original = gui.create_server

    def create_server(*args):
        """record each server that serve() creates."""
        server = original(*args)
        servers.append(server)
        return server

    def fail(url):
        """stand in for a browser that cannot open."""
        raise OSError("Browser startup test failure")

    monkeypatch.setattr(gui, "create_server", create_server)
    monkeypatch.setattr(gui.webbrowser, "open", fail)
    with pytest.raises(OSError, match="Browser startup test failure"):
        gui.serve(tmp_path, port=0)
    assert len(servers) == 1
    assert servers[0].fileno() == -1
    assert servers[0].workspace.closed
