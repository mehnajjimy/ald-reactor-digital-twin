# Input reference

Use `ald-twin inspect PROCESS` to see the exact values, sources, units, validation
issues and derived flow before calculating. Packaged inputs live in
`src/ald_twin/processes/`. Copy one to a new JSON file to make an explicit trial;
pass that filename to `inspect` or `simulate`. Each run saves its validated inputs,
including recipe overrides, as `inputs.json`; the original file is not edited.

DEZ property work is continuing separately. The DEZ-like inputs shipped here are
synthetic placeholders. Replacing them with accepted properties later requires
new provenance and verification of the affected calculations; editing a number
does not by itself establish a physical result.

## What this model describes

Only synthetic `two-event-nu1` inputs at **423.15 K (150 °C)** are admitted by the
new workflow. Both examples use the existing effective one-to-one event loop:

```text
rA = Gamma * kA * cA * (1 - theta)
rB = Gamma * kB * cB * theta
dtheta/dt = (rA - rB) / Gamma
```

`theta` is the A-terminated fraction; B restores available sites. Each event
consumes one mole of its precursor per mole of events. A single site population,
constant capacity and constant effective rates are assumed. No chemical identity
or film property follows merely from renaming A and B.

## Values and locations

| JSON field | Units | Meaning and admitted range |
|---|---|---|
| `schema_version` | — | Exactly 1 |
| `id`, `name`, `species.a`, `species.b` | text | Explicit process and species labels |
| `kind`, `physical_fit_ready` | — | Exactly `synthetic`, `false` |
| `model` | — | Exactly `two-event-nu1` |
| `channel.length`, `width`, `height` | m | Positive dimensions; height is the full plate gap |
| `channel.temperature` | K | Exactly 423.15 in this workflow |
| `channel.outlet_pressure` | Pa | Positive absolute pressure, not inlet or uniform pressure |
| `channel.molar_flow` | mol/s | Positive prescribed carrier molar flow |
| `channel.viscosity` | Pa s | Positive constant carrier viscosity, explicitly synthetic here |
| `reactive_interval` | m | `[start, end]` within channel length; two facing reactive plates |
| `fraction_scale` | 1 | Positive inlet trace fraction and state scale, at most 0.01 here |
| `diffusivity.a`, `.b` | object | Each requires synthetic `kind`, nonempty text `source`, `source_type: synthetic_verification`, positive `value` (m²/s), `temperature` (K), `pressure` (Pa); optional `uncertainty` is retained as metadata |
| `chemistry.capacity` | mol/m² | Positive effective capacity Gamma |
| `chemistry.rate_a`, `.rate_b` | m³/(mol s) | Positive constant effective rates; no temperature extrapolation |
| `recipe.a_pulse`, `.a_purge`, `.b_pulse`, `.b_purge` | residence times | Four positive durations, each at most 20; order is fixed |
| `spatial_grids` | cell counts | At least two integer grids, each doubles; ceiling 2560 |
| `film` | object or null | Null means no thickness output; see below |
| `units` | field/unit map | Must exactly match `process_inputs.UNITS`; no automatic unit conversion |
| `provenance` | section records | Channel, transport, chemistry, recipe and film each need source, `synthetic_verification` type and explicit validity |

Both species enter at `channel.molar_flow * fraction_scale` during their own
pulse. Purges have zero precursor inlet while carrier flow continues. Unequal
feed fractions, arbitrary sequence topologies and other boundary choices are not
exposed by this small input format. Lower-level research APIs are documented
separately; accepting arguments there does not establish scientific validity.

The first fixture's SI values were exported from the existing mathematical
Pe=2, Da=3 fixture. The second changes capacity, B rate and B diffusion by declared
software factors. These are examples, not measured properties, recommended
operating ranges, uncertainties, or reconstructed experiments. Per-section
`uncertainty: null` means no distribution is available.

