# marts

Downstream "data marts" — datasets built by joining multiple pipeline outputs
together, as opposed to `extractors/`, which ingest a single source each.

## `bigsheet.py`

> **FROZEN — historical provenance only (2026-07-25).** `bigsheet` has been
> migrated to the website repo as a BigQuery Cloud Function that builds one SQL
> string and exports DEFLATE AVRO: `sps-by-the-numbers-website/functions/src/bigsheet/`
> (see `BIGSHEET_MIGRATION_PLAN.md` there for the full record). The migration
> was originally proven value-for-value against this script's Seattle output;
> since then the website generator has **intentionally diverged** (clean
> source-prefixed column names, merged spelling-variant columns, SAFE_DIVIDE
> semantics — see `functions/src/bigsheet/NAMING.md` and `COLUMN_MAPPING.csv`
> there). The golden CSV no longer constrains anything. `bigsheet.py`,
> `vitals.sql` and `assessment.sql` are kept only as historical reference;
> deleting them is the owner's call.
>
> The seven static inputs under `data/sps/{map,building,s275,sqss}/` are
> published to BigQuery external tables by `scripts/publish_bigsheet_inputs.sh`
> + `scripts/create_bigsheet_input_tables.sh`. **Whenever those CSVs change,
> re-run both scripts and then bump `BIGSHEET_SQL_VERSION` in the website
> (`functions/src/bigsheet/assemble.ts`)** — the export cache does NOT
> auto-invalidate on CSV content changes (only on pivot-combo changes).

Joins **all the per-school data this repo has** into one wide table: one row
per school per cohort year, ~1,240 columns. Enrollment and demographics,
per-pupil spend by program, S-275 staffing/salary/experience, MAP scores,
building condition and utilization, staffing churn, assessment results and
SQSS — all on the same grain, ready for regression or spreadsheet work.

Inputs come from BigQuery by default, so the sheet is reproducible end to end
and picks up new school years automatically as they land.

### Quick start

```console
$ venv/bin/python3 -m marts.bigsheet -o sheet.csv
```

Run it **from the repo root** — some inputs are read from `data/` by relative
path. Takes a couple of minutes, most of it BigQuery.

Prerequisites:

- `pip install -r requirements.txt` (needs `google-cloud-bigquery` and
  `db-dtypes`; the latter is required by `to_dataframe()`).
- BigQuery access to project `sps-btn-data` via Application Default
  Credentials. If a query fails with an auth error, run
  `gcloud auth application-default login`.
