# CLI and package code, explained

Each table covers the file in order. Blank lines only separate sections. These
are statement-level explanations so the source stays short and readable.

## `src/ald_twin/cli.py`

| Lines | Meaning |
|---|---|
| 1–9 | Describe the CLI; import argument parsing, JSON, paths and standard streams. Reuse the existing study runner, source hashing and atomic JSON writer. |
| 11–19 | Name the four segments as flag names and recipe keys, and the keys printed after a simulation and by `status` for one run. |
| 22–26 | Add the base, plan and required output options shared by the historical `run` and `case` commands. |
| 29–32 | Create the parser and require a named command. |
| 34–38 | Register GUI startup, run collection, port and optional browser suppression. |
| 40–43 | Register process listing and input inspection; inspection accepts an ID or path. |
| 45–50 | Register a single simulation of any valid process, require an output folder, and add the same numeric duration override for each of the four fixed segments. |
| 52–54 | Register saved comparison with at least one run folder. |
| 56–66 | Retain the historical `run`/`case` commands with shared configuration paths. Give a study its resume flag; give a case explicit pulse, purge and scenario arguments. |
| 68–74 | Register historical report generation and read-only status; return the parser. |
| 77–81 | Read packaged process records and print their IDs, names and kinds, synthetic or estimate. |
| 84–91 | Load and inspect inputs, print strict JSON, and return whether inputs are runnable. No integration occurs. |
| 94–96 | Stream actual stage messages to stderr with immediate flushing, so stdout stays JSON. |
| 99–105 | Load a simulation input and reject missing/non-object recipe data before overrides. |
| 107–111 | Apply only supplied duration overrides; preserve every omitted duration. |
| 113–120 | Call the shared workflow. Print result decisions and models. Exit 0 means numerics passed; recipe feasibility remains separate. |
| 123–126 | Read and verify saved comparisons and print them without solving. |
| 129–134 | Find a historical case's declared scenario by name, or return `None`. |
| 137–148 | Read a historical case's configurations and reject an unknown scenario. Require a new folder, snapshot the case inputs/hashes, run the declared case and print status. |
| 151–161 | For `status`, print an explicit run's raw progress fields. This is polling, not manifest verification. |
| 163–178 | Otherwise read a historical study's status, counts and permanently false physical-fit flag, in output order so a damaged record reports its first missing key. |
| 181–203 | Dispatch each command. Import and start the GUI only when requested. The bounded study and report commands are unchanged. |
| 206–213 | Parse an optional argument list in `main`; convert input/file errors to a concise argparse error and exit code 2. |
| 216–217 | When run as a module, pass `main`'s result to the process exit status. |

The loops enumerate four recipe fields, two historical commands or saved data.
They do not create another solver, retry policy or hidden campaign.

## `pyproject.toml`

| Lines | Meaning |
|---|---|
| 1–3 | Require setuptools 77 or newer for the SPDX license metadata and build with setuptools. |
| 5–13 | Declare identity, dynamic version, MIT license and bundled notice files, scope, README, supported Python and numerical dependencies. |
| 15–17 | Register the CLI and desktop entry points. |
| 19–22 | Keep tests, scientific plotting and the native window optional. |
| 24–28 | Find packages in `src` and read the version from `ald_twin.__version__`. |
| 30–31 | Include process fixtures, viewer, interface and sound assets in the wheel. |
| 33–35 | Configure pytest's test and source locations. |

## `.github/workflows/tests.yml`

| Lines | Meaning |
|---|---|
| 1–4 | Name CI, run it for pushes/pull requests and grant read-only repository access. This file itself performs no push. |
| 5–7 | Define one Linux test job. This does not claim native Mac or Windows verification. |
| 8–11 | Use one numerical-library thread and a noninteractive plotting backend. |
| 12–16 | Check out source and install Python 3.12. |
| 17–19 | Install Node 22 for the dependency-free browser-state tests. |
| 20–21 | Install pinned dependencies and the editable package with that environment. |
| 22–23 | Run the full Python suite and the actual workspace JavaScript regressions. |
| 24–25 | Build a wheel and replace the editable package with its installed contents. |
| 26–28 | Run the remaining checks outside the checkout to prevent accidental source imports. |
| 29–31 | List and inspect both packaged examples without solving. |
| 32–33 | Verify both GUI entry points can parse help without starting a service. |
| 34 | Require each packaged interface and sound file. A missing package-data rule fails CI. |

## `.gitignore`

| Lines | Meaning |
|---|---|
| 1–8 | Ignore local Python environments/caches, OS metadata and build/work products. |
| 9–10 | Keep new raw recipe runs on disk while excluding them from commits. |
| 11–19 | Retain compact historical gate records while ignoring large Phase 4/5 histories. `!` explicitly keeps a named record eligible for tracking. |
| 20–25 | Apply the same rule to comparison and sensitivity histories. |
| 26–32 | Ignore raw process-study cases/refinements while keeping their compact `case.json` evidence. |

Ignore rules do not remove files from disk or stop tracking an already committed
file. The separate source export has simpler rules because it contains no
historical result archive.

## `packaging/make_public_sounds.py`

| Lines | Meaning |
|---|---|
| 1–8 | State the purpose and import standard-library tools for arguments, paths, JSON, mathematics, PCM bytes and WAV files. |
| 10–17 | Set a 24 kHz mono 16-bit format, the full-scale sample value and a quiet 0.15 peak amplitude. |
| 19–20 | Name three explicit pitch/duration pairs. |
| 23–31 | Build one tone: visit each sample, apply a squared-sine envelope that reaches zero at both ends, and store a quiet sine wave as signed little-endian 16-bit PCM. |
| 34–37 | Accept an output path and require a new directory, preventing accidental replacement of local recordings. |
| 38–43 | For each cue, calculate its sample count and write a mono, uncompressed WAV with that count and rate. |
| 45–51 | Save the generator identity, absence of external recordings and each cue's parameters. |
| 54–57 | Parse the required output directory only when the script is executed, then generate the files. |

The tones are for the clean export. The installed app's approved recordings are
unchanged. This script uses no network service or third-party audio source.
