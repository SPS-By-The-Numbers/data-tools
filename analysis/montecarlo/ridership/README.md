# Stage 8 — ridership (tracked intermediates)

Built by `python3 -m analysis.montecarlo.ridership --build` (run from repo
root). Expected yellow-bus riders per school × program for the 2024-25
baseline, from the Stage 6×7 bus-eligible pool. Run without `--build` for a
summary + validation report.

## Model

Per assignment-matrix cell (GEOID × school × band; ES+MS at the 77 schools
with 2024-25 basic routes):

```
p(cell) = clip( s · f(d) · exp(β·x), 0, p_max )
f(d)    = (1−ρ) + ρ·exp(−d / decay_mi)     d = BG centroid → school point, miles
x       = centered school covariates: is_ms, low_income_frac, swd_frac, absent_rate
s       = solved each call so Σ eligible·p = STARS district on-bus target
```

The LEVEL always re-normalizes to the district target (10,008 in 2024-25);
θ = (ρ, decay_mi, β…) only shapes the distribution across schools. θ is fit
(grid + coordinate refinement) against the soft target of route-implied
per-school riders (STARS basic routes × district riders/route).

The gifted program is a separate pool — RC `highly_capable` enrollment at the
7 gifted-route sites, spread via the HCC pathway kernel (ES sites: Cascadia,
Decatur, Thurgood Marshall) or the school's own assignment column (MS sites)
— with one global propensity solved against the gifted target (1,316).

## Files

- `school_ridership.csv` — per school × program (77 basic + 7 gifted rows):
  `school_id, name, level, program, grade_band, n_bus_eligible, propensity,
  riders, n_routes_actual, est_routes`. Basic bands aggregated per school
  (`grade_band` = `es`, `ms`, or `es+ms`); `est_routes` = riders / district
  riders-per-route for the program (49.5 basic, 32.9 gifted in 2024-25).
- `params.csv` — one row: fitted θ, solved scale + gifted propensity,
  riders-per-route, and fit metrics (`pearson_routes_before/after`, SSE).

## 2024-25 fit (see NOTES.md decision log)

- ρ=1.0, decay 4.69 mi → propensity is a pure exponential **decay with
  distance** (distant eligible kids ride less — consistent with service-area
  limits at big-draw option schools), β_ms +0.19, β_li +0.38, β_swd +6.13,
  β_abs −0.31.
- Per-school riders vs STARS basic route counts: **r 0.718 (flat M4
  propensity) → 0.814 (shaped)**.
- swd_frac is the strongest covariate (ablating it: r → 0.734; raw
  correlation of implied per-school propensity with swd_frac is +0.46). It is
  a *demographic proxy* on the basic program — special-ed routes are a
  separate STARS program and are NOT modeled here.
- Gifted propensity solves to **1.011** (> 1): the gifted pool is slightly
  underestimated because MS sites use the school's overall draw column, which
  understates how far HC kids live from school (open question 4b — an MS
  pathway map would fix this). District gifted total is exact by construction.

## API (for Stages 9-10)

```python
from analysis.montecarlo.ridership import (
    load_ridership, load_params, RidershipParams,
    basic_cells, gifted_pool, expected_riders, sample_riders)

expected_riders(assignment=..., walk=..., params=θ)  # pure core; scenario inputs
sample_riders(rng, ...)                              # Poisson count draw (MC)
```

Stage 10 samples θ by `dataclasses.replace(load_params(), ...)` and supplies
population draws via `assignment=build_matrix(pop=sample_synth_pop(rng))` and
scenario walk zones via `walk=walk_fractions(walkzones=...)`.
