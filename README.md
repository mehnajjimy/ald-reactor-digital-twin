# ALD reactor digital twin

How much precursor reaches the end of an ALD reactor? How long does it take to
clear after a pulse? This project follows the gas and surface through each cycle
and compares a simple well-mixed model with one that resolves the channel.

**[Download for Mac](https://github.com/mehnajjimy/ald-reactor-digital-twin/releases/download/v1.0.0/ALD-Reactor-1.0.0-macOS-arm64.zip)** · **[Install guide](docs/install.md)**

Desktop tested only on Apple Silicon macOS. This build is not Apple-notarized.

**66 Python tests · [CI verified](https://github.com/mehnajjimy/ald-reactor-digital-twin/actions/workflows/tests.yml) · 0D + spatial transport · Mac desktop + CLI**

**The examples are synthetic. DEZ is still a placeholder, and the model has not
yet been validated against experiments.**

![A and B delivery, surface conversion and conditional mass response](docs/media/ald-cycle.png)

![Matched 0D and spatial predictions of completion and turnover](docs/media/model-comparison.png)

![Precursor transport and surface conversion along the channel over one cycle](docs/media/transport-heatmap.png)

![ALD Reactor desktop app displaying a saved synthetic result](docs/media/desktop-app.png)

These plots come from a saved simulation. The mass trace is a model estimate,
not QCM data. [How the figures were made](docs/readme-figures.md).

## What it shows

In this example, the 0D model predicts 97.8% A completion. The spatial model finds
91.1% at the channel outlet. That difference matters when a recipe must work
across the whole surface.

A larger synthetic study checked 63 recipe/scenario pairs. Every calculation
passed its numerical checks, but no recipe worked across every scenario.
Nine earlier high-Peclet cases and one capacity-profile point remain unverified.
Getting the math right and finding a working recipe are separate questions.

## Run from source

Use Python 3.12. On macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/ald-twin gui
```

Or inspect and calculate an example from the command line:

```sh
.venv/bin/ald-twin inspect synthetic-ab
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/ald-twin simulate synthetic-ab --output runs/first-ab
.venv/bin/ald-twin compare runs/first-ab
```

The app, CLI and Python API use the same solver. Runs keep their inputs, results
and source hashes so you can check where a result came from. The fictional A/B
example reports surface turnover; it has no thickness conversion.

The standalone Mac app has been tested locally on Apple Silicon. Windows
packaging is not verified. [Installation](docs/installation.md) and the
[desktop guide](docs/desktop-guide.md) cover setup and builds.

## DEZ and what comes next

DEZ transport is the main unfinished piece. Separate molecular calculations are
checking whether we can estimate how fast DEZ diffuses through nitrogen. The Mac
attempt hit its two-hour limit before the stability check finished. A PC handoff
is ready, but there is no accepted interaction energy or diffusivity here yet.

Next is to resolve that input, finish the physical model checks, then compare
with published ZnO growth data using separate fitting and test conditions.
TMA/H₂O remains the reference chemistry; ZnO results won't validate TMA kinetics.

I'd also like to make custom precursor inputs easier, add documented reactor
specifications, and bring in experimental data, including QCM. Other films,
including silicon-containing systems, need their own chemistry and transport
checks first. For now, the app is for offline simulation and comparison.

## Guides and sources

- [Inputs](docs/input-reference.md): units, assumptions and acceptance criteria.
- [Examples](docs/worked-examples.md): changing recipes and comparing saved runs.
- [Code guide](docs/code-guide.md): calculation path and line-by-line explanations.
- [Adding a process](docs/adding-a-process.md): supported changes and their limits.
- [Releases](docs/release-guide.md): builds and the manual update check.

Original code and documentation use the [MIT license](LICENSE).
[References](docs/references.md) explain the scientific sources;
[third-party notices](THIRD_PARTY_NOTICES.md) cover dependencies and assets.
Use [CITATION.cff](CITATION.cff) to cite the software.
