# Session-Kickoff Prompts (living document)

Copy/paste one of these into a **fresh Claude Code context** to resume the
ridership Monte Carlo project without losing the thread. Keep them in sync with
`NOTES.md` — when the plan changes, edit the relevant prompt here too.

> Convention: every session should **start** by reading `NOTES.md` and **end**
> by updating it (Current State, Decision Log, Open Questions) and revising the
> relevant prompt below.

---

## A. Universal resume prompt (use this most of the time)

```
We're continuing a multi-session project: a Monte Carlo simulation of Seattle
Public Schools yellow-bus ridership under walk-zone changes and school closures,
built from public population data. All work lives in analysis/montecarlo/.

Before doing anything: read analysis/montecarlo/NOTES.md in full — it's the
durable handoff (current state, data inventory, decisions, open questions).
Activate the repo venv first: `source venv/bin/activate`.

Today I want to: <FILL IN — e.g. "build the population synthesis stage (#2)">.

Work within the architecture in NOTES.md. Prefer reusing this repo's existing
SAFS/STARS data (enrollment, P223, STARS) over re-fetching. At the end of the
session, update NOTES.md (Current State + Decision Log) and PROMPTS.md.
```

---

## B. Planning session — DONE 2026-06-09 (session 2)

Planning is complete: the locked 11-stage architecture, scenario op set
(walk-zone resize, closure, option→neighborhood conversion, option-school
move), draw-kernel/IPF design, calibration strategy, and M1-M7 build order
all live in NOTES.md → "Architecture (LOCKED)". Don't redo planning; use
Prompt C with the next milestone (M1 = Stage 2 `school_directory.py`). If
scope changes again, update NOTES.md architecture + this file rather than
re-running a generic planning prompt.

---

## C. Building a specific stage (template)

```
Continuing the SPS ridership Monte Carlo (analysis/montecarlo/). Read NOTES.md;
`source venv/bin/activate`.

Build stage #<N> "<name>" from the architecture in NOTES.md.

Requirements:
- New module analysis/montecarlo/<name>.py, importable + runnable as
  `python3 -m analysis.montecarlo.<name>`.
- Pure-functional core so the Monte Carlo loop can call it with sampled params.
- Joins to upstream stages on `school_id` (and small-geography id where
  relevant). Reuse parse_shapes.load_all().
- Include a __main__ summary like parse_shapes.py.
- Validate against <calibration target> before declaring done; report the fit.

When done, update NOTES.md Current State + Decision Log.
```

---

## F. M4 — Stages 6-7 assignment + eligibility — DONE 2026-06-09 (session 6)

Built as specced: `assignment.py` (OD-anchored prior + IPF → tracked
`assignment/assignment_matrix.csv`, 19,094 cells; option-kernel decay fits in
`assignment/kernel_params.csv`: ES/MS 0.50 mi, HS 1.50 mi) and
`eligibility.py` (pure-geometry walk fractions → tracked
`eligibility/walker_fractions.csv`, 2,798 pairs). Combined validation PASS:
bus-eligible pool 15,229 at the 77 basic-route schools → implied propensity
0.657 vs the 10,008 target; per-school eligible vs basic routes r=0.718.
Scenario hooks ready for M6: `build_matrix(pop=...)`,
`kernel_bg_weights(school_id, kind, band)`, `walk_fractions(walkzones=...)`.
See the two READMEs + NOTES.md s6 decision-log entries before touching.

---

## G. M5 — Stage 8 ridership — DONE 2026-06-10 (session 7)

Built as specced: `ridership.py` — bounded-mixture distance shape
`f(d) = (1−ρ)+ρ·exp(−d/L)` × centered demographic tilt, level re-solved to
the 10,008 district target every call (renormalization survives any θ).
Fitted: ρ=1.0 pure decay, L=4.69 mi, β_swd +6.13 dominant (demographic
proxy — SpEd routes are a separate program). Per-school route correlation
**r 0.718 → 0.814**. Gifted via HCC kernel (ES) / assignment columns (MS):
propensity 1.011 vs 1,316 target (>1 ⇒ MS pool understated; fix = open
question 4b). Tracked `ridership/school_ridership.csv` + `params.csv`;
loaders `load_ridership()`, `load_params()`; Stage-10 hooks
`expected_riders(assignment, walk, params θ)` + `sample_riders(rng)`.
Read `ridership/README.md` + NOTES.md s7 decision-log entries before touching.

---

## H. M6 — Stage 9 scenario engine — DONE 2026-06-10 (session 8)

Built as specced: `scenarios.py` (World dataclass + the 5 ops + JSON spec
validation + `apply`/`evaluate`/`run_scenario`) and tracked specs under
`scenarios/` (see README there). Empty scenario reproduces the baseline
within CSV rounding (`--validate` PASS); smokes: `close_sacajawea`
(−104 riders reabsorbed by 3 neighbors, district −4.9) and `es_walk_1p5mi`
(basic 10,008 → 7,170). Critical mechanics: residence strata FIXED (ops edit
only the destination side); scenario evaluation uses the baseline-solved
propensity scale + covariate centering via new backward-compatible
`ridership.py` params (`fixed_scale`, `points`, `basic_ids`, `covar_means`)
— re-solving would renormalize deltas away. Read the module docstring +
NOTES.md s8 decision-log entries before touching.

---

## I. M7 — Stages 10-11 MC loop + report — DONE 2026-06-10 (session 9)

