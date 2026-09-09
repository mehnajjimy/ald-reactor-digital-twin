"""local browser workspace; calculations use the existing cli in one worker."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
from threading import RLock
from urllib.parse import urlsplit
import webbrowser

from .process_inputs import inspect_process, prepare_inputs, process_catalog
from .process_study import write_json
from .workflow import compare_runs, read_run

UI = Path(__file__).with_name("ui")


def read_json(path):
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return record


def worker_command(input_path, output):

    # the bundled app dispatches workers through its own entry point.

    prefix = [sys.executable, "--worker"] if getattr(sys, "frozen", False) else [
        sys.executable, "-m", "ald_twin.cli"]
    return prefix+["simulate", str(input_path), "--output", str(output)]


class Workspace:
    """one local run at a time, with immutable completed output folders."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.process = None
        self.active = None
        self.closed = False

    def folder(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", name):
            raise ValueError("Invalid run name")
        folder = (self.directory/name).resolve()
        if folder.parent != self.directory:
            raise ValueError("Run must belong to this workspace")
        return folder

    def runs(self):
        rows = []
        for folder in self.directory.iterdir():
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            try:
                record = read_json(self.folder(folder.name)/"run.json")
                rows.append(dict(id=folder.name, process_id=record["process_id"],
                    process_name=record["process_name"], status=record["status"],
                    started_at=record.get("started_at", ""),
                    ready=(folder/"manifest.json").is_file()))
            except (OSError, ValueError, KeyError):
                continue
        return sorted(rows, key=lambda row: row["started_at"], reverse=True)

    def result(self, name):
        folder = self.folder(name)
        ready = (folder/"manifest.json").is_file()
        record = read_run(folder) if ready else read_json(folder/"run.json")
        if record.get("kind") != "synthetic" or record.get("physical_fit_ready") is not False:
            raise ValueError("Unsupported saved scientific status")
        if not ready:
            record.update(numerical_acceptance=False, recipe_feasibility="unverified", accepted_cells=None)
            if record.get("status") not in {"RUNNING", "INTERRUPTED", "ERROR"}:
                record.update(status="UNVERIFIED", reason="Saved artifacts are incomplete; no verified result is available")
        return dict(id=name, record=record, inputs=read_json(folder/"inputs.json"), ready=ready)

    def refresh(self):
        """the worker must exit and its manifest verify before a result is ready."""

        if not self.active or not self.active["running"] or self.process.poll() is None:
            return
        folder = self.folder(self.active["id"])
        if (folder/"manifest.json").is_file():
            try:
                self.active.update(running=False, ready=True, record=read_run(folder))
                return
            except (OSError, ValueError) as error:
                self.active.update(running=False, ready=False,
                    record=dict(status="ERROR", stage="Saved result could not be verified", reason=str(error)))
                return
        try:
            record = read_json(folder/"run.json") if (folder/"run.json").exists() else {}
        except (OSError, ValueError) as error:

            # keep the damaged record before saving the worker exit.

            damaged = folder/"run.json"
            if damaged.exists():
                damaged.rename(folder/"run-damaged.json")
            record = dict(reason=f"Could not read worker progress: {error}")
        stopped = self.active.get("stop_requested", False)
        record.update(kind="synthetic", physical_fit_ready=False,
            process_id=self.active["inputs"]["id"], process_name=self.active["inputs"]["name"],
            status="INTERRUPTED" if stopped else "ERROR", numerical_acceptance=False,
            recipe_feasibility="unverified", stage="Stopped" if stopped else "Calculation stopped after an error",
            reason="Stopped by user; completed attempts retained" if stopped else
                   record.get("reason", "Worker exited before completing the saved result"))
        folder.mkdir(exist_ok=True)
        if not (folder/"inputs.json").exists():
            write_json(folder/"inputs.json", self.active["inputs"])
        write_json(folder/"run.json", record)
        self.active.update(running=False, ready=False, record=record)

    def state(self):
        with self.lock:
            self.refresh()
            if not self.active:
                return dict(active=None)
            row = {key: self.active.get(key) for key in ("id", "running", "ready", "stop_requested")}
            if row["running"]:
                row["inputs"] = self.active["inputs"]
                path = self.folder(row["id"])/"run.json"
                try:
                    record = read_json(path) if path.exists() else dict(status="RUNNING", stage="Starting solver")
                except (OSError, ValueError) as error:
                    record = dict(status="RUNNING", stage="Worker progress unavailable", reason=str(error))
            else:
                record = self.active["record"]
            row["record"] = {key: record.get(key) for key in
                ("status", "stage", "reason", "numerical_acceptance", "recipe_feasibility")}
            if row["stop_requested"] and row["running"]:
                row["record"]["stage"] = "Stopping; retaining completed attempts"
            return dict(active=row)

    def start(self, inputs):
        parameters, _, _, _ = prepare_inputs(inputs)
        with self.lock:
            if self.closed:
                raise RuntimeError("This workspace has closed")
            self.refresh()
            if self.active and self.active["running"]:
                raise RuntimeError("A calculation is already running")
            name = datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S-")+secrets.token_hex(3)
            control = self.directory/".gui"
            control.mkdir(exist_ok=True)
            input_path = control/(name+".json")
            write_json(input_path, parameters)
            environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1", OMP_NUM_THREADS="1")
            with (control/(name+".log")).open("w") as log:
                self.process = subprocess.Popen(worker_command(input_path, self.folder(name)),
                    stdout=log, stderr=subprocess.STDOUT, env=environment)
            self.active = dict(id=name, running=True, ready=False, inputs=parameters, stop_requested=False)
            return self.state()

    def stop(self):
        with self.lock:
            self.refresh()
            if self.active and self.active["running"]:
                self.active["stop_requested"] = True
                try:
                    if os.name == "nt":
                        self.process.terminate()
                    else:
                        self.process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
            return self.state()

    def close(self):
        with self.lock:
            self.closed = True
            self.stop()
        if self.process:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            with self.lock:
                self.refresh()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, value, status=200, content_type="application/json"):
        body = json.dumps(value, allow_nan=False).encode() if content_type == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' blob:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def request_allowed(self, api=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")

        # require the launch token and local origin so other browser pages
        # cannot start jobs or read run files.

        return (self.headers.get("Host") in hosts
            and (origin is None or origin in {"http://"+host for host in hosts})
            and (not api or secrets.compare_digest(self.headers.get("X-Workspace-Token", ""), self.server.token)))

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.request_allowed(path.startswith("/api/")):
            return self.send(dict(error="Local workspace access only"), 403)
        try:
            workspace = self.server.workspace
            if path == "/":
                page = (UI/"index.html").read_text().replace("__WORKSPACE_TOKEN__", self.server.token)
                page = page.replace("__DESKTOP__", "true" if getattr(self.server, "desktop", False) else "false")
                return self.send(page.encode(), content_type="text/html; charset=utf-8")
            if path == "/api/processes":
                return self.send([inspect_process(data) for data in process_catalog()])
            if path == "/api/runs":
                return self.send(workspace.runs())
            if path == "/api/state":
                return self.send(workspace.state())
            if path == "/api/desktop/sound" and getattr(self.server, "desktop", None):
                return self.send(self.server.desktop.sound_enabled())
            if path.startswith("/api/run/"):
                return self.send(workspace.result(path.removeprefix("/api/run/")))
            if path.startswith("/api/report/"):
                name = path.removeprefix("/api/report/")
                read_run(workspace.folder(name))
                return self.send((workspace.folder(name)/"report.md").read_bytes(), content_type="text/plain; charset=utf-8")
            assets = {"/workspace.css", "/workspace.js", "/audio/click.wav", "/audio/crystal.wav", "/audio/complete.wav"}
            if path in assets:
                file = UI/path.lstrip("/")
                return self.send(file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send(dict(error="Not found"), 404)
        except (OSError, ValueError, KeyError) as error:
            self.send(dict(error=str(error)), 400)

    def do_POST(self):
        if not self.request_allowed(api=True):
            return self.send(dict(error="Local workspace access only"), 403)
        try:
            if self.headers.get("Content-Type") != "application/json":
                raise ValueError("Expected JSON inputs")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 524288:
                raise ValueError("Input must be between 1 byte and 512 KB")
            data = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            workspace = self.server.workspace
            desktop = getattr(self.server, "desktop", None)
            if path == "/api/desktop/sound" and desktop:
                desktop.set_sound(data)
                return self.send(dict(saved=True))
            if path == "/api/desktop/export" and desktop:
                return self.send(dict(saved=desktop.save_file(data["text"], data["filename"])))
            if path == "/api/inspect":
                return self.send(inspect_process(data))
            if path == "/api/start":
                return self.send(workspace.start(data), 202)
            if path == "/api/stop":
                return self.send(workspace.stop())
            if path == "/api/compare":
                if not isinstance(data, list) or not 1 <= len(data) <= 4 or any(not isinstance(n, str) for n in data):
                    raise ValueError("Choose one to four saved runs")
                return self.send(compare_runs([workspace.folder(name) for name in data]))
            self.send(dict(error="Not found"), 404)
        except RuntimeError as error:
            self.send(dict(error=str(error)), 409)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.send(dict(error=str(error)), 400)


def create_server(directory, port=8765):
    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = secrets.token_urlsafe(32)
    try:
        server.workspace = Workspace(directory)
    except Exception:
        server.server_close()
        raise
    return server


def serve(directory, port=8765, open_browser=True):
    server = create_server(directory, port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Reactor workspace: {url}", flush=True)
    print(f"Saved runs: {server.workspace.directory}", flush=True)
    try:
        if open_browser:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.workspace.close()
        finally:
            server.server_close()
