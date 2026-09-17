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

The lily icons use the owner's supplied full render from `LILY_BRAND_ASSETS_V3`,
added at the owner's request on 2026-09-16. The white-backed
`github/github-profile-from-gimp-512.png` is retained as `packaging/ald-reactor.png`;
`packaging/make_icon.py` packages it for macOS. Its supplied transparent companion,
`github/github-profile-from-gimp-transparent-512.png`, is retained as
`src/ald_twin/ui/lily.png` so the workspace header shows no white square.
The artwork is provided for this app's branding; the code's MIT license does
not grant a separate license to reuse the owner's branding.

The public source uses original tones from `packaging/make_public_sounds.py`,
covered by the project license. Supplied recordings in the research checkout,
source archives, papers and private data are excluded from the public export.
Build public apps from the clean source export.

Software citation is requested through `CITATION.cff`; it is not an additional
condition on MIT reuse. No external source's license or ownership is changed by
adding a citation here.
