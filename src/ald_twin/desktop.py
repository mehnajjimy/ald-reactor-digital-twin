"""Native window and file dialogs around the existing local workspace."""

import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import webbrowser
from threading import Lock, RLock, Thread

from .process_study import write_json
from .updates import check_release


def data_directory():
    if sys.platform == "darwin":
        return Path.home()/"Library/Application Support/ALD Reactor"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData/Local"))/"ALD Reactor"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home()/".local/share"))/"ald-reactor"


class Preferences:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory/"preferences.json"
        self.lock = RLock()
        try:
            self.values = json.loads(self.path.read_text())
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    def update(self, **values):
        with self.lock:
            updated = dict(self.values, **values)
            write_json(self.path, updated)
            self.values = updated

    def runs(self, override=None):
        path = override or self.values.get("runs")
        return Path(path).expanduser().resolve() if isinstance(path, (str, Path)) else self.directory/"runs"


class DesktopFiles:
    """Native file and preference operations behind the local API's token check."""

    def __init__(self, preferences):
        self._preferences = preferences
        self._window = None

    def sound_enabled(self):
        return self._preferences.values.get("sounds") is True

    def set_sound(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Sound preference must be on or off")
        self._preferences.update(sounds=enabled)

    def save_file(self, text, filename):
        import webview
        if not isinstance(text, str) or len(text.encode("utf-8")) > 524288:
            raise ValueError("Export must be at most 512 KB")
        if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix not in {".json", ".md"}:
            raise ValueError("Export must be a JSON input or Markdown report")
        selection = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not selection:
            return False
        path = Path(selection if isinstance(selection, str) else selection[0]).resolve()
        # Partial attempts and their inputs must survive exports too.
        if any((parent/"manifest.json").exists() or (parent/"run.json").exists()
               for parent in path.parents):
            raise ValueError("Save a copy outside a saved run folder")
        path.write_text(text, encoding="utf-8")
        return True


def show_folder(path):
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def show_updates(window, is_closed, lock):
    """Run off the UI thread; repeated clicks share one check and dialog."""
    if not lock.acquire(blocking=False):
        return
    try:
        if is_closed():
            return
        message, url = check_release()
        if is_closed():
            return
        if url:
            if window.create_confirmation_dialog("ALD Reactor update", message) and not is_closed():
                webbrowser.open(url)
        else:
            window.run_js("alert("+json.dumps(message)+")")
    except Exception:
        logging.exception("Could not display the update check")
    finally:
        lock.release()


def launch(runs=None, settings=None):
    import webview
    from webview.menu import Menu, MenuAction
    from .gui import Workspace, create_server

    preferences = Preferences(settings or data_directory())
    log = preferences.directory/"desktop.log"
    logging.basicConfig(filename=log, level=logging.WARNING)
    if sys.stdout is None:
        sys.stdout = log.open("a", buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout
    server = create_server(preferences.runs(runs), 0)
    bridge = DesktopFiles(preferences)
    server.desktop = bridge
    thread = Thread(target=server.serve_forever, daemon=True)
    closed = False
    close_lock = Lock()
    update_lock = Lock()

    def close():
        nonlocal closed
        with close_lock:
            if closed:
                return
            closed = True
            try:
                # shutdown() blocks forever if startup never reached thread.start().
                if thread.is_alive():
                    server.shutdown()
                server.workspace.close()
            finally:
                server.server_close()
                if thread.is_alive():
                    thread.join(timeout=5)

    url = f"http://127.0.0.1:{server.server_port}/"

    def open_runs():
        try:
            workspace = server.workspace
            if workspace.state()["active"] and workspace.state()["active"]["running"]:
                raise ValueError("Stop the calculation before opening another runs folder")
            selection = window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(workspace.directory))
            if not selection:
                return
            with workspace.lock:
                if workspace.state()["active"] and workspace.state()["active"]["running"]:
                    raise ValueError("Stop the calculation before opening another runs folder")
                next_workspace = Workspace(selection[0])
                preferences.update(runs=str(next_workspace.directory))
                workspace.close()
                server.workspace = next_workspace
            window.load_url(url)
        except (OSError, ValueError) as error:
            window.run_js("errors("+json.dumps([str(error)])+")")

    try:
        preferences.update(runs=str(server.workspace.directory))
        thread.start()
        webview.settings["ALLOW_FILE_URLS"] = False
        window = webview.create_window("ALD Reactor", url,
            width=1180, height=820, min_size=(900, 650), text_select=True,
            background_color="#FFFFFF")
        bridge._window = window
        # Cocoa's Quit menu can terminate without returning from its event loop.
        window.events.closing += close
        menus = [Menu("File", [MenuAction("Open runs folder…", open_runs),
            MenuAction("Show runs folder", lambda: show_folder(server.workspace.directory))]),
            Menu("Help", [MenuAction("Check for Updates…", lambda: Thread(target=show_updates,
                args=(window, lambda: closed, update_lock), daemon=True).start())])]
        webview.start(menu=menus, private_mode=True)
    except Exception:
        logging.exception("ALD Reactor desktop failed")
        raise
    finally:
        close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--worker"]:
        # Windowed frozen apps replace Python's streams with None. The parent
        # already redirected these descriptors to the retained worker log.
        for name, descriptor in (("stdout", 1), ("stderr", 2)):
            if getattr(sys, name) is None:
                setattr(sys, name, os.fdopen(os.dup(descriptor), "w", buffering=1))
        from .cli import main as cli_main
        return cli_main(argv[1:])
    parser = argparse.ArgumentParser(description="Open the ALD Reactor desktop workspace")
    parser.add_argument("--runs", type=Path, help="Run collection to open; remembered for the next launch")
    parser.add_argument("--settings", type=Path, help="Override the per-user settings directory")
    args = parser.parse_args(argv)
    launch(args.runs, args.settings)


if __name__ == "__main__":
    raise SystemExit(main())
