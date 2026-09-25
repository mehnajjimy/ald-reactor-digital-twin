# Input and workflow code explained

These ranges cover every nonblank line in `src/ald_twin/process_inputs.py` and
`src/ald_twin/workflow.py`. Each row explains one small block, including its
declaration, checks and return. Blank lines separate blocks. Line numbers refer
to this reviewed version; update them when either file changes.

The original numerical modules supply the equations and frozen checks. These
two modules validate explicit inputs, call that engine and preserve its output.
The DEZ-like example remains synthetic. The DEZ and water process is an
estimate built from published values and labelled assumptions. It is not fitted
or validated. Numerical acceptance, recipe feasibility and physical validity
remain separate decisions.

## process_inputs.py

| Lines | Explanation |
|---|---|
| 1–10 | State the synthetic and estimate scope. Import independent copying, JSON and paths; reuse the existing flow, grid, chemistry, segment and numeric validators. |
| 12–22 | Locate the packaged examples. Define the exact SI unit labels and the five sections that need provenance. A unit label never converts a value. |
| 24–38 | Name the allowed top-level and diffusion fields, the object sections, the four recipe segments, the synthetic source type, the two process kinds and the three estimate source types. Fix 423.15 K, the 0.01 trace scale and 20 residence times per synthetic segment. |
| 39–46 | Allow estimates up to 10000 residence times per segment. Grids run from 2 cells up to 2560, or up to 20480 for estimates because real diffusivities need finer grids. |
| 47–51 | Fix the synthetic ZnO mapping and species labels, and the estimated ZnO mapping name with its DEZ and H2O species. |
| 54–62 | Read the packaged JSON examples in filename order for a stable catalog. |
| 65–77 | Accept an existing input file or match an example by its filename stem. Raise an input error if neither exists; otherwise decode its JSON. |
| 80–91 | Small shared checks: nonblank text, and the sorted names of unexpected fields. |
| 94–102 | Require exactly two nonempty species labels, keyed `a` and `b`. |
| 105–119 | Valid provenance records need source text and validity text. Synthetic records need the synthetic source type. Estimate records need an estimate source type and an uncertainty note. |
| 122–133 | Require at least two integer grids between 2 cells and the given ceiling, with each refinement doubling. |
| 136–145 | Check channel arguments through the existing flow function and restrict this path to 423.15 K. No temperature kinetics are inferred. Issues found before an error are kept. |
| 146–155 | Check the positive trace scale and its 0.01 ceiling. Validate chemistry and require both event rates to be positive for recurring-cycle diagnostics. |
| 156–163 | Require two numeric, nonnegative reactive positions. Build one matched grid to check interval bounds, transport and positive reactive area. |
| 166–171 | Require exactly four named recipe segments. |
| 172–182 | Use ceilings of 10000 residence times and 20480 cells for estimates, otherwise 20 and 2560. Check each duration is positive and within its ceiling, then check the spatial grids. |
| 185–192 | Start the shared validator and require an input object before accessing fields. Return issues as text. |
| 193–199 | Verify that all values, including retained metadata, can be saved as finite JSON. Return an input issue for unsupported objects, NaN or infinity. |
| 201–209 | Report unexpected top-level names and require object-shaped channel, diffusion, chemistry and recipe sections. Stop this inspection early if their structure is unusable. |
| 210–215 | Require exactly two diffusion objects, keyed `a` and `b`. |
| 217–222 | Require an explicit reactive interval and integer schema version 1. Boolean `true` is not a version number. |
| 223–233 | Read the process kind. For each species, reject unsupported diffusion fields and require a nonempty source description. Synthetic inputs need synthetic provenance and estimates need an estimate source type with an uncertainty note. |
| 234–241 | Require process labels, a synthetic or estimate kind, a closed physical-fitting gate and the supported two-event model. |
| 242–246 | Require exactly two nonempty species labels and the exact declared unit map. |
| 247–256 | Inspect each provenance section against the process kind. Missing or malformed records become issues that name what that kind needs. |
| 258–263 | Convert missing, malformed or overflowing reactor values into an input issue. |
| 264–267 | Convert recipe or grid errors into issues. |
| 269–274 | Require the film field explicitly. An estimate film goes to its own check below. |
| 275–277 | Otherwise admit null or the fixed conditional ZnO mapping with density 5400 kg/m³. |
| 278–280 | Restrict that mapping to the original synthetic ZnO identifier and species labels. Return all collected issues. |
| 283–290 | Check an estimated film. Null is allowed. Otherwise require exactly a mapping and a density, and stop there if not. |
| 291–298 | Require the estimated ZnO mapping name, species DEZ and H2O, and a positive density. Each failure becomes an issue. |
| 301–309 | Copy the caller's input so later edits cannot change the trial. Validate the copy and raise one readable error if needed. |
| 311–316 | Build the matched mixed grid. Divide carrier inventory by molar flow for residence time; multiply carrier flow by trace fraction for precursor feed. Read the duration ratios. |
| 317–321 | Construct A pulse, A purge, B pulse and B purge in that order. Convert each ratio to seconds, use zero precursor during purges, and return the validated inputs, chemistry, segments and residence time. |
| 324–330 | Inspect without integrating. Return original inputs, issues and the runnable flag, keeping physical fitting false. Invalid inputs do not proceed to derived outputs. |
| 331–333 | Prepare valid inputs and evaluate inlet/outlet pressure and mean velocity through the shared flow function. |
| 334–346 | Return residence time, pressure, velocity, segment seconds and integrated precursor dose. Label estimated ZnO growth, conditional synthetic ZnO growth or unavailable film output, then return the inspection. |

