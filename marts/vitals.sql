-- marts/vitals.sql
--
-- Reconstruction of the `--vitals` input consumed by marts/bigsheet.py, from
-- BigQuery (project `sps-btn-data`).  Reverse-engineered from attic/vitals.csv
-- (the pre-baked file whose derivation was recorded nowhere) and validated
-- against it row-for-row.  See the validation notes at the bottom.
--
-- GRAIN: one row per (school_code, class_of).  The row set is exactly
--   ospi.rc_enrollment WHERE ccddd = 17001 AND grade = 'All Grades'
-- which includes 11 "District Total" rows with a NULL school_code (one per
-- year).  attic/vitals.csv has 1185 such rows (class_of 2015..2025); this query
-- reproduces the same set and will grow as newer years land in rc_enrollment.
--
-- WHAT IT COVERS (every column bigsheet.py actually reads):
--   identity   : school_code, class_of, school_name, type, region, is_regular,
--                ms_assignment_code
--   enrollment : all_students
--   spend      : spend_{gen_ed,spec_ed,compensatory,lap,title1,ble,instr_other,
--                district_support,other}_per_pupil  (+ the total_spend_* it
--                divides, kept for auditing)
--   staffing   : class_teacher_exp_50pctile, num_class_teachers,
--                num_class_teachers_{bachelors,masters,doctors},
--                class_teacher_fte, asst_principal_fte, other_teacher_fte
--
--   Also carried through (not read by bigsheet.py, but the old CSV put them in
--   the output sheet): the 20 demographic counts from ospi.rc_enrollment and
--   their pct_* versions (count / all_students).  All 40 match exactly.
--
-- WHAT IT DOES *NOT* COVER:
--   * 58 columns of attic/vitals.csv: the salary / compensation blocks
--     (assignment_salary, c_est_total_compensation, c_est_total_final_salary
--     for each duty group), the principal / counselor / librarian / aide
--     blocks, the comp_amount_*/non_comp_amount_* splits, and fte, fte_per_pupil,
--     grade, school_1.  bigsheet.py reads NONE of them; they were pass-through
--     columns in the CSV, so a sheet built in BigQuery mode is that much
--     narrower.  They were not investigated -- not shown to be unavailable.
--   * NOTHING in the consumed contract is missing.  `region` and
--     `ms_assignment_code`, which looked hand-curated, do in fact live in
--     safs_domains.d_school (sourced from the SPS-BTN spsbtn.xlsx `schools`
--     tab), and match the CSV exactly.
--
-- DELIBERATE DIFFERENCE FROM THE CSV (one column, 5.9% of rows):
--   class_teacher_exp_50pctile differs from attic/vitals.csv on 65 of 1110
--   rows -- exactly the school-years with 14, 28 or 56 class teachers.  The
--   cause is now known: the original (marts/s275_school_summary.sql) used
--       APPROX_QUANTILES(experience_years, 100)[OFFSET(50)]
--   which is an APPROXIMATE sketch, and on those group sizes it lands on the
--   neighbouring order statistic.  APPROX_QUANTILES reproduces the CSV on
--   1110/1110 rows for both p50 and p80, confirming that is what built it.
--   bigsheet.py deliberately computes the EXACT order statistic in numpy
--   instead, so these 65 values are corrected, not wrong.  The two agree
--   everywhere else, including p80 on all 1110 rows.
--
-- PROGRAM->SPEND-BUCKET MAPPING is taken verbatim from the original
-- marts/expenditures_by_school.sql, so it is the real definition.  It
-- reproduces all 9 buckets exactly on every school-year that has spend.
-- The original also computed a 'voc' category and then dropped it: the PIVOT
-- listed only the nine named buckets, so vocational / CTE / skill-center
-- spend never reached the CSV and was excluded from its total_spend.  This
-- query keeps it -- see the spend CTE.
--
-- Spend exists only for class_of >= 2020 in the CSV; that is a source-coverage
-- fact (safs_f19x.general_fund_expenditures has no per-school actuals for
-- Seattle before then), not a filter applied here.

WITH enrollment AS (
  -- Defines the row set, and supplies school_name / all_students and the
  -- demographic counts (bigsheet.py never reads the demographics, but the
  -- old CSV carried them through into the output sheet, so keep them).
  SELECT * EXCEPT (ccddd, grade)
  FROM `{project}.ospi.rc_enrollment`
  WHERE ccddd = 17001
    AND grade = 'All Grades'
),

