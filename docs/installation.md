# Installation and local verification

For the standalone Mac app, see the [desktop guide](desktop-guide.md). The built
app includes Python and the solver; the setup below is for source development
and command-line use.

Use Python 3.12 for the pinned environment verified for local verification. The
package declares Python ≥3.11; other Python/OS combinations need their own check.
Normal reactor use needs NumPy and SciPy. Tests add pytest; historical figures
add Matplotlib. Quantum-calculation packages are not part of this installation.

From the repository root on macOS/Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/ald-twin processes
.venv/bin/ald-twin inspect synthetic-ab
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python -m pytest -q
```

From the repository root in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
$env:OPENBLAS_NUM_THREADS = "1"
$env:VECLIB_MAXIMUM_THREADS = "1"
.\.venv\Scripts\ald-twin.exe processes
.\.venv\Scripts\ald-twin.exe inspect synthetic-ab
.\.venv\Scripts\python.exe -m pytest -q
```

The Windows procedure is documented but not locally verified on this Mac. A
fresh environment downloads dependencies from the configured package index;
without network access it needs previously downloaded compatible wheels.

Activate the environment (`source .venv/bin/activate` on macOS/Linux) to use
`ald-twin` without its full path. An editable install is required for subprocess
CLI tests: pytest's source-path setting alone does not install the package.

## If a command stops

| Message or symptom | What to check |
|---|---|
| `ald-twin` is not found | Use `.venv/bin/ald-twin` or the Windows executable above. Activate the environment to use the short command. |
| `No module named ald_twin` | Run the editable installation with the same environment's Python. Setting pytest's source path does not install the CLI for child processes. |
| The output folder already exists | Choose a new folder name. Existing runs retain their inputs, results and hashes. |
| An input or units error | Run `inspect` on the JSON file. Correct the field identified in the error using the input reference. Missing physical values have no fallback. |
| `UNVERIFIED` | Read the reason and attempts in `run.json`. The solver reached its numerical limit or a check failed. Keep the result; do not weaken its criteria. |
| Numerical PASS with recipe `fail` | The calculation passed numerical checks, but its recipe missed a completion, purge or applicability requirement. Read the two decisions separately. |
| `Saved run changed` | Compare against an intact saved run. Editing a saved report or result invalidates its manifest; a new calculation needs a new folder. |
| A historical command cannot find configuration or raw results | Use the repository checkout containing those records. The wheel bundles the new examples, not the full study archive. |

An exit code of 0 from `simulate` means numerical verification passed. The
recipe can still fail; its status is in `recipe_feasibility`. Exit code 1 means
the run completed unverified, and 2 means a command or input error. Use `status`
to inspect progress while a calculation is running. If you interrupt it, completed
attempts remain on disk; the single-run workflow does not resume them.

## Distribution build

```sh
.venv/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist
python3.12 -m venv work/wheel-check
work/wheel-check/bin/python -m pip install -r requirements-lock.txt
work/wheel-check/bin/python -m pip install --no-deps dist/ald_reactor_digital_twin-0.1.0-py3-none-any.whl
```

Then, from an empty directory outside the checkout, call that environment's
absolute `ald-twin` path with `processes`, `inspect synthetic-ab`, and
`simulate synthetic-ab --output NEW_FOLDER`. The wheel contains the two process
JSON files, the local GUI, its three generated sound cues and the existing viewer template.
It does not bundle historical result
archives, benchmark sources, docs, tests or optional QC tooling.

The historical `run`, `case` and `report` workflows require a repository checkout
and its original source/configuration/evidence files. They are not standalone
wheel examples. The new `simulate`, `inspect` and `compare` workflow is the
portable package entry point. Run `ald-twin gui` for the browser workspace;
see [gui-guide.md](gui-guide.md). It uses the same installed Python environment.

## Historical workflows

The portable application and full regression suite are included here. Historical
study commands also depend on source documents and raw results kept in the
original research checkout. Do not run completed campaigns again to recreate
those omitted files. Their limitations are recorded in [model-limits.md](model-limits.md).
