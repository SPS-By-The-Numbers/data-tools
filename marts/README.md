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
$ venv/bin/python3 -m marts.bigsheet --vitals vitals.csv --assessment assessment.csv -o sheet.csv
```

Runs unchanged as `venv/bin/python3 marts/bigsheet.py ...` too (no
repo-internal imports), but it must be run **from the repo root** — the
hard-coded input paths below are relative.

### CLI inputs

- `--vitals` (required) — CSV with vitals by school. Columns actually read:
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
- `--assessment` (required) — CSV with assessment data. Columns actually read:
  `class_of`, `school_code`, `grade_level`, `test_administration`,
  `test_subject`, `student_group`, `pct_noscore`, `pct_alternative`,
  `pct_met_standard_numeric`, `pct_met_standard_numeric_nodat`.
- `-o` / `--output` (required) — output CSV path.

Recent copies of the `--vitals` and `--assessment` inputs sat at the repo root
(`vitals.csv`, `assessment.csv`) before this reorg; they now live in `attic/`.
Their derivation is recorded nowhere in this repo — Phase 7 (see
`Reorganize.md`) uses these two files as the ground-truth contract when
rewiring `bigsheet.py` to read from BigQuery instead.

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