spend AS (
  -- Per-school general-fund ACTUALS, bucketed by program code.
  --
  -- The program -> bucket mapping is taken VERBATIM from the original
  -- marts/expenditures_by_school.sql (which built scratch.exp_by_school), so
  -- it is the real definition rather than one fitted to the data.  'other' is
  -- the ELSE catch-all, exactly as in the original, which means every program
  -- lands in exactly one bucket and the parts always reconcile to the whole:
  --
  --     total_spend = the nine named buckets + vocational
  --
  -- The one deliberate change: the original PIVOTed only the nine named
  -- buckets and summed total_spend over just those, so the 'voc' category it
  -- had already computed was silently discarded.  Here vocational is kept and
  -- included in total_spend, making total_spend / spend_per_pupil larger than
  -- the old CSV's by $97.3M over the covered years.  Nothing bigsheet.py
  -- computes reads those two columns; the nine buckets it does read are
  -- unchanged and still match the CSV exactly.
  SELECT
    school_code,
    class_of,
    SUM(IF(program_code IN (1, 2, 3, 9, 75),                  amount, NULL)) AS total_spend_gen_ed,
    SUM(IF(program_code IN (21, 22, 23, 24, 25, 26, 29),      amount, NULL)) AS total_spend_spec_ed,
    SUM(IF(program_code IN (54, 56, 57, 58, 59, 61, 62, 67, 68, 69),
                                                              amount, NULL)) AS total_spend_compensatory,
    SUM(IF(program_code IN (55),                              amount, NULL)) AS total_spend_lap,
    SUM(IF(program_code IN (51, 52, 53),                      amount, NULL)) AS total_spend_title1,
    SUM(IF(program_code IN (64, 65),                          amount, NULL)) AS total_spend_ble,
    SUM(IF(program_code IN (79),                              amount, NULL)) AS total_spend_instr_other,
    SUM(IF(program_code IN (97),                              amount, NULL)) AS total_spend_district_support,

    -- Vocational / CTE / Skill Center: 31 Vocational-Basic-State, 34 Middle
    -- School CTE-State, 38 Vocational-Federal, 39 Vocational-Other
    -- Categorical, 45 Skills Center-Basic-State, 46 Skills Center-Federal,
    -- 47 Skills Center-Facility Upgrades.  The original computed this
    -- category and then dropped it on the way out.
    SUM(IF(program_code IN (31, 34, 38, 39, 45, 46, 47),      amount, NULL)) AS total_spend_vocational,

    -- ELSE catch-all, matching the original.  Absorbs everything with no
    -- named bucket -- e.g. 73 Summer School, 89 Other Community Services and
    -- 99 Pupil Transportation.  (Those three never actually reach this grain:
    -- they are booked to school_code/class_of pairs absent from
    -- ospi.rc_enrollment.  99 Pupil Transportation alone is $294.9M.)
    SUM(IF(program_code NOT IN (1, 2, 3, 9, 75, 79, 97, 54, 56, 57, 58, 59,
                                61, 62, 67, 68, 69, 64, 65, 55, 21, 22, 23,
                                24, 25, 26, 29, 51, 52, 53, 31, 34, 38, 39,
                                45, 46, 47),
           amount, NULL))                                                    AS total_spend_other,

    SUM(amount) AS total_spend
  FROM `{project}.safs_f19x.general_fund_expenditures`
  WHERE ccddd = 17001
    AND data_type = 'actuals'
    AND has_school = TRUE          -- both filters are from the original
    AND school_code IS NOT NULL
  GROUP BY school_code, class_of
),

class_teachers AS (
  -- One row per (school-year, school, person) for classroom teachers.
  -- Classroom teacher == duty_root 31 (Elementary Homeroom) + 32 (Secondary).
  -- NB the S-275 FTE gotcha: FTE must come from SUM(assignment.fte_in_assignment),
  -- never from assignment_fte.  Headcount, degrees and experience are per
  -- PERSON, so the person set is de-duplicated first and joined to
  -- report_employee afterwards.
  SELECT DISTINCT
    r.class_of,
    a.school_code,
    a.report_employee_id
  FROM `{project}.safs_s275.assignment` a
  JOIN `{project}.safs_s275.report` r USING (report_id)
  WHERE r.ccddd = 17001
    AND r.report_type = 'final'
    AND a.duty_root_code IN (31, 32)
),

