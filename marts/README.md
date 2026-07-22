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

### `vitals.sql` — reconstructed; 22 of 23 contract columns exact

Row set is `ospi.rc_enrollment` at `ccddd = 17001, grade = 'All Grades'` —
1,185 rows, exactly the CSV's row set (including 11 district-total rows with
NULL `school_code`), no extra and none missing. Sources:

| group | source |
|---|---|
| `school_name`, `all_students`, demographics | `ospi.rc_enrollment` |
| `type`, `region`, `is_regular`, `ms_assignment_code` | `safs_domains.d_school` |
| `spend_*_per_pupil` | `safs_f19x.general_fund_expenditures` (actuals), bucketed by `program_code`, ÷ `all_students` |
| staffing counts / FTE / experience | `safs_s275.assignment` + `report_employee` |

**22 of the 23 columns bigsheet reads match `attic/vitals.csv` exactly** (0
null mismatches, 0 value mismatches). The exception is
`class_teacher_exp_50pctile` at 1045/1110 (94.1%) — see the SQL header; the
65 deviations are exactly the school-years with 14, 28 or 56 class teachers,
where the source CSV took the next-higher order statistic. That is an
artifact of whatever tool built the CSV, not a defect here: the same index
formula reproduces `class_teacher_exp_80pctile` on 1110/1110 and
`class_teacher_exp_avg` on 1110/1110.

End to end, BigQuery mode reproduces CSV mode on **1,176 shared columns ×
1,174 shared rows with only that one column disagreeing** (plus its derived
`class_teacher_exp_50pctile_normalized`).

**BigQuery mode yields a narrower sheet: 1,178 columns vs 1,236.** The 58
absent columns are vitals pass-through columns bigsheet never reads — the
salary/compensation blocks, the principal/counselor/librarian/aide blocks,
the `comp_amount_*`/`non_comp_amount_*` splits, and `fte`, `fte_per_pupil`,
`grade`, `school_1`. They were not investigated, not shown to be unavailable.

Two things worth knowing about the data:

- **`total_spend` silently drops vocational/CTE/skill-center spend.** Programs
  31, 34, 38 and 45 map to no bucket — $83.1M of program 31 alone. Any
  "total per-pupil spend" from vitals understates high schools materially.
  This is faithful to the original CSV, not a new bug.
- **`other_teacher` = duty 33 + 34.** Since duty 34 (Elementary Specialist)
  was carved out of 31 in 2015-16, `class_teacher_fte` has a structural
  discontinuity at `class_of` 2016 that is not a real staffing change.

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
