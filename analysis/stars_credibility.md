# Credibility blend — fat-tail bias correction

**Script:** `stars_credibility.py`

## Purpose
Reduce the formula's *consistent* (systematic) error for large systems like SPS by
blending the formula with each district's own track record, using empirical-Bayes
(Bühlmann) credibility.

## Diagnostic that motivates it
The fat-end error is a **persistent per-district offset, not noise**:
- **SPS costs ~1.6× its formula-expected cost in 6/6 years** (mean log-residual
  +0.48; `cost/A.4` 1.25–2.35).
- Both signs across the fat end: Seattle/Renton/Battle Ground/Tacoma chronically
  **under**-predicted; Everett/Edmonds/Northshore chronically **over**-predicted.

A single cross-sectional regression structurally cannot hold a per-district level.

## Method
```
ln(pred) = m_dY            (collective: per-year cross-sectional cost fit)
         + Z_d · offset_d  (credibility-weighted persistent offset, prior years only)
Z_d = n_d / (n_d + sigma2_d / tau2)
```
`offset_d` = mean prior-year residual; `Z_d` rises with history length **and**
stability (low within-district noise).

## Key findings
Hyperparameters: τ²=0.050 (between) vs σ²=0.015 (within), k=0.31 → Z≈0.87 (n=2),
0.92 (n=5). Persistent spread ≫ year-to-year noise ⇒ trust own history heavily.

| sample | metric | formula | credibility |
|---|---|---|---|
| All (n=839) | median APE | 13.0% | **8.2%** |
| | mean / 95th pct | 17.8% / 45.8% | **10.7% / 28.3%** |
| Fat end (top 15) | median APE | 17.7% | **9.9%** |
| | mean / 95th pct | 25.6% / 74.3% | **13.9% / 48.1%** |

- Credibility beats formula on 66% (all) / 77% (fat end) of district-years.
- **SPS: ~31–47% formula error → ~10–29%** every year.
- Biggest corrections: Everett −60pt, Battle Ground −26, **Seattle −23**, Renton −18.
- Well-fit districts (Kent, Lake Washington) move ≤1.4pt — it does nothing where
  there's no consistent bias.

## Caveats & policy translation
- SPS's offset is **growing** (+0.33→+0.45) — a trend; a recency-weighted offset
  would capture more.
- Doing this in *allocation* space = making the one-sided `D.5` cap **two-sided**
  (STARS already pulls awards down toward prior actuals; this also pulls
  chronically-underfunded districts up). Same, already-legible mechanism.

## Takeaway
The deployable fix for consistent fat-tail error. It is the closed-form
approximation of the random-intercept model (`stars_mixed.md`).

## Run
```
python3 analysis/stars_credibility.py
```