class_teacher_stats AS (
  -- Percentiles are deliberately NOT computed here.  BigQuery's
  -- PERCENTILE_DISC follows a different convention from numpy's and
  -- disagreed with the source CSV on 200 rows at q=0.8.  Instead this
  -- returns the raw per-teacher experience values as a sorted array and
  -- bigsheet.py's add_experience_percentiles() takes the order statistic in
  -- numpy, where the semantics are explicit and testable.
  SELECT
    ct.class_of,
    ct.school_code,
    COUNT(*)                            AS num_class_teachers,
    COUNTIF(re.highest_degree = 'B')    AS num_class_teachers_bachelors,
    COUNTIF(re.highest_degree = 'M')    AS num_class_teachers_masters,
    COUNTIF(re.highest_degree = 'D')    AS num_class_teachers_doctors,
    ARRAY_AGG(re.experience_years IGNORE NULLS
              ORDER BY re.experience_years) AS class_teacher_exp_years
  FROM class_teachers ct
  JOIN `{project}.safs_s275.report_employee` re USING (report_employee_id)
  GROUP BY ct.class_of, ct.school_code
),

fte AS (
  -- FTE by duty-group.  Verified exactly (max |diff| = 0.000000 over 1110
  -- school-years) against attic/vitals.csv:
  --   class_teacher  = duty 31, 32
  --   other_teacher  = duty 33 (Other Teacher), 34 (Elementary Specialist)
  --   asst_principal = duty 22 (Elem Vice Principal), 24 (Secondary Vice Principal)
  -- (also, unused by bigsheet but confirmed: aide = 91, principal = 21+23,
  --  counselor = 42+44, librarian = 41, and `fte` = every duty at the school)
  SELECT
    r.class_of,
    a.school_code,
    SUM(IF(a.duty_root_code IN (31, 32), a.fte_in_assignment, NULL)) AS class_teacher_fte,
    SUM(IF(a.duty_root_code IN (33, 34), a.fte_in_assignment, NULL)) AS other_teacher_fte,
    SUM(IF(a.duty_root_code IN (22, 24), a.fte_in_assignment, NULL)) AS asst_principal_fte
  FROM `{project}.safs_s275.assignment` a
  JOIN `{project}.safs_s275.report` r USING (report_id)
  WHERE r.ccddd = 17001
    AND r.report_type = 'final'
  GROUP BY r.class_of, a.school_code
)

