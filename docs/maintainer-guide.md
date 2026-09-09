# Code and calculation map

Use the [input reference](input-reference.md) to connect a field to an output.
All example inputs remain synthetic. The DEZ placeholder does not establish a
physical transport property. Keep code changes small, names clear and comments
focused on assumptions or units. Do not change equations or thresholds to make
a case pass.

## Calculation

1. `cli.build_parser` defines arguments; `cli.main` dispatches the command.
   `process_inputs.load_process` reads a packaged JSON or an explicit file.
2. `process_inputs.prepare_inputs` validates fields, units, provenance and model
   gates, computes residence time and constructs four recipe segments.
3. `workflow.run_process` creates a new folder and snapshots inputs and sources.
4. `cycle_transport.channel_grid` builds cell inventories and conductances using
   `channel_flow.channel_flow`. `cycles.periodic_cycle` calls the shared solver.
   `CycleChemistry.rates` supplies event rates; `composition_fluxes` supplies the
   same transport fluxes used in the cumulative ledger.
5. Existing recurrence, grid, temporal, conservation and bounds checks decide
   numerical acceptance. Recipe decisions and physical status stay separate.
6. The workflow saves attempt JSON/NPZ files, `run.json`, `inputs.json`, readable
   sources, `report.md` and an artifact manifest. `read_run` checks saved files;
   `compare_runs` reads results without calculating.

Surface turnover is available without an invented material identity. Only the
fixed conditional ZnO mapping calls `periodic_gpc`; fictional A/B film output
stays null. Rounding belongs in the readable report, not in stored metrics.

Progress callbacks receive independent records. A Complete notification follows
finished artifact writing. Polling clients must wait for a valid manifest and
use `read_run`, because a terminal status alone cannot verify saved output.

## Application

The loopback-only server in `gui.py` serves `ui/index.html`, `workspace.css`,
`workspace.js` and local sounds. API calls require a per-launch token. One worker
runs the same CLI calculation with single-thread numerical settings. The server
waits for worker exit and verifies completed artifacts before loading a result.
A numerical UNVERIFIED result with intact files remains a valid saved result.

The interface keeps the edited input draft separate from saved output. Opening
a result uses its stored inputs. A stop retains completed attempts. The sound
control has one on/off state. Keep the white/light-gray engineering layout and
restrained blue accents; do not add decorative information.

`desktop.main` starts the same service in a native pywebview window. Native file
dialogs use the protected API, and closing the app stops its worker and service.
`gui.worker_command` chooses the Python CLI or frozen `--worker` entry point.
The PyInstaller specification includes readable Python sources for snapshots.
Preferences remember the run collection and sound setting.

The export's original tones come from `packaging/make_public_sounds.py`. To
regenerate them, give `--output` a new directory and replace the sound files only
after checking them. The script refuses an existing output directory.

## Layout and checks

| Location | Purpose |
|---|---|
| `src/ald_twin/` | Equations, runners, saved reports, CLI and desktop |
| `src/ald_twin/processes/` | Two explicit synthetic process files |
| `src/ald_twin/ui/` | Shared interface and generated local sounds |
| `config/synthetic/` | Frozen mathematical regression fixtures |
| `config/benchmarks/benchmark-a.json` | Dimensionless test fixture and unresolved metadata |
| `tests/` | Numerical, provenance, application and interface regressions |
| `packaging/` | Native entry point, build specification, icon and tone generation |
| `docs/` | Public usage guides, scientific limits and this code map |
| `runs/`, `work/`, `build/`, `dist/` | Ignored local calculations and products |

Run the Python suite after affected calculation or application changes. Run
`node --test tests/workspace.test.cjs` for browser state regressions; it uses
Node 22 with no package installation. Build/install the wheel outside the
checkout to check packaged examples and assets. Native changes also require an
actual Apple Silicon Mac bundle check before replacing an installed app.

The retained verification scripts support regression tests. Historical
campaigns require the original research archive. This export's
`process-study-plan.md` is a static public contract at the path expected by the
unchanged study runner; it cannot resume records hashed against the original
document. The [model limits](model-limits.md) preserve unresolved scientific points.

The [code reading guide](code-guide.md) links all line-by-line explanations.

See the [update code guide](update-code-guide.md) and [release steps](release-guide.md)
for the manual updater, versioning and notice inventory.
