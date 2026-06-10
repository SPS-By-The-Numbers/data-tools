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

## G. M5 — Stage 8 ridership (next session)

```
Continuing the SPS ridership Monte Carlo (analysis/montecarlo/). Read NOTES.md
in full; `source venv/bin/activate`.

Build M5: Stage 8 ridership.py from the architecture in NOTES.md.

  P(ride | bus-eligible, distance, grade band, demographics, absenteeism)
  - Start from eligibility.bus_eligible() (per school × band n_bus_eligible).
    Deterministic expected-value mode first; MC wrapper after it fits.
  - The M4 baseline: a single global propensity 0.657 reproduces the 10,008
    basic on-bus target by construction. Stage 8's job is the SHAPE: propensity
    varying with distance-to-school (BG centroid → school point), grade band
    (ES vs MS), and school demographics (low_income, SWD from
    school_enrollment.csv; absenteeism from rc_seattle) — while still hitting
    10,008 district-wide (hard re-normalization is fine).
  - Soft target: per-school basic route counts (school_routes.csv, 202 routes;
    current eligible-vs-routes correlation is r=0.718 — distance/demographic
    shape should IMPROVE it; report before/after).
  - Gifted program: separate propensity on the HCC pathway flows
    (kernel/OD columns for Cascadia, Decatur, TM ES; MS gifted sites pending
    open question 4b) vs the 1,316 gifted rider target.
  - Map riders → routes/buses via riders-per-route by program (~49.5
    basic 2024-25) for cost-ish outputs.
  - Output: tracked ridership/ table per school × program (+ loaders);
    pure-functional core taking (assignment, walk_fractions, params θ) so
    Stage 10 can sample θ.

When done, update NOTES.md Current State + Decision Log + this prompt.
```

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
  - M4 (`assignment` + `eligibility`) DONE (s6).
  - **Next up: N=8 (`ridership`, prompt G)**. After that: N=9 (scenarios),
    N=10/11 (MC loop + report).
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
- If a planning answer changes the architecture, edit NOTES.md *and* prompt B/C
  so future sessions inherit the new plan.
- These prompts assume the repo conventions in the top-level CLAUDE.md (run
  modules from repo root; analysis/ is ad-hoc, not the production pipeline).
```
