# STARS operations-allocation analysis

Exploratory analysis of OSPI's STARS pupil-transportation **operations allocation**
formula: reproducing it, probing alternative predictors, diagnosing where it fails
at the "fat end" (large systems like Seattle Public Schools), and prototyping fixes.

**Inputs (working data, not checked in):**
- `out_stars/stars_operations_allocation.csv` — the STARS Section A–D ledger.
- `transit-expenditures.csv` — F-196 reported district transportation costs (used
  as the real-world cost target; default definition excludes object codes 0/1/9 =
  transfers + Capital Outlay).

Most results are reported on the **non-COVID** years (2020-21 and 2021-22 excluded
as anomalous). Each model has a companion `<name>.md` summary.

## Reading order (the narrative arc)

### 1. Reproduce the formula
- **`stars_exploration`** — STARS Section A is a per-year log-linear OLS
  (`ln(allocation) ~ ln(land_area) + average_distance + destinations +
  ln(basic_program) + ln(special_program) + non_high dummies`). Recovers the
  published coefficients; `A.4` (expected allocation) match is circular, and the
  `D.8` actual needs the B/C/D adjustment ledger on top.

### 2. Alternative predictors & targets
- **`stars_poly_forecast`** — extrapolating a district's *own* allocation history
  (linear, 2–3 yr) gets within ~13%; STARS wins the median (~8.5%) but has a fatter
  error tail. First sign the fat tail is the real problem.
- **`stars_ruralness`** — a single density term (`population/land_area`) adds
  nothing (null result).
- **`stars_target_timing`** — which cost series/timing reproduces the coefficients;
  `D.4` adjusted prior-year expenditures is *worse* than same-year F-196 cost, and a
  ~0.17 coefficient-recovery floor implicates the *estimator*, not the target.
- **`stars_rural_interaction`** — rural vs urban districts do have different cost
  structures (geography matters more rurally), but the effect is small (~0.4% R²);
  includes the cautionary `a4` control showing the F-test over-detects at high R².

### 3. Diagnose the fat tail
The fat-end error is **consistent (persistent per-district bias), not variance**:
SPS costs ~1.6× its formula-expected cost in 6/6 years; Everett is chronically
over-predicted; etc. A single cross-sectional formula cannot hold a per-district
level.

### 4. Fix it
- **`stars_credibility`** — empirical-Bayes (Bühlmann) blend of formula + the
  district's own history. **Deployable fix**: fat-end median APE ~18%→10%, SPS
  ~47%→20%. Equivalent to making the one-sided `D.5` cap two-sided.
- **`stars_mixed`** — the textbook random-intercept mixed model behind the
  credibility blend. ICC = 0.85 (85% of residual variance is persistent district
  identity); roughly halves fat-end error out-of-sample.
- **`stars_mixed_slope`** — adds a random slope on `basic_program`. Strongly
  significant in-sample (urban economies of scale: Seattle elasticity 0.58 vs 0.74)
  but **no out-of-sample value** — keep the random-intercept model for production.

## Recommendation
For reducing SPS / fat-end systematic error: ship the **credibility blend**
(`stars_credibility`), justified by the **random-intercept mixed model**
(`stars_mixed`). Skip the random slope. The cleanest policy framing is a
**two-sided prior-year cap** on the existing STARS award.

## Running
All scripts run from the repo root and share the `stars_exploration.py` loader:
```
python3 analysis/stars_exploration.py --report
python3 analysis/stars_credibility.py
python3 analysis/stars_mixed.py
```
Dependencies: `numpy`, `statsmodels`, `scipy` (already in `requirements.txt`).
