# Desktop code, line by line

These tables cover every nonblank line in the reviewed desktop wrapper and build
scripts. Related lines share a row so the explanation stays beside the operation
it explains. The source remains short; no second annotated copy is maintained.
Line numbers refer to this maintenance review and must follow later source edits.

## `src/ald_twin/desktop.py`

| Lines | What they do and why |
|---|---|
| 1–14 | Describe the wrapper and import its tools: `argparse` for launch flags, `json` for preferences and error text, `logging` for failures, `os` for platform paths and streams, `Path` for files, `subprocess` for Finder, `sys` for launch arguments, locks for shared state, and `Thread` for the service. Reuse the existing atomic JSON writer and release checker; `webbrowser` opens a confirmed download page. |
| 17–22 | Choose the normal application-data folder for macOS, Windows or Linux. The Mac path is under the user's Library; the other paths respect their platform environment variables. This chooses storage only and makes no directory yet. |
| 25–30 | Define preferences; resolve and create their folder, name `preferences.json`, and allocate a reentrant lock for updates from different request threads. |
| 31–36 | Read the saved JSON object. Missing, unreadable, malformed or non-object preferences fall back to an empty object. Nothing in the run collection is changed. |
| 38–42 | Lock an update, merge new values with existing ones, write the new object atomically, then update memory. A failed write leaves the in-memory settings unchanged. |
| 44–46 | Prefer an explicit run-folder argument, then the remembered folder. Expand `~` and resolve the chosen path; otherwise use `runs` beside preferences. |
| 49–54 | Define the native operations used by the protected local API. Hold preferences and reserve the window reference until its creation. |
| 56–57 | Enable sounds only for the exact saved boolean `true`; a missing or invalid value leaves them off. |
| 59–62 | Accept only a boolean on/off choice and save it through the preference writer. There is no additional sound setting. |
| 64–69 | Import the optional native window library only when exporting. Require text no larger than 512 KB and a plain suggested filename ending in `.json` or `.md`. Reject directory components in that suggestion. |
| 70–73 | Open the native save dialog, return `False` for cancellation, and resolve its selected destination. Accept either the string or sequence form returned by the native library. |
| 74–77 | Check each ancestor of the resolved destination. A `run.json` protects running and interrupted records; `manifest.json` also protects completed runs. Reject an export inside any of them. Following the resolved path also checks a symlink's destination. |
| 78–79 | Write the exported text as UTF-8 and return success. File errors propagate to the API's error response. |
| 82–86 | Ask the platform file manager to show the folder: Windows `startfile`, Mac `open`, or Linux `xdg-open`. Arguments are passed directly, without a shell. |
| 89–95 | Acquire the update lock without blocking and stop if another check is active or the window already closed. |
| 96–98 | Read the release status off the UI thread and discard it if the app closed during the lookup. |
| 99–103 | Ask before opening a newer release's download page; otherwise show its status. JSON encoding keeps alert text a safe JavaScript argument. |
| 104–107 | Log native dialog errors and always release the check lock. |
| 110–113 | Start the native application with optional run and settings folders. Load pywebview, its menus, and the existing workspace/server only on this desktop path. |
| 115–121 | Load preferences, place `desktop.log` beside them, and configure warning/error logging. A windowed bundle has no normal console streams, so missing output streams are directed to the log. |
| 122–128 | Create the loopback service on an available port. Attach native operations, prepare its daemon thread, and initialize the flag and lock that make cleanup run once. A separate lock permits one update check/dialog at a time. |
| 130–135 | Define cleanup; use the enclosing flag under its lock and return if a window event or finalizer already closed the app. Mark cleanup as entered before proceeding. |
| 136–140 | Shut down request handling only if the service thread actually started, avoiding a startup-failure deadlock. Close the workspace, which stops and joins any calculation worker. |
| 141–144 | Always close the listening socket, even if workspace cleanup raises. Join a still-running service thread for at most five seconds. |
| 146 | Build the window URL from the actual assigned loopback port. |
| 148–155 | Define the Open runs folder action. Reject switching while a calculation is active, open the native folder dialog at the current collection, and leave everything unchanged on cancellation. |
| 156–162 | Lock the old workspace and check again because a run could start while the dialog was open. Create the selected workspace, remember its path, close the old workspace, then assign the new one to the service. |
| 163–165 | Reload the existing window against the new collection. Present filesystem or selection errors through the page's existing error display; JSON encoding keeps error text safe as a JavaScript argument. |
| 167–170 | Begin the guarded startup sequence. Save the selected run folder, start the service, and disable local `file:` URLs in the native view. |
| 171–174 | Create the white desktop window with its initial and minimum dimensions, allow text selection, and provide its reference to native exports. |
| 175–176 | Register cleanup on the native closing event. This also handles Mac Quit, which may terminate before the native event loop returns. |
| 177–181 | Add the two File actions and Help → Check for Updates. The latter starts a daemon thread with the window, close-state reader and update lock. Enter pywebview's private session. |
| 182–186 | Log startup/event-loop failures and re-raise them. Always call cleanup when the native loop finishes or startup fails. |
| 189–191 | Normalize supplied or process arguments and detect the internal `--worker` entry before any window startup. |
| 192–196 | Restore missing output/error streams in a windowed frozen worker. Duplicate the descriptors the parent redirected to that worker's retained log; line buffering preserves progress text. The two-item loop handles only these two streams. |
| 197–198 | Send all remaining worker arguments to the existing CLI and return its exit code. This runs the shared solver without opening another window. |
| 199–203 | Define normal desktop flags, parse optional run/settings paths, and launch the window. |
| 206–207 | When invoked as a module, execute `main` and return its result as the process exit status. |