- The `data/sps/...` files listed under [Inputs](#inputs).

### Output

One row per (`school_code`, `class_of`) — `class_of` being the year the
cohort graduates, used throughout the repo as the per-cohort year key. Note
11 rows per-year are district totals, with a null `school_code`.

| column family | what it is |
|---|---|
| identity | `school_code`, `class_of`, `school_name`, `type`, `region`, `is_regular`, `ms_assignment_code` |
| enrollment | `all_students`, 20 demographic counts and their `pct_*` shares |
| spend | `total_spend_*` and `spend_*_per_pupil` for ten program buckets, plus the compensation / non-compensation split (`comp_amount_*`) |
| staffing | headcount, FTE, salary, compensation and experience percentiles per duty group (classroom teacher, other teacher, aide, principal, asst principal, counselor, librarian) |
| indicators | school-type, region and middle-school-assignment dummies (`Elementary`, `r_NW`, `m_Eckstein`, …) for regression convenience |
| derived | `spend_grp_*` roll-ups, `*_fte_per_pupil`, `pct_class_teacher_ge_bachelors`, `log_enrollment`, `at_or_after_2021`, various `*_normalized` |
| MAP | `hc_*` / `nonhc_*` RIT score, std dev and N, pivoted by subject × grade × season |
| building | BEX condition scores, utilization, income by school |
| churn | `bldg_staff_*` — transfers in/out, hires, departures, net churn |
| assessment | `<administration>_<subject>_<group>_<measure>`, pivoted |
| SQSS | attendance, dual credit, ninth-grade-on-track by student group |

**Coverage**: `class_of` 2015–2025 (school years 2014-15 through 2024-25).
Spend exists only from `class_of` 2020 — the source has no per-school actuals
before that. SQSS runs one year behind everything else (through `class_of`
2024). Nothing for 2025-26 exists upstream yet; when it lands in
`ospi.rc_enrollment` it will flow through with no query changes.

### Inputs

`--vitals` and `--assessment` are optional and control where the two main
inputs come from:

| flag | omitted (default) | given a CSV path |
|---|---|---|
| `--vitals` | BigQuery via `vitals.sql` | reads the CSV verbatim |
| `--assessment` | BigQuery via `assessment.sql` | reads the CSV verbatim |

The CSV form is the offline / fallback path and reproduces the historical
behaviour exactly. `--bq-project` (default `sps-btn-data`) affects only the
BigQuery path.

Columns actually consumed from those two inputs:

- vitals — `school_code`, `class_of`, `school_name`, `type`, `region`,
  `is_regular`, `ms_assignment_code`, `all_students`, the nine
  `spend_*_per_pupil` buckets, `class_teacher_exp_50pctile`,
  `num_class_teachers`, `num_class_teachers_{bachelors,masters,doctors}`,
  `class_teacher_fte`, `asst_principal_fte`, `other_teacher_fte`. Everything
  else in the vitals table is passed through to the output untouched.
- assessment — `class_of`, `school_code`, `grade_level`,
  `test_administration`, `test_subject`, `student_group`, `pct_noscore`,
  `pct_alternative`, `pct_met_standard_numeric`,
  `pct_met_standard_numeric_nodat`.

These are read from `data/` by relative path and are not configurable:

- `data/sps/map/map-score-2017-2024-average-{hc,nonhc}.csv`
- `data/sps/building/{bex-vi-historic-building-scores,utilization_condition,income_by_school}.csv`
- `data/sps/s275/building_transitions.csv`
- `data/sps/sqss/sqss.csv`

---

## Provenance of the queries

The `--vitals` and `--assessment` inputs used to be pre-baked CSVs whose
derivation was recorded nowhere. `vitals.sql` and `assessment.sql` replace
them. Both were validated against the last such CSVs, preserved in `attic/`.

### `assessment.sql`

`ospi.rc_assessment`, filtered to `ccddd = 17001` (Seattle) and
`grade_level = 'All Grades'` — those two predicates alone reproduce the old
CSV's row count exactly. `class_of` already exists in the table, so only two
derived columns were needed, both parsed from the `pct_met_standard` string:

| column | rule |
|---|---|
| `pct_met_standard_numeric` | `^[<>]?(\d+(\.\d+)?)%$` → value / 100. Bounded markers (`<10%`, `>90%`) ARE converted, using the bound itself. NULL for `Suppressed: N<10`, `N<10`, `No Students`, `N<10 (Count Protected)`. |
| `pct_met_standard_numeric_nodat` | Same, but bounded markers are ALSO NULL — only exact percentages survive. |

Verified: **0 disagreements across all 92,090 rows**, with no extra or
missing rows. Despite the name, the `dat` column is *not* what distinguishes
the `_nodat` variant — the distinction is purely whether `pct_met_standard`
carried a `<`/`>` bound.

### `vitals.sql`

A direct inlining of the three original queries, which are kept in this
directory for reference and can no longer run (the `scratch` dataset they
read and write is empty):

| file | what it built |
|---|---|
| `vitals_org.sql` | the final `vitals.csv` join |
| `expenditures_by_school.sql` | `scratch.exp_by_school` — the spend buckets |
| `s275_school_summary.sql` | `scratch.s275_school_summary` — the staffing blocks |

Sources:

| block | from |
|---|---|
| row set, `school_name`, `all_students`, demographics | `ospi.rc_enrollment` (`ccddd=17001`, `grade='All Grades'`) |
| `type`, `region`, `is_regular`, `ms_assignment_code`, `school`, `ms_assignment` | `safs_domains.d_school` |
| spend buckets and `comp_amount_*` splits | `safs_f19x.general_fund_expenditures` (actuals, `has_school`) |
| staffing, salary, experience, per-duty blocks | `safs_s275.assignment` + `report` + `private_assignment` + `report_employee` |

It produces all 139 columns of the old `vitals.csv`, in the same order, over
the same 1,185 rows, **plus four new vocational columns**. 134 of the 139
match with 0 disagreements. Five differ deliberately, from the two bug fixes
below.

End to end, BigQuery mode reproduces the historical sheet over 1,185 rows ×
1,236 shared columns, disagreeing only on those fixes' six columns. It is not
*byte*-identical: the pivoted assessment column order differs, because the
original `assessment.csv` was exported in an arbitrary row order that cannot
be reproduced. Values are unaffected.

#### Fix 1 — vocational spend was being dropped

`expenditures_by_school.sql` computed a `voc` category (programs 31, 34, 38,
39, 45, 46, 47 — Vocational Basic/Federal/Other-Categorical, Middle School
CTE, Skill Center Basic/Federal/Facility-Upgrades) and then silently
discarded it: its `PIVOT` listed only the nine other categories. Vocational
spend never reached `vitals.csv` and was missing from `comp_amount`,
`non_comp_amount` and `total_spend`.

`vitals.sql` keeps it — adding `comp_amount_voc`, `non_comp_amount_voc`,
`total_spend_voc` and `spend_voc_per_pupil` — and folds it into the totals.
**$97.3M recovered across 205 school-years.** This changes exactly four of
the original columns, all aggregates that should change: `total_spend` (204
rows), `spend_per_pupil` (204), `comp_amount` (200), `non_comp_amount` (138).
The ten buckets now reconcile to `total_spend` to 0.000000.

#### Fix 2 — experience percentiles were approximate

`s275_school_summary.sql` used
`APPROX_QUANTILES(experience_years, 100)[OFFSET(n)]` — a sketch, not an exact
quantile. (It is verified to be what built the CSV: it reproduces both
percentile columns on 1110/1110 rows.) On school-years with exactly 14, 28 or
56 class teachers it returns the neighbouring order statistic.

`vitals.sql` returns the raw sorted per-person experience values instead, and
`bigsheet.add_experience_percentiles()` takes the exact order statistic in
numpy via `np.percentile(..., method='inverted_cdf')`, inserting the columns
back in their original positions. This corrects **65 of 1110**
`class_teacher_exp_50pctile` values (median ~0.9 yr, max 7.3 yr; the sketch
always picked the higher neighbour). The other three percentile columns were
already exact.

Note BigQuery's `PERCENTILE_DISC` is a third answer again, disagreeing with
the CSV on 200 rows at q=0.8 — which is why the definition lives in Python,
where it is explicit and testable, rather than depending on a SQL dialect.

---

## Gotchas

- **`other_teacher` = duty 33 + 34.** Duty 34 (Elementary Specialist) was
  carved out of 31 in 2015-16, so `class_teacher_fte` has a structural
  discontinuity at `class_of` 2016 that is not a real staffing change.
- **S-275 FTE**: sum `assignment.fte_in_assignment`. The `assignment_fte`
  table's cert/class FTE is a per-employee marker that over-counts ~5×.
- **Salary is per person, not per assignment**, and is not FTE-normalized.
  See `docs/guides/STAFFING_ANALYSIS_GUIDE.md` for the full set of S-275
  traps.
- **BigQuery returns nullable/`Decimal` dtypes**, which break `np.where` on
  `pd.NA`. `bigsheet.to_csv_like_dtypes()` converts them to the numpy dtypes
  `pd.read_csv` would have produced, so both input modes behave identically.
- **Spend excludes anything with no school attribution** (`has_school`), so
  district-level costs — notably Pupil Transportation, $294.9M — never reach
  this grain at all.
