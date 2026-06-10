# simulate/ — saved Monte Carlo runs (Stage 10 outputs)

One subdirectory per scenario, written by
`python3 -m analysis.montecarlo.simulate --scenario <name>` and consumed by
`python3 -m analysis.montecarlo.report <name>` (Stage 11). Re-running a
scenario overwrites its directory.

The draws are PAIRED: each draw evaluates baseline and scenario with the same
sampled θ + population, and the scenario reuses the calibration (propensity
scale, covariate centering, gifted propensity) solved on that draw's own
baseline. See the `simulate.py` module docstring for the sampling and
calibration decisions.

Files per run:

| file | grain | columns |
|---|---|---|
| `district_draws.csv` | draw × program | base/scen riders, d_riders; rider-weighted `dist_mean/p50/p90` base+scen (basic rows only) |
| `school_draws.csv` | draw × school × program | base/scen eligible + riders; base/scen rider-weighted mean stop→school distance (basic rows only) |
| `theta_draws.csv` | draw | sampled θ fields + solved `gifted_propensity` and propensity `scale` |
| `meta.json` | run | scenario spec, n_draws, seed, sample flags, runtime |
| `report.txt` | run | Stage 11 text report (only if `report --save` was run) |

District basic/gifted baseline totals are constant across draws BY
CONSTRUCTION (per-draw calibration against the observed STARS targets); the
uncertainty lives in the per-school split and in every scenario delta.
