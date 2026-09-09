"""copy notices from the pinned mac build environment into a new directory."""

import argparse
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import sys


def collect(destination):
    root = Path(__file__).resolve().parents[1]
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for pin in (root/"packaging/requirements-macos-lock.txt").read_text().splitlines():
        name, version = pin.split("==")
        package = distribution(name)
        if package.version != version:
            raise ValueError(f"{name}: expected {version}, found {package.version}")
        files = [path for path in package.files or []
            if Path(str(path)).name.lower().startswith(("license", "copying", "copyright", "notice"))
            and Path(str(path)).suffix not in (".py", ".pyc", ".so", ".yml")]
        if not files:
            fallback = "pyobjc-core" if name.startswith("pyobjc-") else name
            source = root/"licenses/upstream"/(fallback+"-LICENSE.txt")
            files = [source]
        for path in files:
            source = path if isinstance(path, Path) and path.is_absolute() else package.locate_file(path)
            relative = Path(path.name) if source.is_relative_to(root/"licenses/upstream") else Path(str(path))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unexpected license path: {path}")
            target = destination/name/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = source.read_bytes()
            target.write_bytes(data)
            records.append({"package": name, "version": version, "source_path": str(relative),
                "file": str(target.relative_to(destination)), "sha256": hashlib.sha256(data).hexdigest()})
    source = Path(sys.base_prefix)/"lib/python3.12/LICENSE.txt"
    data = source.read_bytes()
    (destination/"CPython-LICENSE.txt").write_bytes(data)
    records.append({"package": "CPython", "version": sys.version.split()[0], "source_path": "lib/python3.12/LICENSE.txt",
        "file": "CPython-LICENSE.txt", "sha256": hashlib.sha256(data).hexdigest()})
    (destination/"inventory.json").write_text(json.dumps(records, indent=2)+"\n")
    print(f"Copied {len(records)} notices to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    collect(parser.parse_args().destination)
