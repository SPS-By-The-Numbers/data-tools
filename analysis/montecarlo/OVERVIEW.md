# SPS Yellow-Bus Ridership Monte Carlo — Technical Overview <a id="top"></a>

This document explains how the simulation is constructed: the pipeline
stages, the variables and the distributions they are drawn from, the
calibration strategy, and the modeling assumptions an expert should check
before trusting a number. Links go to the code in this directory; the
living project log (decision history, open questions, per-session results)
is [NOTES.md](NOTES.md). For the results rather than the methods, see the
**[scenario findings report](https://sps-by-the-numbers.github.io/data-tools/montecarlo/findings.html)**
(charts, fiscal impacts, and plain-language interpretation of every
scenario; generated from the saved runs by
[`findings_html.py`](findings_html.py)).

**What it estimates.** For a *scenario* — walk-zone resizes, school
closures, option→neighborhood conversions, school moves, adding bus service
— the model produces district and per-school deltas, with confidence
intervals, for:

- **basic & gifted ridership** in *rides per day* as counted by STARS —
  the Student Transportation Allocation Reporting System of OSPI
  (Washington's Office of Superintendent of Public Instruction), the
  state's per-district transportation reporting/funding dataset (AM and PM
  boardings each count once, so a both-ways student counts as 2);
- **route count** (rides ÷ district rides-per-route);
- **bus fleet** (2-bell-shift rule, below) and **annual bus cost**;
- **state reimbursement** (EXAL — the STARS *Expected Allocation* funding
  formula, below) and the
  **net fiscal delta**;
- rider-weighted stop→school distance, and equity cuts by school
  low-income share and ES attendance-area poverty.

Everything is calibrated to school year **2024-25**, the latest with full
STARS + OSPI Report Card overlap.

---

## Pipeline at a glance <a id="pipeline"></a>

Eleven stages, one module per stage, each writing tracked intermediate CSVs
so a fresh checkout can run without the gitignored raw sources:

| # | Stage | Module | Output |
|---|---|---|---|
| 1 | Geography | [`parse_shapes.py`](parse_shapes.py) | 7 SPS transportation shapefile layers, normalized |
| 2 | School directory | [`school_directory.py`](school_directory.py) | [`school_directory/`](school_directory/) — 98 schools, classification, name maps |
| 3 | Baseline ridership | [`baseline_ridership.py`](baseline_ridership.py) | [`baseline_ridership/`](baseline_ridership/) — STARS routes/targets × enrollment |
| 4 | ACS population | [`acs_population.py`](acs_population.py) | [`census_seattle/`](census_seattle/) — Census block groups (BG), age, public-school share (ACS = American Community Survey) |
| 5 | Synthetic population | [`synth_population.py`](synth_population.py) | `census_seattle/synth_pop.csv` — kids per BG × grade band + Dirichlet α |
| 6 | Assignment | [`assignment.py`](assignment.py) | [`assignment/`](assignment/) — P(school \| BG, band): iterative proportional fitting (IPF) anchored to observed origin–destination (OD) flows; both defined below |
| 7 | Eligibility | [`eligibility.py`](eligibility.py) | [`eligibility/`](eligibility/) — walk-zone membership fractions |
| 8 | Ridership | [`ridership.py`](ridership.py) | [`ridership/`](ridership/) — propensity model θ, expected rides |
| 9 | Scenario engine | [`scenarios.py`](scenarios.py) | applies [`scenarios/*.json`](scenarios/) specs to a `World` copy |
| 10 | MC driver | [`simulate.py`](simulate.py) | [`simulate/<name>/`](simulate/) — paired draws (district/school/θ CSVs) |
| 11 | Report | [`report.py`](report.py) | `simulate/<name>/report.txt` — deltas + CIs + fiscal sections |

Supporting ingests: [`stars_seattle.py`](stars_seattle.py) (STARS Seattle
slice → [`stars_seattle/`](stars_seattle/)), [`rc_seattle.py`](rc_seattle.py)
(Report Card enrollment + chronic absenteeism → [`rc_seattle/`](rc_seattle/)),
[`section4_seattle.py`](section4_seattle.py) (the 2024-25 enrollment-report
origin–destination tables → [`section4/`](section4/)), and the HCC
(Highly Capable Cohort, the district's gifted program) pathway maps
[`hcc_pathways_es.csv`](hcc_pathways_es.csv) /
[`hcc_pathways_ms.csv`](hcc_pathways_ms.csv).

```
ACS+TIGER ──► synth_pop ──┐                        ┌─► eligibility (walk zones)
                          ├─► assignment (IPF) ────┤
Section-4 OD ─────────────┘        ▲               └─► ridership (propensity θ)
RC enrollment (column marginals) ──┘                        ▲
STARS (district targets, routes) ───────────────────────────┘  ← calibration
```

## Geography and units <a id="geography"></a>

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

## Baseline construction <a id="baseline"></a>

### Synthetic population (stages 4–5) <a id="synthetic-population"></a>

ACS 5-year 2023 block-group age counts (table B01001) × tract-level
public-school fractions (B14003, suppressed at BG level) × Census
TIGER/Line 2023 boundary geometries, clipped
to SPS territory: 558 block groups, 76,474 school-age children, 75.7%
public ⇒ 52,904 expected public-school kids. Age→grade-band split is fixed
integer-grade algebra (5-9 → ES; 10-14 → 20/60/20 ES/MS/HS; 15-17 → HS).
The 1.06× over-count vs actual SPS enrollment is absorbed by the IPF column
constraints, not corrected ad hoc. See
[`synth_population.py`](synth_population.py).

### Assignment (stage 6) <a id="assignment"></a>

`P(school | block group, grade band)` is **anchored to observed flows**,
not a fitted gravity model: the 2024-25 Annual Enrollment Report Section 4
is an **origin–destination (OD) matrix** — for each attendance area
(origin), the count of resident students enrolled at each school
(destination), per grade level — so it pins down empirically where kids
from each area actually go (stay-rates ES 68.2% / MS 56.6% / HS 69.8%). The (BG × school) matrix is
then balanced by **IPF — iterative proportional fitting** (a.k.a. raking /
RAS): starting from a prior matrix, alternately rescale every row to its
row target and every column to its column target until both sets of
marginals converge; the result is the assignment closest to the prior (in
Kullback–Leibler divergence) that satisfies both totals exactly. The prior is
(block-group → attendance-area area-overlay weights) × (observed
P(school | area, band)); `ipf()` in [`assignment.py`](assignment.py)
matches **row marginals** (synthetic kids per BG, scaled per band to
enrollment totals) and **column marginals** (Report Card per-grade 2024-25
enrollment, 98 schools, PK excluded). Result: 19,094 cells. Option-school
draw kernels (single exponential distance decay per band, grid-searched
against the observed option draws: ES/MS 0.50 mi, HS 1.50 mi) are used only
to *generalize* flows under scenarios (e.g. a moved option school), not for
the baseline.

### Eligibility (stage 7) <a id="eligibility"></a>

Pure geometry, no fitting: `walk_fractions()` in
[`eligibility.py`](eligibility.py) computes, per (block group, school), the
fraction of the BG's SPS-territory area inside the school's official walk
zone. Missing pair = 0 (fully bus-eligible). Walk zones are the official
GIS polygons (hazard carve-outs included); per a verified SPS rule, ES and
K-8 zones are 1 mile and MS/HS 2 miles, and the K-8 layers' spurious 2-mile
union pieces are dropped in `parse_shapes.load_walkzones` (Licton Springs
has no 1-mile piece and keeps its smallest, 1.88 mi).

### Ridership (stage 8) <a id="ridership"></a>

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

**High school** (cells exist only when a scenario adds HS service — SPS
runs no HS basic yellow bus): HS rides are modeled as a *fraction of the
MS propensity*. HS cells take the MS tilt, times
`hs_indep_factor · (0.5 + 0.5·hs_car_factor)` — an all-HS discount
(default 0.7) for rides lost to independent travel on public transit,
especially after school, and an additional grades-11-12 discount (default
0.5; age 16+, kids get cars), with the two grade pairs weighted 50/50.
Effective default: 0.525 × the MS-like propensity. These are
user-specified assumptions, not fits (see assumption 2).

## Scenario engine (stage 9) <a id="scenario-engine"></a>

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

## Monte Carlo design (stage 10) <a id="monte-carlo"></a>

[`simulate.py`](simulate.py) runs a **paired design**: each draw samples
(θᵢ, populationᵢ) once and evaluates baseline and scenario with the *same*
draw, so deltas difference out shared noise. 200 draws ≈ 40 s.

**What a draw means.** Each draw constructs one plausible alternate world
by perturbing two kinds of inputs — *where the kids are* (the grade-band
mix of every block group, which the Census only measures with survey noise
and an approximate age→grade mapping) and *how families behave* (how fast
bus-riding falls off with distance, and how strongly it tilts with school
demographics — both estimated from a single year of noisy data). Baseline
and scenario are then evaluated in that same world. A reported interval
like "+2,073 [+1,901, +2,228]" reads: across a few hundred plausible
combinations of those inputs, the expected effect of the policy lands in
this range. It is uncertainty about the world the policy is applied to —
not year-to-year randomness, and not doubt about the district totals,
which are pinned to the official numbers in every draw.

**What is sampled, and from what:**

| variable | distribution | code |
|---|---|---|
| population: grade-band split per block group | Dirichlet(α), α_band = n_pub_band + 0.5 per BG; the sampled fractions × the BG's fixed `n_pub_total` | `sample_synth_pop` in [`synth_population.py`](synth_population.py) |
| `decay_mi` | lognormal around the fit: `decay·exp(N(0, σ=0.2))` | `sample_params` in [`simulate.py`](simulate.py) |
| each β (4 of them) | Normal(β̂, max(0.2·\|β̂\|, 0.05)) | same |
| `hs_indep_factor` (HS-only scenarios) | Normal(0.7, 0.1), clipped to [0.05, 1] | same |
| `hs_car_factor` (HS-only scenarios) | Normal(0.5, 0.2), clipped to [0.05, 1] | same |
| ρ, p_max | **fixed** at fitted values (the fit pinned ρ; p_max is structural) | same |
| scale s, gifted propensity | **solved per draw** on that draw's baseline cells, then reused for the paired scenario arm | `run_mc` |
| scenario behavioral params (stay-rate etc.) | **not sampled** — spec constants | — |

**Why these shapes:**

- **Dirichlet (population).** The (ES, MS, HS) shares of each block group
  must be non-negative and sum to 1 — a draw that adds middle schoolers
  must take them from the other bands, not invent people. The
  concentration α = estimated count + 0.5 (a weakly informative
  Jeffreys-style prior) makes the draw's mean ≈ the point estimate and its
  variance shrink as counts grow: a 200-kid block group barely moves, a
  6-kid one swings a lot. Each BG's total stays fixed; draws are
  independent across block groups (no spatial error correlation — a known
  simplification).
- **Lognormal (decay).** The decay length must stay positive, and its
  uncertainty is naturally relative ("about ±20%") rather than additive —
  `exp(N(0, 0.2))` is a multiplicative wiggle whose *median* is the fitted
  4.69 mi.
- **Normal with a floor (βs).** sd = 20% of each estimate expresses "trust
  each tilt to within about a fifth of its size"; the 0.05 absolute floor
  keeps near-zero coefficients (β_absent = 0.06) from being treated as
  precisely known when they are the least pinned-down. βs are sampled
  independently of each other and of the decay — no covariance from a
  joint fit.
- **Fixed ρ.** The fit pinned ρ; sampling it would re-introduce a shape
  the data firmly rejected.

These are "start-simple" perturbations around a point fit — chosen for
shape correctness (positivity, sum-to-one, relative scaling), not derived
from a likelihood or posterior; the 0.2's and the 0.05 floor are judgment
calls (assumption 9 below).

Two further deliberate choices to scrutinize:

1. **Calibration is per-draw.** The district targets (10,008.5 / 1,315.5)
   are observed facts, not uncertain inputs, so every sampled world
   reproduces them at baseline; uncertainty lives in the per-school split
   and in all deltas. Baseline district totals are therefore degenerate
   across draws *by construction*. The solved scale and gifted propensity
   are not distributions of their own — they are deterministic functions
   of the draw.
2. **No count noise.** Draws propagate parameter (θ) and population
   uncertainty through *expected* rides per cell; there is no Poisson
   resampling in the driver (a `sample_riders` wrapper exists in
   [`ridership.py`](ridership.py) but is unused). CIs are uncertainty in
   the expected value, not year-to-year realization noise.

Scenario worlds are built once from the expected-value baseline (geometry
and flow edits don't depend on the draw); per-world walk fractions are
hoisted out of the loop. Reported CIs are 95% percentile intervals over
draws. All reported runs use `--n-draws 200 --seed 20260610`.

## Fiscal models (stage 11) <a id="fiscal-models"></a>

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

**State reimbursement (EXAL = Expected Allocation).** The STARS funding
formula (`funding_summary`, constants `EXAL_COEF` / `EXAL_BASE`):

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

## Calibration & validation summary <a id="validation"></a>

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

## Modeling assumptions & limitations <a id="assumptions"></a>

Roughly ordered by how much they could move a result.

1. **Rides, not riders.** All "rider" quantities are boardings/day; unique
   students ∈ [rides/2, rides]. The propensity is rides/day per eligible
   student (max 2), and its fitted distance decay partly *is* the AM-only
   behavior on long routes.
2. **HS ridership is an extrapolation.** SPS has run no HS basic yellow bus
   in the STARS record (ORCA only), so `add_basic_service` scenarios model
   HS as a *fraction of MS*: the MS tilt × 0.7 (all HS — losses to
   independent transit travel, especially PM) × (0.5 + 0.5·0.5) (grades
   11-12 at half — cars), ≈ 0.525 overall, with both factors sampled in
   the MC. The structure and the levels are user-specified judgment, and
   basic rides-per-route is reused for routes; nothing calibrates any of
   it.
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
   structural uncertainty — the independence assumptions (βs sampled
   independently of each other and of the decay; block-group population
   draws spatially uncorrelated) are the most likely source of
   under-coverage.
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

## Reproducing <a id="reproducing"></a>

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
