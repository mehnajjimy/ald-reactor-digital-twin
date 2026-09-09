# Worked synthetic examples

Install as described in [installation.md](installation.md). Run commands from
the repository with its environment activated. Each `simulate` command below
starts one new bounded recipe calculation, with matched 0D/1D and numerical checks.
Output folders must not already exist. Use a new name for each changed trial.

## 1. Existing conditional ZnO-equivalent mapping

```sh
ald-twin inspect synthetic-zno
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 ald-twin simulate synthetic-zno --output runs/zno-example
ald-twin status runs/zno-example
```

Inspect the channel, explicitly synthetic diffusivity and effective rates first.
This fixture exports the Pe=2, Da=3 mathematical inputs as SI values. It keeps
the A pulse / purges / B pulse ratios 3 / 5 / 3 with two purges. Film output uses
the existing conditional ZnO mapping at 150 °C. It is not experimental growth.
This single recipe is not a repeat of the 63-pair scenario study or its selection.

## 2. Fictional second process

```sh
ald-twin inspect synthetic-ab
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 ald-twin simulate synthetic-ab --output runs/ab-example
ald-twin compare runs/zno-example runs/ab-example
```

The second input changes capacity, B kinetics and B transport by labelled
mathematical factors. The equations stay the same. `mean_gpc_angstrom` remains
null, while surface turnover, completion, purge and delivery outputs are retained.
The comparison reads hash-checked saved records and performs no calculation.

The measured example passes numerical verification at 1280 cells but leaves
13.433% A termination after the B pulse, above the 10% limit. It therefore fails
the recipe constraints. This result demonstrates why a numerical pass and a
successful recipe need separate labels. These changes were made together, so the
comparison does not isolate the contribution of any one changed input.

New `report.md` files show readable labels and units, with values rounded for
reading. Purge clearance reads "Not cleared" when the purge never cleared, while
a missing film output reads "Unavailable". Earlier saved reports retain their
original format and hashes. `run.json` retains full scalar metrics and
the final spatial turnover profile. Attempt JSON/NPZ files retain states and
accounting. `inputs.json`, `sources/` and `manifest.json` establish run provenance.
Do not edit saved files; make a new input and new output folder instead.

## Recipe change or custom file

```sh
ald-twin simulate synthetic-ab --b-pulse 4 --output runs/ab-longer-b
ald-twin compare runs/ab-example runs/ab-longer-b
```

That optional command is another calculation; it does not run merely because a
saved comparison is opened. It is not part of the baseline example verification.
For changes beyond durations, copy a process JSON and pass its path to `inspect`
and `simulate`. [Adding a process](adding-a-process.md) names the files/functions.

## Python entry points

The CLI calls the same functions available to a maintainer or a future GUI:

```python
from ald_twin.process_inputs import inspect_process, load_process
from ald_twin.workflow import compare_runs, run_process

inputs = load_process("synthetic-ab")
inspection = inspect_process(inputs)  # validates inputs and calculates flow only
print(inspection["issues"])

# This call starts a new calculation; choose an unused output folder.
result = run_process(inputs, "runs/ab-python")
comparison = compare_runs(["runs/ab-python"])  # reads and verifies saved files
```

Check `inspection["runnable"]` before offering a Run button. The runner also
validates inputs itself, so calling it directly cannot bypass the input gates.

## Reading acceptance

A completed numerical PASS may still fail the recipe constraints or wall screen.
UNVERIFIED means the numerical budget/ceiling did not establish the result; it is
not a recipe pass. A null clearance is an uncleared purge, not zero seconds.
All outputs remain synthetic. Neither a passing example nor a changed recipe
closes the physical transport, applicability, inference or holdout gates.

The numerical and physical limitations remain in [model-limits.md](model-limits.md).
