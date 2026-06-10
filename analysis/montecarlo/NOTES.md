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

Last updated: **2026-06-10** (session 9 — M7 `simulate.py` + `report.py`
DONE; **all milestones M1-M7 complete — the pipeline is fully built**).
**Next session:** real scenario definitions from the user (Prompt D) — the
machinery runs any spec end-to-end in ~40 s for 200 draws:
`python3 -m analysis.montecarlo.simulate --scenario <name>` then
`python3 -m analysis.montecarlo.report <name> --save`. Remaining model-quality
work lives in the open questions (4 walk-rule verification, 4b MS HC
pathways, 6 requirements pinning).

Scenario scope EXPANDED in session 2: besides walk-zone changes and closures,
we also model **converting option schools to neighborhood schools** and
**moving option schools**.

---

## Current state (what exists today)

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
  (neighborhood / option / hcc_pathway — hcc uses `hcc_pathways_es.csv`).
  GOTCHA: ES od rows with grade_band "6-8" (Blaine/Broadview-Thomson blocks)
  are EXCLUDED from flows — those kids are already in the MS OD tables.
- **`eligibility.py`** — DONE (session 6). Stage 7: walk-zone membership,
  pure geometry. `walker_fractions.csv` (tracked under `eligibility/`):
  2,798 nonzero (GEOID, school_id) → walk_frac pairs (fraction of the BG's
  SPS-territory area inside the school's official walk zone; missing pair =
  0). Scenario hook: `walk_fractions(walkzones=<gdf>)` recomputes for resized
  polygons. API: `load_walker_fractions()`, `bus_eligible()` (joins Stage 6 ×
  Stage 7 → per school × band n_assigned/n_walk/n_bus_eligible),
  `validate_pipeline()`. **M4 validation (2024-25): PASS** — 77 basic-route
  schools, ES+MS assigned 31,123, walkers 15,894 (~50%), bus-eligible
  15,229; implied on-bus propensity 10,008/15,229 = **0.657** (Stage 8's free
  parameter, plausible); per-school bus-eligible vs STARS basic routes
  Pearson r=0.718, Spearman ρ=0.622; median eligible/route 79 × 0.657 ≈ 52
  riders/route vs actual 49.5 — consistent.
- **`ridership.py`** — DONE (session 7). Stage 8: ride propensity → expected
  riders per school × program, tracked under `ridership/` (see README there).
  Model per cell: `p = clip(s·f(d)·exp(β·x), 0, 0.95)` with
  `f(d) = (1−ρ) + ρ·exp(−d/decay_mi)` (d = BG centroid → school point) and
  centered school covariates x = (is_ms, low_income_frac, swd_frac,
  absent_rate); s re-solved every call so basic riders = the STARS district
  target (10,008) — hard renormalization, θ shapes only the distribution.
  Fitted θ (2024-25): ρ=1.0 (pure distance DECAY), decay 4.69 mi, β_ms +0.19,
  β_li +0.38, β_swd +6.13, β_abs −0.31. Per-school riders vs STARS basic
  routes: **r 0.718 (flat M4) → 0.814 (shaped)**. Gifted: HC enrollment at
  the 7 gifted-route sites spread by HCC pathway kernel (ES) / own assignment
  column (MS, 4b caveat); solved propensity 1.011 vs the 1,316 target.
  Riders→routes via district riders-per-route (basic 49.5, gifted 32.9).
  API: `load_ridership()`, `load_params()` → `RidershipParams` (θ dataclass),
  `expected_riders(assignment, walk, params)` pure core,
  `sample_riders(rng, ...)` Poisson MC wrapper. Stage 10 samples θ via
  `dataclasses.replace(load_params(), ...)`.
- **`scenarios.py`** — DONE (session 8). Stage 9: scenario engine — the 5 ops
  (`set_walk_threshold`, `scale_walkzone`, `close_school`,
  `convert_option_to_neighborhood`, `move_school`) over a `World` dataclass
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
  - **M6 validation PASS:** empty scenario reproduces the tracked baseline
    within CSV rounding (19,094 cells max |Δ| 5e-5; walk 5e-7; riders
    0.005). Smoke `close_sacajawea`: −104 riders at Sacajawea reabsorbed as
    +78 Olympic View / +17 Wedgwood / +4.5 Rogers, district −4.9.
    Smoke `es_walk_1p5mi`: basic 10,008→7,170 (−57 routes est).
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
  PASS:** `close_sacajawea` 200 draws → district basic Δ −4.4, 95% CI
  [−11.2, +2.8] brackets the expected-value −4.9; per-school movers match
  the M6 smoke (Sacajawea −104.2 [−107.7, −99.8] → OV +78 / Wedgwood +17 /
  Rogers +4.5). `es_walk_1p5mi` 200 draws → basic Δ −2,835 [−3,007, −2,693]
  (≈ the −2,838 EV run), gifted −97 (Decatur walk zone), est routes −57.
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

### KEY JOIN FACT (established session 1)
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
- Added this session (NOT yet pinned in `requirements.txt` — **open task**):
  `geopandas`, `shapely`, `pyproj`, `pyogrio`. These upgraded `pandas` to 3.0
  and `numpy` to 2.4 in the venv. Decide whether to pin or keep a separate
  geo-requirements file (the SAFS pipeline may not want pandas 3.0).

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
- **SPS walk thresholds (verify before using):** ~1 mile for elementary, ~2
  miles for middle/high. These define who is *walk-zone* (ineligible for the
  bus) vs *transportation-zone* (eligible). Confirm exact rule + any
  hazard-route exceptions.

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
- The PDF covers **ES only**. MS gifted destinations in STARS (Hamilton,
  Washington, Eagle Staff, Jane Addams K-8, Madison) need their own pathway
  mapping later; HS HCC transportation ended with Garfield routes after
  2018-19.

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
1. **Concrete scenario list** — which schools to convert/move/close, what
   thresholds to sweep. (User: "will specify later." Prompt D is for this.)
2. **Conversion semantics** — when an option school becomes a neighborhood
   school, where does its attendance area come from: carve from its geozone,
   redraw neighboring areas (hard sub-problem), or user-supplied polygon? And
   do we report steady-state or the transition years (current distant
   enrollees grandfathered)?
3. **HCC behavior on closure/move** — does the pathway relocate (riders
   follow) or dissolve (riders go to neighborhood schools)? Default: pathway
   relocates intact.
4. **Walk-rule verification** — confirm exact SPS thresholds (~1 mi ES, ~2 mi
   MS/HS) + hazard-route exceptions before Stage 7.
4b. **MS HC pathways** — map Hamilton / Washington / Eagle Staff / Jane Addams
   / Madison to MS attendance areas (analogous to `hcc_pathways_es.csv`).
5. **Output decision context** — cost? equity? bus-count planning? Shapes
   which report metrics get emphasis.
6. **requirements.txt** strategy (see Environment above) — geo deps still
   unpinned.

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

---

## Glossary
- **Walk zone** — area close enough to a school that students are *not* bus
  eligible (must walk). **Transportation zone** = bus-eligible remainder.
- **Attendance area** — geographic zone assigned to a neighborhood school.
- **Option / choice school** — no attendance area; enrolls by application from
  an eligibility **geozone**.
- **STARS** — OSPI Student Transportation Allocation Reporting System.
- **P223** — monthly SPS enrollment count report.
- **SAFS** — the main ETL pipeline in this repo (enrollment, s275, etc.).
