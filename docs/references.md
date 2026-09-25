# Scientific references

These sources support the formulation, benchmark selection and property methods.
They do not establish experimental validity of the shipped synthetic examples.
Source papers and books are not redistributed. Software attribution is in
`CITATION.cff`; dependency notices are in `THIRD_PARTY_NOTICES.md`.

## Reactor model and benchmarks

1. Yanguas-Gil, A., and Elam, J. W. (2012). *Simple model for atomic layer
   deposition precursor reaction and transport in a viscous-flow tubular reactor*.
   [DOI: 10.1116/1.3670396](https://doi.org/10.1116/1.3670396).
   Benchmark A is dimensionless/model reproduction only. The implemented
   occupied-capacity variable is one minus the paper's available-site variable.
   The reported Pe = 65, Da = 1550, gamma = 2.5 and beta0 = 0.01 are retained;
   reaction probability is already included in Da. Missing pulse/readout metadata
   prevents an exact published-curve claim. No dimensional reconstruction is used.

2. Holmqvist, A., et al. (2012). *A model-based methodology for the analysis and
   design of atomic layer deposition processes—Part I: Mechanistic modelling of
   continuous flow reactors*. [DOI: 10.1016/j.ces.2012.07.015](https://doi.org/10.1016/j.ces.2012.07.015).
   Table 1 is the experimental-data authority for the provisional DEZ/H2O ZnO
   benchmark. Its spatial growth-per-cycle measurements are distinct from
   single-half-cycle capacity or QCM signals. The source's larger chemical
   mechanism is not the synthetic two-event model supplied here.

3. Holmqvist, A., et al. (2013). *A model-based methodology for the analysis and
   design of atomic layer deposition processes—Part II: Experimental validation
   and mechanistic analysis*. [DOI: 10.1016/j.ces.2012.06.063](https://doi.org/10.1016/j.ces.2012.06.063).
   Supports the source fitting/validation history and conditional density mapping.
   Its fitted constants are not independent validation inputs for this project.
   The 150 °C equivalent-ZnO output is a conditional mapping, not validated GPC.

4. Holmqvist, A., et al. (2014). *Dynamic parameter estimation of atomic layer
   deposition kinetics applied to in situ quartz crystal microbalance diagnostics*.
   [DOI: 10.1016/j.ces.2014.02.005](https://doi.org/10.1016/j.ces.2014.02.005).
   Future QCM context only. This distinct experiment does not supply interchangeable
   geometry, delivery timing or pressure conditions for the 2012 benchmark.
   No QCM importer, observation model or QCM validation is implemented here.

## Transport properties

5. Poling, B. E., Prausnitz, J. M., and O'Connell, J. P. (2001).
   *The Properties of Gases and Liquids*, 5th ed. McGraw-Hill. ISBN 978-0-07-011682-5.
   The implemented replacement functions use Chapter 11, Eqs. 11-3.2 and
   11-3.4–6 for diffusion; Chapter 9, Eqs. 9-3.9 and 9-4.3 for pure viscosity;
   and Eqs. 9-5.14–16 for mixture viscosity. Appendix B supplies the Svehla
   Lennard–Jones inputs for N2 and H2O. This is the consulted source for these
   numerical inputs, not evidence of Holmqvist's hidden numerical choices.

6. Neufeld, P. D., Janzen, A. R., and Aziz, R. A. (1972). *Empirical equations
   to calculate 16 of the transport collision integrals for the Lennard-Jones
   (12–6) potential*. Journal of Chemical Physics, 57, 1100–1102.
   [DOI: 10.1063/1.1678363](https://doi.org/10.1063/1.1678363).
   Original collision-integral correlation source; implementation conventions
   follow the audited Poling equations above.

7. Wilke, C. R. (1950). *A viscosity equation for gas mixtures*.
   Journal of Chemical Physics, 18, 517–519.
   [DOI: 10.1063/1.1747673](https://doi.org/10.1063/1.1747673).
   Original mixture-rule source; the implementation uses supplied composition,
   not a universal inlet composition throughout a reacting chamber.

The water collision model remains an approximation. The synthetic example files
deliberately contain made-up values; a source citation does not make those
values physical.

## DEZ and water estimates

These supply the `dez-water-zno` estimate process. None of its values is fitted.

8. Zhuang, et al. (2021). AIChE Journal, 67, e17305.
   [DOI: 10.1002/aic.17305](https://doi.org/10.1002/aic.17305).
   Supporting Table S2 (p. 50 of the OSTI accepted manuscript) gives DEZ
   σ = 5.86 Å and ε/k = 405 K, estimated there from Poling and from Jackson (1992).
   Used for the DEZ-N2 diffusivity. Its N2 values (3.621 Å, 97.53 K) come from
   CHEMKIN. This project keeps Poling's N2 values, which changes D by 1.3%.

9. Gonsalves, et al. (2026). arXiv:2609.12460 (preprint).
   Table 1, p. 10: 6.6 Zn per nm² per cycle, 0.165 nm per cycle and XRR density
   5.3 g/cm³ at 150 °C. Used for capacity and film density.

10. Cai, et al. (2019). Journal of Materials Science, 54, 5236–5248.
    [DOI: 10.1007/s10853-018-03260-3](https://doi.org/10.1007/s10853-018-03260-3).
    QCM mass per cycle of 126 ng/cm² at 150 °C (Fig. 1b) and about 1.5 OH used
    per DEZ (Eqs. 3–4). Used for the capacity spread and the ethane split.

11. Elam, J. W., Routkevitch, D., and George, S. M. (2003). Journal of the
    Electrochemical Society, 150, G339.
    [DOI: 10.1149/1.1569481](https://doi.org/10.1149/1.1569481).
    Table I: 5.62 g/cm³ at 177 °C. Used for the density spread.

No published sticking probability for DEZ on ZnO, or for water on the ethyl
surface, was found. Both are assumed in the process file.

## Numerical software

12. Virtanen, P., et al. (2020). *SciPy 1.0: Fundamental algorithms for scientific
   computing in Python*. Nature Methods, 17, 261–272.
   [DOI: 10.1038/s41592-019-0686-2](https://doi.org/10.1038/s41592-019-0686-2).
   SciPy supplies the time integrators and optimization routines. See
   [solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html)
   for Radau/BDF method references. Agreement between the integrators does not
   independently verify their shared spatial discretization.

## Public source trail

The frozen `config/benchmarks/benchmark-a.json` retains historical references to
`docs/implementation-freeze.md`, which is omitted from the clean public export.
Reference 1 and its convention mapping above explain those entries without
rewriting the frozen configuration. The public [input reference](input-reference.md)
describes the active synthetic model, units, flow reduction and decision criteria.
Internal checkpoint filenames are historical provenance, not additional required
inputs to the portable `inspect`, `simulate`, `compare` or `gui` commands.
