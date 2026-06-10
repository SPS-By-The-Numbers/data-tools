# SPS Yellow-Bus Ridership Monte Carlo — Technical Overview

This document explains how the simulation is constructed: the pipeline
stages, the variables and the distributions they are drawn from, the
calibration strategy, and the modeling assumptions an expert should check
before trusting a number. Links go to the code in this directory; the
living project log (decision history, open questions, per-session results)
is [NOTES.md](NOTES.md).

**What it estimates.** For a *scenario* — walk-zone resizes, school
closures, option→neighborhood conversions, school moves, adding bus service
— the model produces district and per-school deltas, with confidence
intervals, for:

- **basic & gifted ridership** (STARS *rides per day*: AM and PM boardings
  each count once, so a both-ways student counts as 2);
- **route count** (rides ÷ district rides-per-route);
- **bus fleet** (2-bell-shift rule, below) and **annual bus cost**;
- **state reimbursement** (the STARS EXAL funding formula, below) and the
  **net fiscal delta**;
- rider-weighted stop→school distance, and equity cuts by school
  low-income share and ES attendance-area poverty.

Everything is calibrated to school year **2024-25**, the latest with full
STARS + OSPI Report Card overlap.

---

## Pipeline at a glance

Eleven stages, one module per stage, each writing tracked intermediate CSVs
so a fresh checkout can run without the gitignored raw sources:

| # | Stage | Module | Output |
|---|---|---|---|
| 1 | Geography | [`parse_shapes.py`](parse_shapes.py) | 7 SPS transportation shapefile layers, normalized |
| 2 | School directory | [`school_directory.py`](school_directory.py) | [`school_directory/`](school_directory/) — 98 schools, classification, name maps |
| 3 | Baseline ridership | [`baseline_ridership.py`](baseline_ridership.py) | [`baseline_ridership/`](baseline_ridership/) — STARS routes/targets × enrollment |
| 4 | ACS population | [`acs_population.py`](acs_population.py) | [`census_seattle/`](census_seattle/) — block groups, age, public-school share |
| 5 | Synthetic population | [`synth_population.py`](synth_population.py) | `census_seattle/synth_pop.csv` — kids per BG × grade band + Dirichlet α |
| 6 | Assignment | [`assignment.py`](assignment.py) | [`assignment/`](assignment/) — P(school \| BG, band) via OD-anchored IPF |
| 7 | Eligibility | [`eligibility.py`](eligibility.py) | [`eligibility/`](eligibility/) — walk-zone membership fractions |
| 8 | Ridership | [`ridership.py`](ridership.py) | [`ridership/`](ridership/) — propensity model θ, expected rides |
| 9 | Scenario engine | [`scenarios.py`](scenarios.py) | applies [`scenarios/*.json`](scenarios/) specs to a `World` copy |
| 10 | MC driver | [`simulate.py`](simulate.py) | [`simulate/<name>/`](simulate/) — paired draws (district/school/θ CSVs) |
| 11 | Report | [`report.py`](report.py) | `simulate/<name>/report.txt` — deltas + CIs + fiscal sections |

Supporting ingests: [`stars_seattle.py`](stars_seattle.py) (STARS Seattle
slice → [`stars_seattle/`](stars_seattle/)), [`rc_seattle.py`](rc_seattle.py)
(Report Card enrollment + chronic absenteeism → [`rc_seattle/`](rc_seattle/)),
[`section4_seattle.py`](section4_seattle.py) (the 2024-25 enrollment-report
origin–destination tables → [`section4/`](section4/)), and the HCC pathway
maps [`hcc_pathways_es.csv`](hcc_pathways_es.csv) /
[`hcc_pathways_ms.csv`](hcc_pathways_ms.csv).

```
ACS+TIGER ──► synth_pop ──┐                        ┌─► eligibility (walk zones)
                          ├─► assignment (IPF) ────┤
Section-4 OD ─────────────┘        ▲               └─► ridership (propensity θ)
RC enrollment (column marginals) ──┘                        ▲
STARS (district targets, routes) ───────────────────────────┘  ← calibration
```

## Geography and units

