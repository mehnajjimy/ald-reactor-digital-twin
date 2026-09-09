# Model limits

Every shipped process is synthetic, including the DEZ-like example. Physical
DEZ diffusion and uncertainty have not been integrated. Physical fitting,
temperature generalization and arbitrary chemistry or film mappings remain
blocked. Positive inputs and a numerical PASS do not establish applicability.

The model uses one surface population and two first-order, one-to-one events.
Capacity, temperature and effective rate coefficients are constant. The channel
flow is isothermal, no-slip and parallel-plate; it neglects side walls, axial
inertia, slip and changes in total molar flow. See the [input reference](input-reference.md)
for equations, units and the exact fixed acceptance criteria.

A result has separate numerical, recipe and physical status. A converged result
can fail completion or purge constraints. An UNVERIFIED result retains that
status; a failed point cannot become acceptable by changing a label. The
fictional A/B process has no film mapping. Its thickness output stays null.

The original research archive contains a numerically verified 63-pair synthetic
study and nominal candidate recheck. No recipe passed every declared scenario.
Nine earlier high-Peclet cases and one Gamma x0.5 profile point remain unverified.
This source export does not include those results and does not supersede them.
Small regression tests and worked examples cannot erase those limitations.
