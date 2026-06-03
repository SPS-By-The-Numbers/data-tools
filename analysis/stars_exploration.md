# STARS log-linear regression — reproduction

**Script:** `stars_exploration.py`
**Target:** `out_stars/stars_operations_allocation.csv`

## Purpose
Reverse-engineer and reproduce the log-linear regression that OSPI's STARS report
(Section A) uses to set each district's pupil-transportation *operations*
allocation.

## The model
Section A is a log-linear OLS, re-estimated once per school year:

```
ln(expected_allocation) = intercept
    + b1·ln(land_area) + b2·average_distance + b3·destinations
    + b4·ln(basic_program) + b5·ln(special_program)
    + b6·[non_high_yes] + b7·[non_high_no]
```

- `land_area`, `basic_program`, `special_program` enter as **natural logs** (the
  "(Ln)" columns); `average_distance`, `destinations` are linear.
- `non_high_yes` / `non_high_no` are a 3-level dummy (regular district = base).
- Ledger chain: `A.1` = Σ(coef·transform(x)), `A.2` = intercept, `A.3 = A.1+A.2`,
  **`A.4 = exp(A.3)`** = expected/initial allocation. Confirmed `exp(A.3)≈A.4` to ~5e-6.
- Coefficients are constant within a year, change every year.

## Key finding — which dependent variable reproduces the published coefficients
| dependent variable | mean coef diff vs published |
|---|---|
| `a4` / `a3` (expected allocation) | **0.038** ✓ |
| `d8` actual allocation | 0.449 |
| `d2` prior-year expenditures | 0.588 |

The published coefficients reproduce the **expected allocation `A.4`** (fit on the
same year) — but this is **circular**: `A.4` is built *from* those coefficients,
so OLS just inverts the formula (residual ~0.038 is only transform-rounding noise).

`d8_actual_allocation_amount` = expected allocation **plus the B/C/D adjustments**
(non-high, low-ridership, co-op, alt-calendar, the prior-year-expenditure cap,
legislative salary/benefit). Regressing straight on `ln(d8)` lands ~0.45 off.

## Takeaway
The formula structure is fully recovered. To predict `d8` you must run the
regression to get the expected allocation, then walk the B/C/D ledger. A genuinely
independent recalibration needs **reported district costs** as the target — not in
this file (see `stars_target_timing.md`, `stars_credibility.md`).

## Run
```
python3 analysis/stars_exploration.py --report          # full comparison
python3 analysis/stars_exploration.py --coeffs 2023-2024 # recalc one year's coefs
```
