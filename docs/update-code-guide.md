# Update and license code, explained

These ranges cover every nonblank line of the two new modules. Related statements
share an explanation; the source keeps its short functions and useful comments.

## `src/ald_twin/updates.py`

| Lines | Meaning |
|---|---|
| 1–9 | Describe the manual lookup and import JSON, version matching, HTTP errors, URL encoding and HTTPS requests. Read the package's sole version constant. |
| 11–13 | Set the public release destination to `mehnajjimy/ald-reactor-digital-twin`. No credentials or run data are sent. |
| 16–21 | Require a stable three-part numeric tag, optionally prefixed with `v`. Convert its parts to integers so 0.10.0 sorts after 0.9.0. Reject prereleases and malformed tags. |
| 24–32 | Select the configured or explicitly supplied repository and prepare installed-version text. Missing or malformed locations return a local message without networking. |
| 33–34 | Construct the fixed GitHub API endpoint and public JSON/User-Agent headers. No credentials or run inputs are sent. |
| 35–39 | Open the request with a five-second socket timeout. Read at most one byte over 1 MB so an oversized response is rejected. Close the response on leaving the context. |
| 40–45 | Parse JSON, require a stable non-draft release object, and parse its tag and the installed version before comparison. |
| 46–53 | Distinguish absent public releases, access/rate limits and other HTTP failures; none claims the app is current. |
| 54–55 | Turn connection, timeout, decoding and malformed-response errors into a concise failure message. |
| 56–61 | For a newer release, construct a GitHub release-page URL from the configured repository and validated tag. Ignore remote URL fields. Return a confirmation question and that destination. |
| 62–63 | Distinguish equal versions from a local build ahead of the public release, with no download offer. |

`src/ald_twin/__init__.py` lines 1–3 state the verification scope and define
`__version__`. Package metadata, desktop packaging and the updater read that value.
The [desktop code guide](desktop-code-guide.md) explains the menu and dialog code.

## `packaging/collect_licenses.py`

| Lines | Meaning |
|---|---|
| 1–8 | Describe the build-only collector and import argument, hashing, installed metadata, JSON, path and interpreter tools. |
| 11–14 | Resolve the repository and require a new output directory, preserving the existing notice snapshot. Start an inventory. |
| 15–19 | Visit the explicit build pins and reject an installed version that differs from the lock. |
| 20–22 | Select license/copyright/notice files, excluding Python code and compiled test artifacts whose names happen to match. |
| 23–26 | If a wheel lacks text, require the retained upstream notice. PyObjC bindings share the core's MIT notice; other packages need their own fallback. |
| 27–31 | Resolve the installed or fallback file and reject absolute/traversing destination paths. |
| 32–37 | Preserve the notice bytes under its package/path and record version, source path and SHA-256. No license is rewritten. |
| 38–42 | Copy the Python 3.12 interpreter license and record the actual interpreter version/hash. Static-library notices are retained separately in `licenses/upstream`. |
| 43–44 | Save the inventory and report the copied count. |
| 47–50 | Parse one destination and invoke the collector when run as a script. |

The collector is not an automatic determination of redistribution rights. The
notices and actual bundled dependencies are reviewed together. `CITATION.cff`
describes software attribution; `LICENSE` and the retained third-party texts
describe reuse terms. These files contain metadata/text, not runtime logic.
