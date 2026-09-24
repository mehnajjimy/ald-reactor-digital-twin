"""build on the target os. the verified local artifact is macos arm64."""

from pathlib import Path
import runpy
import sys
from PyInstaller.utils.hooks import collect_data_files

# read the version from the package without importing it
root = Path(SPECPATH).parent
version = runpy.run_path(root/"src/ald_twin/__init__.py")["__version__"]

# bundle readable sources so each run can record its solver hashes.
data = collect_data_files("ald_twin", include_py_files=True)
data += [(str(root/name), ".") for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")]
data += [(str(root/"licenses"), "licenses")]

# the icon file is only used for mac builds
icon = None
if sys.platform == "darwin":
    icon = str(root/"packaging/ald-reactor.icns")

# collect the app with its data, leaving out packages the app does not need
analysis = Analysis([str(root/"packaging/desktop_entry.py")],
    pathex=[str(root/"src")], datas=data,
    excludes=["pytest", "IPython", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"])
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
    name="ALD Reactor", console=False, icon=icon)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name="ALD Reactor")

# on mac, wrap the collection in an .app bundle
if sys.platform == "darwin":
    app = BUNDLE(collection, name="ALD Reactor.app", icon=str(root/"packaging/ald-reactor.icns"),
        bundle_identifier="local.aldreactor.workspace",
        info_plist={"CFBundleDisplayName":"ALD Reactor", "CFBundleName":"ALD Reactor",
            "CFBundleShortVersionString":version, "CFBundleVersion":version,
            "LSMinimumSystemVersion":"14.0", "NSHighResolutionCapable":True,
            "NSRequiresAquaSystemAppearance":True})
