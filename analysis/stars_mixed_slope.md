# Random slope on basic_program

**Script:** `stars_mixed_slope.py`

## Purpose
Extend the random-intercept model with a per-district random slope on
`ln(basic_program)` (the dominant predictor), letting each district have its own
ridership elasticity.

## Model
```
ln(cost_dy) = X_dy·beta + u_d + v_d·(ln basic_program_dy − mean) + eps
```
`ln(basic_program)` is **centered** so the intercept (`u_d`) and slope (`v_d`) are
not mechanically collinear. Compares random-intercept (RI) vs intercept+slope (RIS).

## Key findings — significant in-sample, no forecast value
**(A) In-sample:** LR test RIS vs RI = **39.4, p≈1.6e-9** — highly significant.
Elasticity spread SD=0.071 around fixed β_basic=0.74. **Intercept–slope
correlation = −0.69**: high-level districts have *flatter* cost-vs-ridership curves.

| district | u_d (level) | v_d | total elasticity |
|---|---|---|---|
| **Seattle** | +1.177 | −0.157 | **0.582** |
| Spokane | +0.507 | −0.097 | 0.643 |
| Tacoma | +0.516 | −0.064 | 0.676 |
| *typical* | ~0 | ~0 | **0.740** |

→ Large urban systems have high *structural* cost but lower *marginal* cost per
rider (**economies of scale**). The smooth version of the rural/urban interaction.

**(B) Walk-forward:** RIS does **not** improve over RI — it slightly hurts.
| | median | mean | 95th |
|---|---|---|---|
| RI | 9.0% | 11.6% | 29.6% |
| RIS | 9.4% | 11.9% | 30.0% |

RIS beats RI only 44% of the time; SPS gets *worse* in 3/4 years.

## Why, and the verdict
The slope is identified from **within-district ridership variation over a short
(2–5 yr) panel**, which is tiny — so `v_d` overfits the training residuals (huge
in-sample LR) but doesn't generalize. Same lesson as the rural-interaction F-test:
**in-sample significance ≠ predictive value.**

**Verdict: keep the random-intercept model for production.** The slope is worth
reporting *descriptively* (urban economies of scale) but not for forecasting with
this panel length. To make it pay off, pool the slope by district *type* (one urban,
one rural slope) instead of per district — far fewer parameters, more stable.

## Run
```
python3 analysis/stars_mixed_slope.py
```
