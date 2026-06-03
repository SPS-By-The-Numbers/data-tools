# Cost target & timing — which dependent reproduces the coefficients

**Script:** `stars_target_timing.py`

## Purpose
The expected-allocation regression is calibrated to predicted *cost*. Determine
which cost series, at which timing, best reproduces the published STARS
coefficients — in particular whether OSPI's own "adjusted prior-year expenditures"
(`D.4`), aligned to the adjacent year, is the right dependent.

## Candidates
- **`D.4`** adjusted prior-year expenditures (= `D.2` + `D.3` federal indirects);
  the basis of the `D.5` cap. A year-(Y−1) quantity → pair with adjacent-year inputs.
- **`D.2`** raw prior-year expenditures.
- **F-196** reconstructed cost (same-year), the baseline.

## Key findings (mean max |recovered − published| coef diff, non-COVID)
| target / timing | vs that year | vs next year |
|---|---|---|
| `A.4` formula output (circular control) | 0.029 | — |
| **F-196 cost, same-year (baseline)** | **0.192** | **0.175** |
| `D.4` adj prior-yr exp, contemporaneous | 0.295 | 0.275 |
| `D.4` adj prior-yr exp, as-stored lag | 0.241 | — |
| `D.2` prior-yr exp, contemporaneous | 0.333 | 0.342 |

- **`D.4` is *worse* than F-196 in every timing**, despite being OSPI's own number.
  Reason: `D.4 = D.2 + D.3`, and `D.3` (federal restricted-rate indirects) is
  district-specific administrative noise the route regression can't explain.
- The **"apply next year" timing** is weakly better than same-year (0.175 vs
  0.192); 2024-25 cost vs 2025-26 published coefs = **0.027** (near-exact).
- **Nothing breaks below a ~0.17 floor.** The floor is the *estimator*, not the
  target.

## Takeaway
Regressing on adjusted prior-year expenditures does **not** help; same-year (or
apply-next-year) F-196 cost remains the best target. To close the residual gap,
fix the estimator (weighting / outlier trimming), not the dependent variable.

## Run
```
python3 analysis/stars_target_timing.py
```
