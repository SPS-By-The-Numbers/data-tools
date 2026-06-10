# Seattle Report Card intermediates (enrollment + chronic absenteeism)

Seattle-only (ccddd 17001) slices of two OSPI Report Card sources, produced by
`analysis/montecarlo/rc_seattle.py`. Both upstream sources are gitignored and
local-only, so **these CSVs are checked in**. Regenerate with:

    python3 -m analysis.montecarlo.rc_seattle --build

Use the loaders (`rc.load_enrollment()`, `rc.load_attendance_all_students()`,
`rc.load_attendance_by_group()`) rather than reading by hand.

## Files

| File | Rows | What |
|---|---|---|
| `enrollment.csv` | 8,408 | OSPI Report Card enrollment per school × grade × year (2014-15..2024-25) with demographic counts: `all_students`, `low_income`, `homeless`, `foster_care`, `section_504`, `highly_capable`, `english_language_learners`, `students_with_disabilities`, gender, race. `is_district_total` flags the rollup rows (blank `school_code`). |
| `attendance_all_students.csv` | 7,316 | Chronic absenteeism for the **AllStudents** group, across all grade bands, per school × year (2014-2015..2023-2024). |
| `attendance_by_group.csv` | 27,773 | Chronic absenteeism at **school level** (`grade_level == "All Grades"`) for **every subgroup** (low_income, swd, homeless, foster, english_learner, race_ethnicity, gender, …). |

### Attendance columns
Derived from OSPI's "Regular Attendance" SQSS measure (regularly attending =
absent <10% of enrolled days):
- `n_students` (denominator), `n_regular` (numerator)
- `regular_attendance_rate` = n_regular / n_students
- **`chronic_absent_rate`** = 1 − regular_attendance_rate  ← the signal
- `chronic_absent_count` = n_students − n_regular
- `suppressed` (bool), `dat` (raw annotation)
- `year` = fall start year (int), normalized across sources

## Join keys — the three-way link is clean
- **`school_code`** (4-digit OSPI building code) joins enrollment ↔ attendance
  (113/114 overlap) **and** matches `parse_shapes.load_locations().school_code`
  **exactly (98/98)**. So geography ↔ enrollment ↔ absenteeism need no fuzzy
  matching. STARS is the only source still keyed by messy name (`destination_name`).
- **`year`** (int fall start) normalizes the three school-year string formats:
  enrollment `2014-15`, SQSS `2014-2015`, STARS `2017-2018`.

## Known quirks
- The SQSS avro's `percent` column is unpopulated (always 0); rates are computed
  from numerator/denominator.
- Suppression is keyed off whether a rate is computable, NOT the `dat` string —
  OSPI changed `dat` to "Top/Bottom Range: …"/blank in 2022-23+ on rows that
  still carry real counts, so a dat-based flag would wrongly drop recent years.
- **Chronic-absenteeism trend:** ~12-13% pre-COVID → **23-25% in 2021-22..2023-24**
  (documented post-COVID spike). 2019-2020 reads an artificially low 8.3% (year
  cut short by COVID March 2020; attendance accounting changed).
