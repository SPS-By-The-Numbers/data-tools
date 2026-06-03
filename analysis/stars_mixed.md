# District random-effects / partial-pooling model

**Script:** `stars_mixed.py`

## Purpose
The "textbook" version of the fat-tail fix: a mixed model with a per-district
random intercept, jointly estimated by REML. It is the generative model the
credibility blend (`stars_credibility.md`) approximates in closed form.

## Model
```
ln(cost_dy) = X_dy·beta + u_d + eps_dy ,   u_d ~ N(0, tau2),  eps ~ N(0, sigma2)
```
- (A) in-sample fit with **year fixed effects** (absorb each year's level).
- (B) walk-forward forecast vs the *same model without the random effect* (pooled
  OLS), isolating the partial-pooling contribution.

## Key findings
**(A) Structure:** ICC = **0.854** — *85% of the residual cost variance is
persistent district identity*, only 15% year-to-year noise. The fat-tail miss is
overwhelmingly a fixed per-district offset.

BLUP offsets `u_d` (relative to the pooled fixed-effects):
| district | u_d | implied |
|---|---|---|
| **Seattle** | +1.068 | **2.9×** formula |
| Tacoma | +0.540 | 1.7× |
| Renton | +0.508 | 1.7× |
| Everett | −0.048 | ~1.0× |

**(B) Forecast (RE vs no-RE, same year handling):**
| sample | metric | pooled OLS | mixed +RE |
|---|---|---|---|
| All (n=839) | median / mean / 95th | 14.9% / 19.3% / 48.6% | **9.0% / 11.6% / 29.6%** |
| Fat end (15) | median / mean / 95th | 22.0% / 25.8% / 57.5% | **11.0% / 13.3% / 29.9%** |

RE wins 68% (all) / 75% (fat end). **SPS: 31%→4% (2019-20), 49%→21% (2024-25).**

**Per-year R² vs the STARS recreation** (in-sample, same per-year denominator):
| | STARS recreation (per-yr OLS) | mixed marginal (fixed only) | mixed conditional (fixed+random) |
|---|---|---|---|
| mean R² | 0.9672 | 0.9541 | **0.9938** |

- Pooling coefficients costs ~1.3 pts on the fixed part (0.967 → 0.954: shared vs
  free per-year coefficients), but the random intercept lifts every year well above
  STARS (→ 0.994).
- Unexplained within-year variance: STARS **3.3% → conditional 0.6%** — an **~81%
  cut**, matching ICC=0.85.
- Caveat: this is **explanatory** R² (the random intercept sees each year's own
  data) — "structure captured", not forecasting skill. The honest predictive gain
  is the walk-forward APE above.

## Reconciliations
- **τ² = 0.073 here vs 0.050 in the credibility run.** The credibility version fit
  a fresh cross-section per year (year-specific coefficients absorbed more), while
  this uses pooled coefficients + year fixed effects, so more structure surfaces as
  the random intercept (hence SPS u_d +1.07 vs +0.48). ICC=0.85 is the
  baseline-independent takeaway; forecast accuracy matches credibility.
- **2022-23 is rough for both** (SPS still 48.5%) — the linear year-trend must
  extrapolate the statewide level across the 2-year COVID gap. A level problem, not
  the random effect.

## Takeaway
Confirms the diagnosis (85% persistent identity) and roughly halves fat-end error.
**For production, ship the credibility blend** (more robust to the COVID-gap level
issue) and cite this mixed model as its statistical justification.

## Run
```
python3 analysis/stars_mixed.py
```
