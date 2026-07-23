# marts

Downstream "data marts" — datasets built by joining multiple pipeline outputs
together, as opposed to `extractors/` which ingest a single source.

## `bigsheet.py`

Key feature: joins ALL per-school data we have — vitals (enrollment, spend,
staffing, region/type indicators), MAP scores (HC and non-HC), BEX building
condition/utilization/income, S-275 building staffing churn, assessment
results, and SQSS — into one wide per-school-per-class-of-year sheet, suitable
for regression/analysis work.

### Invocation

```console
$ venv/bin/python3 -m marts.bigsheet -o sheet.csv                      # BigQuery mode
$ venv/bin/python3 -m marts.bigsheet --assessment assessment.csv -o sheet.csv   # CSV override
```

`--vitals` and `--assessment` are optional. When omitted, the input is
fetched from BigQuery (project `--bq-project`, default `sps-btn-data`) using
the `.sql` files in this directory; when given a CSV path, the file is read
verbatim, which is the offline/fallback path. `--bq-project` only affects the
BigQuery path.

BigQuery auth is Application Default Credentials. If a query fails with an
auth error, run `gcloud auth application-default login`.

Runs unchanged as `venv/bin/python3 marts/bigsheet.py ...` too (no
repo-internal imports), but it must be run **from the repo root** — the
hard-coded `data/sps/...` input paths below are relative.

### CLI inputs

- `--vitals` (optional; BigQuery via `vitals.sql` when omitted) — CSV with
  vitals by school. Columns actually read:
  `school_code`, `class_of`, `school_name`, `type`, `region`, `is_regular`,
  `ms_assignment_code`, `all_students`,
  `spend_gen_ed_per_pupil`, `spend_instr_other_per_pupil`,
  `spend_district_support_per_pupil`, `spend_other_per_pupil`,
  `spend_spec_ed_per_pupil`, `spend_compensatory_per_pupil`,
  `spend_title1_per_pupil`, `spend_lap_per_pupil`, `spend_ble_per_pupil`,
  `class_teacher_exp_50pctile`, `num_class_teachers`,
  `num_class_teachers_bachelors`, `num_class_teachers_masters`,
  `num_class_teachers_doctors`, `class_teacher_fte`, `asst_principal_fte`,
  `other_teacher_fte`.
- `--assessment` (optional; BigQuery via `assessment.sql` when omitted) — CSV
  with assessment data. Columns actually read:
  `class_of`, `school_code`, `grade_level`, `test_administration`,
  `test_subject`, `student_group`, `pct_noscore`, `pct_alternative`,
  `pct_met_standard_numeric`, `pct_met_standard_numeric_nodat`.
- `-o` / `--output` (required) — output CSV path.

Recent copies of the `--vitals` and `--assessment` inputs sat at the repo root
(`vitals.csv`, `assessment.csv`) before the repo reorg; they now live in
`attic/` and were the ground truth used to reconstruct the queries below.

### `assessment.sql` — fully reconstructed and verified

Source: `ospi.rc_assessment`, filtered to `ccddd = 17001` (Seattle) and
`grade_level = 'All Grades'`. Those two predicates alone reproduce the CSV's
row count exactly — the per-grade rows in `rc_assessment` were never part of
this input.

`class_of` already exists in `rc_assessment`, so only the two `_numeric`
columns had to be derived, both from the `pct_met_standard` string:

| column | rule |
|---|---|
| `pct_met_standard_numeric` | `^[<>]?(\d+(\.\d+)?)%$` → value / 100. Bounded markers (`<10%`, `>90%`) ARE converted, using the bound itself. NULL for `Suppressed: N<10`, `N<10`, `No Students`, `N<10 (Count Protected)`. |
| `pct_met_standard_numeric_nodat` | Same, but bounded markers are ALSO NULL — only exact percentages survive. |

Verification: both rules reproduce `attic/assessment.csv` with **0
disagreements across all 92,090 rows**, and the query returns exactly those
92,090 rows (no extra, no missing). End to end, BigQuery mode reproduces
CSV mode's output with 0 disagreements across 1,185 rows × 1,236 columns.

Note the `dat` column is a suppression annotation and is NOT
what distinguishes the `_nodat` variant, despite the name — the distinction
is purely whether `pct_met_standard` carried a `<`/`>` bound.

### `vitals.sql` — exact reproduction of `vitals.csv`

`vitals.sql` is a direct inlining of the three original queries
(`vitals_org.sql`, `expenditures_by_school.sql`, `s275_school_summary.sql`),
which no longer run because the `scratch` dataset they read and write is now
empty. Everything they did is reproduced as CTEs, in the same order and with
the same semantics.

**It reproduces all 139 columns of `attic/vitals.csv`, in the same order,
over all 1,185 rows.** 135 of them match with 0 disagreements; the other
four are the spend aggregates changed on purpose by the vocational fix
below.

