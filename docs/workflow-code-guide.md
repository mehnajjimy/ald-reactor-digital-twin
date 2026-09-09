# Input and workflow code explained

These ranges cover every nonblank line in `src/ald_twin/process_inputs.py` and
`src/ald_twin/workflow.py`. Each row explains one small block, including its
declaration, checks and return. Blank lines separate blocks. Line numbers refer
to this reviewed version; update them when either file changes.

The original numerical modules supply the equations and frozen checks. These
two modules validate explicit inputs, call that engine and preserve its output.
The DEZ-like example remains synthetic. Numerical acceptance, recipe feasibility
and physical validity remain separate decisions.

## process_inputs.py

| Lines | Explanation |
|---|---|
| 1–10 | State the synthetic scope. Import independent copying, JSON and paths; reuse the existing flow, grid, chemistry, segment and numeric validators. |
| 12–20 | Locate the packaged examples. Define the exact SI unit labels and the five sections that need provenance. A unit label never converts a value. |
| 23–24 | Read the packaged JSON examples in filename order for a stable catalog. |
| 27–33 | Accept an existing input file or match an example by its filename stem. Raise an input error if neither exists; otherwise decode its JSON. |
| 36–41 | Start the shared validator and require an input object before accessing fields. Return issues as text. |
| 42–48 | Verify that all values, including retained metadata, can be saved as finite JSON. Return an input issue for unsupported objects, NaN or infinity. |
| 49–58 | Define the allowed top-level fields, report unexpected names, and require object-shaped channel, diffusion, chemistry and recipe sections. Stop this inspection early if their structure is unusable. |
| 59–61 | Require exactly two diffusion objects, keyed `a` and `b`. |
| 62–65 | Require an explicit reactive interval and integer schema version 1. Boolean `true` is not a version number. |
| 66–73 | For each species, reject unsupported diffusion fields and require a nonempty source description with synthetic provenance. |
| 74–80 | Require process labels, synthetic kind, a closed physical-fitting gate and the supported two-event model. |
| 81–86 | Require exactly two nonempty species labels and the exact declared unit map. |
| 87–93 | Inspect each provenance section. Missing or malformed records become issues; valid records need source text, synthetic source type and validity text. |
| 94–98 | Check channel arguments through the existing flow function and restrict this path to 423.15 K. No temperature kinetics are inferred. |
| 99–108 | Check the positive trace scale and its 0.01 ceiling. Validate chemistry and require both event rates to be positive for recurring-cycle diagnostics. |
| 109–116 | Require two numeric, nonnegative reactive positions. Build one matched grid to check interval bounds, transport and positive reactive area. |
| 117–118 | Convert missing, malformed or overflowing reactor values into an input issue. |
| 119–125 | Require exactly four named recipe segments. Check each duration is positive and no more than 20 residence times. |
| 126–132 | Require at least two integer grids between 2 and 2560 cells, with each refinement doubling. Convert recipe or grid errors into issues. |
| 133–137 | Require the film field explicitly. Admit null or the fixed conditional ZnO mapping with density 5400 kg/m³. |
| 138–141 | Restrict that mapping to the original synthetic ZnO identifier and species labels. Return all collected issues. |
| 144–150 | Copy the caller's input so later edits cannot change the trial. Validate the copy and raise one readable error if needed. |
| 151–154 | Build the matched mixed grid. Divide carrier inventory by molar flow for residence time; multiply carrier flow by trace fraction for precursor feed. Read the duration ratios. |
| 155–159 | Construct A pulse, A purge, B pulse and B purge in that order. Convert each ratio to seconds, use zero precursor during purges, and return the validated inputs, chemistry, segments and residence time. |
| 162–168 | Inspect without integrating. Return original inputs, issues and the runnable flag, keeping physical fitting false. Invalid inputs do not proceed to derived outputs. |
| 169–171 | Prepare valid inputs and evaluate inlet/outlet pressure and mean velocity through the shared flow function. |
| 172–177 | Return residence time, pressure, velocity, segment seconds and integrated precursor dose. Label conditional ZnO growth or unavailable film output, then return the inspection. |

## workflow.py