- Analysis CRS is **EPSG:2926** (NAD83(HARN) / Washington North, US feet) —
  the native CRS of the SPS zone polygons; walk thresholds are in miles
  (× 5280). School points, walk zones, attendance areas, option geozones,
  and HCC pathway areas all live in this frame
  ([`parse_shapes.py`](parse_shapes.py)).
- The universal school key is `school_id` (3-digit SPS site number);
  `school_code` (4-digit OSPI building code) bridges to Report Card data
  (98/98 exact match). STARS destinations are name-keyed and resolved by
  [`school_directory.py`](school_directory.py) (154/154, with explicit
  override dicts for the ambiguous/typo cases).
- **Ridership unit: rides/day**, matching STARS `basic_students_on_buses`
  (10,008.5 in 2024-25) and `special_students_gifted` (1,315.5). Unique
  students are between half and all of any figure; long-route students
  disproportionately ride mornings only.

## Baseline construction

### Synthetic population (stages 4–5)

ACS 5-year 2023 block-group age counts (B01001) × tract-level public-school
fractions (B14003, suppressed at BG level) × TIGER 2023 geometries, clipped
to SPS territory: 558 block groups, 76,474 school-age children, 75.7%
public ⇒ 52,904 expected public-school kids. Age→grade-band split is fixed
integer-grade algebra (5-9 → ES; 10-14 → 20/60/20 ES/MS/HS; 15-17 → HS).
The 1.06× over-count vs actual SPS enrollment is absorbed by the IPF column
constraints, not corrected ad hoc. See
[`synth_population.py`](synth_population.py).

### Assignment (stage 6)

`P(school | block group, grade band)` is **anchored to observed flows**,
not a fitted gravity model: the 2024-25 Annual Enrollment Report Section 4
gives, per attendance area, where resident students actually enrolled
(stay-rates ES 68.2% / MS 56.6% / HS 69.8%). The prior for IPF is
(block-group → attendance-area area-overlay weights) × (observed
P(school | area, band)); `ipf()` in [`assignment.py`](assignment.py) then
matches **row marginals** (synthetic kids per BG, scaled per band to
enrollment totals) and **column marginals** (Report Card per-grade 2024-25
enrollment, 98 schools, PK excluded). Result: 19,094 cells. Option-school
draw kernels (single exponential distance decay per band, grid-searched
against the observed option draws: ES/MS 0.50 mi, HS 1.50 mi) are used only
to *generalize* flows under scenarios (e.g. a moved option school), not for
the baseline.

### Eligibility (stage 7)

Pure geometry, no fitting: `walk_fractions()` in
[`eligibility.py`](eligibility.py) computes, per (block group, school), the
fraction of the BG's SPS-territory area inside the school's official walk
zone. Missing pair = 0 (fully bus-eligible). Walk zones are the official
GIS polygons (hazard carve-outs included); per a verified SPS rule, ES and
K-8 zones are 1 mile and MS/HS 2 miles, and the K-8 layers' spurious 2-mile
union pieces are dropped in `parse_shapes.load_walkzones` (Licton Springs
has no 1-mile piece and keeps its smallest, 1.88 mi).

### Ridership (stage 8)

Per assignment cell (ES+MS bands at the 77 schools that ran basic routes in
2024-25), expected rides/day are `n_eligible · p(cell)` with

```
p(cell) = clip( s · f(d) · exp(β·x), 0, p_max )
f(d)    = (1−ρ) + ρ·exp(−d / decay_mi)        d = BG centroid → school point, miles
x       = centered school covariates (is_ms, low_income_frac, swd_frac, absent_rate)
s       = solved each call so Σ n_eligible·p = the STARS district target
```

The scale `s` is **not a free parameter** — it is re-solved against the
district target (hard renormalization, with an active-set correction for
cells pinned at `p_max`), so θ shapes only the *distribution* across
schools. θ is fit by coarse grid + coordinate refinement against
route-implied per-school rides (STARS basic routes × rides/route). Fitted
values ([`ridership/params.csv`](ridership/params.csv)):

