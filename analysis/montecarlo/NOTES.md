# Ridership Monte Carlo — Project Notes (living document)

**Purpose:** Estimate how Seattle Public Schools (SPS) yellow-bus *ridership*
changes under (a) **walk-zone boundary changes** and (b) **school closures**,
using public data to build a bottom-up estimate of where school-age children
live. Monte Carlo because the inputs (where kids live, who opts in, ride-share
rates) are uncertain and we want distributions, not point estimates.

> This file is the durable handoff between sessions. **Update it at the end of
> every working session**: move items between sections, append to the Decision
> Log, and refresh "Current State". A fresh context should be able to read this
> top-to-bottom and continue without re-deriving anything. Keep it honest —
> record what is *assumed/unverified* as well as what is *done*.

Last updated: **2026-06-10** (session 10 — 11 user scenarios specified +
run end-to-end: walk-zone changes, HS bussing, KUOW Option A/B closures,
option→neighborhood conversions, fab-4 closure. New 6th op
`add_basic_service`; bus-fleet cost model ($148.9k/bus-yr, 2-bell-shift
fleet rule) and the STARS EXAL funding formula wired into report.py →
every report now ends in a NET fiscal Δ ($M/yr). UNITS CORRECTION: all
"riders" figures are STARS rides/day (AM+PM boardings; both-ways student
= 2). Results: scenario + fiscal tables in "User scenarios" below; full
text in `simulate/<name>/report.txt`). The machinery runs any spec
end-to-end in ~40 s for 200 draws:
`python3 -m analysis.montecarlo.simulate --scenario <name>` then
`python3 -m analysis.montecarlo.report <name> --save`. Remaining
model-quality work: the Madison+Denny→Washington 2023-2025 MS-pathway
assumption (4b note) is still unverified; known per-school basic/gifted
double-count at the 4 mixed MS pathway sites (see the HCC-verification
decision-log entry).

Scenario scope EXPANDED in session 2: besides walk-zone changes and closures,
we also model **converting option schools to neighborhood schools** and
**moving option schools**.

---

## Current state (what exists today)