| Lines | Explanation |
|---|---|
| 1–10 | State the single-recipe scope. Import dataclass conversion/replacement, UTC time, independent copying, JSON, paths, elapsed timing and numerical arrays. |
| 12–18 | Reuse the existing metrics, resolution checks, recipe decision, solver options, wall screen, grid and cycle engine. Import explicit validation, hashing, convergence checks and atomic JSON writing. |
| 21–26 | Obtain existing cycle metrics. Select cells with reactive area and compute turnover range divided by mean turnover; a zero mean leaves spread unavailable. |
| 27–33 | Default film output to unavailable. Only an admitted film mapping calls the existing ZnO conversion; average it over reactive area and label its conditional synthetic meaning. Return the summary. |
| 36–42 | Combine field and decision differences between two resolutions, then obtain turnover summaries. Growth comparisons use turnover so fictional A/B needs no invented film mass. |
| 44–51 | Compare mean turnover and relative spread. A value defined on only one side leaves growth convergence unresolved; otherwise retain the largest absolute change and return it with other differences. |
| 54–61 | Define the single-run API and progress contract. Validate all inputs before creating an output folder. |
| 62–68 | Resolve and create a new folder, refusing an existing one. Copy the package's Python sources and save the validated input snapshot. |
| 69–78 | Initialize synthetic status, labels, UTC start time, recipe, residence, input/source hashes, wall screen and empty attempts/results. Leave numerical and recipe acceptance unset; obtain frozen solver options. |
| 80–84 | The progress helper updates the stage, writes `run.json` atomically and sends an independent copy to an optional callback. |
| 86–95 | The solve helper announces and times one attempt. Construct its grid and call the shared recurring-cycle solver with tolerance 1e-7 and ceiling 200 cycles. Use denser saved times for the tighter repeat; carry the saved terminal state and original accounting origin into that repeat. |
| 96–100 | If recurrence fails, save the failed result and its checks, append an unverified attempt and propagate the failure to the run handler. |
| 101–106 | Save a successful attempt, including elapsed seconds, cycle count, checks and solver settings. Announce completion and return the result. This attempt status alone does not accept the entire run. |
| 108–109 | Bind each resolution comparison to this trial's segments, residence time and permitted film mapping. |
| 111–117 | Begin verification, solve the mixed reactor, then visit only the declared spatial grids. Keep the previous grid for comparison. |
| 118–125 | Compare successive grids and retain the change. Accept the first spatial result satisfying the existing 0.001 convergence limit and 0.05 diffusion-ratio ceiling; otherwise advance to the next declared grid. |
| 126–128 | If no spatial result passed, mark the run numerically unverified and record the declared ceiling. |
| 129–136 | For a spatially accepted run, tighten both solver tolerances tenfold and halve the maximum step. Repeat mixed and spatial results from their recurring states and save each temporal difference. |
| 137–140 | Stop acceptance if a temporal difference fails the existing 1e-5 check. Keep the attempt and failure reason. |
| 141–145 | Combine time change with spatial change where applicable. Use the largest gas, coverage, event or decision change as the numerical guard on the unchanged recipe decision; save each verified model summary. |
| 146–150 | This loop `else` runs only when neither temporal check broke. Translate the spatial recipe decision to pass, fail or unresolved; a failed wall screen makes the combined recipe/screen status outside-screen. |
| 151–156 | Mark numerical acceptance independently. Save accepted cell count, diffusion ratio, actual spatial profile, cycle seconds and delivered precursor moles. |
| 157–158 | Convert a recurrence failure into an unverified final record. |
| 159–163 | On interruption, retain completed attempts, set interrupted status, save progress and re-raise so the worker exits. No completed manifest is written. |
| 164–167 | On another calculation error, save error type/message and retained progress, then re-raise. |
| 168–176 | Record completion time and stage, then save the final record and report. Hash every saved artifact into the manifest. Send the final callback only after the manifest exists, then return the record. |
| 179–186 | Read the completed manifest and record from a resolved folder. Reject non-object JSON before looking up fields. |
| 187–197 | Require schema 1 and the closed synthetic physical gate. Permit only completed PASS/UNVERIFIED records with matching numerical flags and appropriate recipe status. |
| 198–206 | Require source hashes and attempts. Start the mandatory artifact set with record, inputs and report; add every recorded source with a plain filename. |
| 207–213 | Require a valid filename label for every attempt. Add its JSON and NPZ artifacts, then reject a manifest missing any mandatory entry. |
| 214–218 | Resolve each manifest path, reject absolute paths or parent traversal, keep it inside the run folder and compare its actual bytes with its recorded hash. Missing/unreadable files also fail the read. |
| 219–221 | Match input and source hashes against the copies stored in `run.json`; rebuilding a manifest alone cannot relabel a calculation. |
| 222–225 | Decode inputs and compare their identifier, name and recipe with the displayed run record. |
| 226–233 | Decode each attempt's metadata and require its full parameter snapshot, chemistry and trace scale to match the saved inputs. Return the checked record labelled saved output. These local consistency checks are not a digital signature. |
| 236–244 | Read and verify each requested saved run. Return only comparison fields and the synthetic limitation; no integration, optimization or uncertainty propagation occurs. |
| 247–252 | Define readable report rows and unpack the two species' purge-clearance, consumption and escape values. |
| 253–260 | Convert completion fractions to percent, retain scaled purge residuals, and distinguish an uncleared purge from a numeric clearance time of zero. |
| 261–267 | Label minimum/mean turnover, relative spread and each species' consumed/delivered and escaped/delivered fractions. |
| 268–271 | Add cycle seconds and equivalent ZnO growth, keeping unsupported growth null. Return the row list. |
| 274–278 | Begin the Markdown report with its process name, synthetic gate and separate numerical and recipe/screen decisions. |
| 279–284 | Include a failure reason when present. For each available model, choose its mixed/spatial title, show film status and open the output table. |
| 285–293 | Format each output: null becomes unavailable, existing text is retained, and numbers use eight significant digits. Append table rows and spacing. |
| 294–298 | Explain uncleared, zero and unavailable values, keep rounding confined to this report, identify retained evidence and write the Markdown file. |