| parameter | value | note |
|---|---|---|
| ρ | 0.85 | mixture weight: 0.15 flat floor + 0.85 exponential decay |
| decay_mi | 4.69 | rides/day fall with distance — consistent with AM-only riding on long routes |
| β_ms | +0.125 | middle-school tilt |
| β_low_income | +0.31 | |
| β_swd | +5.63 | strongest covariate; a demographic *proxy* (special-ed routes are a separate, unmodeled STARS program) |
| β_absent | +0.06 | ≈ 0; retained, contributes nothing |
| p_max | 0.95 | structural cap (a *shape* bound — the propensity unit is rides/day per eligible student, theoretical max 2) |
| solved s | 0.849 | baseline |
| gifted propensity | 0.918 | single solved value vs the 1,315.5 target |

Fit quality: per-school expected rides vs STARS basic route counts Pearson
r = 0.806 (vs 0.715 for a flat propensity). The **gifted program** is a
separate pool: highly-capable enrollment at the 7 gifted-route sites,
spread spatially by the HCC pathway kernel (exact unions of feeder
attendance areas from the district's pathway maps — see
[`hcc_pathways_es.csv`](hcc_pathways_es.csv),
[`hcc_pathways_ms.csv`](hcc_pathways_ms.csv)), with one solved propensity.

Rides → routes via district rides-per-route (2024-25: basic 49.5, gifted
32.9 — ≈ 25 students on a one-way run).

## Scenario engine (stage 9)

A scenario is an ordered list of ops in a JSON spec
([`scenarios/README.md`](scenarios/README.md)) applied by
[`scenarios.py`](scenarios.py) to a copy of a `World` dataclass (flows,
enrollment marginals, walk zones, school points, gifted table, basic
service set). Six ops: `set_walk_threshold`, `scale_walkzone`,
`close_school`, `convert_option_to_neighborhood`, `move_school`,
`add_basic_service`. Design invariants worth verifying in code:

- **Residence strata are fixed.** Ops never touch where kids live (the
  BG × attendance-area weights); they edit only the destination side. Kids
  stay put; their school changes. This keeps the Section-4 OD anchoring
  intact under every op.
- **Enrollment is conserved.** After flow edits, each school×band marginal
  is rescaled by its flow-total ratio and each band renormalizes to its
  baseline total (`_rescale_col_marg`) — closures move kids between
  schools, never out of the district.
- **Walk-zone resizes use calibrated buffers**: per school, a multiplier
  `m = √(official_area/π)/(T·5280)` reproduces the official polygon's
  *area* at the current threshold `T`; a scenario threshold `T'` yields a
  circle of radius `m·T'·5280` ft. The empty scenario keeps the official
  polygons — buffers only replace zones an op touches.
- **Closure defaults**: attendance school → 3 nearest open same-level
  neighborhood schools, split per residence area ∝ the receivers' existing
  draw from that area; option school → nearest open option site; an HCC
  pathway relocates *intact* (member areas + HC enrollment) to
  `hcc_receiver`. Explicit `receivers`/`hcc_receiver` override all of this.
- **Conversion is steady-state**: geozone residents attend at the band's
  observed stay-rate; former lottery enrollees return to their areas' other
  destinations pro-rata. No transition-year grandfathering.
- **Scenario evaluation reuses the baseline-solved scale** (`fixed_scale`)
  and baseline covariate centering. Re-solving would renormalize every
  scenario back to the district target and all deltas would vanish by
  construction.

Static validation (`validate_scenario`) checks op names, required params,
school ids against the directory, sequential closure consistency, and
conversion targets.

## Monte Carlo design (stage 10)

[`simulate.py`](simulate.py) runs a **paired design**: each draw samples
(θᵢ, populationᵢ) once and evaluates baseline and scenario with the *same*
draw, so deltas difference out shared noise. 200 draws ≈ 40 s.

**What is sampled, and from what:**

| variable | distribution | code |
|---|---|---|
| population: grade-band split per block group | Dirichlet(α), α_band = n_pub_band + 0.5 per BG; the sampled fractions × the BG's fixed `n_pub_total` | `sample_synth_pop` in [`synth_population.py`](synth_population.py) |
| `decay_mi` | lognormal around the fit: `decay·exp(N(0, σ=0.2))` | `sample_params` in [`simulate.py`](simulate.py) |
| each β (4 of them) | Normal(β̂, max(0.2·\|β̂\|, 0.05)) | same |
| ρ, p_max | **fixed** at fitted values (the fit pinned ρ; p_max is structural) | same |
| scale s, gifted propensity | **solved per draw** on that draw's baseline cells, then reused for the paired scenario arm | `run_mc` |
| scenario behavioral params (stay-rate etc.) | **not sampled** — spec constants | — |