Schema version must be the integer `1`. Unknown diffusion fields are rejected;
adding an exponent to the input cannot change the transport law. Uncertainty
metadata is retained with the inputs but is not propagated by a single run.

## Flow and transport

`channel_flow.channel_flow` evaluates the same conditional isothermal, no-slip,
parallel-plate reduction used in the completed studies:

```text
p(z)^2 = p_out^2 + 24*mu*F*R*T*(L-z)/(width*height^3)
u(z) = F*R*T/(width*height*p(z))
residence = integral(carrier concentration * cross-section * dz) / F
D(z) = D_ref * p_ref/p(z), at the declared reference temperature only
```

`channel_grid` integrates the carrier inventory over each cell. Transport uses
composition gradients, prescribed inlet molar flux and a convective outlet.
The very same face fluxes supply gas balances and cumulative inlet/outlet ledgers.
This full-cycle path differs from the frozen Phase 1 constant-coefficient
concentration-gradient half-cycle; those earlier equations remain separate.

The flow reduction neglects side walls, slip, axial inertia and changes in total
molar flow. The wall screen requires both declared ratios at most 0.1; it is not
a certified physical error bound. Positive input numbers do not prove model
applicability. Standard volumetric flow must first be converted with explicit
reference K and Pa using `units.sccm_to_molar_flow`; no sccm convention is guessed.

## Outputs

| Output | Definition and units |
|---|---|
| Pressure, mean velocity, residence | Pa, m/s, s; derived from the prescribed carrier flow |
| Concentration | `scaled field * fraction_scale * p/(R*T)`, mol/m³ |
| A completion, B remaining | Minimum theta after A and maximum theta after B over active cells; fractions |
| Turnover | B-event increment / Gamma in the last recurring cycle; dimensionless turnover per cycle |
| Relative turnover spread | `(max-min)/area-weighted mean`; null for zero mean |
| Purge residual | Maximum `(xA+xB)/fraction_scale` at purge end; dimensionless |
| Purge clearance | Last downward continuous crossing of residual 0.01 within each purge; s from purge start; null = uncleared, zero = already clear |
| Consumption, escape fractions | Event-consumed or escaped precursor moles / inlet precursor moles, for each species |
| Cycle time, dose | Sum of four durations (s); integrated inlet A+B (mol) |
| Equivalent ZnO GPC | `1e10*M_ZNO*Gamma*turnover/5400`, Å/cycle; restricted conditional mapping below |

Only `synthetic-zno` can request the following `film` value with its declared
species labels:

```json
{"mapping": "conditional-zno-150c", "density_kg_m3": 5400.0}
```

This is the existing
150 °C equivalent-growth output. It is not a real-process validation. The
fictional A/B fixture sets `film: null`; no density, molecular mass, film thickness,
QCM signal or retained fragment is invented for it.

## Missing inputs and acceptance

Missing required values, nonfinite numbers, wrong unit labels, unsupported
chemistry, temperature or film mappings stop before an output folder or solver
is created. `inspect` returns the issues. An explicit null film does **not** stop
surface-turnover calculations. Real DEZ diffusivity and uncertainty remain
unresolved in the original benchmark registry; the new path cannot admit a
physical input by changing a label or filling in that registry.

Each run finds recurrence within 200 cycles at tolerance 1e-7, then checks
successive grids and tenfold tighter time tolerances with half maximum step.
Spatial field/event/decision/growth changes must be at most 0.001; temporal
changes at most 1e-5; clearance changes at most 0.001 residence times;
numerical/physical diffusion ratio at most 0.05. Ledger, event balance and bounds
limits remain 1e-8, zero-inventory residual 1e-10, with exact segment carryover.

Recipe constraints remain A completion ≥0.9, B remaining ≤0.1 and both purge
residuals ≤0.01, guarded by measured numerical changes. Numerical PASS, recipe
pass/fail/unresolved, wall-screen status and physical status are separate. Failed
refinements remain saved. No automatic grid extension, optimization or scenario
campaign follows a single run.
