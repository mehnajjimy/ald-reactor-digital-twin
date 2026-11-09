# DEZ and water example

The `dez-water-zno` example swaps made-up placeholder numbers for published estimates of DEZ (diethylzinc) and water. It predicts about 1.68 Å of ZnO per cycle, close to the 1.65 Å reported at 150 °C, but it fails the model's own wall check. Back to the [README](../README.md).

> [!NOTE]
> <sub>DEZ: diethylzinc, the zinc precursor · ZnO: zinc oxide, the film · Å: angstrom, a ten-billionth of a meter · diffusivity: how fast a gas spreads · wall check: test of whether gas mixes across the channel gap fast enough to treat the gap as well mixed</sub>

## What changed

For a long time DEZ was just a placeholder with numbers picked to make the math convenient. `dez-water-zno` replaces those with published estimates.

- DEZ diffuses through nitrogen at about 0.0073 m²/s at 150 °C and 200 Pa. That comes from Lennard-Jones values published by Zhuang et al. (2021).
- The surface holds about 6.6 zinc atoms per nm² per cycle, and the film density is 5.3 g/cm³. Both come from a 2026 preprint.
- How likely DEZ and water are to react when they hit the surface is a guess. I couldn't find a published number for either one, so the file says "assumed". The values it uses are 1e-2 for DEZ and 1e-3 for water.

Every value lists its source and how uncertain it is. The full table is in
[the input reference](input-reference.md#the-dez-and-water-estimates).

## Running it

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/ald-twin simulate dez-water-zno --output runs/dez
```

Be warned, this one takes about 13 minutes. Real DEZ diffuses around 200 times slower than the old placeholder, so the solver needs a 20480-cell grid before the purge timing settles down. The DEZ example is in the source code but not in the 1.0.0 app download yet.

## What came out

It predicts about 1.68 Å of ZnO per cycle, which is close to the 1.65 Å reported at 150 °C. That figure is what a fully filled surface gives, using the 5.3 g/cm³ film density and the 6.6 zinc atoms per nm² per cycle above.

The assumed reaction probabilities set how long a pulse takes to fill the surface. So any conclusion about pulse times is a guess until those probabilities are measured or fitted.

More interesting is that it fails the model's own wall check. In this 2 mm channel, DEZ takes too long to spread across the gap, so treating the gap as well mixed isn't really valid anymore. The model still gives a number, but it flags the recipe as outside the range it trusts instead of quietly passing it, which is the behavior I wanted.

## What it doesn't show

None of these inputs has been fitted or validated against measurements. Both reaction probabilities are assumed. Matching 1.65 Å at 150 °C is a single comparison, and it doesn't make the example a validated model.

Sources: docs/input-reference.md, src/ald_twin/processes/, tests/test_dez_estimates.py, docs/references.md
