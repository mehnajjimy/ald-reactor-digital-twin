# Recipe study

I ran a larger synthetic study of 63 recipe and scenario pairs. Every calculation passed its numerical checks, but no single recipe worked in every scenario. Back to the [README](../README.md).

> [!NOTE]
> <sub>recipe: the pulse and purge durations for A and B · scenario: one set of reactor conditions · Péclet number: how much faster flow carries gas than diffusion spreads it · capacity point: one value of the surface site capacity, Gamma · unverified: a result that has not been numerically verified</sub>

## What was run

The study covered 63 pairs of a recipe with a scenario. Each pair was a synthetic calculation, and none used real experimental data. A nominal candidate recheck followed it.

A recipe counts as working only if A completion is at least 0.9, B remaining is at most 0.1 and purge residual is at most 0.01. The [study contract](process-study-plan.md) lists these limits and the numerical thresholds.

## What came out

Every calculation passed its numerical checks. That does not mean any recipe was good. A converged result can still fail the completion or purge constraints, and no recipe passed every declared scenario.

Nine earlier high-Péclet cases and one capacity point (Gamma x0.5) are still unverified. A failed point cannot become acceptable by changing a label.

## Where the results live

The study sits in the original research archive. This source export does not include those results and does not supersede them. Small regression tests and worked examples cannot erase these limitations.

The math being right doesn't mean a working recipe exists. The [model limits](model-limits.md) page says how a result gets separate numerical, recipe and physical status.

Sources: docs/model-limits.md, docs/process-study-plan.md