SELECT
  e.class_of,
  e.school_code,

  -- identity (safs_domains.d_school, sourced from the SPS-BTN spsbtn.xlsx
  -- `schools` tab; matches attic/vitals.csv on 1174/1174 school rows)
  s.type,
  s.is_regular,
  s.region,
  s.school,
  s.ms_assignment_code,
  s.ms_assignment,

  -- enrollment (ospi.rc_enrollment; exact match)
  e.school_name,
  e.school_year,
  e.all_students,

  -- demographic counts, and the pct_* versions the CSV carried (count over
  -- all_students).  Pass-through only; bigsheet.py reads none of these.
  e.military_parent,
  e.migrant,
  e.low_income,
  e.homeless,
  e.foster_care,
  e.mobile,
  e.section_504,
  e.highly_capable,
  e.english_language_learners,
  e.students_with_disabilities,
  e.female,
  e.male,
  e.gender_x,
  e.white,
  e.black_african_american,
  e.native_hawaiian_other_pacific,
  e.hispanic_latino_of_any_race,
  e.american_indian_alaskan_native,
  e.asian,
  e.two_or_more_races,
  SAFE_DIVIDE(e.military_parent, e.all_students) AS pct_military_parent,
  SAFE_DIVIDE(e.migrant, e.all_students) AS pct_migrant,
  SAFE_DIVIDE(e.low_income, e.all_students) AS pct_low_income,
  SAFE_DIVIDE(e.homeless, e.all_students) AS pct_homeless,
  SAFE_DIVIDE(e.foster_care, e.all_students) AS pct_foster_care,
  SAFE_DIVIDE(e.mobile, e.all_students) AS pct_mobile,
  SAFE_DIVIDE(e.section_504, e.all_students) AS pct_section_504,
  SAFE_DIVIDE(e.highly_capable, e.all_students) AS pct_highly_capable,
  SAFE_DIVIDE(e.english_language_learners, e.all_students)
    AS pct_english_language_learners,
  SAFE_DIVIDE(e.students_with_disabilities, e.all_students)
    AS pct_students_with_disabilities,
  SAFE_DIVIDE(e.female, e.all_students) AS pct_female,
  SAFE_DIVIDE(e.male, e.all_students) AS pct_male,
  SAFE_DIVIDE(e.gender_x, e.all_students) AS pct_gender_x,
  SAFE_DIVIDE(e.white, e.all_students) AS pct_white,
  SAFE_DIVIDE(e.black_african_american, e.all_students)
    AS pct_black_african_american,
  SAFE_DIVIDE(e.native_hawaiian_other_pacific, e.all_students)
    AS pct_native_hawaiian_other_pacific,
  SAFE_DIVIDE(e.hispanic_latino_of_any_race, e.all_students)
    AS pct_hispanic_latino_of_any_race,
  SAFE_DIVIDE(e.american_indian_alaskan_native, e.all_students)
    AS pct_american_indian_alaskan_native,
  SAFE_DIVIDE(e.asian, e.all_students) AS pct_asian,
  SAFE_DIVIDE(e.two_or_more_races, e.all_students) AS pct_two_or_more_races,

  -- spend
  sp.total_spend,
  sp.total_spend_gen_ed,
  sp.total_spend_spec_ed,
  sp.total_spend_compensatory,
  sp.total_spend_lap,
  sp.total_spend_title1,
  sp.total_spend_ble,
  sp.total_spend_instr_other,
  sp.total_spend_district_support,
  sp.total_spend_other,
  sp.total_spend_vocational,
  SAFE_DIVIDE(sp.total_spend,                   e.all_students) AS spend_per_pupil,
  SAFE_DIVIDE(sp.total_spend_gen_ed,            e.all_students) AS spend_gen_ed_per_pupil,
  SAFE_DIVIDE(sp.total_spend_spec_ed,           e.all_students) AS spend_spec_ed_per_pupil,
  SAFE_DIVIDE(sp.total_spend_compensatory,      e.all_students) AS spend_compensatory_per_pupil,
  SAFE_DIVIDE(sp.total_spend_lap,               e.all_students) AS spend_lap_per_pupil,
  SAFE_DIVIDE(sp.total_spend_title1,            e.all_students) AS spend_title1_per_pupil,
  SAFE_DIVIDE(sp.total_spend_ble,               e.all_students) AS spend_ble_per_pupil,
  SAFE_DIVIDE(sp.total_spend_instr_other,       e.all_students) AS spend_instr_other_per_pupil,
  SAFE_DIVIDE(sp.total_spend_district_support,  e.all_students) AS spend_district_support_per_pupil,
  SAFE_DIVIDE(sp.total_spend_other,             e.all_students) AS spend_other_per_pupil,
  SAFE_DIVIDE(sp.total_spend_vocational,        e.all_students) AS spend_vocational_per_pupil,

  -- staffing
  -- Raw sorted per-teacher experience; bigsheet.py turns this into
  -- class_teacher_exp_{50pctile,80pctile,avg} in numpy.
  cts.class_teacher_exp_years,
  cts.num_class_teachers,
  cts.num_class_teachers_bachelors,
  cts.num_class_teachers_masters,
  cts.num_class_teachers_doctors,
  f.class_teacher_fte,
  f.other_teacher_fte,
  f.asst_principal_fte

FROM enrollment e
LEFT JOIN `{project}.safs_domains.d_school` s
  ON s.school_code = e.school_code AND s.ccddd = 17001
LEFT JOIN spend sp
  ON sp.school_code = e.school_code AND sp.class_of = e.class_of
LEFT JOIN class_teacher_stats cts
  ON cts.school_code = e.school_code AND cts.class_of = e.class_of
LEFT JOIN fte f
  ON f.school_code = e.school_code AND f.class_of = e.class_of
ORDER BY e.class_of, e.school_code
