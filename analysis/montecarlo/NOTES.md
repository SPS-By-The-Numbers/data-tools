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

Last updated: **2026-06-09** (session 5 — M3 `acs_population.py` + `synth_population.py` DONE).
**Next session = M4:** Stages 6-7 `assignment.py` + `eligibility.py` (IPF + walk-zone membership).

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
- **M4** Stages 6-7 assignment + eligibility — **← next session.**
  `assignment.py`: draw kernels + IPF → P(school|block_group, grade). Anchored
  to Section 4 OD flows (area→school). `eligibility.py`: walk-zone membership
  (scenario-aware) → walker vs bus-eligible, computed geometrically from the
  official walk-zone polygons (parse_shapes). NOTE: STARS
  `basic_students_in_walk_areas` is only ~96-324/yr — it is a STARS reporting
  adjustment, NOT a count of kids living in walk zones; do not calibrate
  walker counts to it. Calibrate the combined pipeline to
  `basic_students_on_buses` = 10,008 (2024-25) instead.
- **M5** Stage 8 ridership; calibrate to STARS on_bus.
- **M6** Stage 9 scenario engine + the 5 ops.
- **M7** Stages 10-11 MC loop + reporting; first real scenario runs.

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