## workflow.py

| Lines | Explanation |
|---|---|
| 1–10 | State the single-recipe scope. Import dataclass conversion/replacement, UTC time, independent copying, JSON, paths, elapsed timing and numerical arrays. |
| 12–19 | Reuse the existing metrics, resolution checks, recipe decision, solver options, wall screen, grid and cycle engine. Import the process kinds, explicit validation, hashing, convergence checks, change measures and atomic JSON writing. |
| 21–36 | Name the recurrence tolerance 1e-7 and ceiling of 200 cycles, the saved-time counts, the 0.001 spatial and 1e-5 time limits, the 0.05 diffusion-ratio ceiling, the accepted recipe states, the saved label fields and the comparison fields. |
| 39–51 | Obtain existing cycle metrics. Select cells with reactive area and compute turnover range divided by mean turnover; a zero mean leaves spread unavailable. |
| 52–61 | Default film output to unavailable. Only an admitted film mapping calls the existing ZnO conversion; average it over reactive area. Label it estimated or conditional synthetic by process kind, then return the summary. |
| 64–69 | Combine field and decision differences between two resolutions, then obtain turnover summaries. Growth comparisons use turnover so fictional A/B needs no invented film mass. |
| 71–76 | Compare mean turnover and relative spread. A value defined on only one side leaves growth convergence unresolved; otherwise retain the largest absolute change and return it with other differences. |
| 79–90 | Translate the spatial recipe decision to pass, fail or unresolved; a failed wall screen makes the combined recipe/screen status outside-screen. |
| 93–102 | Define the single-run API and progress contract. Validate all inputs before creating an output folder. |
| 103–112 | Resolve and create a new folder, refusing an existing one. Copy the package's Python sources and save the validated input snapshot. |
| 113–125 | Initialize the process kind from the inputs, status, labels, UTC start time, recipe, residence, input/source hashes, wall screen and empty attempts/results. Leave numerical and recipe acceptance unset; obtain frozen solver options. |
| 127–133 | The progress helper updates the stage, writes `run.json` atomically and sends an independent copy to an optional callback. |
| 135–160 | The solve helper announces and times one attempt. Construct its grid and call the shared recurring-cycle solver with tolerance 1e-7 and ceiling 200 cycles. Use denser saved times for the tighter repeat; carry the saved terminal state and original accounting origin into that repeat. |
| 161–165 | If recurrence fails, save the failed result and its checks, append an unverified attempt and propagate the failure to the run handler. |
| 166–171 | Save a successful attempt, including elapsed seconds, cycle count, checks and solver settings. Announce completion and return the result. This attempt status alone does not accept the entire run. |
| 173–176 | Bind each resolution comparison to this trial's segments, residence time and permitted film mapping. |
| 178–187 | Begin verification, solve the mixed reactor, then visit only the declared spatial grids. Keep the previous grid for comparison. |
| 188–196 | Compare successive grids and retain the change. Accept the first spatial result satisfying the existing 0.001 convergence limit and 0.05 diffusion-ratio ceiling; otherwise advance to the next declared grid. |
| 197–199 | If no spatial result passed, mark the run numerically unverified and record the declared ceiling. |
| 200–211 | For a spatially accepted run, tighten both solver tolerances tenfold and halve the maximum step. Repeat mixed and spatial results from their recurring states and save each temporal difference. |
| 212–216 | Stop acceptance if a temporal difference fails the existing 1e-5 check. Keep the attempt and failure reason. |
| 217–223 | Combine time change with spatial change where applicable. Use the largest gas, coverage, event or decision change as the numerical guard on the unchanged recipe decision; save each verified model summary. |
| 224–226 | This block runs only when neither temporal check failed. Take the combined recipe/screen status from the spatial decision and the wall screen. |
| 227–231 | Mark numerical acceptance independently. Save accepted cell count, diffusion ratio, actual spatial profile, cycle seconds and delivered precursor moles. |
| 232–233 | Convert a recurrence failure into an unverified final record. |
| 234–238 | On interruption, retain completed attempts, set interrupted status, save progress and re-raise so the worker exits. No completed manifest is written. |
| 239–242 | On another calculation error, save error type/message and retained progress, then re-raise. |
| 244–257 | Record completion time and stage, then save the final record and report. Hash every saved artifact into the manifest. Send the final callback only after the manifest exists, then return the record. |
| 260–278 | Require schema 1, a synthetic or estimate kind and the closed physical gate. Permit only completed PASS/UNVERIFIED records with matching numerical flags and appropriate recipe status. |
| 281–288 | Start the mandatory artifact set with record, inputs and report; add every recorded source with a plain filename. |
| 289–296 | Require a valid filename label for every attempt and add its JSON and NPZ artifacts. |
| 299–306 | Resolve each manifest path, reject absolute paths or parent traversal, keep it inside the run folder and compare its actual bytes with its recorded hash. Missing/unreadable files also fail the read. |
| 309–316 | Read the completed manifest and record from a resolved folder. Reject non-object JSON before looking up fields. |
| 317–325 | Check the run status and require source hashes and attempts. Reject a manifest missing any mandatory entry, then check every manifest file. |
| 327–336 | Match input and source hashes against the copies stored in `run.json`; rebuilding a manifest alone cannot relabel a calculation. |
| 337–342 | Decode inputs and compare their identifier, name and recipe with the displayed run record. |
| 344–353 | Decode each attempt's metadata and require its full parameter snapshot, chemistry and trace scale to match the saved inputs. Return the checked record labelled saved output. These local consistency checks are not a digital signature. |
| 356–367 | Read and verify each requested saved run. Keep only comparison fields and note each run's kind. |
| 369–375 | Label the comparison synthetic if any run is synthetic, otherwise estimate. Return the rows and the limitation; no integration, optimization or uncertainty propagation occurs. |
| 378–385 | Define readable report rows and unpack the two species' purge-clearance, consumption and escape values. |
| 386–397 | Convert completion fractions to percent, retain scaled purge residuals, and distinguish an uncleared purge from a numeric clearance time of zero. |
| 398–404 | Label minimum/mean turnover, relative spread and each species' consumed/delivered and escaped/delivered fractions. |
| 405–408 | Add cycle seconds and equivalent ZnO growth, keeping unsupported growth null. Return the row list. |
| 411–418 | Format each output: null becomes unavailable, existing text is retained, and numbers use eight significant digits. |
| 421–427 | Pick the report's basis line by process kind. Estimated inputs are labelled not fitted or validated, and synthetic inputs keep physical fitting blocked. |
| 428–431 | Begin the Markdown report with its process name, basis line and separate numerical and recipe/screen decisions. |
| 432–440 | Include a failure reason when present. For each available model, choose its mixed/spatial title, show film status and open the output table. |
| 441–443 | Append table rows and spacing. |
| 444–448 | Explain uncleared, zero and unavailable values, keep rounding confined to this report, identify retained evidence and write the Markdown file. |
