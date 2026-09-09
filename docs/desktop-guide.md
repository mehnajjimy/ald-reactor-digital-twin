# ALD Reactor desktop app

The native Mac wrapper opens the same [reactor workspace](gui-guide.md) without
a terminal. A built app contains Python, the solver, process examples, interface
and sounds. The build targets Apple Silicon macOS 14+; testing used macOS 26.6.2. Windows and
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

The local bundle uses an ad-hoc signature. The downloadable release is not Developer ID signed or notarized. See the
[install guide](install.md) for the Mac download and first-launch instructions.

## Version 1.0.0

The public release includes a Mac app ZIP and an [install guide](install.md).
Testing used Apple Silicon macOS 26.6.2. The app is ad-hoc signed and not notarized.
The logo and sound toggle are unchanged; the public build uses original tones.
Use **Help → Check for Updates…** for a manual release check.
