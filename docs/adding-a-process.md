# Adding a precursor/co-reactant process

Adding a process starts with the equations it needs. If it uses the existing
single surface population and one-to-one A/B event loop, a labelled synthetic
example can be defined in one JSON file. A process with additional reactions or
surface populations needs a reviewed model change first. The walkthrough below
shows the first case; it does not establish arbitrary-precursor support.

## An example that fits the equations

Start with `src/ald_twin/processes/synthetic-ab.json`. It represents fictional
A*/B* with one site population: A fills available sites, B consumes the A
termination and restores availability. Capacity is constant, both rates are
first order in their own gas concentration, and stoichiometry is one-to-one.
Both events may respond to residual gas carried through the recipe switches.

Relative to `synthetic-zno.json`, this fixture uses 0.8 times capacity, 0.6 times
the B rate and 0.7 times B diffusion. Sources explicitly identify these as
mathematical choices. It keeps 423.15 K and sets `film: null`. Output is surface
turnover, completion, carryover and precursor accounting. Its verified example
fails the B-completion constraint, which remains part of the result. This checks
that changed inputs reach the solver and reports without assigning a real
material's chemistry or density.

In Python, use the installed example to create an input file:

```python
import json
from pathlib import Path
from ald_twin.process_inputs import load_process

with Path("my-synthetic-process.json").open("x") as file:
    json.dump(load_process("synthetic-ab"), file, indent=2)
```

Opening with `"x"` requires a new filename and preserves any existing file.
This creates an input only; it does not calculate a result.

1. Edit the new file's `id`, `name`, species,
   input values and per-section provenance. Keep units and explicit nulls.
2. Run `ald-twin inspect my-synthetic-process.json`. Address each missing or
   unsupported input. Inspection evaluates flow but does not integrate cycles.
3. Run `ald-twin simulate my-synthetic-process.json --output runs/my-process`.
   Every spatial/time attempt is retained; hitting the ceiling means UNVERIFIED.
4. Read `runs/my-process/report.md` and `ald-twin compare runs/my-process`.
   Keep numerical acceptance separate from recipe and physical acceptance.
5. To ship the example, place the reviewed JSON in `src/ald_twin/processes/`.
   `process_inputs.process_catalog` discovers it and the package-data rule in
   `pyproject.toml` includes it. No new class or solver registration is needed.
6. Add the relevant gate and agreement checks to `tests/test_explicit_workflow.py`
   and update the input guide. Preserve the original fixture and its results.

## Exact implementation boundaries

| Change | Files/functions and required evidence |
|---|---|
| Synthetic SI values or allowed recipe | Process JSON; `process_inputs.input_issues` and `prepare_inputs` define validation and segment construction. No equation edit for a compatible input. |
| Accepted physical diffusivity | Separate scientific review first; `cycle_transport.diffusivity` currently rejects physical properties. Supply source/range/uncertainty and validate pressure/temperature dependence before adding a physical route. Do not turn the synthetic flag off as a shortcut. |
| Surface event law or stoichiometry | `cycles.CycleChemistry.rates`, `solve_cycle`, `cycle_sparsity`, `CycleResult.checks` and observation mappings. Review state/equation meaning before implementing. |
| Extra transported species or populations | `cycle_transport.CycleGrid`, `composition_fluxes` and all state layout, scaling, sparsity, conservation and result code in `cycles.py`; this is a new model, not a JSON addition. |
| Film mass or thickness | `cycles.periodic_gpc` is specifically ZnO; `process_inputs.input_issues` gates it and `workflow.output_metrics` handles absent mapping. Another material needs atom/event balances, retained mass, density, range and uncertainty before a separately reviewed mapping. |
| Temperature dependence | The validator restricts 423.15 K. Accepted rate, transport, density and applicability relations plus new verification must precede widening it. |
| GUI support | Use `inspect_process`, `run_process`, `read_run` and `compare_runs`; display null outputs and scientific status. Do not add a separate calculator. |

## Processes that do not fit

Multiple site populations, reversible adsorption/desorption, coverage-dependent
rates, gas-phase reaction, plasma/radical kinetics, non-unit stoichiometry and
temperature-changing recipes require new chemistry and/or transport equations.
Film conformality inside features is not represented by a reactor channel model.
Do not approximate these effects by relabeling a rate or altering Gamma without
reviewing the model meaning.

For a reviewed equation change, establish independent analytical limits,
species/event and element balances, state bounds, exact switches, recurrence,
spatial/time convergence and observation consistency. Tests in `test_cycles.py`,
`test_transport_core.py`, `test_purge_events.py` and `test_explicit_workflow.py`
show the current checks. Matching a synthetic generator alone does not validate
real kinetics. Physical fitting still needs accepted properties, applicability,
identifiability, data and holdout verification.
