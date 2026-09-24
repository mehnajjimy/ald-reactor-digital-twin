"""copy notices from the pinned mac build environment into a new directory."""

import argparse
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import sys

# file name starts that mark a license or notice file
NOTICE_PREFIXES = ("license", "copying", "copyright", "notice")

# code and config files that only look like notices by name
SKIPPED_SUFFIXES = (".py", ".pyc", ".so", ".yml")

# where the python license sits inside the base python install
CPYTHON_LICENSE = "lib/python3.12/LICENSE.txt"


def is_notice(path):
    """true for a package file that looks like a license or notice."""
    file = Path(str(path))
    if not file.name.lower().startswith(NOTICE_PREFIXES):
        return False
    return file.suffix not in SKIPPED_SUFFIXES


def notice_files(root, name, package):
    """list a package's notice files, or the bundled upstream copy if it ships none."""
    files = []
    for path in package.files or []:
        if is_notice(path):
            files.append(path)
    if files:
        return files

    # every pyobjc-* package shares the pyobjc-core license
    if name.startswith("pyobjc-"):
        fallback = "pyobjc-core"
    else:
        fallback = name
    return [root/"licenses/upstream"/(fallback+"-LICENSE.txt")]


def collect(destination):
    """copy each pinned package's notices plus the python license, with an inventory."""
    root = Path(__file__).resolve().parents[1]
    destination.mkdir(parents=True, exist_ok=False)
    records = []

    # one pinned package per line, as name==version
    for pin in (root/"packaging/requirements-macos-lock.txt").read_text().splitlines():
        name, version = pin.split("==")
        package = distribution(name)
        if package.version != version:
            raise ValueError(f"{name}: expected {version}, found {package.version}")
        for path in notice_files(root, name, package):

            # installed files are relative to the package, upstream copies are absolute
            if isinstance(path, Path) and path.is_absolute():
                source = path
            else:
                source = package.locate_file(path)
            if source.is_relative_to(root/"licenses/upstream"):
                relative = Path(path.name)
            else:
                relative = Path(str(path))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unexpected license path: {path}")

            # copy the file and record where it came from
            target = destination/name/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            target.write_bytes(data)
            records.append({"package": name, "version": version, "source_path": str(relative),
                "file": str(target.relative_to(destination)), "sha256": hashlib.sha256(data).hexdigest()})

    # the python license comes from the interpreter that runs the build
    source = Path(sys.base_prefix)/CPYTHON_LICENSE
    data = source.read_bytes()
    (destination/"CPython-LICENSE.txt").write_bytes(data)
    records.append({"package": "CPython", "version": sys.version.split()[0], "source_path": CPYTHON_LICENSE,
        "file": "CPython-LICENSE.txt", "sha256": hashlib.sha256(data).hexdigest()})
    (destination/"inventory.json").write_text(json.dumps(records, indent=2)+"\n")
    print(f"Copied {len(records)} notices to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    collect(parser.parse_args().destination)
