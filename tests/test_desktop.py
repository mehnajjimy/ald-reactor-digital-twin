"""desktop app: exports never write inside a saved or partial run."""

import json
import sys
from types import SimpleNamespace

import pytest

from ald_twin import desktop


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
