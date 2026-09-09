# ALD reactor digital twin

This project calculates delivery, transport and surface reaction in a repeating
ALD cycle. It compares a well-mixed reactor with a spatial channel using the
same equations and precursor accounting.

All supplied process inputs are synthetic. **DEZ remains a placeholder.**
Numerical verification, recipe feasibility and physical validity are separate
questions. The software does not establish real DEZ transport, experimental
agreement or readiness to operate a reactor.

## Install and run

Use Python 3.12 from this folder on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/ald-twin inspect synthetic-ab
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/ald-twin simulate synthetic-ab --output runs/first-ab
.venv/bin/ald-twin compare runs/first-ab
.venv/bin/ald-twin gui
```

`inspect` validates the input and calculates flow without integrating a cycle.
`simulate` saves the input, solver sources, every numerical attempt and a report
in a new folder. `compare` checks saved files and reads their results without
calculating. Each calculation needs a new output folder.

The fictional A/B example has no film mapping. Its verified reference recipe
leaves about 13.43% A termination after the B pulse, above the 10% limit. Its
numerical check passes while its recipe fails. The ZnO-equivalent example has a
fixed conditional mapping at 150 °C; this is not experimental growth.

## What is still missing

The main gap is a tested comparison with experimental growth data under
conditions the model can represent. The published DEZ/H₂O ZnO data have been
audited, but physical calibration and predictions for the reserved test
conditions have not been completed. TMA/H₂O remains the reference chemistry;
a future ZnO comparison would not validate its kinetics.

The app's full-cycle examples are limited to a parallel-plate channel, one
effective surface population and a conditional reaction model at 150 °C.
Different temperatures, reactor layouts and film chemistries need their own
supported inputs and model checks. Experimental data import and QCM analysis
are not implemented. The existing synthetic studies also do not establish
physical uncertainty bounds or an experimentally supported optimum recipe.

## Where the DEZ work stands

The missing transport input is the gas diffusivity of diethylzinc (DEZ) in
nitrogen. It controls how quickly DEZ spreads through the carrier gas, which
affects how much precursor reaches each part of the surface. Fitting a reaction
rate to compensate for an invented diffusivity would mix those two effects.

Separate quantum-chemistry work is checking whether DEZ–N₂ molecular interaction
calculations can support a diffusivity estimate. At the recorded September 8,
2026 checkpoint, the Mac calculation had reached its roughly two-hour time
limit. The initial Hartree–Fock calculation converged, but its stability check
did not finish and the higher-level energy calculation had not started. A PC
continuation package is prepared; no returned PC result is recorded here.

There is no accepted interaction energy or physical DEZ diffusivity yet. Even
a successful first calculation would need further interaction and collision
calculations before it could produce a transport property with a stated
uncertainty. The app therefore keeps its synthetic diffusion value. Replacing
that value would still leave checks on flow, surface transport and parameter
identifiability before physical fitting could begin.

## Planned work

The next scientific priority is to resolve DEZ transport, finish the physical
model checks, and then fit the smallest supported parameter set to the audited
growth data. Predictions would be checked against the reserved conditions.
That evidence would support a broader comparison of when the well-mixed model
makes the same recipe decisions as the spatial model.

Several app additions are under consideration:

- **Custom precursor records:** easier entry of properties, units and sources,
  with missing inputs kept explicit. A new precursor name alone cannot define
  its reaction chemistry or film growth.
- **Reactor specifications:** documented dimensions and operating conditions
  from papers, patents or measured equipment. Each geometry must fit the flow
  model; a patent description alone does not validate a particular machine.
- **Experimental data and QCM:** import measured growth and, later, quartz
  crystal microbalance data. QCM work would start with calibrated mass changes
  after purge, with recipe timing and sensor location recorded. Full transient
  fitting needs a supported model of what the sensor measures.
- **Additional film systems:** assess a specific silicon-containing ALD
  chemistry once its transport, reactions and mass accounting are established.
  Silicon dioxide and elemental silicon would be separate process models.

These additions are not current capabilities or a fixed delivery schedule.
The manual **Check for Updates…** menu is already implemented; connecting it to
actual releases waits for the GitHub repository to be created.

## Interface

The local workspace uses white and light-gray panels, square controls and
restrained blue accents. It runs the same solver as the command line. It shows
progress, retains stopped attempts and opens saved results with their inputs.
Sound has one on/off toggle. This source folder includes quiet original tones
generated by `packaging/make_public_sounds.py`, with no external recordings.

The [desktop guide](docs/desktop-guide.md) explains the native Mac wrapper and
build. Only Apple Silicon macOS has been locally verified. Windows and Intel
Mac packaging have not been verified.

## Guides and tests

- [Installation](docs/installation.md): setup, tests, wheel packaging and errors.
- [Inputs](docs/input-reference.md): fields, units, equations and acceptance.
- [Examples](docs/worked-examples.md): recipes and saved comparisons.
- [Adding a process](docs/adding-a-process.md): supported input changes and gates.
- [GUI](docs/gui-guide.md): controls, saved files and shutdown.
- [Code map](docs/maintainer-guide.md): calculation and application boundaries.
- [Model limits](docs/model-limits.md): scientific scope and retained limitations.

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python -m pytest -q
```

This source folder includes the full regression suite and its small fixtures.
It excludes private source archives, QC handoffs, completed study results,
internal planning records, local runs and built apps. Some legacy study commands
need records retained in the research checkout; the portable entry points are
`inspect`, `simulate`, `compare` and `gui`. Do not recreate historical studies to
fill an absent archive.

Original code and documentation use the [MIT license](LICENSE). See
[third-party notices](THIRD_PARTY_NOTICES.md) for dependencies and assets,
[scientific references](docs/references.md) for sources and their roles, and
`CITATION.cff` to cite the software. Supplied recordings and source archives
remain excluded. The [release guide](docs/release-guide.md) covers updates.

The [code reading guide](docs/code-guide.md) links all line-by-line explanations.
