"""desktop app: worker dispatch, safe exports, startup failure and quit."""

import json
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ald_twin import desktop, gui
from ald_twin.process_inputs import load_process


def record_servers(monkeypatch):
    """wrap gui.create_server so the test can see every server it made."""
    servers = []
    original = gui.create_server

    def create_server(*args):
        """make a real server and remember it."""
        server = original(*args)
        servers.append(server)
        return server

    monkeypatch.setattr(gui, "create_server", create_server)
    return servers


def test_frozen_worker_runs_the_cli_without_opening_a_window(monkeypatch, tmp_path):
    """catches the packaged app opening a second window instead of simulating."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/ALD Reactor.app/Contents/MacOS/ALD Reactor")
    command = gui.worker_command(tmp_path/"inputs.json", tmp_path/"run")
    assert command[1:3] == ["--worker", "simulate"]
    calls = []

    def fake_cli(args):
        """record the cli arguments instead of simulating."""
        calls.append(args)
        return 1

    monkeypatch.setattr("ald_twin.cli.main", fake_cli)
    monkeypatch.setattr(desktop, "launch", lambda *args: pytest.fail("Worker opened a window"))
    assert desktop.main(command[1:]) == 1
    assert calls == [["simulate", str(tmp_path/"inputs.json"), "--output", str(tmp_path/"run")]]


def test_exports_never_write_inside_saved_or_partial_runs(tmp_path, monkeypatch):
    """catches an export that overwrites the evidence of a finished or running run."""
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1)))
    bridge = desktop.DesktopFiles(desktop.Preferences(tmp_path/"settings"))

    # a normal export writes the file, and a cancelled dialog writes nothing
    target = tmp_path/"export.json"
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: [str(target)])
    assert bridge.save_file('{"example": true}', "process-inputs.json")
    assert json.loads(target.read_text()) == {"example": True}
    bridge._window.create_file_dialog = lambda *a, **k: None
    assert bridge.save_file("cancelled", "process-inputs.json") is False
    assert "example" in target.read_text()

    # a completed run has a manifest, a running or interrupted one only run.json
    completed = tmp_path/"completed"
    (completed/"sources").mkdir(parents=True)
    (completed/"manifest.json").write_text("{}")
    partial = tmp_path/"partial"
    partial.mkdir()
    (partial/"run.json").write_text(json.dumps({"status": "RUNNING"}))
    (partial/"inputs.json").write_text("original")
    for file in (completed/"inputs.json", completed/"sources/copied.json", partial/"inputs.json"):
        bridge._window.create_file_dialog = lambda *a, **k: str(file)
        with pytest.raises(ValueError, match="outside a saved run"):
            bridge.save_file("changed", "process-inputs.json")
    assert not (completed/"inputs.json").exists()
    assert (partial/"inputs.json").read_text() == "original"


def test_startup_failure_closes_the_server(tmp_path, monkeypatch):
    """catches a failed launch that leaves the local server port open."""
    def fail(*args, **kwargs):
        """stand in for a startup step that fails."""
        raise OSError("Startup test failure")

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=fail, settings={}))
    monkeypatch.setitem(sys.modules, "webview.menu", SimpleNamespace(Menu=None, MenuAction=None))
    servers = record_servers(monkeypatch)

    # first the window fails to open, then saving preferences fails
    for failure in ("window", "preferences"):
        if failure == "preferences":
            monkeypatch.setattr(desktop.Preferences, "update", fail)
        with pytest.raises(OSError, match="Startup test failure"):
            desktop.launch(tmp_path/"runs", tmp_path/"settings")
    assert len(servers) == 2
    assert all(server.fileno() == -1 for server in servers)


def test_quitting_stops_the_worker_and_marks_the_run_interrupted(tmp_path, monkeypatch):
    """catches a quit that leaves a worker running or a run looking finished."""
    servers = record_servers(monkeypatch)

    class Event(list):
        def __iadd__(self, callback):
            """register a callback like a pywebview event."""
            self.append(callback)
            return self

    window = SimpleNamespace(events=SimpleNamespace(closing=Event()))

    def create_window(title, url, **kwargs):
        """remember the page address instead of opening a window."""
        window.url = url
        return window

    def start(**kwargs):
        """stand in for the native event loop and drive the app over http."""
        # the page is served, and the api needs the page token
        assert b'content="true"' in urlopen(window.url).read()
        address = window.url+"api/desktop/sound"
        with pytest.raises(HTTPError) as error:
            urlopen(address)
        assert error.value.code == 403
        headers = {"X-Workspace-Token": servers[0].token, "Content-Type": "application/json"}
        assert json.load(urlopen(Request(address, headers=headers))) is False
        urlopen(Request(address, data=b"true", headers=headers)).close()
        assert json.load(urlopen(Request(address, headers=headers))) is True

        # start a real worker, then quit through the native closing event
        workspace = servers[0].workspace
        workspace.start(load_process("synthetic-ab"))
        assert workspace.process.poll() is None
        for close in window.events.closing:
            close()
        assert workspace.process.poll() is not None

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window,
        start=start, settings={}))
    monkeypatch.setitem(sys.modules, "webview.menu", SimpleNamespace(
        Menu=lambda *args: args, MenuAction=lambda *args: args))
    desktop.launch(tmp_path/"runs", tmp_path/"settings")
    assert servers[0].fileno() == -1
    record = json.loads(next((tmp_path/"runs").glob("*/run.json")).read_text())
    assert record["status"] == "INTERRUPTED"
    assert not record["numerical_acceptance"]
