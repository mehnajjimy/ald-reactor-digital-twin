# Desktop code, line by line

These tables cover every nonblank line in the reviewed desktop wrapper and build
scripts. Related lines share a row so the explanation stays beside the operation
it explains. The source remains short; no second annotated copy is maintained.
Line numbers refer to this maintenance review and must follow later source edits.

## `src/ald_twin/desktop.py`

| Lines | What they do and why |
|---|---|
| 1–14 | Describe the wrapper and import its tools: `argparse` for launch flags, `json` for preferences and error text, `logging` for failures, `os` for platform paths and streams, `Path` for files, `subprocess` for Finder, `sys` for launch arguments, `webbrowser` to open a confirmed download page, locks for shared state, and `Thread` for the service. Reuse the existing atomic JSON writer and release checker. |
| 16–23 | Name the 512 KB export limit, the two exportable file types and the five-second wait for the service thread on quit. |
| 26–32 | Choose the normal application-data folder for macOS, Windows or Linux. The Mac path is under the user's Library; the other paths respect their platform environment variables. This chooses storage only and makes no directory yet. |
| 35–43 | Define preferences; resolve and create their folder, name `preferences.json`, and allocate a reentrant lock for updates from different request threads. |
| 44–49 | Read the saved JSON object. Missing, unreadable, malformed or non-object preferences fall back to an empty object. Nothing in the run collection is changed. |
| 51–56 | Lock an update, merge new values with existing ones, write the new object atomically, then update memory. A failed write leaves the in-memory settings unchanged. |
| 58–66 | Prefer an explicit run-folder argument, then the remembered folder. Expand `~` and resolve the chosen path; otherwise use `runs` beside preferences. |
| 69–75 | Define the native operations used by the protected local API. Hold preferences and reserve the window reference until its creation. |
| 77–79 | Enable sounds only for the exact saved boolean `true`; a missing or invalid value leaves them off. |
| 81–85 | Accept only a boolean on/off choice and save it through the preference writer. There is no additional sound setting. |
| 87–95 | Import the optional native window library only when exporting. Require text no larger than 512 KB and a plain suggested filename ending in `.json` or `.md`. Reject directory components in that suggestion. |
| 97–103 | Open the native save dialog, return `False` for cancellation, and resolve its selected destination. Accept either the string or sequence form returned by the native library. |
| 105–108 | Check each ancestor of the resolved destination. A `run.json` protects running and interrupted records; `manifest.json` also protects completed runs. Reject an export inside any of them. Following the resolved path also checks a symlink's destination. |
| 109–110 | Write the exported text as UTF-8 and return success. File errors propagate to the API's error response. |
| 113–120 | Ask the platform file manager to show the folder: Windows `startfile`, Mac `open`, or Linux `xdg-open`. Arguments are passed directly, without a shell. |
| 123–129 | Acquire the update lock without blocking and stop if another check is active or the window already closed. |
| 130–132 | Read the release status off the UI thread and discard it if the app closed during the lookup. |
| 134–139 | Ask before opening a newer release's download page; otherwise show its status. JSON encoding keeps alert text a safe JavaScript argument. |
| 140–143 | Log native dialog errors and always release the check lock. |
| 146–150 | Report whether the workspace has an active worker that is still running. |
| 153–157 | Start the native application with optional run and settings folders. Load pywebview, its menus, and the existing workspace/server only on this desktop path. |
| 159–166 | Load preferences, place `desktop.log` beside them, and configure warning/error logging. A windowed bundle has no normal console streams, so missing output streams are directed to the log. |
| 168–175 | Create the loopback service on an available port. Attach native operations, prepare its daemon thread, and initialize the flag and lock that make cleanup run once. A separate lock permits one update check/dialog at a time. |
| 177–183 | Define cleanup; use the enclosing flag under its lock and return if a window event or finalizer already closed the app. Mark cleanup as entered before proceeding. |
| 184–188 | Shut down request handling only if the service thread actually started, avoiding a startup-failure deadlock. Close the workspace, which stops and joins any calculation worker. |
| 189–192 | Always close the listening socket, even if workspace cleanup raises. Join a still-running service thread for at most five seconds. |
| 194–196 | Let the update check read whether the app has closed. |
| 198 | Build the window URL from the actual assigned loopback port. |
| 200–208 | Define the Open runs folder action. Reject switching while a calculation is active, open the native folder dialog at the current collection, and leave everything unchanged on cancellation. |
| 210–217 | Lock the old workspace and check again because a run could start while the dialog was open. Create the selected workspace, remember its path, close the old workspace, then assign the new one to the service. |
| 218–220 | Reload the existing window against the new collection. Present filesystem or selection errors through the page's existing error display; JSON encoding keeps error text safe as a JavaScript argument. |
| 222–228 | Define Show runs folder, and Check for Updates, which starts a daemon thread with the window, close-state reader and update lock. |
| 230–233 | Begin the guarded startup sequence. Save the selected run folder, start the service, and disable local `file:` URLs in the native view. |
| 234–237 | Create the white desktop window with its initial and minimum dimensions, allow text selection, and provide its reference to native exports. |
| 239–240 | Register cleanup on the native closing event. This also handles Mac Quit, which may terminate before the native event loop returns. |
| 241–244 | Add the two File actions and Help → Check for Updates, then enter pywebview's private session. |
| 245–249 | Log startup/event-loop failures and re-raise them. Always call cleanup when the native loop finishes or startup fails. |
| 252–258 | Normalize supplied or process arguments and detect the internal `--worker` entry before any window startup. |
| 259–264 | Restore missing output/error streams in a windowed frozen worker. Duplicate the descriptors the parent redirected to that worker's retained log; line buffering preserves progress text. |
| 265–266 | Send all remaining worker arguments to the existing CLI and return its exit code. This runs the shared solver without opening another window. |
| 267–271 | Define normal desktop flags, parse optional run/settings paths, and launch the window. |
| 274–275 | When invoked as a module, execute `main` and return its result as the process exit status. |

## `packaging/desktop_entry.py`

| Lines | What they do and why |
|---|---|
| 1–3 | Identify the frozen entry point and import the same desktop dispatcher used by the source installation. |
| 5–6 | Run that dispatcher and propagate its exit code, including a calculation worker's failure code. |

## `packaging/ald-reactor.spec`

| Lines | What they do and why |
|---|---|
| 1–6 | Describe the target and import paths, the small source-version reader, platform detection and package-data collection. |
| 8–10 | Resolve the repository and read `__version__` from its source without importing the package. |
| 12–15 | Collect package assets plus readable source snapshots, and include the project license, notices and complete third-party license tree in the bundle. |
| 17–20 | Use the existing icon only on Mac builds. |
| 22–29 | Analyze the desktop entry and exclude unused GUI frameworks/test shells. Archive Python modules, build the windowed executable with the icon, and collect binaries/data. |
| 31–38 | Create the Mac app with its existing identifier and icon, shared version in both version fields, macOS 14 minimum and light appearance. |

## `packaging/make_icon.py`

| Lines | What they do and why |
|---|---|
| 1–4 | Describe the icon build and import paths and Pillow. |
| 6–9 | Open the supplied white-backed PNG beside the script and save its Mac ICNS. The workspace uses the supplied transparent companion. |

`packaging/requirements-macos-lock.txt` pins one verified Mac build environment,
including transitive libraries, the numerical runtime, tests and packaging tools.
Each nonblank line names a package and its exact version; it contains no program
control flow. These build pins do not claim Windows or Intel Mac verification.
The package's normal runtime requirements remain in `pyproject.toml`.