| block | source |
|---|---|
| identity — `type`, `region`, `is_regular`, `ms_assignment_code`, `school`, `ms_assignment` | `safs_domains.d_school` |
| row set, `school_name`, `all_students`, demographics + `pct_*` | `ospi.rc_enrollment` (`ccddd=17001`, `grade='All Grades'`) |
| spend buckets, `comp_amount_*` / `non_comp_amount_*` | `safs_f19x.general_fund_expenditures` (actuals, `has_school`) |
| staffing, salary, experience, per-duty blocks | `safs_s275.assignment` + `report` + `private_assignment` + `report_employee` |

End to end, BigQuery mode reproduces the original sheet (`attic/wide.csv`)
on **all 1,236 columns × 1,185 rows with 0 disagreements**, in the same row
order. It is not *byte*-identical: the pivoted assessment column order
differs, because the original `assessment.csv` was exported in an arbitrary
(unordered) row order that cannot be reproduced. Values are unaffected.

### Fixed: the dropped vocational spend

`expenditures_by_school.sql` computed a `voc` category — programs 31, 34,
38, 39, 45, 46, 47 (Vocational Basic/Federal/Other-Categorical, Middle
School CTE, Skill Center Basic/Federal/Facility-Upgrades) — and then
silently discarded it: its `PIVOT` listed only the nine other categories. So
vocational spend never reached `vitals.csv`, and was missing from
`comp_amount`, `non_comp_amount` and `total_spend`.

`vitals.sql` keeps it, adding four columns — `comp_amount_voc`,
`non_comp_amount_voc`, `total_spend_voc`, `spend_voc_per_pupil` — and
folding it into the totals. **$97.3M is recovered across 205 school-years.**

Of the original 139 columns this changes exactly four, all of them
aggregates that should change: `total_spend` (204 rows), `spend_per_pupil`
(204), `comp_amount` (200) and `non_comp_amount` (138). The other 135 still
match `attic/vitals.csv` exactly, and the ten buckets now reconcile to
`total_spend` to 0.000000.

One behaviour of the original is still preserved: the experience percentiles
use `APPROX_QUANTILES`, an approximate sketch, which on school-years with
exactly 14, 28 or 56 class teachers returns the neighbouring order statistic
rather than the true one.

One thing worth knowing about the data:

- **`other_teacher` = duty 33 + 34.** Since duty 34 (Elementary Specialist)
  was carved out of 31 in 2015-16, `class_teacher_fte` has a structural
  discontinuity at `class_of` 2016 that is not a real staffing change.

### The original queries, for reference

Three files record how `vitals.csv` was actually built. They are kept for
provenance and are **not** used by `bigsheet.py`. None of them can run as-is:
they read/write `scratch.exp_by_school` and `scratch.s275_school_summary`,
and the `scratch` dataset is now empty.

| file | what it built |
|---|---|
| `vitals_org.sql` | the final `vitals.csv` join |
| `expenditures_by_school.sql` | `scratch.exp_by_school` — the spend buckets |
| `s275_school_summary.sql` | `scratch.s275_school_summary` — the staffing blocks |

They corroborate everything `vitals.sql` had reverse-engineered — row set,
`d_school` identity columns, `pct_* = count / NULLIF(all_students, 0)`, the
duty-code groupings (`class_teacher` 31+32, `other_teacher` 33+34,
`asst_principal` 22+24, `aide` 91, `principal` 21+23, `counselor` 42+44,
`librarian` 41), and `fte = SUM(fte_in_assignment)` — and settled two things
guesswork could not:

1. **The spend buckets**, now copied verbatim. The fitted lists were
   *narrower* than the real ones (e.g. `ble` is 64+65, not just 65;
   `title1` is 51+52+53; `spec_ed` is 21–26+29). They agreed on the data at
   hand only because the extra programs have no mass at these schools — but
   they would have misfiled future data.
2. **The percentile**, which was `APPROX_QUANTILES`, explaining the 65-row
   residual as a sketch artifact.

They also show where the 58 uncovered columns come from: `exp_by_school`
split every bucket into compensation (`object_code IN (2,3,4)`) and
non-compensation halves, and `s275_school_summary` built the per-duty salary
blocks from `safs_s275.private_assignment`. Those are reconstructible now —
they simply have not been done, since `bigsheet.py` reads none of them.

### Hard-coded inputs (all under the GCS-synced `data/` tree)

- `data/sps/map/map-score-2017-2024-average-hc.csv`
- `data/sps/map/map-score-2017-2024-average-nonhc.csv`
- `data/sps/building/bex-vi-historic-building-scores.csv`
- `data/sps/building/utilization_condition.csv`
- `data/sps/building/income_by_school.csv`
- `data/sps/s275/building_transitions.csv`
- `data/sps/sqss/sqss.csv`

### Join keys

`school_code` and `class_of` (school year the row's class graduates, used
throughout as the per-cohort year key).