Built as specced: `simulate.py` (paired MC driver, `run_mc(scenario,
n_draws, seed)` → tracked CSVs under `simulate/<scenario>/`) and `report.py`
(district/per-school delta CIs, distance stats, equity cuts by RC low-income
and ES-area poverty terciles). Key decisions (NOTES s9 decision log):
**per-draw calibration** (scale + covar means + gifted propensity re-solved
on each draw's own baseline, reused for the paired scenario run); θ sampling
= decay_mi lognormal σ=0.2, betas normal sd=max(0.2|β̂|, 0.05), ρ FIXED at
the fitted 1.0 boundary; scenario worlds built once (θ/pop-independent).
Perf: ~0.2 s per paired draw (the 30-60 s estimate was cold-cache; per-world
walk fractions hoisted out of the loop). Validation PASS: 200-draw
`close_sacajawea` basic Δ −4.4 [−11.2, +2.8] brackets the EV −4.9; sampling
disabled reproduces EV exactly; `es_walk_1p5mi` Δ −2,835 [−3,007, −2,693].
Usage: `python3 -m analysis.montecarlo.simulate --scenario <name>` then
`python3 -m analysis.montecarlo.report <name> --save`.

---

## D. Scenario definition (when the user is ready to specify changes)

```
Continuing the SPS ridership Monte Carlo. Read NOTES.md; `source venv/bin/activate`.

I'm specifying the scenarios to simulate. Here they are:
  Closures: <school_ids or names>
  Walk-zone changes: <description / new polygons / radius edits>

Turn these into a machine-readable scenario spec under analysis/montecarlo/
(e.g. scenarios/*.json or .py), validate the referenced school_ids against
parse_shapes locations, then run them through the pipeline and report ridership
deltas with confidence intervals vs. the baseline. Record the scenarios in
NOTES.md.
```

---

## E. Multi-year Section 4 ingestion — DONE 2026-06-09 (session 3)

Completed via a different route than this prompt planned: a standalone
repo-root script `enrollment_reports.py` ingests ALL Annual Enrollment
Report PDFs (`data/sps/enrollment/`, 2010-11..2024-25, 2022-23 missing at
source) → `out_enrollment/` (untracked): `section4_od.csv`,
`section4_attendees.csv`, `section4_option_draw.csv`, plus Table 1-D
`enrollment_by_school.csv`. Handoff + format-drift map: repo-root
**`ENROLLMENT_HANDOFF.md`** — read it before touching the parser; don't
re-explore the PDF formats. `section4_seattle.py` + tracked `section4/`
remain the 2024-25 baseline loaders. Note `year` in `out_enrollment/` is a
string label ("2024-25"), not the int fall-year used in montecarlo.

## Notes on using these
- The architecture stage numbers (#1–#11) live in NOTES.md → "Architecture
  (LOCKED)". Keep prompt C's `<N>` consistent with that list.
  - M1 (`school_directory`) DONE (s3). M2 (`baseline_ridership`) DONE (s4).
  - M3 (`acs_population` + `synth_population`) DONE (s5).
  - M4 (`assignment` + `eligibility`) DONE (s6). M5 (`ridership`) DONE (s7).
  - M6 (`scenarios`) DONE (s8). M7 (`simulate` + `report`) DONE (s9).
  - **All milestones complete. Next up: user-specified scenarios (prompt D)**
    — write the spec JSON under `scenarios/`, then
    `simulate --scenario <name>` + `report <name> --save`.
- school_directory loaders: `load_schools()`, `load_stars_name_map()`,
  `load_section4_name_map()`. See `school_directory/README.md`.
- baseline_ridership loaders: `load_school_routes()`, `load_school_enrollment()`,
  `load_district_targets()`, `load_kernel_check()`. See `baseline_ridership/README.md`.
  2024-25 calibration targets: 10,008 basic on-bus, 1,316 gifted, 202 basic routes.
- assignment loaders: `load_assignment()`, `load_kernel_params()`; MC/scenario
  hooks `build_matrix(pop=...)`, `kernel_bg_weights()`. See `assignment/README.md`.
- eligibility loaders: `load_walker_fractions()`, `bus_eligible()`,
  `validate_pipeline()`; scenario hook `walk_fractions(walkzones=...)`.
  See `eligibility/README.md`.
- ridership loaders: `load_ridership()`, `load_params()` → `RidershipParams`;
  Stage-10 hooks `expected_riders(assignment, walk, params)`,
  `sample_riders(rng, ...)`. See `ridership/README.md`.
- scenarios API: `baseline_world()`, `load_scenario(name)`, `apply(scenario)`,
  `evaluate(world, params=, pop=)`, `run_scenario(scenario)`; specs under
  `scenarios/` (see README there). CLI: `--validate` (baseline check),
  `--run <name>` (delta report).
- simulate API: `run_mc(scenario, n_draws=200, seed=20260610)`, `load_run()`,
  `sample_params(rng)`; saved runs under `simulate/<scenario>/` (see README
  there). report API: `report(name)`, `district_summary()`, `school_summary()`,
  `equity_cuts()`. CLI: `simulate --scenario <name> [--no-theta] [--no-pop]`;
  `report <name> [--save] [--top N]`.
- If a planning answer changes the architecture, edit NOTES.md *and* prompt B/C
  so future sessions inherit the new plan.
- These prompts assume the repo conventions in the top-level CLAUDE.md (run
  modules from repo root; analysis/ is ad-hoc, not the production pipeline).
```