## `packaging/desktop_entry.py`

| Lines | What they do and why |
|---|---|
| 1–2 | Identify the frozen entry point and import the same desktop dispatcher used by the source installation. |
| 4 | Run that dispatcher and propagate its exit code, including a calculation worker's failure code. |

## `packaging/ald-reactor.spec`

| Lines | What they do and why |
|---|---|
| 1–5 | Describe the target and import paths, the small source-version reader, platform detection and package-data collection. |
| 7–10 | Resolve the repository, read `__version__` from its source and collect package assets plus readable source snapshots. |
| 11–12 | Include the project license, notices and complete third-party license tree in the bundle. |
| 13–15 | Analyze the desktop entry and exclude unused GUI frameworks/test shells. |
| 16–20 | Archive Python modules, build the windowed executable with the existing icon, and collect binaries/data. |
| 21–27 | Create the Mac app with its existing identifier and icon, shared version in both version fields, macOS 14 minimum and light appearance. |

## `packaging/make_icon.py`

| Lines | What they do and why |
|---|---|
| 1–3 | Describe the build-only icon generator and import filesystem paths plus Pillow's image and drawing tools. |
| 5–8 | Create a transparent 1024-pixel-square image, attach a drawing context, draw the light rounded base and outline, then the blue horizontal accent. Coordinates and stroke widths are pixels. |
| 9–12 | Use a fixed blue ink and straight strokes for the A and its crossbar. Fixed coordinates avoid an installed-font dependency. |
| 13 | Draw the L with one connected stroke. |
| 14–15 | Draw the D outline with connected coordinates, the same ink and a rounded stroke join. |
| 16–18 | Find the script's folder and save PNG and Mac ICNS copies there. These are the icon files used by the bundle. |

`packaging/requirements-macos-lock.txt` pins one verified Mac build environment,
including transitive libraries, the numerical runtime, tests and packaging tools.
Each nonblank line names a package and its exact version; it contains no program
control flow. These build pins do not claim Windows or Intel Mac verification.
The package's normal runtime requirements remain in `pyproject.toml`.
