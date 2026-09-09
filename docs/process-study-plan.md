# Synthetic study contract

This static contract supports the retained study-runner regression tests. Its
historical path is required by `process_runner.source_hashes`. This source export
contains no completed campaign or internal planning history.

Study inputs are declared mathematical Pe/Da scales with synthetic diffusion,
constant capacity and the existing two-event, one-to-one A/B surface loop.
A/purge/B/purge segments carry the complete state across every switch. Transport
and accounting use the same face fluxes. Physical fitting remains unavailable.

The original equations, 200-cycle recurrence ceiling, recurrence tolerance 1e-7,
spatial threshold 0.001, temporal threshold 1e-5, clearance threshold 0.001
residence times and numerical-diffusion ratio limit 0.05 remain unchanged.
Recipe limits are A completion at least 0.9, B remaining at most 0.1 and purge
residual at most 0.01, guarded by measured numerical changes. The wall screen
and physical validity remain separate from numerical convergence.

The source export replaces only this explanatory document with a public
contract; frozen solver/configuration files retain their original bytes.
It cannot resume archived campaigns whose source manifest contains the original
research document. No completed study should be rerun to replace that archive.
