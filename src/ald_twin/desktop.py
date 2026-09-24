"""native window and file dialogs around the existing local workspace."""

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

# largest text the export dialog will save (512 KB)
MAX_EXPORT_BYTES = 524288

# file types the export dialog will save
EXPORT_SUFFIXES = {".json", ".md"}

# how long quitting waits for the server thread
SERVER_JOIN_SECONDS = 5


def data_directory():
    """return the per-user settings folder for this platform."""
    if sys.platform == "darwin":
        return Path.home()/"Library/Application Support/ALD Reactor"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData/Local"))/"ALD Reactor"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home()/".local/share"))/"ald-reactor"


class Preferences:
    """remembered choices saved in preferences.json."""

    def __init__(self, directory):
        """load saved preferences. a missing or damaged file starts empty."""
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
        """save new values. memory only changes after the file is written."""
        with self.lock:
            updated = dict(self.values, **values)
            write_json(self.path, updated)
            self.values = updated

    def runs(self, override=None):
        """return the runs folder: the override, then the saved one, then a default."""
        if override:
            path = override
        else:
            path = self.values.get("runs")
        if isinstance(path, (str, Path)):
            return Path(path).expanduser().resolve()
        return self.directory/"runs"


class DesktopFiles:
    """native file and preference operations behind the local api's token check."""

    def __init__(self, preferences):
        """start without a window. launch sets it once the window exists."""
        self._preferences = preferences
        self._window = None

    def sound_enabled(self):
        """sounds stay off unless the user turned them on."""
        return self._preferences.values.get("sounds") is True

    def set_sound(self, enabled):
        """save the sound choice, which must be true or false."""
        if type(enabled) is not bool:
            raise ValueError("Sound preference must be on or off")
        self._preferences.update(sounds=enabled)

    def save_file(self, text, filename):
        """ask where to save an export. returns False if the user cancels."""
        import webview

        # only small json inputs and markdown reports can be exported
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_EXPORT_BYTES:
            raise ValueError("Export must be at most 512 KB")
        if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix not in EXPORT_SUFFIXES:
            raise ValueError("Export must be a JSON input or Markdown report")

        selection = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not selection:
            return False
        if isinstance(selection, str):
            path = Path(selection).resolve()
        else:
            path = Path(selection[0]).resolve()

        # keep exports outside partial runs too.
        for parent in path.parents:
            if (parent/"manifest.json").exists() or (parent/"run.json").exists():
                raise ValueError("Save a copy outside a saved run folder")
        path.write_text(text, encoding="utf-8")
        return True


def show_folder(path):
    """open a folder in the system file browser."""
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def show_updates(window, is_closed, lock):
    """run off the ui thread. repeated clicks share one check and dialog."""
    if not lock.acquire(blocking=False):
        return
    try:
        if is_closed():
            return
        message, url = check_release()
        if is_closed():
            return

        # a newer release asks before opening its page. otherwise just show the message.
        if url:
            if window.create_confirmation_dialog("ALD Reactor update", message) and not is_closed():
                webbrowser.open(url)
        else:
            window.run_js("alert("+json.dumps(message)+")")
    except Exception:
        logging.exception("Could not display the update check")
    finally:
        lock.release()


def calculation_running(workspace):
    """true while the workspace has a worker running."""
    if not workspace.state()["active"]:
        return False
    return workspace.state()["active"]["running"]


def launch(runs=None, settings=None):
    """open the desktop window on a local server and clean up when it closes."""
    import webview
    from webview.menu import Menu, MenuAction
    from .gui import Workspace, create_server

    # settings, a log file and console streams for a windowed app
    preferences = Preferences(settings or data_directory())
    log = preferences.directory/"desktop.log"
    logging.basicConfig(filename=log, level=logging.WARNING)
    if sys.stdout is None:
        sys.stdout = log.open("a", buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout

    # the local server runs on a free port in a background thread
    server = create_server(preferences.runs(runs), 0)
    bridge = DesktopFiles(preferences)
    server.desktop = bridge
    thread = Thread(target=server.serve_forever, daemon=True)
    closed = False
    close_lock = Lock()
    update_lock = Lock()

    def close():
        """stop the server and worker once, however the app quits."""
        nonlocal closed
        with close_lock:
            if closed:
                return
            closed = True
            try:
                # only stop the server if its thread started, otherwise shutdown hangs.
                if thread.is_alive():
                    server.shutdown()
                server.workspace.close()
            finally:
                server.server_close()
                if thread.is_alive():
                    thread.join(timeout=SERVER_JOIN_SECONDS)

    def is_closed():
        """tell the update check whether the app has quit."""
        return closed

    url = f"http://127.0.0.1:{server.server_port}/"

    def open_runs():
        """switch to another runs folder chosen in a folder dialog."""
        try:
            workspace = server.workspace
            if calculation_running(workspace):
                raise ValueError("Stop the calculation before opening another runs folder")
            selection = window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(workspace.directory))
            if not selection:
                return

            # check again under the lock, since a run may have started while the dialog was open
            with workspace.lock:
                if calculation_running(workspace):
                    raise ValueError("Stop the calculation before opening another runs folder")
                next_workspace = Workspace(selection[0])
                preferences.update(runs=str(next_workspace.directory))
                workspace.close()
                server.workspace = next_workspace
            window.load_url(url)
        except (OSError, ValueError) as error:
            window.run_js("errors("+json.dumps([str(error)])+")")

    def show_runs():
        """open the current runs folder in the file browser."""
        show_folder(server.workspace.directory)

    def check_updates():
        """check for updates without blocking the window."""
        Thread(target=show_updates, args=(window, is_closed, update_lock), daemon=True).start()

    try:
        preferences.update(runs=str(server.workspace.directory))
        thread.start()
        webview.settings["ALLOW_FILE_URLS"] = False
        window = webview.create_window("ALD Reactor", url,
            width=1180, height=820, min_size=(900, 650), text_select=True,
            background_color="#FFFFFF")
        bridge._window = window

        # the native quit event must stop workers before the event loop exits.
        window.events.closing += close
        menus = [Menu("File", [MenuAction("Open runs folder…", open_runs),
                               MenuAction("Show runs folder", show_runs)]),
                 Menu("Help", [MenuAction("Check for Updates…", check_updates)])]
        webview.start(menu=menus, private_mode=True)
    except Exception:
        logging.exception("ALD Reactor desktop failed")
        raise
    finally:
        close()


def main(argv=None):
    """open the desktop app, or run a cli worker when started with --worker."""
    if argv is None:
        argv = list(sys.argv[1:])
    else:
        argv = list(argv)
    if argv[:1] == ["--worker"]:
        # windowed apps have no console streams, so reuse the worker log descriptors
        # already opened by the parent.
        if sys.stdout is None:
            sys.stdout = os.fdopen(os.dup(1), "w", buffering=1)
        if sys.stderr is None:
            sys.stderr = os.fdopen(os.dup(2), "w", buffering=1)
        from .cli import main as cli_main
        return cli_main(argv[1:])
    parser = argparse.ArgumentParser(description="Open the ALD Reactor desktop workspace")
    parser.add_argument("--runs", type=Path, help="Run collection to open; remembered for the next launch")
    parser.add_argument("--settings", type=Path, help="Override the per-user settings directory")
    args = parser.parse_args(argv)
    launch(args.runs, args.settings)


if __name__ == "__main__":
    raise SystemExit(main())
