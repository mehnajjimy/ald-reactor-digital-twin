# ALD Reactor desktop app

The native Mac wrapper opens the same [reactor workspace](gui-guide.md) without
a terminal. A built app contains Python, the solver, process examples, interface
and sounds. Apple Silicon macOS 14+ is the locally tested platform. Windows and
Intel Mac bundles have not been verified.

## Use

- File → Open runs folder chooses and remembers a collection of saved runs.
  Stop a calculation before changing collections.
- File → Show runs folder opens the collection in Finder.
- Open inputs, Save inputs and Save report use native dialogs. Export copies
  outside existing run folders to preserve saved records.
- Sounds on/off is the only sound control. A new user starts with sound off.
- Closing the window or choosing Quit stops the service and active worker.
  Completed attempts remain. Unsaved input edits are not restored.

The default runs, preferences and application log are under
`~/Library/Application Support/ALD Reactor/`. Worker logs are in the selected
run collection's `.gui/` folder. Choosing a collection does not move its files.

All examples remain synthetic. The DEZ values are placeholders. Opening the
app does not start a calculation or enable physical fitting.

## Build on an Apple Silicon Mac

Use Python 3.12 from the source folder:

```sh
python3.12 -m venv work/desktop-build
work/desktop-build/bin/python -m pip install -r packaging/requirements-macos-lock.txt
work/desktop-build/bin/python -m pip install --no-build-isolation --no-deps -e .
work/desktop-build/bin/python packaging/make_icon.py
PYINSTALLER_CONFIG_DIR="$PWD/work/desktop-cache" work/desktop-build/bin/python -m PyInstaller --noconfirm --distpath dist/desktop --workpath work/desktop-pyinstaller packaging/ald-reactor.spec
codesign --verify --deep --strict 'dist/desktop/ALD Reactor.app'
```

Quit any running build first. PyInstaller replaces its output, so preserve a
build that is needed as evidence. The app is written to
`dist/desktop/ALD Reactor.app`; copy it to an Applications folder after checking
startup, a real calculation, saved source hashes, native exports and shutdown.
Build success alone does not verify the solver worker.

This source export contains generated original tones. No private recording is
required. The Mac dependency lock includes the native window and build tools;
the ordinary browser/CLI installation remains smaller.

For development, run `work/desktop-build/bin/ald-reactor --runs "$PWD/runs"`.
Use `--settings /absolute/path` to isolate preferences during checks.

The local bundle uses an ad-hoc signature. Public Mac distribution requires
its own Developer ID signing and notarization. No built app is included in this
source folder.

## Version 0.1.2

The repeated sidebar and footer labels are removed; numerical, recipe and physical
status remain separate in the results. The logo and sound toggle are unchanged.
The desktop menu **Help → Check for Updates…** shows the installed version.
The update check now uses `mehnajjimy/ald-reactor-digital-twin`. Until a stable
release is published, it reports that no public release was found. See the [release guide](release-guide.md).
