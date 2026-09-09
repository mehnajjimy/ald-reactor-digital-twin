"""Desktop packaging boundaries: dispatch, persistent choices, exports and quit."""
import json
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ald_twin import desktop, gui
from ald_twin.process_inputs import load_process


def test_frozen_worker_dispatch_does_not_open_a_window(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/ALD Reactor.app/Contents/MacOS/ALD Reactor")
    command = gui.worker_command(tmp_path/"inputs.json", tmp_path/"run")
    assert command[1:3] == ["--worker", "simulate"]
    calls = []
    monkeypatch.setattr("ald_twin.cli.main", lambda args: calls.append(args) or 1)
    monkeypatch.setattr(desktop, "launch", lambda *args: pytest.fail("Worker opened a window"))
    assert desktop.main(command[1:]) == 1
    assert calls == [["simulate", str(tmp_path/"inputs.json"), "--output", str(tmp_path/"run")]]


def test_preferences_survive_relaunch_and_run_folder_override(tmp_path):
    preferences = desktop.Preferences(tmp_path/"settings")
    assert preferences.runs() == tmp_path/"settings/runs"
    bridge = desktop.DesktopFiles(preferences)
    assert not bridge.sound_enabled()
    bridge.set_sound(True)
    preferences.update(runs=str(tmp_path/"old runs"))
    reopened = desktop.Preferences(preferences.directory)
    assert desktop.DesktopFiles(reopened).sound_enabled()
    assert reopened.runs() == tmp_path/"old runs"
    assert reopened.runs(tmp_path/"new runs") == tmp_path/"new runs"
    with pytest.raises(ValueError):
        bridge.set_sound("on")


def test_native_exports_require_a_dialog_and_preserve_completed_runs(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1)))
    bridge = desktop.DesktopFiles(desktop.Preferences(tmp_path/"settings"))
    target = tmp_path/"export.json"
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: [str(target)])
    assert bridge.save_file('{"example": true}', "process-inputs.json")
    assert json.loads(target.read_text()) == {"example": True}
    bridge._window.create_file_dialog = lambda *a, **k: None
    assert bridge.save_file("cancelled", "process-inputs.json") is False
    assert "example" in target.read_text()
    saved = tmp_path/"completed"
    (saved/"sources").mkdir(parents=True)
    (saved/"manifest.json").write_text("{}")
    for file in (saved/"inputs.json", saved/"sources/copied.json"):
        bridge._window.create_file_dialog = lambda *a, **k: str(file)
        with pytest.raises(ValueError, match="outside a saved run"):
            bridge.save_file("changed", "process-inputs.json")
        assert not file.exists()
    with pytest.raises(ValueError):
        bridge.save_file("not allowed", "../outside.json")


@pytest.mark.parametrize("status", ["RUNNING", "INTERRUPTED"])
def test_native_exports_preserve_partial_runs(tmp_path, monkeypatch, status):
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1)))
    bridge = desktop.DesktopFiles(desktop.Preferences(tmp_path/"settings"))
    saved = tmp_path/"partial"
    saved.mkdir()
    (saved/"run.json").write_text(json.dumps({"status": status}))
    target = saved/"inputs.json"
    target.write_text("original")
    bridge._window = SimpleNamespace(create_file_dialog=lambda *a, **k: str(target))
    with pytest.raises(ValueError, match="outside a saved run"):
        bridge.save_file("changed", "process-inputs.json")
    assert target.read_text() == "original"


@pytest.mark.parametrize("failure", ["preferences", "window"])
def test_startup_failure_closes_created_server(tmp_path, monkeypatch, failure):
    servers = []
    original = gui.create_server
    def create_server(*args):
        server = original(*args)
        servers.append(server)
        return server
    def fail(*args, **kwargs):
        raise OSError("Startup test failure")
    monkeypatch.setattr(gui, "create_server", create_server)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=fail, settings={}))
    monkeypatch.setitem(sys.modules, "webview.menu", SimpleNamespace(Menu=None, MenuAction=None))
    if failure == "preferences":
        monkeypatch.setattr(desktop.Preferences, "update", fail)
    with pytest.raises(OSError, match="Startup test failure"):
        desktop.launch(tmp_path/"runs", tmp_path/"settings")
    assert len(servers) == 1
    assert servers[0].fileno() == -1


def test_quitting_closes_the_server_and_retains_the_worker_record(tmp_path, monkeypatch):
    servers = []
    original = gui.create_server
    def create_server(*args):
        server = original(*args)
        servers.append(server)
        return server
    monkeypatch.setattr(gui, "create_server", create_server)
    class Event(list):
        def __iadd__(self, callback):
            self.append(callback)
            return self
    window = SimpleNamespace(events=SimpleNamespace(closing=Event()))
    def create_window(title, url, **kwargs):
        window.url = url
        return window
    def start(**kwargs):
        assert b'content="true"' in urlopen(window.url).read()
        address = window.url+"api/desktop/sound"
        with pytest.raises(HTTPError) as error:
            urlopen(address)
        assert error.value.code == 403
        headers = {"X-Workspace-Token": servers[0].token, "Content-Type": "application/json"}
        assert json.load(urlopen(Request(address, headers=headers))) is False
        urlopen(Request(address, data=b"true", headers=headers)).close()
        assert json.load(urlopen(Request(address, headers=headers))) is True
        workspace = servers[0].workspace
        workspace.start(load_process("synthetic-ab"))
        assert workspace.process.poll() is None
        # The native Quit event must clean up even if the Cocoa loop never returns.
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