- **`findings_html.py`** → **`docs/montecarlo/findings.html`** — NEW (s10):
  self-contained findings report (inline-SVG charts, no external deps) for
  a school-board/advocacy audience, PUBLISHED via GitHub Pages (main:/docs)
  at https://sps-by-the-numbers.github.io/data-tools/montecarlo/findings.html
  and linked from OVERVIEW.md. Fig 1 Δrides with CIs, Fig 2 routes vs
  buses (bell-shift effect), Fig 3 fiscal (funding slate / cost yellow —
  deliberately valence-neutral hues, user request), full table +
  per-scenario cards + key findings + caveats. REGENERATE after any
  re-run: `python3 -m analysis.montecarlo.findings_html` (it reads the
  saved `simulate/<name>/` runs via the report-stage summary functions, so
  it always matches the tracked outputs; editorial blurbs live in the
  script's SCENARIOS list — update them when adding scenarios).
- **`breakdown.py`** — NEW (s10): per-school assumption + delta breakdown
  for one scenario → `simulate/<name>/breakdown.md`. Shows the RESOLVED
  assumptions (e.g. closure receivers with kids-received shares, engine
  default vs spec-named), the evaluation invariants, and a per-school
  table: enrolled / bus-eligible / EV rides baseline→scenario with the MC
  Δ + 95% CI from the saved run. Run:
  `python3 -m analysis.montecarlo.breakdown <scenario>`. First use:
  close_sacajawea (Olympic View 74% / Wedgwood 20% / Rogers 6% of the 196
  displaced kids). `compute()` returns the structured data;
  `findings_html.py` embeds the same breakdown as an expandable
  `<details>` per scenario in the published findings page (§5).
- **`OVERVIEW.md`** — NEW (s10): technical documentation of the simulation
  (pipeline construction, variables + sampling distributions, fitted θ,
  fiscal models, calibration/validation table, enumerated assumptions and
  limitations) with GitHub links into the code. Audience: technical
  reviewers. KEEP IN SYNC when the model changes — especially the fitted-θ
  table, the validation table, and the assumptions list.

- **`parse_shapes.py`** — DONE. Loads + normalizes the 7 SPS transportation
  shapefiles into a `Shapes` dataclass. Run `python3 -m
  analysis.montecarlo.parse_shapes` for a summary. This is the geographic
  foundation; everything downstream joins on `school_id`.
- **`stars_seattle.py`** — DONE. Extracts the Seattle (ccddd 17001) slice of
  STARS from gitignored `out_stars/` and writes **tracked** intermediate CSVs
  to `analysis/montecarlo/stars_seattle/` (so future sessions don't need
  `out_stars/`). `--build` regenerates; loader fns (`load_routes()`,
  `load_efficiency()`, …) read the intermediates. This is the **ridership
  ground truth** for calibration. See that dir's README for the file map.
- **`plot_ridership.py`** — DONE. Splits basic-program ridership into yellow-bus
  (`on_bus`) vs transit-pass (ORCA) from `quarterly_metrics` and plots both.
  Output `ridership_bus_vs_transit.png`. **Model on_bus, not `basic_riders`.**
- **`rc_seattle.py`** — DONE. Ingests OSPI Report Card **enrollment**
  (`data/enrollment/rc_enrollment_17001.csv`) and **SQSS chronic absenteeism**
  (`safs_prod/sqss/rc_sqss.avro`, all-district) into tracked intermediates under
  `rc_seattle/`. Loaders: `load_enrollment()`,
  `load_attendance_all_students()`, `load_attendance_by_group()`. Lets us
  distribute riders across schools by enrollment + demographics + absenteeism.
- **`school_directory.py`** — DONE (session 3). Stage 2: canonical school
  list with classification + program flags, plus two name maps. Run
  `python3 -m analysis.montecarlo.school_directory` (or `--build` to
  regenerate). Outputs tracked under `school_directory/` — see README there.
  Key outputs:
  - `schools.csv` — 98 rows: school_id, school_code, name, level,
    classification (neighborhood/option/hcc_pathway/service), is_hcc_site_*
    (3 era configs), has_gifted/has_bilingual/has_early_ed from STARS.
  - `stars_name_map.csv` — all 154 STARS destination_names → school_id
    (0 unmatched; 4 fuzzy all verified correct). Also written back to
    `stars_seattle/destinations.csv` (school_id column now filled).
  - `section4_name_map.csv` — all 197 Section 4 school/area names → school_id
    (0 unmatched; 44 non-school/program entries correctly get NA).
  IMPORTANT: normalization is iterative (strips multiple suffixes per name);
  "West Seattle H.S." has an explicit override → 19 (would otherwise collide
  with "west seattle" → 236 Elementary). Override dicts in the module are the
  durable fix — don't rely on fuzzy-matching for these cases.
- **`baseline_ridership.py`** — DONE (session 4). Stage 3: per-school ×
  program × year calibration table + kernel validation. Run
  `python3 -m analysis.montecarlo.baseline_ridership` (or `--build` to
  regenerate). Outputs tracked under `baseline_ridership/` — see README there.
  Key outputs:
  - `school_routes.csv` — 1,666 rows: school_id × program × year (98 schools,
    9 years 2017-25, 6 programs); n_routes, avg_distance_mi, avg_stops.
  - `school_enrollment.csv` — 1,056 rows: school_id × year (98 schools, 11
    years 2014-24); enrollment + demographics. 2024-25 total = 49,765 in 98
    SPS schools (9 non-SPS programs excluded).
  - `district_targets.csv` — 9 rows (per year 2017-25): district-level
    riders/routes/buses by program, averaged across quarters. 2024-25:
    basic_students_on_buses=10,008; gifted=1,316; routes_basic=202.
  - `kernel_check.csv` — 60 rows: basic vs gifted distance for 17 schools with
    BOTH programs. **Kernel hypothesis confirmed:** 88.3% of non-COVID rows
    have gifted > basic distance. Pure HC schools (Cascadia/Decatur/TM) have
    no basic routes → correctly absent (their draw is entirely HCC).
- **`acs_population.py`** — DONE (session 5). Stage 4: ACS 5-year 2023 data
  (B01001 age×sex at block-group level; B14003 school enrollment public/private
  at tract level — suppressed at BG), plus TIGER/Line 2023 WA block-group
  geometries, clipped to SPS territory. Raw cache → gitignored `data/census/`;
  tracked intermediates → `census_seattle/` (see README there).
  Key outputs:
  - `block_groups.csv` — 558/1545 King County BGs with SPS overlap; GEOID,
    geoid_tract, area/sps_area/sps_frac, centroid, geometry_wkt (EPSG:2926).
  - `acs_age.csv` — per BG: age_5_9/10_14/15_17/age_5_17. District total: 76,474.
  - `acs_enrollment.csv` — per BG (tract-level fractions): pub/priv counts and
    pub_frac by age band. District avg: 75.7% public.
  Build: `python3 -m analysis.montecarlo.acs_population --build`
  (CENSUS_API_KEY env var required; TIGER zip cached after first run)
- **`synth_population.py`** — DONE (session 5). Stage 5: combines age + enrollment
  → expected public school children per block group × grade band (ES/MS/HS).
  Age-to-grade split: 5-9→100% ES; 10-14→20%ES/60%MS/20%HS; 15-17→100%HS.
  Public-school fraction from parent tract. sps_frac area-weights partial overlaps.
  Key outputs:
  - `census_seattle/synth_pop.csv` — 558 rows: n_pub_es/ms/hs, n_pub_total,
    alpha_es/ms/hs (Dirichlet α for MC sampling). District total: 52,904
    (49,765 SPS enrollment → 1.06x ACS over-count, expected; IPF will calibrate).
    Grade split: ES 46.8%, MS 23.2%, HS 30.0%.
  Sampler: `sample_synth_pop(rng)` draws grade-band fractions from Dirichlet
  per block group; district total is preserved, variance is spatial + grade-band.
  Build: `python3 -m analysis.montecarlo.synth_population --build`
- **`assignment.py`** — DONE (session 6). Stage 6: baseline P(school | block
  group, grade band) anchored to Section 4 OD flows + IPF. Run
  `python3 -m analysis.montecarlo.assignment` (or `--build`). Outputs tracked
  under `assignment/` — see README there.
  Key outputs:
  - `assignment_matrix.csv` — 19,094 cells: GEOID × school_id × grade_band
    (es/ms/hs) → n_expected, p. Rows = synth_pop kids (scaled ×0.93/0.87/0.95
    per band to enrollment totals); columns = RC per-grade 2024-25 enrollment
    by band (98 schools, PK excluded); prior = BG-area overlay weights ×
    observed P(school|area,band). IPF: columns exact, row residual ≈ 0.
  - `kernel_params.csv` — option-kernel exponential decay fit to OD draws:
    ES 0.50 mi (TV 0.28 vs 0.75 uniform), MS 0.50 mi, HS 1.50 mi.
  API: `load_assignment()`, `load_kernel_params()`,
  `build_matrix(pop=sample_synth_pop(rng))` (MC hook),
  `kernel_bg_weights(school_id, kind, band)` for scenario kernels
  (neighborhood / option / hcc_pathway — hcc uses `hcc_pathways_{es,ms}.csv`
  by band, s9).
  GOTCHA: ES od rows with grade_band "6-8" (Blaine/Broadview-Thomson blocks)
  are EXCLUDED from flows — those kids are already in the MS OD tables.
- **`eligibility.py`** — DONE (session 6; rebuilt s9 after the K-8 1-mile
  fix). Stage 7: walk-zone membership, pure geometry. `walker_fractions.csv`
  (tracked under `eligibility/`): 2,654 nonzero (GEOID, school_id) →
  walk_frac pairs (fraction of the BG's SPS-territory area inside the
  school's official walk zone; missing pair = 0). Scenario hook:
  `walk_fractions(walkzones=<gdf>)` recomputes for resized polygons. API:
  `load_walker_fractions()`, `bus_eligible()` (joins Stage 6 × Stage 7 → per
  school × band n_assigned/n_walk/n_bus_eligible), `validate_pipeline()`.
  **M4 validation (2024-25, s9 numbers): PASS** — 77 basic-route schools,
  ES+MS assigned 31,123, bus-eligible 15,500; implied on-bus propensity
  10,008/15,500 = **0.646**; per-school bus-eligible vs STARS basic routes
  Pearson r=0.715, Spearman ρ=0.609.
- **`ridership.py`** — DONE (session 7). Stage 8: ride propensity → expected
  riders per school × program, tracked under `ridership/` (see README there).
  Model per cell: `p = clip(s·f(d)·exp(β·x), 0, 0.95)` with
  `f(d) = (1−ρ) + ρ·exp(−d/decay_mi)` (d = BG centroid → school point) and
  centered school covariates x = (is_ms, low_income_frac, swd_frac,
  absent_rate); s re-solved every call so basic riders = the STARS district
  target (10,008) — hard renormalization, θ shapes only the distribution.
  Fitted θ (2024-25, refit s9 after the K-8 + MS-pathway fixes): ρ=0.85
  (decay + a 0.15 flat floor), decay 4.69 mi, β_ms +0.12, β_li +0.31,
  β_swd +5.62, β_abs +0.06 (≈0; confirmed noise). Per-school riders vs
  STARS basic routes: **r 0.715 (flat M4) → 0.806 (shaped)**. Gifted: HC
  enrollment at the 7 gifted-route sites spread by HCC pathway kernel (ES
  era 2023-2025 + MS map, s9 — 4b resolved); solved propensity 0.918 vs the
  1,316 target.
  Riders→routes via district riders-per-route (basic 49.5, gifted 32.9).
  API: `load_ridership()`, `load_params()` → `RidershipParams` (θ dataclass),
  `expected_riders(assignment, walk, params)` pure core,
  `sample_riders(rng, ...)` Poisson MC wrapper. Stage 10 samples θ via
  `dataclasses.replace(load_params(), ...)`.
- **`scenarios.py`** — DONE (session 8; 6th op s10). Stage 9: scenario
  engine — the 6 ops (`set_walk_threshold`, `scale_walkzone`, `close_school`,
  `convert_option_to_neighborhood`, `move_school`, `add_basic_service`
  (s10 — grants basic service by level or ids, e.g. re-add HS bussing;
  `World.bus_bands` + `basic_cells(bands=)` carry the served grade bands))
  over a `World` dataclass
  copied from the baseline; specs are tracked JSONs under `scenarios/` (see
  README there). Run `python3 -m analysis.montecarlo.scenarios`
  (`--validate` = empty-scenario baseline check, `--run <name>` = delta
  report). Key design (full semantics in the module docstring):
  - Residence strata (BG × attendance-area weights) are FIXED; ops edit only
    the destination side: flow columns, enrollment marginals, walk zones,
    school points, gifted table. Enrollment band totals conserved exactly.
  - Walk resize = calibrated buffers (per-school multiplier reproducing the
    official polygon AREA at ES 1 mi / MS,HS 2 mi). Empty scenario keeps the
    official polygons.
  - Closure moves the school's flow column to receivers (kids stay put);
    defaults: 3 nearest same-level neighborhood schools split ∝ existing
    draw per area / nearest option site / HCC pathway relocates intact
    (member areas + HC enrollment merge into `hcc_receiver`).
  - Conversion (steady-state, no grandfathering): geozone residents attend
    at the band's observed stay-rate; old decay-draw enrollees return to
    their areas' other destinations pro-rata.
  - Scenario evaluation REUSES the baseline-solved propensity scale +
    covariate centering (`fixed_scale` / `covar_means` added to
    `ridership.py`) — re-solving would renormalize every scenario back to
    10,008 and all deltas would vanish.
  - **M6 validation PASS** (re-confirmed s9 after each model change): empty
    scenario reproduces the tracked baseline within CSV rounding (19,094
    cells max |Δ| 5e-5; walk 5e-7; riders 0.005). EV smokes on the final s9
    model: `close_sacajawea` −104 riders at Sacajawea reabsorbed by 3
    neighbors, district −7.6; `es_walk_1p5mi` basic 10,008→7,485 (−51
    routes est).
- **`simulate.py`** — DONE (session 9). Stage 10: the paired MC driver.
  `run_mc(scenario, n_draws, seed)` samples θ (`sample_params`: decay_mi
  lognormal σ=0.2, betas normal sd=max(0.2|β̂|, 0.05), ρ fixed at the fitted
  1.0 boundary) + population (`sample_synth_pop`) per draw, evaluates
  baseline and scenario with the SAME draw. **Calibration is PER-DRAW**: the
  propensity scale, covariate means, and gifted propensity are re-solved on
  each draw's baseline cells then reused for the paired scenario run —
  baseline district totals hit the STARS targets every draw by construction;
  uncertainty lives in the per-school split and all deltas. Per-world
  invariants (mutated World, walk fractions) hoisted out of the loop →
  **~0.2 s/draw** (the old 30-60 s/evaluate estimate was cold-cache). Saves
  tracked CSVs under `simulate/<scenario>/` (see README there):
  district_draws / school_draws / theta_draws / meta.json. CLI:
  `--scenario <name> [--n-draws 200] [--seed] [--no-theta] [--no-pop]`;
  no-arg lists saved runs. API: `run_mc()`, `load_run()`, `sample_params()`.
- **`report.py`** — DONE (session 9). Stage 11: summarizes a saved run —
  district rider + est-route deltas with 95% percentile CIs, rider-weighted
  distance stats (mean/p50/p90), per-school movers with CIs, equity cuts
  (basic Δriders per draw grouped by RC low-income terciles and by ES
  attendance-area `poverty` terciles). CLI: `python3 -m
  analysis.montecarlo.report <name> [--save] [--top N]`. **M7 validation
  PASS (re-confirmed s9 on the final model — K-8 1-mi + MS pathways):**
  `close_sacajawea` 200 draws → district basic Δ −7.1, 95% CI [−13.3, −1.8]
  brackets the expected-value −7.6. `es_walk_1p5mi` 200 draws → basic
  Δ −2,523 [−2,664, −2,405] (EV −2,524), gifted −86.5, est routes −51.
  **Headline outputs (user, s9): Δriders, Δroutes, Δ avg stop→school
  distance** — school_draws carries per-school rider-weighted distance; no
  AM/PM split (STARS has no direction/AM-PM dimension anywhere — checked
  metrics + route numbering).
- **`section4_seattle.py`** — DONE (session 2). Parses
  `data/2024-25-section4.pdf` into the observed area→school OD matrix +
  option-school draw tables under tracked `section4/`. The empirical anchor
  for the assignment stage. `--build` regenerates; loaders `load_od()`,
  `load_attendees()`, `load_option_draw()`.
- **`hcc_pathways_es.csv`** — DONE (session 2). ES attendance area → HC
  pathway site mapping, three era configs (2017-2022 incl. Fairmount Park,
  2023-2025, proposed 2025 map). ES HCC kernel = exact union of areas.
- **Planning DONE (session 2):** architecture locked (see below), scenario
  scope expanded (conversions + moves), build order M1-M7 set. No simulation
  code exists yet — next concrete step is Stage 2 `school_directory.py`
  (STARS name→school_id join + school classification).

### User scenarios — SPECIFIED + RUN session 10 (Prompt D)
All three: spec under `scenarios/`, 200-draw MC (seed 20260610) under
`simulate/<name>/`, full summary in `simulate/<name>/report.txt`. Deltas are
vs. the 2024-25 baseline (basic 10,008 riders / 202 routes), 95% CIs.

UNITS (user correction, s10): "riders" everywhere = STARS **rides/day**
(AM + PM boardings each count; a both-ways student = 2; unique students are
between half and all of the figure — long-route kids often ride AM only).

| scenario | spec | Δ basic rides/day | Δ est routes | Δ buses (fleet-only $M/yr; see fiscal table for with-overage) | Δ avg stop→school dist |
|---|---|---|---|---|---|
| `ms_walk_1mi` | MS walk zones 2 → 1 mi | **+2,073** [+1,901, +2,228] | +41.8 [+38.4, +45.0] | **+0.0 (+$0.00)** | −0.08 mi (district mean) |
| `hs_bussing` | re-add HS yellow bus, walk zones as-is (2 mi) | **+1,659** [+1,143, +2,332] | +33.5 [+23.1, +47.1] | **+0.0 (+$0.00)** | +0.15 mi |
| `hs_bussing_1mi` | HS yellow bus + HS walk zones 2 → 1 mi | **+3,532** [+2,411, +4,908] | +71.3 [+48.7, +99.1] | **+0.0 (+$0.00)** | +0.06 mi |
| `hs_ms_bussing_1mi` | HS bus + 1-mi walk zones for MS *and* HS | **+5,615** [+4,417, +7,085] | +113.3 [+89.2, +143.0] | +6.5 [0, +35.5] (+$0.97) | −0.02 mi |
| `close_option_a` | KUOW "well-resourced" plan: close 21 schools | **−147** [−227, −63] | −3.0 [−4.6, −1.3] | −8.4 (−$1.25) | +0.04 mi |
| `close_option_b` | KUOW "choice" plan: close 17 schools incl. Thurgood Marshall | **+279** [+233, +328] | +5.6 [+4.7, +6.6] | +2.7 (+$0.40) | +0.07 mi |
| `close_fab4` | close North Beach, Sacajawea, Stevens, Sanislo → named single receivers | **+174** [+141, +206] | +3.5 [+2.8, +4.2] | +3.5 (+$0.52) | ±0.00 mi |
| `dissolve_hcc` | ALL HCC schools → neighborhood (Cascadia/Decatur get 1-mi catchments); gifted Δ −1,315.5, −40 routes | **+339** [+290, +385] | +6.8 (basic) | −15.3 (−$2.28) | −0.00 mi |
| `close_option_a_no_hcc` | Option A + dissolve HCC first (gifted −1,315.5) | **+338** [+216, +462] | +6.8 (basic) | −21.3 (−$3.17) | +0.04 mi |
| `close_option_b_no_hcc` | Option B + dissolve HCC first (gifted −1,315.5) | **+739** [+668, +809] | +14.9 (basic) | −10.5 (−$1.56) | +0.07 mi |
| `convert_optA_5` | 5 option schools → neighborhood (LS excluded by user) | **−171** [−195, −145] | −3.4 [−3.9, −2.9] | −3.3 (−$0.49) | +0.07 mi |

Bus/cost column from the bell-shift fleet rule (s10, see below): MS/HS-shift
route additions are FREE in fleet terms while the ES shift stays the busier
one — which is why `ms_walk_1mi` and `hs_bussing` show +42/+56 routes but
+0 buses, and why the conversions (+4.8 routes, all ES-shift) cost MORE
buses (+7.5) than their net route delta.

Fiscal totals with the STARS EXAL funding formula (s10, 95% CIs; revenue =
state reimbursement change; cost = fleet Δ × $148.9k + overage-hours
ASSUMPTION (2.0 hr/route/day × $61.5 × 175 d ≈ $21.5k/route-yr for routes
on existing buses, s10) — fleet-only lower bound in parentheses; NET =
revenue − with-overage cost (fleet-only NET in parens where it differs):

| scenario | Δ EXAL revenue $M/yr | Δ bus cost $M/yr (fleet-only) | **NET $M/yr** (fleet-only) |
|---|---|---|---|
| `ms_walk_1mi` | +5.33 [+4.90, +5.71] | +1.01 (0.00) | **+4.33** (+5.33) |
| `hs_bussing` | +5.17 [+3.81, +6.98] | +0.72 (0.00) | **+4.45** (+5.17) |
| `hs_bussing_1mi` | +9.65 [+6.87, +12.98] | +1.53 (0.00) | **+8.11** (+9.65) |
| `hs_ms_bussing_1mi` | +14.62 [+11.78, +17.96] (≈$51.3M total — under the cap) | +3.37 (+0.97) | **+11.24** (+13.65) |
| `close_option_a` | −10.29 [−10.44, −10.12] | −1.14 (−1.25) | **−9.15** (−9.04) |
| `close_option_b` | −7.71 [−7.81, −7.61] | +0.46 (+0.40) | **−8.17** (−8.11) |
| `close_option_b_dearborn` | −7.71 [−7.81, −7.61] | +0.44 (+0.37) | **−8.15** (−8.08) |
| `close_fab4` | −1.73 [−1.82, −1.66] | +0.52 (+0.52) | **−2.26** |
| `dissolve_hcc` | −0.62 [−0.73, −0.51] | −2.66 (−2.28) | **+2.04** (+1.66) |
| `close_option_a_no_hcc` | −10.44 [−10.66, −10.22] | −3.43 (−3.17) | **−7.01** (−7.27) |
| `close_option_b_no_hcc` | −7.99 [−8.12, −7.85] | −1.88 (−1.56) | **−6.11** (−6.43) |
| `convert_optA_5` | −0.50 [−0.57, −0.42] | −0.49 (−0.49) | **−0.00** [−0.02, +0.02] |
| `close_sacajawea` | −0.62 [−0.64, −0.61] | −0.08 (−0.09) | **−0.54** (−0.53) |
| `es_walk_1p5mi` | −6.74 [−7.15, −6.39] | −7.97 (−7.97) | **+1.24** |

(Destinations CORRECTED s10 — counted vs the any-program served set;
closure defaults CHANGED to the everywhere-rule s10 — see the decision-log
entries. No scenario crosses the $59.8M cap.) Headline: the KUOW closure
plans LOSE ~$8.2-9.2M/yr of state transportation funding net — the
Destinations term (each closed served school −0.01523 in the exponent ≈
−$0.55M at current levels) dominates; under the everywhere-rule the
ridership side is now small (A even SAVES rides/buses by dispersing long
option-K-8 draws). Building-operations savings ($31.5M/$25.5M) are
outside this model. Expanding service is revenue-POSITIVE on boardings
(`hs_bussing` nets +$4.5M/yr; only Nova is a NEW destination).
es_walk_1p5mi (service cut) loses revenue but saves more in buses →
net +$1.2M.

Notes: `ms_walk_1mi` also adds +162 gifted riders (MS HCC pathway sites'
walk zones shrink); K-8s are level "ES" so the MS op leaves them alone.
The closure pair (from the KUOW article on SPS's 2024 consolidation
proposals) uses the engine's DEFAULT relocation rules, NOT SPS's actual
boundary-redraw maps: neighborhood kids → 3 nearest open neighborhood ES
split by existing draw; option kids → nearest open option site (Pathfinder
+~380 and Hazel Wolf +~118 riders absorb most displaced option-K-8 kids in
both plans); HCC pathways relocate intact — Decatur's HC draw → Cascadia
(default; 646 gifted riders there in both plans), and in B Thurgood
Marshall's HC → **Beacon Hill International (205), per the plan**
(USER-CORRECTED s10; `close_option_b_dearborn` is the Dearborn Park (251)
alternative the plan also names — district deltas identical, gifted Δ +1.3
vs −3.4). Option B adds MORE bus riders than A despite closing fewer
schools — A
eliminates more big option-K-8 ridership outright while B's TM closure
scatters central-Seattle kids farther. Both plans skew rider GAINS toward
high-poverty areas (equity cut, e.g. A: high-poverty ES tercile +705 vs
low +362) — displaced kids in those areas more often land outside their
receiver's walk zone.
The HS pair rests on a **non-calibratable assumption** (refined s10, user
direction): HS rides = a fraction of the MS propensity — MS tilt ×
hs_indep_factor 0.7 (all HS; independent transit travel, esp. PM) ×
(0.5 + 0.5·hs_car_factor 0.5) (grades 11-12; cars) ⇒ 0.525 × MS, both
factors MC-sampled — plus the basic 49.5 rides-per-route. There is no SPS
HS yellow-bus history to fit against (HS has been ORCA-only; STARS shows
zero HS basic routes). All 13 open HS-level sites get service, incl.
Center School (option) and Nova (service).
`school_code` (4-digit OSPI building code) is a **clean** join across
geography + enrollment + absenteeism:
- `parse_shapes.load_locations().school_code` ↔ `rc_seattle` enrollment/attendance
  `school_code` = **98/98 exact match** (names cross-check). No fuzzy matching.
- enrollment ↔ attendance = 113/114 school_code overlap.
- Use `year` (int fall start) to bridge the 3 school-year string formats
  (enrollment `2014-15`, SQSS `2014-2015`, STARS `2017-2018`).
- **Only STARS** is still keyed by messy `destination_name` (deferred join).
  Note: `parse_shapes` also has `school_id` (3-digit site #) distinct from
  `school_code`; STARS routes have neither — must map by name.

### Environment / deps
- Work inside the repo venv: `source venv/bin/activate`.
- `requirements.txt` is fully PINNED (s9) to the working venv, including the
  geo stack (`geopandas` 1.1.3, `shapely`, `pyproj`, `pyogrio`) and the
  pandas 3.0.3 / numpy 2.4.6 they pulled forward. Single requirements file —
  no separate geo-requirements; the SAFS pipeline runs on the same versions.

---

## Data inventory

### Source shapefiles — `data/transit/shapes/Transpo Files/` (untracked working data)
All parsed by `parse_shapes.py`. Native CRS: school points are EPSG:3857 (Web
Mercator); all polygons are EPSG:2926 (NAD83(HARN)/WA North, **US feet**). The
parser standardizes everything to **EPSG:2926** (feet → good for walk-distance
thresholds) and reprojects to 4326 on demand for lat/long.

| Normalized layer | n | Geometry | Notes |
|---|---|---|---|
| `locations` | 98 | Point | **All 98 have coords.** school_id, school_code, name, level (ES/MS/HS), grades, status |
| `walkzones` | 101 | (Multi)Polygon | dissolved per school; walkzone, region (NE/SE/…), grades |
| `attendance_es` | 58 | Polygon | has **`poverty`** + feeder `ms_sch`/`ms_zone` |
| `attendance_ms` | 12 | Polygon | |
| `attendance_hs` | 10 | Polygon | |
| `option_esk8` | 13 | Polygon | option/choice ES+K8 eligibility zones |
| `option_hs` | 2 | Polygon | option/choice HS eligibility zones |
| `regions` (derived) | 95 | Polygon | long-form stack of all attendance+option zones for point-in-polygon |

**Key facts established:**
- Universal join key is **`school_id`** (3-digit SPS site number, e.g. 209 =
  Bryant). `school_code` (4-digit) is the separate OSPI/state code.
- All geometries valid; none empty.
- Walk zones: raw 117 rows → 101 schools after dissolving disjoint pieces.
  Dropped 6 rows with `school_id == 0` (unidentified program sites, no
  walk-zone name).
- 4 walk-zone school_ids (911/950/960/983 = John Marshall, South Lake, World
  School, "Y - Mc @ Uw") are closed/leased/service schools absent from
  `locations`. Kept but flagged.
- **SPS walk thresholds — VERIFIED s9** against
  https://www.seattleschools.org/resources/transportation/ : "Elementary and
  K-8 schools have a 1-mile walk boundary"; "Middle schools have a 2-mile
  walk boundary" (yellow bus OR Metro ORCA); "High schools have a 2-mile
  walk boundary" (ORCA only — consistent with STARS showing zero HS basic
  yellow-bus routes). Shapefile reach medians match (0.92/1.89/1.87 mi).
  **Open discrepancy (question 7):** the website says K-8 = 1 mile, but the
  raw walk-zone layer carries separate ~1-mi AND ~1.7-2.0-mi pieces for most
  K-8s (Hazel Wolf, TOPS, Orca, South Shore, Broadview-Thomson, Blaine,
  Licton Springs) which our dissolve unions — so the model's K-8 walk zones
  follow the GIS (2-mi for the union), not the published 1-mi rule.

### Public data sources to wire in (NOT yet pulled)
Goal: estimate the count + location of school-age children, by grade band, at a
fine geographic level (block group / tract) so we can intersect with attendance
& walk zones.
- **US Census / ACS** (tract & block-group): population by age, school
  enrollment (public vs private), B14001/B14003, B01001 age tables.
- **Census TIGER/Line**: block-group + tract polygons for King County (to
  intersect with SPS zones). Need same-CRS handling.
- **SAIPE** (Small Area Income & Poverty Estimates): district-level poverty,
  cross-check vs the ES `poverty` attribute already in the shapefile.
- **American Community/Family Survey**: household composition, ride behavior (?).
- **Seattle Open Data / King County GIS**: parcels, residential units, maybe
  finer child-density signals.
- **King County Public Health**: ? (user listed it — clarify what signal).
- **OSPI / SAFS pipeline (this repo!)**: actual enrollment by school
  (`enrollment` dataset) and P223 monthly counts — the ground truth to
  *calibrate* the synthetic population against. This repo already ingests these
  into BigQuery (`safs_enrollment`, `ospi`). **Reuse, don't re-fetch.**
  Seattle Report Card enrollment + chronic absenteeism now ingested →
  `rc_seattle/` (see below).
- **STARS** (already analyzed in `analysis/stars_*`): the OSPI student
  transportation allocation reports — directly about ridership/eligibility.
  Review what the existing STARS work established before modeling ridership.
  **Seattle slice now ingested** → `stars_seattle/` (see below).

### STARS Seattle slice — INGESTED this session → `analysis/montecarlo/stars_seattle/`
- Built by `stars_seattle.py --build` from `out_stars/` (gitignored), filtered
  to ccddd 17001. Intermediates are tracked CSVs. Years 2017-2018..2025-2026.
- Key tables: `routes` (13.3k per-route rows: destination/program/stops/
  average_distance), `quarterly_metrics` (riders by program & quarter),
  `efficiency` (annual buses/riders/distance), `kpi`, `operations_allocation`,
  plus `d_*` decoders. Derived: `destinations` (154 names) + `routes_by_school_year`.
- **Calibration signal (CORRECTED):** the efficiency table's `basic_riders`
  (20,473→8,556) is **misleading** — it conflates yellow-bus riders with
  transit-pass (ORCA) riders. Split them via `quarterly_metrics`
  (`basic_students_on_buses` vs `basic_students_transit_buses`):
  - **Yellow bus (model this):** ~12,118 (2017-18) → ~9,171 (2025-26) — modest
    decline + COVID dip to 332 in 2020-21, then recovery.
  - **Transit pass:** ~8,715 (2017-18) → **0 from 2022-2023 on**. This is the
    bulk of the headline "drop" and is NOT yellow-bus demand.
  - Identity: `basic_students_total = on_buses + transit_buses − in_walk_areas`.
  - See `plot_ridership.py` → `ridership_bus_vs_transit.png`.
  - avg route distance 2.42 → 2.16 mi. COVID years 2020-21/2021-22 missing from
    the efficiency/kpi tables (present but sparse in routes).
- **Open join task:** STARS `destination_name` (messy, e.g. "Clevland H.S.") is
  NOT yet mapped to `parse_shapes` `school_id`. `destinations.csv` has a blank
  `school_id` column to fill via fuzzy name match in a later stage.

### HCC ES pathway areas — INGESTED session 2 → `hcc_pathways_es.csv`
- Source: `data/ES-HCC-pathways.pdf` (SPS "Highly Capable Eligible Pathway
  Sites" map, map data Oct 2025, updated 3/16/2026, MapFile
  `HC_proposed_pathways`). Each HC pathway area = a **union of ES attendance
  areas**, so the HCC draw kernel needs NO decay fitting at ES level — it's
  exact point-in-polygon over `attendance_es` + this mapping.
- Tracked CSV `analysis/montecarlo/hcc_pathways_es.csv`: 58 rows (one per ES
  attendance area, joins `attendance_es.name` **58/58 exact**), three
  era-based configs:
  - `pathway_2025map` — the new/proposed 5-site config: Cascadia (21 areas),
    Thurgood Marshall (12), Alki (11), Rainier View (9), Decatur (5).
  - `pathway_2023_2025` — school years 2023-24..2025-26, 3 sites: TM (32),
    Cascadia (21), Decatur (5). Alki + Rainier View areas served by TM.
  - `pathway_2017_2022` — school years 2017-18..2022-23, 4 sites:
    **Fairmount Park** was the West Seattle HC site with the same draw as
    today's Alki pathway area (USER-CONFIRMED; matches STARS: FP ran 2-5
    gifted routes/yr through 2022-23, 0 after). TM (21), Cascadia (21),
    FP (11), Decatur (5).
  - Rainier View areas → TM in both historical eras.
- The PDF covers **ES only**; HS HCC transportation ended with Garfield
  routes after 2018-19.

### HCC MS pathway areas — INGESTED session 9 → `hcc_pathways_ms.csv`
- Source: `data/sps/shapes/MS-HCC-pathways.pdf` (SPS "Middle School HCC
  Pathways" map, 2022, updated 7/18/2022, MapFile `HC_Pathways_2022`). Each
  MS pathway = a union of MS attendance areas: **Robert Eagle Staff** ←
  {Whitman, Eagle Staff}; **Jane Addams** ← {Jane Addams, Eckstein};
  **Hamilton** ← {Hamilton, McClure}; **Washington** ← {Meany, Washington,
  Mercer, Aki Kurose}; **Madison** ← {Madison, Denny}.
- Tracked CSV `hcc_pathways_ms.csv`: 12 rows (joins `attendance_ms.name`
  **12/12 exact**), same three era columns as the ES file so the
  `hcc_era` API works uniformly:
  - `pathway_2017_2022` — the 5-site 2022 map as-is (STARS: Madison ran
    gifted routes through 2021-22).
  - `pathway_2023_2025` — 4 sites; **Madison + Denny areas → Washington
    (ASSUMED, needs user verification** — inferred from STARS: Madison ran 0
    gifted routes 2022-23..2024-25; parallels the ES Fairmount-Park→TM
    consolidation).
  - `pathway_2025map` — 5 sites; Madison resumes (STARS 2025-26 shows
    Madison with 2 gifted routes again, matching the proposed-map era).

### Section 4 OD flows — INGESTED session 2 → `analysis/montecarlo/section4/`
- Source: `data/2024-25-section4.pdf` (SPS Annual Enrollment Report 2024-25,
  "Comparison of Enrollment and Attendance Areas"). Built by
  `section4_seattle.py --build`; tracked CSVs + README in `section4/`.
- **This is the observed origin-destination matrix for the baseline year**:
  per attendance area, where resident students actually enrolled (ES/MS/HS),
  plus per option/K-8 school, where its enrollees live (K-5 vs 6-8).
- Stay-rates (residents attending their area school): ES 68.2%, MS 56.6%,
  HS 69.8%. Kernel contrast confirmed empirically: Cascadia (HCC) draw is
  diffuse (535 kids over 25 areas, max 49/area); Thornton Creek (geozone
  option) is local (142 of 370 from View Ridge alone).
- **Impact on architecture:** stage 6 (assignment) baseline is now *anchored
  to observed flows* at attendance-area granularity — IPF only distributes
  within-area down to block groups; kernels are needed only to generalize
  flows under scenarios (conversion/move/closure), fit to this OD.
- SPS-only (no private/homeschool); names raw (normalize in school_directory
  stage); 3 source pages truncated at the page border (small tail losses);
  validation 80/80 diagonal + 656/656 transpose. See `section4/README.md`.

### Multi-year Section 4 + Table 1-D — INGESTED session 3 → `out_enrollment/` (untracked)
- **Supersedes Prompt E**, built outside the montecarlo dir as a standalone
  repo-root script `enrollment_reports.py` (pdftotext + pandas, no package
  imports). Full handoff: **`ENROLLMENT_HANDOFF.md`** (repo root) — read it
  before touching the parser; it maps all the format drift 2010-2025.
- Inputs: 14 Annual Enrollment Report PDFs in `data/sps/enrollment/`
  (2010-11..2024-25; **2022-23 missing at the source**). Outputs (all years
  combined, `year` = school-year **string label** e.g. `2024-25`, NOT the
  int fall-year convention used elsewhere — bridge when consuming):
  - `section4_od.csv` (20,977) — area residents → schools, per level.
  - `section4_attendees.csv` (14,079) — school attendees by residence.
  - `section4_option_draw.csv` (5,465) — option/K-8 draw blocks.
  - `enrollment_by_school.csv` (1,340) — Table 1-D per-school enrollment
    (2016-17 chart-only at source → skipped).
- Verified: 0 duplicate cells; Table 1-D internal cross-check 100%; only 2
  garbled names (2010-11 source defects, dropped). Names RAW.
- **Caveats for this project:** `out_enrollment/` is NOT tracked (unlike the
  tracked-intermediates convention here) and not yet gitignored — open
  decision in ENROLLMENT_HANDOFF.md. `section4_seattle.py` + tracked
  `section4/` remain the 2024-25 baseline loaders (do NOT delete); the
  multi-year files are the scenario-response/natural-experiment source
  (Fairmount Park HCC era, COVID years). Wiring montecarlo loaders to
  `out_enrollment/` (or copying a tracked slice in) is a small open task —
  natural to fold into Stage 2/3.

### Report Card slice — INGESTED this session → `analysis/montecarlo/rc_seattle/`
- Built by `rc_seattle.py --build`. Two OSPI Report Card sources (both
  gitignored, local-only), filtered to Seattle, tracked intermediates.
- `enrollment.csv` (8,408 rows; per school×grade×year 2014-15..2024-25 +
  demographics). `attendance_all_students.csv` (7,316; chronic absenteeism by
  grade band) and `attendance_by_group.csv` (27,773; school-level by subgroup),
  both 2014-2015..2023-2024.
- Chronic absenteeism = 1 − (n_regular / n_students) from the SQSS "Regular
  Attendance" measure. Trend ~12-13% pre-COVID → 23-25% post-COVID.
- Purpose: distribute total district riders across schools non-uniformly using
  enrollment size + demographic mix (low_income, SWD, homeless) + absenteeism.
- See `rc_seattle/README.md` for column details and the join keys.

---

## Architecture (LOCKED — planning session 2026-06-09)

### Scenario operations the simulator must support

A *scenario* is an ordered list of composable operations applied to a copy of
the baseline world (geography + school directory + draw kernels):

| Op | Parameters | Effect |
|---|---|---|
| `set_walk_threshold` | level (ES/MS/HS), miles | Regenerate all walk zones at the new threshold |
| `scale_walkzone` | school_id, factor or miles | Resize one school's walk zone |
| `close_school` | school_id, reassign rule | Remove school; redistribute its draw to fallback schools |
| `convert_option_to_neighborhood` | school_id, attendance_geom source | Swap draw kernel option→attendance-area; school gains an attendance area (carved from geozone or supplied polygon); neighbors' areas shrink accordingly |
| `move_school` | school_id, new point, move_geozone? | Relocate building → walk zone recenters; geozone optionally moves with it |

### Core modeling concept: per-school **draw kernels**

Each school×program has a *draw kernel* — the spatial distribution of where
its students live. This is what makes the expanded scenarios tractable, and it
encodes the key domain fact (CONFIRMED empirically in STARS routes,
2024-25: gifted routes avg **3.27 mi, ~11 stops** vs basic **2.00 mi, ~8
stops**):

- **Neighborhood school:** ~uniform over its attendance area (minus opt-outs).
  Most kids near school → many walkers.
- **Option school w/ geozone:** distance-decay around the school, geozone
  priority + lottery tail from the rest of the district. Many nearby kids.
- **HCC/gifted pathway (Cascadia, Thurgood Marshall, Washington MS, …):**
  region/district-wide draw, few kids near the school → nearly all enrolled
  non-walk-zone kids are bus-eligible, long multi-stop routes.

Scenario semantics become kernel edits: *conversion* = swap option-decay
kernel for an attendance-area kernel (its riders mostly become walkers);
*move* = recenter the kernel + walk zone (geozone optionally follows);
*closure* = delete the school's column and redistribute by fallback rule
(attendance kids → receiving neighborhood school(s); option/HCC kids → next
pathway/option site).

**Assignment is an IPF (iterative proportional fitting) problem:** known
per-school enrollment (rc_seattle) = column marginals; synthesized kids per
block group × grade = row marginals; kernel = prior. Baseline reproduces
reality by construction; scenarios re-run IPF with edited kernels/marginals.

### Pipeline stages → modules (one module per stage, pure-functional core)

```
 1. geography           parse_shapes.py                       [DONE]
 2. school_directory    school_directory.py — STARS destination_name →
                        school_id join (154 names, fill destinations.csv);
                        classify every school: neighborhood | option |
                        hcc_pathway | service; program flags        [DONE s3]
 3. baseline_ridership  baseline_ridership.py — per school × program × year:
                        riders, routes, avg distance, stops (STARS) joined to
                        enrollment (rc) ⇒ THE calibration-target table; also
                        verifies the kernel hypothesis per school    [DONE s4]
 4. acs_population      acs_population.py — ACS block-group pulls (B01001 age
                        ×sex; B14003 enrollment public/private) + TIGER block
                        groups, clipped to SPS. Raw → gitignored data/census/;
                        Seattle slice → tracked census_seattle/ (same pattern
                        as stars_seattle/)
 5. synth_population    synth_population.py — kids per block group × grade
                        band; samplable (Dirichlet/multinomial); private-
                        school share deducted; parcel-level refinement = later
 6. assignment          assignment.py — draw kernels + IPF → P(school | block
                        group, grade); baseline anchored to the OBSERVED
                        Section 4 OD flows (area→school); IPF distributes
                        within-area to block groups; kernels (fit to the OD)
                        generalize flows under scenarios
 7. eligibility         eligibility.py — walk-zone membership (scenario-aware
                        polygons) → walker vs bus-eligible; calibrate against
                        STARS basic_students_in_walk_areas identity
 8. ridership           ridership.py — P(ride | eligible, distance, grade,
                        demographics, absenteeism); calibrate district on_bus
                        by program; soft-target per-school route counts; map
                        riders → route/bus estimates via riders-per-route by
                        program (for cost-ish outputs)
 9. scenarios           scenarios.py + scenarios/*.json — machine-readable
                        spec (the 5 ops above), validation against locations,
                        apply() → mutated world
10. simulate            simulate.py — MC driver: sample params θ, run stages
                        5-8 for baseline AND scenario with the SAME θ
                        (paired design → tight delta CIs)
11. report              report.py — per-school + district rider deltas,
                        route/bus deltas, distance distributions, equity cuts
                        (ES poverty attr, low_income), with CIs
```

### Walk-zone resizing approach (decided)

Start with **calibrated buffers**: fit a crow-flies-distance multiplier per
school so a buffer around the school point reproduces its *actual* walk-zone
polygon area at the current threshold (the official polygons embed
hazard/arterial adjustments); apply the same multiplier at scenario
thresholds. Upgrade path (only if buffers prove too crude): street-network
isochrones via osmnx. Avoids a heavy dependency until the simple thing fails.

### Calibration strategy

- **Baseline year: 2024-25** (latest with full STARS + Report Card overlap).
- Hard constraint: per-school enrollment (IPF marginal — exact by construction).
- Fit targets, in priority order:
  1. district yellow-bus riders by program (`quarterly_metrics`
     `basic_students_on_buses` etc.) — the headline number;
  2. `basic_students_in_walk_areas` — pins the eligibility stage;
  3. per-school route counts + avg route distance
     (`routes_by_school_year`) — pins the spatial shape of each kernel.
- Build a **deterministic expected-value mode first** (no sampling) for
  debugging + calibration; wrap MC sampling around it once it fits.

### What the MC loop samples (θ)

- spatial allocation of kids among/within block groups (multinomial/Dirichlet)
- private-school share by area
- option + HCC kernel decay parameters
- ride-propensity curve parameters (distance, grade, demographics)
- scenario behavioral responses: post-conversion enrollment retention (do
  current far-away enrollees leave?), opt-in rate of newly-zoned families,
  steady-state vs transition-year toggle

### Build order (milestones — one per session, roughly)

- **M1** Stage 2 `school_directory` — DONE (s3). 154/154 STARS + 197/197 S4
  names resolved; 98-school classification table.
- **M2** Stage 3 `baseline_ridership` — DONE (s4). Per-school calibration
  table; kernel hypothesis confirmed at 88.3%; district 2024-25 targets locked.
- **M3** Stages 4-5 `acs_population` + `synth_population` — DONE (s5).
  558 SPS-territory block groups; 76,474 school-age children; 52,904 est.
  public (1.06x SPS enrollment — calibrates in IPF). Tracked → `census_seattle/`.
- **M4** Stages 6-7 assignment + eligibility — DONE (s6). OD-anchored IPF
  matrix (19,094 cells, tracked `assignment/`); walk fractions (tracked
  `eligibility/`); combined validation PASS (implied propensity 0.657,
  route-count correlation r=0.72).
- **M5** Stage 8 ridership — DONE (s7). Distance-decay + demographic
  propensity shape; district totals exact by renormalization; per-school
  route correlation r 0.718 → 0.814; gifted propensity 1.011 (4b caveat).
- **M6** Stage 9 scenario engine + the 5 ops — DONE (s8). Empty scenario ==
  baseline (CSV-rounding exact); closure + walk-threshold smokes sensible;
  all 5 op code paths exercised; band enrollment conserved.
- **M7** Stages 10-11 `simulate` + `report` — DONE (s9). Paired MC with
  per-draw calibration, ~0.2 s/draw; 200-draw validation on both smoke
  scenarios PASS (CI brackets the expected-value deltas). **Pipeline
  complete — next: user-specified scenarios (Prompt D).**

---

## Open questions (updated session 2 — defaults chosen, user can override)

Resolved with **working defaults** this session (revisit any time):
- **Ridership definition → yellow bus (`on_bus`) only.** ORCA/transit-pass
  went to 0 from 2022-23; not modeled.
- **Calibration year → 2024-25**; targets = on_bus by program, walk-area
  counts, per-school routes (see Calibration strategy above).
- **Granularity → block group** (Dirichlet-sampled placement within); parcel
  refinement only if calibration demands it.
- **Choice/opt-out → modeled via draw kernels + IPF** (it's load-bearing for
  the option-school scenarios, so it's now core, not optional).
- **Walk-zone resize mechanics → calibrated buffers** (osmnx isochrones as
  upgrade path).

Still genuinely open for the user:
1. **Concrete scenario list** — first three specified + run s10
   (`ms_walk_1mi`, `hs_bussing`, `hs_bussing_1mi` — see "User scenarios"
   above); more welcome any time.
2. **Conversion semantics** — when an option school becomes a neighborhood
   school, where does its attendance area come from: carve from its geozone,
   redraw neighboring areas (hard sub-problem), or user-supplied polygon? And
   do we report steady-state or the transition years (current distant
   enrollees grandfathered)?
3. **HCC behavior on closure/move** — does the pathway relocate (riders
   follow) or dissolve (riders go to neighborhood schools)? Default: pathway
   relocates intact.
4. ~~**Walk-rule verification**~~ — VERIFIED s9, two ways: (a) shapefiles —
   median max-reach of the official polygons from the school point is 0.92
   mi (ES, n=72), 1.89 mi (MS), 1.87 mi (HS) vs the nominal 1 / 2 / 2;
   hazard carve-outs trim area (median ES equivalent radius 0.61 mi);
   (b) the SPS transportation page (USER-VERIFIED + fetched s9) states the
   same 1 / 2 / 2 rule, with MS = yellow bus or ORCA and HS = ORCA only.
   Licton Springs' 3.6-mi reach is a disjoint-piece artifact.
7. ~~**K-8 walk-zone rule conflict**~~ — RESOLVED s9 (USER decision: the
   website is authoritative). `parse_shapes.load_walkzones` now keeps only
   the 1-mile core piece for K-8/PK-8 zones (min max-reach from the school
   point; `k8_full_union=True` restores the old union). Eligibility +
   ridership rebuilt, MC re-run. Caveat: Licton Springs (955) has no ~1-mi
   piece in the layer at all — it keeps its smallest piece (1.88 mi reach).
4b. ~~**MS HC pathways**~~ — RESOLVED s9: `hcc_pathways_ms.csv` from
   `data/sps/shapes/MS-HCC-pathways.pdf`; gifted pool now uses the MS
   pathway kernel (propensity 1.011 → 0.918). One **ASSUMPTION to verify**:
   Madison + Denny areas → Washington in the 2023-2025 era (see the MS
   pathway section above).
5. ~~**Output decision context**~~ — RESOLVED s9 (user): the outputs that
   matter are **Δ basic riders, Δ # bus routes, Δ avg stop→school distance**
   (≈ STARS `average_distance`, labeled "average route length" in places).
   No AM/PM split — STARS has no direction dimension. report.py leads with
   these; equity cuts stay as a secondary section.
6. ~~**requirements.txt** strategy~~ — RESOLVED s9: pinned everything in
   `requirements.txt` to the working venv (pandas 3.0.3 / numpy 2.4.6 /
   geopandas 1.1.3 stack); no separate geo-requirements file.

---

## Decision log (append-only)
- **2026-06-09** Standard analysis CRS = EPSG:2926 (WA State Plane N, US feet).
  Rationale: native CRS of the zone polygons; feet match walk thresholds.
- **2026-06-09** Universal join key = `school_id` (not `school_code`).
- **2026-06-09** Walk zones dissolved to one geometry per school; `school_id==0`
  rows dropped as noise.
- **2026-06-09** All new code lives under `analysis/montecarlo/`. Treated as
  ad-hoc analysis (not the production SAFS pipeline), per repo conventions.
- **2026-06-09** Seattle STARS intermediates written as **tracked CSVs** under
  `stars_seattle/` (not parquet — no pyarrow; subsets are small). Rationale:
  `out_stars/` is gitignored, so committing the filtered slice keeps future
  sessions self-sufficient. Constant cols (ccddd/county/district) dropped.
- **2026-06-09** STARS `destination_name`→`school_id` mapping deferred to a
  later stage; `destinations.csv` seeds it with a blank `school_id` column.
- **2026-06-09** Report Card enrollment + SQSS chronic absenteeism ingested to
  tracked `rc_seattle/`. Chronic absenteeism derived from counts
  (numerator/denominator), NOT the broken `percent` column; `suppressed` keyed
  off rate-computability, not the `dat` string (which changed format in
  2022-23+). Did NOT persist the full 169k per-grade×subgroup table (15MB);
  kept AllStudents-all-grades + all-subgroups-school-level instead.
- **2026-06-09** Confirmed `school_code` links geography↔enrollment↔absenteeism
  (98/98 with parse_shapes). Added normalized int `year` to bridge school-year
  string formats across sources.
- **2026-06-09 (session 2, planning)** Scenario scope expanded to four op
  families: walk-zone resize, closure, **option→neighborhood conversion**,
  **option-school move**. Architecture locked as the 11-stage pipeline above.
- **2026-06-09 (s2)** Student-residence modeling = per-school **draw kernels**
  (neighborhood: attendance-area; option: distance-decay in geozone; HCC:
  region-wide) + **IPF** against known per-school enrollment. Empirical
  support from STARS routes: gifted avg 3.27 mi/~11 stops vs basic 2.00
  mi/~8 stops (2024-25) — confirms HCC = few neighborhood kids, options w/
  geozones = many.
- **2026-06-09 (s2)** Calibration year 2024-25; model `on_bus` only;
  block-group granularity; walk-zone resizing via calibrated buffers (osmnx
  isochrones deferred). Deterministic expected-value mode before MC sampling.
- **2026-06-09 (s2)** Build order M1..M7 as listed; next session builds
  Stage 2 `school_directory.py`.
- **2026-06-09 (s2)** HCC ES pathway areas ingested from
  `data/ES-HCC-pathways.pdf` → tracked `hcc_pathways_es.csv` (joins
  `attendance_es.name` 58/58). ES HCC kernel = exact union of attendance
  areas, not a fitted decay. Two configs: `pathway_2025map` (5 sites — itself
  usable as a *scenario* vs the historical baseline) and `pathway_historical`
  (3 sites; per user, Alki + Rainier View areas → Thurgood Marshall all
  years). Fairmount Park's 2017-2023 gifted routes flagged as an open caveat.
- **2026-06-09 (s2)** Section 4 OD flows ingested (`section4_seattle.py` →
  tracked `section4/`): observed 2024-25 area→school assignment matrix +
  option-school draws by grade band. Assignment stage re-anchored: baseline
  = observed OD; kernels only generalize under scenarios. Names kept raw
  (normalization owed to school_directory stage — it now owns Section 4
  names too, alongside STARS destination names).
- **2026-06-09 (s2)** USER-CONFIRMED: Fairmount Park was the old West Seattle
  ES HC site with the same draw as the new Alki pathway area. CSV restructured
  to three era configs: `pathway_2017_2022` (4 sites incl. FP),
  `pathway_2023_2025` (3 sites), `pathway_2025map` (proposed 5 sites). Era
  boundary: FP's last gifted routes in 2022-23. Pre-2023 gifted data is now
  usable for calibration/validation.
- **2026-06-09 (s3)** Multi-year Section 4 (2010-11..2024-25) + Table 1-D
  ingested via standalone `enrollment_reports.py` → untracked
  `out_enrollment/` (handoff: repo-root `ENROLLMENT_HANDOFF.md`). This
  replaces Prompt E's plan to extend `section4_seattle.py`; that module +
  tracked `section4/` stay as the 2024-25 baseline loaders. `year` there is
  a string label ("2024-25"), not int fall year — bridge on consumption.
- **2026-06-09 (s3)** Stage 2 `school_directory.py` built and verified:
  154/154 STARS names resolved (0 unmatched); 197/197 Section 4 names
  resolved. Classification: 80 neighborhood / 15 option / 2 hcc_pathway
  (Cascadia, Decatur) / 1 service (Nova). Key overrides: "West Seattle H.S."
  → 19 (explicit, prevents collision with "west seattle" → 236 ES); "Clevland
  H.S." → 12 (typo); "Thorton Creek Elementary" → 977 (typo). STARS
  destinations.csv school_id column now filled.
- **2026-06-09 (s4)** Stage 3 `baseline_ridership.py` built and verified.
  Calibration targets for 2024-25 locked: 10,008 basic on-bus, 1,316 gifted,
  202 basic routes, 40 gifted routes. [CORRECTED s5: this entry originally
  claimed "10,948 walk-area kids" — wrong; see the s5 correction entry below.]
  Kernel hypothesis
  confirmed: gifted routes average 3.0 mi vs basic 1.6 mi; 88.3% of
  school×year rows (non-COVID) have gifted > basic distance. 7 exceptions are
  near-parity in low-route-count years (noise, not refutation). 2024-25:
  4/4 schools with both programs confirm gifted > basic. Pure HC pathway
  schools (Cascadia, Decatur, TM) have no basic routes — consistent with
  district-wide draw design. Enrolled total 49,765 across 98 SPS schools
  (9 non-SPS programs excluded from school_directory join). COVID year 2020-21
  flagged `is_covid=True` in district_targets; excluded from kernel stats.
- **2026-06-09 (s5)** Stages 4-5 `acs_population.py` + `synth_population.py`
  built. ACS 5-year 2023; King County FIPS 53033. B14003 is suppressed at
  block-group level → pulled at tract level instead (448/495 tracts have
  nonzero values); tract fractions joined to each member block group. TIGER/Line
  2023 WA block groups clipped to SPS territory (union of attendance + option
  zones) → 558/1545 King County BGs. SPS territory = 93.1 sq miles. School-age
  children (5-17) in SPS territory: 76,474 (30k ES-age / 29k MS-age / 17k HS-age).
  Public school fraction: 75.7% overall (slightly higher at HS 80.2%). Synth
  population total: 52,904 public school children vs 49,765 SPS enrollment =
  1.06x ACS over-count (within ACS survey noise; IPF calibrates anyway).
  Age→grade split: 5-9→ES; 10-14→20%ES/60%MS/20%HS; 15-17→HS (integer-grade
  algebra, not a fitted parameter). Dirichlet α = n_pub + 0.5 per grade band
  per block group; sample_synth_pop(rng) draws consistent with paired MC design.
- **2026-06-09 (s5, correction)** The s4 figure "10,948 walk-area kids" was a
  documentation error — it appears nowhere in the data. Actual STARS
  `basic_students_in_walk_areas` (district_targets.csv): 96.5 in 2024-25,
  range ~96-324 across all years. The STARS identity `basic_students_total =
  on_buses + transit_buses − in_walk_areas` verifies the column (10,008.5 −
  96.5 = 9,912 ✓). At that magnitude it is a STARS reporting adjustment (e.g.
  walk-area students nonetheless served), NOT the count of children living in
  walk zones (~tens of thousands). Consequence for Stage 7: walk-zone
  membership comes purely from the official walk-zone polygons (geometry);
  the eligibility stage has no independent district-level walker target —
  end-to-end calibration runs against `basic_students_on_buses` = 10,008.

- **2026-06-09 (s6)** Stage 6 `assignment.py` built. Baseline anchored to
  Section 4 OD as planned: prior = BG-area overlay weights × P(school|area,
  band); IPF rows = synth_pop (scaled per band ×0.93 es / ×0.87 ms / ×0.95 hs
  to RC totals), columns = RC per-grade 2024-25 enrollment by band (98
  schools; PK excluded — not transported and not in synth_pop). All 98 OD
  destination schools and all 80 residence areas resolve via
  school_directory; every school with RC band enrollment has an OD flow
  column (no structural-zero drops). ES OD "6-8" rows excluded to avoid
  double-counting with MS OD. Cells < 1e-4 expected kids dropped from the
  tracked CSV (affects only ~11 near-empty BG-bands).
- **2026-06-09 (s6)** Option draw kernels fit to OD: single exponential
  distance decay per band on BG centroids, grid-searched. ES/MS 0.50 mi,
  HS 1.50 mi; mean total-variation vs observed draws ~0.18-0.36, far better
  than the no-decay baseline (~0.46-0.75). Geozone-priority + lottery-tail
  structure NOT modeled (plain decay was sufficient at area granularity);
  revisit in M6 only if scenario realism demands it.
- **2026-06-09 (s6)** Stage 7 `eligibility.py` built: walk_frac = area
  fraction of the BG's SPS-clipped area inside the official walk-zone
  polygon (denominator sps_area_sqft, consistent with sps_frac weighting in
  synth_pop). No fitting, per the s5 correction. ~50% of ES+MS kids assigned
  to basic-route schools live in walk zones.
- **2026-06-09 (s6)** M4 combined validation PASS (criteria: implied
  propensity ∈ [0.2, 0.9] and Pearson > 0.5): bus-eligible pool 15,229 at
  the 77 basic-route schools → implied on-bus propensity 0.657 vs the
  10,008 target; per-school eligible vs basic route counts r=0.718
  (ρ=0.622); median eligible-per-route 79 → ~52 riders/route at 0.657,
  matching the actual 49.5. Note: HS has NO basic yellow-bus routes (STARS
  2024-25) — basic eligibility is an ES+MS concept; HS enters only via
  scenario reporting, not basic calibration.
- **2026-06-09 (s6)** `kernel_bg_weights()` (assignment.py) is the scenario
  kernel API for M6: neighborhood (attendance-area membership), option
  (fitted exp decay), hcc_pathway (era-config union from
  hcc_pathways_es.csv). Raises on an empty kernel (wrong school for the
  kind).

- **2026-06-10 (s7)** Stage 8 `ridership.py` built. Propensity form
  `p = clip(s·f(d)·exp(β·x), 0, p_max)` with bounded mixture
  `f(d) = (1−ρ) + ρ·exp(−d/decay_mi)`; the level s is NOT a parameter — it is
  re-solved against the district on-bus target every call (capped cells
  handled by an active-set renormalization), so θ only shapes the
  distribution and the 10,008 target holds under any θ/scenario. θ fit by
  coarse grid + converging coordinate refinement against route-implied
  per-school riders (STARS basic routes × 10,008/Σroutes, 77 schools).
- **2026-06-10 (s7)** Fit result: ρ pinned at 1.0 = pure exponential distance
  decay (decay 4.69 mi) — bus propensity FALLS with distance from school.
  Interpretation: service-area limits at big-draw option schools (distant
  eligible kids don't get/take service), NOT a hazard-dip near school (an
  unbounded near-school-boost parameterization degenerated into this same
  pure-decay shape, so it was reparameterized to the bounded mixture).
- **2026-06-10 (s7)** swd_frac is the strongest ridership covariate
  (β_swd +6.13; ablation drops r 0.814 → 0.734; raw correlation of implied
  per-school propensity with swd_frac +0.46). It is a demographic PROXY on
  the basic program — special-ed routes are a separate STARS program, not
  modeled. β_absent ≈ −0.31 adds ~nothing to r (kept on SSE only).
- **2026-06-10 (s7)** Gifted pool: HC enrollment at the 7 gifted-route sites
  (ES: HCC pathway kernel, era 2023-2025; MS: the school's own assignment
  column). Solved propensity 1.011 > 1 ⇒ the pool is slightly UNDERESTIMATED,
  because the MS OD-column approximation understates how far HC kids live
  from school. Open question 4b (MS pathway map) is the fix; district gifted
  total (1,316) is exact by construction regardless.
- **2026-06-10 (s7)** Riders → route-ish outputs via district riders-per-route
  by program (2024-25: basic 49.5, gifted 32.9); `est_routes` in
  `ridership/school_ridership.csv`. Per-school n_routes_actual kept alongside
  for comparison (191 of the 202 district basic routes map to schools).
- **2026-06-10 (s7)** Known pre-existing repo breakage (not this project):
  `extractors/safs/data_reader_test.py` imports a nonexistent
  `extractors.safs.mdb_reader` → pytest collection error. Untouched.

- **2026-06-10 (s8)** Stage 9 `scenarios.py` built (M6). Central design
  decision: scenario ops NEVER touch the residence strata (BG × area
  weights) — they edit only the destination side (flow columns, enrollment
  marginals, walk zones, points, gifted table). This keeps the Section-4 OD
  anchoring intact under every op; "kids stay where they live, only their
  destination changes."
- **2026-06-10 (s8)** Scenario evaluation must NOT re-solve the propensity
  scale: Stage 8's hard renormalization would pin every scenario at the
  10,008 district target and all deltas would vanish by construction.
  `ridership.py` gained backward-compatible hooks: `expected_riders(...,
  fixed_scale=)` (use the baseline-solved s), `basic_cells(..., points=,
  basic_ids=, covar_means=)` (moved schools / changed service set / baseline
  covariate centering so the tilt of untouched cells doesn't shift).
  Verified: solved-vs-fixed paths agree to 0.0 on the baseline.
- **2026-06-10 (s8)** Enrollment marginals follow flow edits by per-school
  flow-total ratio, then each band renormalizes to its baseline total
  (closures/conversions move kids between schools, never out of the
  district). Conservation verified exact on a 3-op scenario.
- **2026-06-10 (s8)** Walk-zone resizing per the locked calibrated-buffer
  plan: m = sqrt(official_area/π)/(T·5280) per school (T = ES 1 mi, MS/HS
  2 mi — open question 4 still owes verification); scenario zones =
  point.buffer(m·T'·5280). The empty scenario keeps the official polygons —
  buffers only replace zones an op touches. Schools lacking an official
  zone (only Decatur 287) get their level's median m; note
  `set_walk_threshold ES` therefore GIVES Decatur a walk zone it lacks at
  baseline (−77 gifted riders in the 1.5-mi smoke — defensible reading of
  "regenerate all zones", revisit if it surprises).
- **2026-06-10 (s8)** Closure fallback defaults (user defaults from open
  questions 2-3): attendance school → 3 nearest open same-level
  neighborhood schools, displaced kids split per residence area ∝ the
  receivers' existing draw from that area (nearest receiver if none draws);
  option school → nearest open same-level option site; HCC pathway
  relocates INTACT (member areas + HC enrollment merge into hcc_receiver,
  default nearest same-band gifted site). Conversion is STEADY-STATE (no
  transition-year grandfathering). Known caveat: a mixed site (Thurgood
  Marshall: neighborhood + HC) moves its whole basic flow column by the
  neighborhood rule while HC moves via the gifted table — the basic column
  isn't split by program (baseline has the same conflation).
- **2026-06-10 (s8)** Smoke results: `close_sacajawea` — Sacajawea's 104
  basic riders → Olympic View +78 / Wedgwood +17 / Rogers +4.5, district
  −4.9 (some displaced kids land inside receivers' walk zones).
  `es_walk_1p5mi` — basic 10,008 → 7,170 (−28%, −57 est routes); biggest
  losers are option K-8s (Hazel Wolf −192, Salmon Bay −130, TOPS −122)
  whose decay draws concentrate kids near school. Note K-8s carry level
  "ES" → ES threshold ops resize their single walk-zone polygon for both
  bands.

- **2026-06-10 (s9)** Stage 10 `simulate.py` built (M7). **Calibration is
  per-draw**, not fixed at the expected-value baseline: each draw re-solves
  the propensity scale, covariate centering means, and gifted propensity on
  its OWN baseline cells (with that draw's θ + population), then reuses all
  three for the paired scenario run. Rationale: the district targets
  (10,008 / 1,316) are observed facts, not uncertain inputs — every sampled
  world must reproduce them at baseline; fixed EV calibration would let the
  baseline district total drift with the draw, adding variance that is
  calibration error rather than parameter uncertainty. Consequence: baseline
  district totals are degenerate across draws by construction; distributions
  live in the per-school split and in every delta.
- **2026-06-10 (s9)** θ sampling distributions (start-simple defaults,
  revisit when scenario realism demands): `decay_mi` lognormal around the
  fit with σ_log = 0.2 (≈ ±20%); each β normal around the fit with
  sd = max(0.2·|β̂|, 0.05); **ρ held fixed at the fitted 1.0** (the fit
  pinned it at the pure-decay boundary — sampling below adds a flat floor
  the fit firmly rejected, s7); `p_max` fixed (structural cap);
  `gifted_propensity` solved per draw (see calibration entry). Population
  per draw via `sample_synth_pop` (Dirichlet, s5). Scenario behavioral
  responses (stay-rate etc., NOTES "What the MC loop samples") are NOT yet
  sampled — they remain scenario-spec constants; add per-op sampling if a
  real scenario needs it.
- **2026-06-10 (s9)** Scenario worlds are built ONCE from the expected-value
  baseline (geometry/flow edits don't depend on θ or the population draw);
  per-world walk fractions are computed once outside the draw loop. One
  approximation noted: a moved option school's flow column is re-derived
  inside `apply()` with the EV population (the per-draw IPF reconciles it).
  Performance correction: a full paired draw costs **~0.2 s** (2× IPF +
  cells + gifted + riders) — the "30-60 s per evaluate()" figure in the s8
  notes was dominated by cold geometry loads, not per-draw work; no further
  caching needed for hundreds of draws.
- **2026-06-10 (s9)** Stage 11 `report.py` built: percentile 95% CIs over
  the paired draws; routes derived from rider deltas via district
  riders-per-route (route CIs inherit rider CIs); equity cuts sum basic
  Δriders per draw per group (RC low-income terciles over the run's schools;
  ES attendance-area `poverty` terciles, option/K-8 sites grouped as
  "(no ES area)"). MC results saved as tracked CSVs under
  `simulate/<scenario>/` (per-run overwrite), consistent with the
  tracked-intermediates convention.
- **2026-06-10 (s9)** M7 validation PASS: `close_sacajawea` n=200 (seed
  20260610) district basic Δ −4.4 [−11.2, +2.8] brackets the EV −4.9
  (decomposition: θ-only sd 2.9, pop-only sd 1.9); with sampling disabled
  the loop reproduces the EV run exactly (Δ −4.9 both draws).
  `es_walk_1p5mi` n=200: basic Δ −2,835 [−3,007, −2,693], gifted −97
  [−99.5, −94.4], est routes −57; equity cut shows the rider loss skews
  away from high-poverty ES areas (low-poverty tercile −827 vs high −610).

- **2026-06-10 (s9)** `requirements.txt` pinned (open question 6 resolved):
  all direct deps at the working-venv versions — single file, no separate
  geo-requirements. Notable: pandas 3.0.3 / numpy 2.4.6 (pulled forward by
  the geo stack) are now the pinned baseline for the SAFS pipeline too; also
  added previously-missing direct deps (numpy, SQLAlchemy, psycopg2-binary,
  matplotlib/plotnine/mizani/scipy/statsmodels, extract-msg, requests,
  python-dateutil). Repo test suite = the one pre-broken data_reader_test.py
  (NOTES s7) — nothing else to regress; dry-run resolve clean.

- **2026-06-10 (s9)** Open question 4b RESOLVED: MS HCC pathway map ingested
  from `data/sps/shapes/MS-HCC-pathways.pdf` → tracked `hcc_pathways_ms.csv`
  (12/12 attendance_ms names join; same era columns as the ES file).
  `kernel_bg_weights` hcc_pathway kind generalized to es/ms bands;
  `ridership.gifted_pool` + `scenarios` gifted handling now use the MS
  pathway kernel instead of the school's own assignment column. Effect:
  MS eligible pools grew (Washington 49.8 → 89.7 — the od-column draw had
  concentrated HC kids inside the walk zone), gifted propensity 1.011 →
  **0.918** (now < 1, as a propensity should be); basic θ unchanged
  (r 0.814). Tracked ridership/ rebuilt; empty-scenario baseline check
  PASS; both 200-draw MC runs + reports re-generated (es_walk_1p5mi gifted
  Δ −97 → −88). ASSUMED pending user check: Madison+Denny → Washington for
  2023-2025 (STARS route evidence; parallels ES FP→TM).
- **2026-06-10 (s9)** Open question 4 (walk thresholds) VERIFIED from the
  walk-zone shapefiles: max polygon reach from the school point has median
  0.92 mi ES / 1.89 MS / 1.87 HS vs nominal 1 / 2 / 2 mi — consistent with
  crow-flies caps + hazard carve-outs (median ES equivalent radius 0.61 mi,
  i.e. ~⅓ of the nominal disk area survives the carve-outs). K-8 option
  sites reach ~2 mi (MS rule in the same dissolved polygon). Calibrated-
  buffer approach unchanged — it already absorbs per-school trimming via m.
- **2026-06-10 (s9)** Walk rule verified against the live SPS transportation
  page (https://www.seattleschools.org/resources/transportation/, fetched at
  user direction): ES + K-8 = 1-mile walk boundary, MS = 2 (yellow bus or
  ORCA), HS = 2 (ORCA only). Confirms the model's thresholds AND its
  HS-has-no-basic-yellow-bus structure. NEW open question 7 from the same
  check: the GIS walk-zone layer carries ~2-mi pieces for K-8s that the
  website's 1-mi K-8 rule contradicts; model currently follows the GIS
  union. Page silent on crow-flies vs walking distance and hazard
  exceptions (the polygons embed them).
- **2026-06-10 (s9)** Output decision context locked (user): headline
  outputs = Δ basic riders, Δ routes, Δ avg stop→school distance; AM/PM
  split impossible (no direction dimension anywhere in STARS — checked
  metric definitions and route-number conventions). simulate.py
  school_draws.csv gained per-school rider-weighted base/scen mean distance
  (basic rows); report.py movers table shows it; district distance section
  relabeled "avg stop→school distance".

- **2026-06-10 (s9)** Open question 7 RESOLVED — USER decision: the SPS
  website's K-8 = 1-mile rule is authoritative over the GIS layer's K-8
  piece unions. `parse_shapes.load_walkzones` now keeps only the 1-mile core
  piece per K-8/PK-8 zone (min max-reach from the school point;
  `k8_full_union=True` restores the union; Licton Springs has no 1-mi piece
  → keeps its smallest, 1.88 mi). Full rebuild downstream: eligibility
  (2,798 → 2,654 pairs; basic pool 15,229 → 15,500; implied propensity
  0.646), ridership refit (ρ 1.0 → 0.85 — a 0.15 flat propensity floor
  appears once K-8 pools grow; β_swd 5.62 still dominant; β_abs ≈ 0;
  r 0.806), scenarios `--validate` PASS, both 200-draw MC runs + reports
  regenerated. EV deltas moved: `close_sacajawea` −4.9 → −7.6 (CI [−13.3,
  −1.8] brackets it); `es_walk_1p5mi` −2,838 → −2,524 (smaller because K-8
  calibrated buffers now expand from a 1-mi base, so K-8s lose fewer
  riders; est routes −51).

- **2026-06-10 (s10)** First user scenarios (Prompt D) specified, validated,
  and run end-to-end (200 draws each, seed 20260610): `ms_walk_1mi` (MS walk
  threshold 2 → 1 mi), `hs_bussing` (re-add HS yellow bus, walk zones
  unchanged), `hs_bussing_1mi` (HS bussing + HS walk threshold 2 → 1 mi).
  Headline deltas (basic riders, 95% CI): +2,073 [+1,901, +2,228] /
  +2,780 [+2,542, +3,016] / +5,908 [+5,463, +6,364]; est routes +42 / +56 /
  +119. Full reports in `simulate/<name>/report.txt`; specs recorded in the
  "User scenarios" table in Current state.
- **2026-06-10 (s10)** New 6th scenario op `add_basic_service` ({level} or
  {school_ids}) for the HS-bussing scenarios: grants basic yellow-bus
  service without touching walk zones (compose with the walk ops).
  Plumbing: `World.bus_bands` (baseline {es, ms}) + a `bands=` override on
  `ridership.basic_cells` replace the hard-coded `_BUS_BANDS` filter at the
  three call sites (scenarios calibration/evaluate, simulate `_eval_arm`);
  defaults unchanged — empty-scenario baseline check re-run PASS. MODELING
  CAVEAT (recorded in the specs too): added-HS riders reuse the
  ES/MS-calibrated propensity (distance decay, demographic tilt with
  is_ms=0, baseline-solved scale) and basic riders-per-route (49.5) — SPS
  has no HS yellow-bus history (ORCA only; zero HS basic routes in STARS),
  so the HS level is an extrapolation, not a fit. `add_basic_service
  level=HS` covers all 13 open HS sites including Center School (option)
  and Nova (service).
- **2026-06-10 (s10)** `ms_walk_1mi` side-effect worth remembering: the MS
  walk-threshold op also shrinks MS HCC pathway sites' walk zones → +162
  gifted riders ride along with the +2,073 basic. K-8s (level "ES") are
  untouched by MS-level ops by construction.
- **2026-06-10 (s10)** USER CORRECTION to `close_option_b`: under the real
  plan, Thurgood Marshall's HCC service relocates to **Beacon Hill
  International or Dearborn Park**, not the engine default (nearest gifted
  site = Cascadia). Spec updated with `hcc_receiver: 205` (Beacon Hill);
  variant `close_option_b_dearborn.json` carries the Dearborn Park (251)
  alternative. Both re-run (200 draws, seed 20260610): basic deltas
  UNCHANGED (+1,136 [+1,078, +1,188] — the receiver only moves the gifted
  table); gifted Δ now ≈0 (+1.3 Beacon Hill / −3.4 Dearborn, vs +10.6 with
  the Cascadia default) — TM's ~189 gifted riders land at the new site
  (192 / 187) instead of stacking onto Cascadia, whose gain is back to the
  Decatur-only +173. Reports re-saved.
- **2026-06-10 (s10)** Conversion scenarios `convert_optA_rand1/2`: the
  Option A closure list contains 6 option schools (Licton Springs 955,
  Salmon Bay 949, Cedar Park 210, TOPS 935, Orca 939, Boren 972 — all with
  geozones); two random 5-of-6 combos (Python `random.Random(20260610)`)
  converted to neighborhood schools instead of closing. rand1 keeps Boren
  option, rand2 keeps Salmon Bay. 200-draw MC: basic Δ **+240** [+203,
  +280] and **+238** [+208, +273] — virtually identical, so WHICH 5 of the
  6 barely matters. Counterintuitive sign worth remembering: conversion was
  expected to cut riders (lottery draws → local walkers, e.g. TOPS −213,
  its avg rider distance 1.86 → 1.05 mi), but steady-state semantics send
  each converted school's former lottery enrollees back to their areas'
  OTHER destinations pro-rata — those replacement assignments are mostly
  non-walkable (district avg stop→school distance +0.09 mi), and Orca's
  geozone residents at stay-rate out-ride its old diffuse draw (+99). Net:
  the two effects nearly cancel, slightly positive.
- **2026-06-10 (s10)** VERIFIED (user check): district **basic riders
  exclude HCC/gifted** — the 10,008.5 calibration target is STARS
  `basic_students_on_buses`; gifted is the separate `special_students_gifted`
  (1,315.5) with its own propensity; special_ed (2,506) is a third program,
  not modeled. KNOWN PER-SCHOOL CONFLATION at the 4 mixed MS pathway sites
  (Hamilton 105, Jane Addams 106, Eagle Staff 113, Washington 117): the
  basic-pool column marginals are TOTAL RC enrollment incl. HC kids (e.g.
  Hamilton 989 incl. 298 HC; ~783 HC kids across the 4), and `basic_cells`
  does not subtract them, while the SAME kids form those sites' gifted
  pools — so per-school basic+gifted sums double-count there, and scenario
  deltas touching those sites (e.g. ms_walk_1mi: ~+695 of the +2,073 basic
  delta is at the 4 sites, ~25% HC-share ⇒ rough ~+175-rider overlap) carry
  a modest double-count. District BASELINES are immune (each program
  renormalizes to its own STARS target). Extends the s8 closure-op note
  ("the basic column isn't split by program"). Possible fix if it starts to
  matter: subtract `highly_capable` from `col_marg` at gifted-route sites.
- **2026-06-10 (s10)** KUOW closure plans modeled: `close_option_a` (the
  "well-resourced schools" plan, 21 closures incl. most option/K-8s) and
  `close_option_b` (the "choice" plan, 17 closures incl. Thurgood
  Marshall). All names resolved against school_directory (Hay=234,
  Decatur=287 hcc_pathway, TM=212 mixed neighborhood+HCC). 200-draw MC:
  A basic Δ **+850** [+758, +937] riders / +17 routes; B **+1,136**
  [+1,078, +1,188] / +23 routes; reports in `simulate/close_option_*/`.
  Engine-default relocations (3-nearest-neighborhood split / nearest option
  site / HCC intact to nearest gifted site = Cascadia for both Decatur and
  TM), sequential NW→SW op order — NOT SPS's actual reassignment maps; the
  bus-cost increase is a lower-bound-flavored estimate of transport
  response, and the claimed $31.5M/$25.5M savings are building-operations
  numbers outside this model. B > A in added riders even with fewer
  closures (A removes more big option-K-8 ridership outright). Both skew
  rider gains toward high-poverty ES areas.
- **2026-06-10 (s10)** Bus fleet + cost model INGESTED (user-provided):
  SPS pays ~**$148.9k per bus-year** (SY2024-25 all-in vendor cost: $56.89M
  purchased transportation / 382 buses; SY2023-24 ≈ $148.4k; ≈ $820/bus/day
  over ~181 service days; base daily rate alone $580-650; +~$12k/bus if
  district supervision/crossing-guard overhead ~$4.7M/yr is added ⇒ ~$161k;
  pre-COVID ≈ $106k; SY2022-23 ~$169k = Zūm-failure outlier, excluded).
  Fleet rule (user): 2 bell shifts — ES rides at a different time from
  MS/HS, a bus serves one route per shift, so **buses = max(simultaneously
  active routes)**. Implemented POOLED across basic+gifted in
  `report.bus_cost_summary` (validation: rule gives max(144+27, 47+13) =
  171 vs STARS 2024-25 actual basic+gifted buses 162, +5.6%; per-program
  maxes do NOT reproduce STARS — basic 144 vs 123, gifted 27 vs 39). All
  10 saved reports regenerated with the new "Bus fleet + annual cost"
  section. Headline consequence: MS/HS-shift route additions cost ~0 buses
  while the ES shift stays the binding max (`ms_walk_1mi` +42 routes → +0
  buses; `hs_bussing` +56 → +0; `hs_bussing_1mi` +119 → +3.5), whereas
  ES-shift additions pay full freight (closures +17/+23 buses →
  +$2.6M/+$3.4M/yr; conversions +7.5/+7.9 buses → +$1.1M/+$1.2M). CAVEAT:
  $/bus is the all-in annual average — adding a 2nd route to an existing
  bus still adds driver-hours/fuel ("excess hours"), so the +$0.00 rows
  are a lower bound on marginal cost.
- **2026-06-10 (s10)** USER CORRECTION — units: the STARS counts the model
  calibrates to (`basic_students_on_buses` 10,008.5,
  `special_students_gifted` 1,315.5) are **RIDES per day**, not unique
  students: AM and PM boardings each count, a both-ways student = 2; on
  longer routes more students ride mornings only. NO math changes — model
  and targets share the unit, so all totals/deltas/CIs stand — but every
  "riders" label means rides/day: unique students ∈ [rides/2, rides];
  riders-per-route 49.5 = rides/day/route ≈ 25 students on a one-way run;
  the solved "propensity" (0.646 implied, etc.) is expected rides/day per
  eligible student (theoretical max 2, not 1 — the p_max=0.95 cap is a
  calibrated shape bound, not a probability ceiling); the fitted distance
  decay partly captures the AM-only behavior on long routes. Docstrings
  (ridership.py, report.py), report output header, this file's scenario
  table + glossary updated; all 10 reports regenerated.
- **2026-06-10 (s10)** STARS EXAL funding formula INGESTED (user-provided,
  2025-26): EXAL = exp(0.66498·ln(BasicRiders+1) + 0.11·ln(SpecialRiders+1)
  + 0.01523·Destinations + 0.04231·AvgDistance + 0.02839·ln(LandArea)
  − 0.29176·NonHighDist + 8.6013); allocation = min(EXAL, $59.8M prior-yr
  cap) + $1,048,782 salary adj. Per user: assume the cap never binds and
  coefficients are stable, so cap + salary adj drop out of deltas.
  Implemented in `report.funding_summary` + a "State funding" report
  section with NET fiscal Δ (= revenue − bus cost) per draw; validated
  against the user's worked numbers (baseline EXAL $36.68M, marginal
  $2,653/boarding ✓). Scenario deltas feed the formula on top of the
  OFFICIAL SY2024-25 inputs (BasicRiders 9,194.75 — a different STARS
  count than the model's 10,008.5 baseline; SpecialRiders 4,256.25 takes
  the gifted deltas since gifted is a STARS "special" program;
  Destinations 105.75 takes the change in served-school count, riders>0.5;
  AvgDistance 2.16 takes the rider-weighted basic distance delta as a
  proxy — route-avg vs rider-weighted measures differ). Results in the
  fiscal table (Current state): closures LOSE ~$7.5-9.6M/yr net (the
  Destinations term ≈ $0.55M per served school dominates), service
  expansions GAIN (+$5.3M ms_walk_1mi, +$17.1M hs_bussing — each new HS
  destination is worth ~$0.7M at the bigger scale). FLAG: `hs_bussing_1mi`
  pushes EXAL to ~$62.4M > the $59.8M cap — its +$25.7M revenue assumes
  the user's never-hit-cap instruction; capped reality would clip it to
  ~+$23.1M.
- **2026-06-10 (s10)** HS ridership model REFINED (user direction): HS is
  now a *fraction of MS*, not ES-like. HS cells take the MS tilt (is_ms=1)
  × `hs_indep_factor` (default **0.7**, all HS grades — rides lost to
  independent travel on public transit, especially after school) ×
  (0.5 + 0.5·`hs_car_factor`) (default **0.5** for grades 11-12 — age 16+,
  kids get cars; grade pairs weighted 50/50) ⇒ effective **0.525 × MS**.
  Both factors are new RidershipParams fields (defaults in dataclass;
  load_params tolerates the old params.csv) sampled in the MC
  (N(0.7, 0.1) / N(0.5, 0.2), clipped to [0.05, 1]). Baseline untouched
  (no HS cells; empty-scenario check PASS). HS scenarios re-run:
  `hs_bussing` +2,780 → **+1,659** rides/day [+1,143, +2,332], EXAL
  +$13.6M; `hs_bussing_1mi` +5,908 → **+3,532** [+2,411, +4,908], EXAL
  +$18.9M — now +0 buses (the smaller MS/HS shift no longer overtakes the
  ES shift) and back UNDER the $59.8M cap (~$55.6M total), retiring the
  earlier cap flag. CIs are much wider than before — the sampled HS
  factors dominate the uncertainty, as they should for an uncalibrated
  assumption. OVERVIEW.md ridership section, MC distribution table, and
  assumption 2 updated.
- **2026-06-11 (s10)** Rules-of-thumb table added to findings.html (user
  request) as new §2 (later sections renumbered §3-§7), computed LIVE
  from the model constants in `findings_html.rules_of_thumb()` so it
  cannot drift: $/basic ride-yr ≈ $2,652 (×2 for a both-ways student),
  $/special ride-yr ≈ $948; closing 1/5/10 served schools −$0.55/−2.69/
  −5.18M-yr (exact exponential, not linearized — losses sub-linear,
  gains super-linear: openings +$0.56/+2.90/+6.03M); new ES-shift route
  ≈ $149k-yr (new bus), MS/HS-shift ≈ $21.5k (overage hours); break-even
  rides/day for a new route: basic 56 (ES — avg route carries 50, so a
  typically-loaded ES route ~pays for its bus) / 8 (MS/HS); special 157
  (ES — infeasible) / 23 (MS/HS).
- **2026-06-11 (s10)** dissolve_hcc CORRECTED (user: leaving Cascadia/
  Decatur draw-less was "a fairly big error"): pure pathway sites now
  become TRUE neighborhood schools competing for local students via an
  **artificial 1-mile catchment** — a 1-mile circle at the school point
  fed through the conversion stay-rate machinery (`_carve_local_draw`,
  refactored out of op_convert; convert_optA_5 EV verified unchanged to
  the decimal), a calibrated 1-mile-buffer walk zone, and membership in
  the basic service set. Cascadia draws 711 students, Decatur 678 — large
  because a 1-mile radius covers ~2 typical ES areas; band totals stay
  conserved. Numbers moved little (dissolve_hcc NET +2.06 → **+2.04**;
  A_no_hcc −6.99 → −7.01; B_no_hcc −6.09 → −6.11 — the catchment kids are
  mostly walkers) but the structure is now right and the EXAL-destination
  caveat is moot (the sites keep service). All three re-run + reports +
  page regenerated.
- **2026-06-11 (s10)** New 7th op `dissolve_hcc` + three scenarios (user:
  "turn all HCC schools into neighborhood schools"). Op semantics: the
  gifted table empties (gifted transportation → 0, all 40 routes); PURE
  pathway sites (classification hcc_pathway: Cascadia, Decatur) lose their
  entire flow column via the everywhere-rule; MIXED sites (TM + the 4 MS
  pathway sites) lose their HC cohort — apportioned to member feeder areas
  by band population, capped by actual draw, returned to each area's other
  destinations pro-rata; classifications flip to neighborhood; band
  enrollment conserved. CAVEATS: emptied pure sites stay open with ~no
  draw (no attendance area is carved for them) and their lost service is
  NOT counted as an EXAL destination change; the mixed-site HC apportion
  uses band population, not true HC residence. Results (200 draws):
  `dissolve_hcc` basic **+329** [+309, +346] (ex-HCC kids ride locally),
  gifted −1,315.5, buses −15.5, EXAL −$0.63M (SpecialRiders term loss ≈
  basic gain), **NET +$2.06M/yr** — ending HCC transportation saves ~$2M
  net. Variants: `close_option_a_no_hcc` NET **−6.99** (vs A −9.15) and
  `close_option_b_no_hcc` NET **−6.09** (vs B −8.17) — dissolution is
  ~additive (+$2.1M each). scenario_gifted_pool gained an empty-table
  guard; simulate's outer-join already handled a vanished program.
- **2026-06-11 (s10)** Conversion scenarios REPLACED (user): Licton
  Springs (955) excluded from consideration ("too different"), which
  leaves exactly 5 candidates on the Option A list — so the two random
  5-of-6 combos collapse into the single deterministic set
  `convert_optA_5` (Cedar Park, TOPS, Orca, Salmon Bay, Boren); the
  rand1/rand2 specs + runs are deleted. Label renamed to "5 option
  schools → neighborhood". 200-draw MC: basic Δ **−171** rides/day
  [−195, −145] — SIGN FLIP vs the old +240/+238, because this set
  includes BOTH big-riddershed K-8s (Salmon Bay −141, Boren) while LS
  contributed ~nothing; buses −3.3, EXAL −$0.50M, **NET −$0.00M**
  [−0.02, +0.02] — conversions are now an almost exact fiscal wash.
- **2026-06-11 (s10)** Closure default CHANGED to the "everywhere-rule"
  (USER correction: "when a school closes, the students can go *anywhere*
  ... probably choose by distance ... no hard-cap to enrollment"): the old
  default (3 nearest open neighborhood schools; option→nearest option
  site) is GONE. New default in `op_close_school`: each residence area's
  displaced students redistribute across ALL open schools pro-rata to the
  area's existing draw (revealed choice, dominated by distance — e.g. 32%
  of Sacajawea-area kids already choose Hazel Wolf); receiving schools'
  enrollment grows via `_rescale_col_marg` (no caps). IPF cannot do this
  itself — column marginals pin school sizes, so the op must grow them.
  Explicit `receivers` still model designated consolidations (split ∝
  named receivers' draw; basic service follows the kids — under the
  default, unserved schools do NOT gain service from spillover). HCC
  pathways still relocate intact. Re-runs: `close_sacajawea` −7.6 →
  **−29** rides/day [−35, −23] (Hazel Wolf top receiver +38); Option A
  **+850 → −147** (sign flip — dispersing long option-K-8 draws to nearby
  choices SAVES rides; buses −8.4, cost −$1.1M); Option B +1,136 →
  **+279**; fab4 (named receivers) unchanged. Fiscal nets: A −9.15,
  B −8.17, dearborn −8.15, sacajawea −0.54 — the Destinations funding
  loss now utterly dominates the closure story. All affected reports,
  breakdowns, findings.html (incl. §6 key findings + Fig 1/3 captions),
  OVERVIEW, spec descriptions, and this file updated.
- **2026-06-11 (s10)** EXAL Destinations CORRECTED (user caught the
  +$21.5M hs_ms_bussing_1mi net looking wrong): the old logic counted any
  school gaining/losing MODELED rides as a destination change, but the
  formula's 105.75 input counts schools served by ANY STARS program —
  and 12 of the 13 HS sites already run special-ed routes (only Nova is
  service-free). New basis in `funding_summary`: destination deltas vs
  the any-program 2024-25 served set — additions only for never-served
  schools; closures count even when the model carries no rides there
  (Sanislo). Effects: HS-scenario revenue drops sharply (hs_bussing
  +13.56 → **+5.17**, net +4.45; hs_bussing_1mi +18.94 → **+9.65**;
  hs_ms_bussing_1mi +24.90 → **+14.62**, net +11.24 — and no longer
  crosses the cap, retiring that flag); closures get WORSE (Option A dest
  −18 → −21, net −9.58 → **−10.91**; B −13/−14 → −17 both, nets
  **−9.44/−9.42** — the old B-vs-Dearborn gap was a counting artifact;
  fab4 −3 → −4, net −2.26); walk/conversion scenarios unchanged. All
  reports, findings.html (incl. §6 key findings), and this file updated.
- **2026-06-11 (s10)** EXAL change table added to every scenario breakdown
  (user request): `breakdown._exal_terms` decomposes the reimbursement
  change per formula term (input base→scen, multiplicative factor) — the
  factors multiply exactly to scenario EXAL at mean-draw inputs, with the
  MC mean Δ alongside. Rendered in both `simulate/<name>/breakdown.md`
  and the expandable sections of findings.html.
- **2026-06-11 (s10)** Uptake annotation added (user request): reports now
  show the district Δ bus-eligible pool + **marginal uptake** = Δrides ÷
  Δeligible (rides/day per newly-eligible student, theoretical max 2 since
  both-ways riders count twice); breakdown tables (md + HTML) gained a
  per-school "propensity base→scen (marginal)" column; findings cards show
  "bus-eligible Δ · uptake" where meaningful (|Δeligible| > 50). Values
  confirm the model's structure: `ms_walk_1mi` uptake **0.67** [0.62,
  0.73] (≈ the 0.65 system average — newly eligible MS kids behave like
  existing riders), `hs_bussing` **0.27** [0.18, 0.38] (the 0.525 HS
  discount + long distances), `hs_ms_bussing_1mi` 0.37 (blend). CAVEAT:
  for closures the district ratio mixes additions and removals (e.g.
  close_sacajawea Δeligible +34 net, ratio −0.21 — not meaningful); use
  the per-school marginal column there instead.
- **2026-06-11 (s10)** Fleet-scope clarification (user catch): the model's
  "≈180 buses" is the MODELED basic+gifted subset (STARS 2024-25 actual
  162; bell-shift rule estimates ~171-180), NOT the district fleet — SPS
  runs ≈382 buses total, the other ~220 serving special-ed (2,506
  rides/day), early-ed, and McKinney-Vento, all outside the model. The
  $148.9k/bus-yr cost is the all-fleet average ($56.89M ÷ 382) applied to
  modeled deltas. Scope notes added to report.py output, findings.html
  (§1 baseline, Fig 2 caption, §5 table caption), and OVERVIEW.md; all
  reports + page regenerated.
- **2026-06-11 (s10)** Overage-hours cost term ADDED (user-directed
  ASSUMPTION): bus cost = Δfleet × $148.9k + (Δroutes − Δbuses) ×
  **2.0 hr/route/day × $61.5/hr × 175 service days ≈ $21.5k/route-yr**
  (signed — routes removed from retained buses save hours). Context: SPS
  spend shows ~$9.8M/yr (both 2023-24 and 2024-25) that may be hourly
  overages at ~$61.5/hr, but the bucket CANNOT be broken down; attributing
  all of it to MS+K-8 route overages would imply ~9.6-10.1 hr/route/day
  (95/90 such routes) — implausible vs a 6-hr contract day, so the 2.0
  figure is a judgment call (≈ an AM+PM run pair), documented in report.py
  constants. Reports + findings.html now show BOTH values (fleet-only
  lower bound and with-overage). Effect: expansion nets trimmed ~5-10%
  (hs_bussing +13.56 → +12.84; hs_ms_bussing_1mi +23.93 → +21.53);
  closures unchanged (ΔroutesΔ≈Δbuses); conversions slightly LESS costly
  (+7.5 buses vs +4.8 routes ⇒ retained buses shed hours). No headline
  sign flips. Also: findings.html tables wrapped in horizontal-scroll
  containers (were drawing off the right edge on narrow screens).
- **2026-06-10 (s10)** Combined scenario `hs_ms_bussing_1mi` (user):
  add_basic_service HS + set_walk_threshold MS 1.0 + HS 1.0. EV confirms
  the components are exactly ADDITIVE (+5,603 = ms_walk_1mi +2,080 +
  hs_bussing_1mi +3,523 — the ops touch disjoint cells). 200-draw MC:
  basic **+5,615** rides/day [+4,417, +7,085], gifted +162, routes +113,
  buses +6.5 [0, +35.5] (the MS/HS shift overtakes ES in the high-HS-
  ridership draws), EXAL revenue +$24.9M, NET +$23.9M. CAP FLAG: mean
  total EXAL ≈ $61.6M > the $59.8M prior-year cap — under a binding cap
  revenue clips to ≈ +$23.1M (net ≈ +$22.1M). findings.html regenerated
  (12 scenarios; scenario-count wording now derived from the list).
- **2026-06-10 (s10)** "Fab-4" closure modeled (`close_fab4`): North Beach
  259→Viewlands 276, Sacajawea 268→Rogers 266, Stevens 272→Montlake 255,
  Sanislo 273→Highland Park 235 — explicit single receivers (the named
  consolidation partners), overriding the 3-nearest default. 200-draw MC:
  basic Δ **+174** rides/day [+141, +206], +3.5 routes/buses (+$0.52M
  cost), EXAL revenue −$1.20M (Destinations −3, NOT −4: Sanislo has ~0
  baseline riders — its kids walk — so it never counted as a served
  destination), **NET −$1.72M/yr**. District avg distance unchanged.
  Equity cut: the rider gain lands almost entirely in the high-low-income
  tercile (+217) — Highland Park/Rogers/Viewlands absorb ex-walkers as new
  bus riders. Each pair's riders + the displaced walkers land at the named
  receiver (Rogers +143, Viewlands +138, Montlake +83, Highland Park +74).

---

## Glossary
- **Riders / rides per day** — every "riders" figure in this pipeline (and
  the STARS `*_students_on_buses` / `special_students_gifted` columns it
  calibrates to) counts **boardings per day**: AM and PM each count once, a
  both-ways student = 2 (USER correction, s10). Unique students ∈
  [rides/2, rides]; long-route students disproportionately ride AM only.
- **Walk zone** — area close enough to a school that students are *not* bus
  eligible (must walk). **Transportation zone** = bus-eligible remainder.
- **Attendance area** — geographic zone assigned to a neighborhood school.
- **Option / choice school** — no attendance area; enrolls by application from
  an eligibility **geozone**.
- **STARS** — OSPI Student Transportation Allocation Reporting System.
- **EXAL** — *Expected Allocation*: the STARS pupil-transportation funding
  formula / reimbursement amount (USER-provided, s10; implemented in
  report.py).
- **P223** — monthly SPS enrollment count report.
- **SAFS** — the main ETL pipeline in this repo (enrollment, s275, etc.).