Two deliberate choices to scrutinize:

1. **Calibration is per-draw.** The district targets (10,008.5 / 1,315.5)
   are observed facts, not uncertain inputs, so every sampled world
   reproduces them at baseline; uncertainty lives in the per-school split
   and in all deltas. Baseline district totals are therefore degenerate
   across draws *by construction*.
2. **No count noise.** Draws propagate parameter (θ) and population
   uncertainty through *expected* rides per cell; there is no Poisson
   resampling in the driver (a `sample_riders` wrapper exists in
   [`ridership.py`](ridership.py) but is unused). CIs are uncertainty in
   the expected value, not year-to-year realization noise.

Scenario worlds are built once from the expected-value baseline (geometry
and flow edits don't depend on the draw); per-world walk fractions are
hoisted out of the loop. Reported CIs are 95% percentile intervals over
draws. All reported runs use `--n-draws 200 --seed 20260610`.

## Fiscal models (stage 11)

Both live in [`report.py`](report.py) with sources in comments at the top.

**Bus fleet & cost.** SPS runs two bell shifts (ES vs MS/HS), a bus serves
one route per shift, so fleet = **max(ES-shift routes, MS/HS-shift
routes)**, pooled across basic+gifted (`bus_cost_summary`; K-8s ride the ES
shift). Validation: the rule gives 171 buses at baseline vs 162 actual
basic+gifted STARS buses (+5.6%); per-program maxes do *not* reproduce
STARS. Cost = Δbuses × **$148.9k/bus-year** (SY2024-25 all-in vendor:
$56.89M purchased transportation ÷ 382 buses). Consequence: MS/HS-shift
route additions are fleet-free while the ES shift stays the binding max;
the $0 rows are a *lower bound* on marginal cost (a second route on an
existing bus still adds driver-hours).

**State reimbursement (EXAL).** The STARS funding formula
(`funding_summary`, constants `EXAL_COEF` / `EXAL_BASE`):

```
EXAL = exp( 0.66498·ln(BasicRiders+1) + 0.11·ln(SpecialRiders+1)
          + 0.01523·Destinations + 0.04231·AvgDistance
          + 0.02839·ln(LandArea) − 0.29176·NonHighDist + 8.6013 )
```

Scenario deltas are applied on top of the official SY2024-25 inputs
(BasicRiders 9,194.75; SpecialRiders 4,256.25; Destinations 105.75;
AvgDistance 2.16; LandArea 85.5; NonHighDist 0): basic ride deltas →
BasicRiders, gifted → SpecialRiders, change in served-school count
(rides > 0.5/day) → Destinations, rider-weighted basic distance delta →
AvgDistance. Implementation reproduces the official worked example
(baseline $36.68M; marginal ≈ $2,653/boarding). The allocation cap
(min(EXAL, $59.8M)) and the legislative salary adjustment are *not*
modeled per instruction; one scenario (`hs_bussing_1mi`) would cross the
cap — flagged in NOTES.

## Calibration & validation summary

| check | result |
|---|---|
| district basic / gifted targets | exact by construction (10,008.5 / 1,315.5 rides/day) |
| per-school rides vs STARS basic routes | Pearson r = 0.806 (flat-propensity baseline 0.715) |
| implied flat propensity | 10,008.5 / 15,500 eligible = 0.646 rides/day per eligible student |
| empty scenario == tracked baseline | max \|Δ\| ≈ 5e-5 (assignment), 5e-7 (walk), 0.005 (rides) |
| MC vs expected value | CI brackets the EV delta on both smoke scenarios (e.g. close_sacajawea EV −7.6, MC −7.1 [−13.3, −1.8]) |
| no-sampling MC mode | reproduces the EV exactly |
| bell-shift fleet rule | 171 est vs 162 actual buses (+5.6%) |
| EXAL implementation | matches the official worked numbers ($36.68M, $2,653/boarding) |
| kernel hypothesis (gifted draws are longer) | 88.3% of non-COVID school×year rows have gifted > basic route distance |

## Modeling assumptions & limitations

Roughly ordered by how much they could move a result.

1. **Rides, not riders.** All "rider" quantities are boardings/day; unique
   students ∈ [rides/2, rides]. The propensity is rides/day per eligible
   student (max 2), and its fitted distance decay partly *is* the AM-only
   behavior on long routes.
2. **HS ridership is an extrapolation.** SPS has run no HS basic yellow bus
   in the STARS record (ORCA only), so `add_basic_service` scenarios give
   HS riders the ES/MS-fitted propensity (is_ms = 0) and basic
   rides-per-route. Nothing calibrates this.
3. **Fixed residence strata / single-year OD anchor.** Where kids live and
   the area→school flow structure are 2024-25 snapshots; scenarios get
   steady-state reassignment, no enrollment growth/decline, no behavioral
   feedback (e.g. families moving or opting out in response to a closure).
4. **Mixed-site basic/gifted double count.** At the 4 MS HCC pathway sites
   (Hamilton, Jane Addams, Eagle Staff, Washington) the basic enrollment
   marginals include HC students (~783) who also form the gifted pool;
   per-school basic+gifted sums and deltas touching those sites carry a
   modest overlap (district baselines are immune — each program
   renormalizes to its own target).
5. **Walk-zone resizes are circular calibrated buffers.** Real boundary
   changes follow streets and hazard rules; the buffer preserves the
   official polygon's *area* relationship, not its shape. (Official
   polygons are used wherever an op doesn't touch the zone.)
6. **Distances are crow-flies BG-centroid → school point**, not network
   distances; AvgDistance in the EXAL formula gets the rider-weighted
   *stop→school* delta as a proxy for the STARS route-average measure.
7. **Routes and buses are derived, not routed.** Routes = rides ÷ a
   constant district rides-per-route; the fleet rule ignores deadheading,
   bell-time tiers within a shift, and capacity. EXAL Destinations deltas
   only see modeled programs (a closure's special-ed destination loss is
   not counted, so closure revenue losses are understated).
8. **Special-ed (2,506 rides/day), early-ed, bilingual, homeless programs
   are not modeled**; β_swd is a demographic proxy on the basic program,
   not a special-ed transportation model.
9. **θ sampling is start-simple**: lognormal/Normal perturbations of a
   point fit, ρ and p_max fixed, no posterior; scenario behavioral
   parameters (conversion stay-rate, opt-in) are constants. CIs understate
   structural uncertainty.
10. **Closure receiver defaults** (3-nearest split ∝ existing draw) stand
    in for SPS's actual boundary redraws unless the spec names receivers;
    one HCC pathway era config (`pathway_2023_2025`) assumes Madison+Denny
    → Washington (consistent with STARS route evidence, unverified by the
    district).
11. **ACS measurement error** (1.06× over-count, tract-level public-school
    fractions imputed to BGs) is absorbed by IPF column constraints and the
    Dirichlet population sampling rather than modeled explicitly.
12. **Funding model scope**: coefficients assumed stable, cap assumed slack
    (one flagged exception), and the EXAL BasicRiders baseline (9,194.75)
    is a different STARS count than the model's quarterly-metrics baseline
    (10,008.5) — deltas are applied to the official input rather than
    re-deriving the level.

## Reproducing

```console
$ venv/bin/python3 -m analysis.montecarlo.scenarios                  # list + validate specs
$ venv/bin/python3 -m analysis.montecarlo.scenarios --validate       # empty == baseline check
$ venv/bin/python3 -m analysis.montecarlo.scenarios --run <name>     # expected-value deltas
$ venv/bin/python3 -m analysis.montecarlo.simulate --scenario <name> --n-draws 200 --seed 20260610
$ venv/bin/python3 -m analysis.montecarlo.report <name> --save       # → simulate/<name>/report.txt
```

Run from the repo root ([`requirements.txt`](../../requirements.txt) is
fully pinned). Tracked intermediates make the scenario pipeline
self-sufficient; rebuilding stages 1–8 from raw sources additionally needs
the gitignored `data/` inputs (`--build` flags on each module) and a
`CENSUS_API_KEY` for stage 4.
