# Per-district polynomial forecast vs STARS

**Script:** `stars_poly_forecast.py`

## Purpose
Test whether extrapolating a district's *own* allocation history with a low-order
polynomial predicts next year's allocation as well as OSPI's full route-data
formula — and characterize where each method wins.

## Method
For target year Y and window k: fit a polynomial (degree 1 = linear, or
min(k−1, 2)) to the district's own `D.8` over years Y−k…Y−1 and extrapolate to Y.
Benchmark = STARS `A.4` expected allocation. Ground truth = `D.8` actual.
Scored by absolute % error (APE) on the same district-years (paired).

## Key findings (non-COVID, level-space linear — the best variant)
| window | poly median APE | poly mean APE | STARS median | STARS mean | poly win rate |
|---|---|---|---|---|---|
| 2 yr | 12.9% | 17.8% | 8.6% | 21.3% | 44.5% |
| 3 yr | 13.2% | 18.1% | 8.5% | 21.9% | 44.4% |
| 4 yr | 15.7% | 19.6% | 8.5% | 21.9% | 39.3% |
| 5 yr | 16.9% | 18.5% | 8.5% | 21.9% | 40.5% |

- **By median, STARS wins** (~8.5% vs ~13%) — the route formula is ~1.5× more
  accurate for the typical district.
- **By mean, the polynomial wins** (~18% vs ~22%) — STARS has a **fatter tail of
  large misses**; anchoring to a district's own history avoids the blowups.
- The polynomial is closer than STARS on ~44% of district-years.
- **Shorter window is better** (2–3 yr); **higher degree is worse** (quadratic
  oscillates); **log-space is worse** than level (amplifies trends).

## Takeaway
A linear extrapolation of 2–3 years of a district's own allocations gets within
~13% with fewer catastrophic errors, but OSPI's formula is more accurate for the
typical district. Value of the history method = a **robustness check / outlier
flag**, not a replacement. This motivated the credibility/partial-pooling work
(`stars_credibility.md`, `stars_mixed.md`) that fuses both.

## Run
```
python3 analysis/stars_poly_forecast.py
python3 analysis/stars_poly_forecast.py --log --windows 2,3,4,5
```
