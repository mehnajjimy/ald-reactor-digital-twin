# Model limits

Two processes are synthetic. `dez-water-zno` uses published estimates and
labelled assumptions: an estimated DEZ diffusivity, a site density from a
preprint and assumed sticking probabilities. None is fitted or validated against
measurements. Physical fitting, temperatures other than 150 °C and arbitrary
chemistry or film mappings remain blocked. Positive inputs and a numerical PASS
do not establish applicability.

The DEZ process fixes one ethane per DEZ step. Published QCM work, and the lab's
85 °C runs, point to about 1.5. This does not change the simulated growth, but it
matters once half-cycle QCM masses are compared.

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
