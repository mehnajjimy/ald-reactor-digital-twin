# CLI and package code, explained

Each table covers the file in order. Blank lines only separate sections. These
are statement-level explanations so the source stays short and readable.

## `src/ald_twin/cli.py`

| Lines | Meaning |
|---|---|
| 1–7 | Describe the CLI; import argument parsing, JSON, paths and standard streams. |
| 8–11 | Reuse the existing study runner, source hashing and atomic JSON writer. |
| 12–14 | Create the parser and require a named command. |
| 15–18 | Register GUI startup, run collection, port and optional browser suppression. |
| 19–21 | Register example listing and input inspection; inspection accepts an ID or path. |
| 22–24 | Register a single simulation and require an output folder. |
| 25–26 | Add the same numeric duration override for each of the four fixed segments. |
| 27–28 | Register saved comparison with at least one run folder. |
| 29–33 | Retain the historical `run`/`case` commands and shared configuration paths. |
| 34–39 | Give a study its resume flag; give a case explicit pulse, purge and scenario arguments. |
| 40–45 | Register historical report generation and read-only status; return the parser. |
| 46–50 | Separate definitions, then parse an optional argument list in `main`. |
| 51–54 | Enter command error handling; import and start the GUI only when requested. |
| 55–58 | Read packaged process records and print their IDs, names and synthetic labels. |
| 59–63 | Load and inspect inputs, print strict JSON, and return whether inputs are runnable. No integration occurs. |
| 64–69 | Load a simulation input and reject missing/non-object recipe data before overrides. |
| 70–73 | Apply only supplied duration overrides; preserve every omitted duration. |
| 74–75 | Call the shared workflow; stream actual stage messages to stderr with immediate flushing. |
| 76–78 | Print result decisions and models. Exit 0 means numerics passed; recipe feasibility remains separate. |
| 79–81 | Read and verify saved comparisons and print them without solving. |
| 82–83 | Dispatch the unchanged historical bounded-study command. |
| 84–88 | Read a historical case's configurations and find its declared scenario; reject an unknown name. |
| 89–93 | Require a new folder, snapshot the case inputs/hashes, run the declared case and print status. |
| 94–96 | Dispatch historical saved-report generation. |
| 97–101 | For `status`, print an explicit run's raw progress fields. This is polling, not manifest verification. |
| 102–106 | Otherwise read a historical study's status, counts and permanently false physical-fit flag. |
| 107–110 | Convert input/file errors to a concise argparse error and exit code 2; blank lines separate the entry point. |
| 111–112 | When run as a module, pass `main`'s result to the process exit status. |

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
| 1–10 | State the purpose and import standard-library tools for arguments, paths, JSON, mathematics, PCM bytes and WAV files. |
| 11–13 | Accept an output path and require a new directory, preventing accidental replacement of local recordings. |
| 14–15 | Set a 24 kHz sample rate and three explicit pitch/duration pairs. |
| 16–18 | For each cue, start an empty PCM buffer and calculate its sample count. |
| 19–21 | Visit each sample and apply a squared-sine envelope that reaches zero at both ends. |
| 22–23 | Calculate a quiet sine wave and store it as signed little-endian 16-bit PCM. |
| 24–26 | Write a mono, uncompressed WAV with the declared sample count and rate. |
| 27–31 | Save the generator identity, absence of external recordings and each cue's parameters. |
| 32–37 | Parse the required output directory only when the script is executed, then generate the files. |

The tones are for the clean export. The installed app's approved recordings are
unchanged. This script uses no network service or third-party audio source.
