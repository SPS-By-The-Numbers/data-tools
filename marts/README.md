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
null mismatches, 0 value mismatches). The 23rd,
`class_teacher_exp_50pctile`, differs on 65 of 1110 rows *on purpose* — see
below.

**Percentiles are computed in numpy, not SQL.** `vitals.sql` returns the raw
sorted per-teacher experience values as an array and
`bigsheet.add_experience_percentiles()` takes the order statistic with
`np.percentile(..., method='inverted_cdf')`.

The original (`s275_school_summary.sql`) used
`APPROX_QUANTILES(experience_years, 100)[OFFSET(50)]` — an *approximate*
sketch. That is verified to be what built the CSV: it reproduces it on
1110/1110 rows for both p50 and p80. On school-years with exactly 14, 28 or
56 class teachers the sketch lands on the neighbouring order statistic,
which is where all 65 differences come from. The numpy value is the exact
order statistic, so those 65 are **corrected, not wrong**. The two agree
everywhere else, including p80 on all 1110 rows.

(BigQuery's `PERCENTILE_DISC` is a third answer again — it disagreed with the
CSV on 200 rows at q=0.8 — which is why the definition lives in Python where
it is explicit and testable rather than depending on a SQL dialect's
convention.)

End to end, BigQuery mode reproduces CSV mode on **1,176 shared columns ×
1,174 shared rows**, disagreeing only on that one column (plus its derived
`class_teacher_exp_50pctile_normalized`) and on `total_spend` /
`spend_per_pupil`, which changed deliberately — see below.

### Spend buckets: `total_spend` now includes vocational

The program→bucket mapping is taken **verbatim from
`expenditures_by_school.sql`**, so it is the real definition rather than one
fitted to the data. `other` is the `ELSE` catch-all, so every program lands
in exactly one bucket.

The original computed a `voc` category and then dropped it — its `PIVOT`
listed only the nine named buckets, so vocational / CTE / skill-center spend
never reached the CSV and was excluded from its `total_spend`. `vitals.sql`
keeps it:

- `total_spend_vocational` / `spend_vocational_per_pupil` — programs 31, 34,
  38, 39, 45, 46, 47.
- `total_spend` is `SUM(amount)` over all programs, which by construction
  equals the nine buckets + vocational (verified to 0.000000).

This makes `total_spend` **$97.3M larger** than the old CSV's over the
covered years, differing on 204 of 643 school-years. The nine buckets —
the ones bigsheet actually reads — still match the CSV exactly.

Worth knowing: **99 Pupil Transportation ($294.9M)** falls in the `other`
`ELSE` bucket by this mapping, but never actually reaches this grain — it,
along with 73 Summer School and 89 Other Community Services, is booked to
`school_code`/`class_of` pairs absent from `ospi.rc_enrollment`.

**BigQuery mode yields a narrower sheet: 1,178 columns vs 1,236.** The 58
absent columns are vitals pass-through columns bigsheet never reads — the
salary/compensation blocks, the principal/counselor/librarian/aide blocks,
the `comp_amount_*`/`non_comp_amount_*` splits, and `fte`, `fte_per_pupil`,
`grade`, `school_1`. They were not investigated, not shown to be unavailable.

One more thing worth knowing about the data:

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
