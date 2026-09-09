# Third-party notices

The root MIT license covers the project's original code and documentation.
Third-party software and supplied assets retain their own terms. The scientific
sources in [references](docs/references.md) are citations, not redistributed papers.

`licenses/` contains unmodified notices from the pinned Mac build environment,
including nested notices for bundled numerical, image and font libraries.
`licenses/bundled/inventory.json` records package versions, original paths and hashes.
The wheel and desktop bundle include these texts; the app stores them in
`Contents/Resources/licenses`. This inventory includes build/test tools as well
as runtime dependencies so their notices survive the source export.

| Component | Role and notice |
|---|---|
| CPython | Interpreter; PSF license and incorporated notices; additional static-library notices are in `licenses/upstream/python-*-LICENSE.txt` |
| NumPy, SciPy | Numerical arrays, integration and optimization; BSD-style licenses and bundled third-party notices |
| pywebview, Bottle | Native window and its dependencies; BSD and MIT notices respectively |
| proxy_tools | BSD notice from its source and upstream repository; its installed metadata incorrectly labels it MIT |
| PyObjC core and Cocoa/Quartz/Security/WebKit/UniformTypeIdentifiers bindings | macOS bridge; MIT notices. This build links to macOS's system libffi |
| Pillow, Matplotlib and supporting packages | Included by the pinned build; retain image-codec, font and package notices |
| PyInstaller | Packaging tool; its GPL exception permits distribution under the application's license subject to dependency terms |

For dependency updates, run `packaging/collect_licenses.py` with the pinned build
Python into a new directory, compare the inventory, and review the actual bundle.
The upstream fallback texts and their source URLs/hashes are retained in
`licenses/upstream/`; some installed wheels did not include those texts.
Python's static-library notices cover bzip2, Expat, libedit, libffi, liblzma,
libuuid, mpdecimal, ncurses, OpenSSL 3, SQLite and zlib. Their source archive is
the interpreter build project's license collection; do not infer exact library
versions from those notice filenames. Recheck the inventory when changing runtimes.
See [PyInstaller's license explanation](https://pyinstaller.org/en/stable/license.html).

The existing ALD monogram comes from `packaging/make_icon.py`. This release does
not include or modify the separate lily concepts. The public source export uses
original tones from `packaging/make_public_sounds.py`, covered by the project
license. Supplied recordings under the research checkout's `ui/audio/`, source
archives, papers and private data are excluded from that license and public export.
The locally installed app retains the supplied sounds for personal use; do not
redistribute that local bundle as the public build. Build a public app from the
clean source export instead.

Software citation is requested through `CITATION.cff`; it is not an additional
condition on MIT reuse. No external source's license or ownership is changed by
adding a citation here.
