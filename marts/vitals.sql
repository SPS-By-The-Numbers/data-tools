-- marts/vitals.sql
--
-- The `--vitals` input consumed by marts/bigsheet.py, built from BigQuery.
--
-- It reproduces the pre-baked vitals.csv (preserved at attic/vitals.csv)
-- column for column, with two bugs fixed -- see below.  It is a direct
-- inlining of the three original queries, kept alongside it for reference:
--
--   vitals_org.sql               -- the final join
--   expenditures_by_school.sql   -- built scratch.exp_by_school
--   s275_school_summary.sql      -- built scratch.s275_school_summary
--
-- Those originals no longer run: the `scratch` dataset they read and write is
-- empty.  Everything they did is reproduced here as CTEs, in the same order
-- and with the same semantics, so the output matches the CSV column for
-- column, with two deliberate exceptions:
--
--   1. FIXED: vocational spend.  The original computed a `voc` category
--      (programs 31, 34, 38, 39, 45, 46, 47) and then DROPPED it -- its
--      PIVOT listed only the nine other categories -- so voc never reached
--      vitals.csv and was missing from comp_amount / non_comp_amount and
--      hence from total_spend.  It is kept here, adding comp_amount_voc,
--      non_comp_amount_voc, total_spend_voc and spend_voc_per_pupil, and
--      making comp_amount / non_comp_amount / total_spend / spend_per_pupil
--      larger than the CSV's by $97.3M over the covered years.
--   2. FIXED: the experience percentiles.  The original used
--      APPROX_QUANTILES, a sketch, which on school-years with exactly 14,
--      28 or 56 class teachers returns the neighbouring order statistic.
--      This query returns the raw sorted values and bigsheet.py takes the
--      exact order statistic in numpy, correcting 65 of 1110 rows.
--
-- GRAIN: one row per (school_code, class_of), from
--   ospi.rc_enrollment WHERE ccddd = 17001 AND grade = 'All Grades',
-- including 11 "District Total" rows with a NULL school_code (one per year).
-- 1185 rows for class_of 2015..2025; grows as newer years land.

WITH demographics_by_school AS (
  -- vitals_org.sql: DemographicsBySchool
  SELECT
    t.*,

    -- Living situation
    t.military_parent / NULLIF(t.all_students, 0) pct_military_parent,
    t.migrant / NULLIF(t.all_students, 0) pct_migrant,
    t.low_income / NULLIF(t.all_students, 0) pct_low_income,
    t.homeless / NULLIF(t.all_students, 0) pct_homeless,
    t.foster_care / NULLIF(t.all_students, 0) pct_foster_care,
    t.mobile / NULLIF(t.all_students, 0) pct_mobile,
    t.section_504 / NULLIF(t.all_students, 0) pct_section_504,

    -- Learning type
    t.highly_capable / NULLIF(t.all_students, 0) pct_highly_capable,
    t.english_language_learners / NULLIF(t.all_students, 0) pct_english_language_learners,
    t.students_with_disabilities / NULLIF(t.all_students, 0) pct_students_with_disabilities,

    -- Gender
    t.female / NULLIF(t.all_students, 0) pct_female,
    t.male / NULLIF(t.all_students, 0) pct_male,
    t.gender_x / NULLIF(t.all_students, 0) pct_gender_x,

    -- Race
    t.white / NULLIF(t.all_students, 0) pct_white,
    t.black_african_american / NULLIF(t.all_students, 0) pct_black_african_american,
    t.native_hawaiian_other_pacific / NULLIF(t.all_students, 0) pct_native_hawaiian_other_pacific,
    t.american_indian_alaskan_native / NULLIF(t.all_students, 0) pct_american_indian_alaskan_native,
    t.hispanic_latino_of_any_race / NULLIF(t.all_students, 0) pct_hispanic_latino_of_any_race,
    t.asian / NULLIF(t.all_students, 0) pct_asian,
    t.two_or_more_races / NULLIF(t.all_students, 0) pct_two_or_more_races,
  FROM `{project}.ospi.rc_enrollment` t
  WHERE ccddd = 17001
    AND grade = 'All Grades'
),

-- ============================ scratch.exp_by_school ========================
-- expenditures_by_school.sql, inlined.

exp_simplified AS (
  SELECT
    class_of,
    school_code,
    school,
    object_code,
    amount,
    CASE
      WHEN program_code in (1, 2, 3, 9, 75) THEN "gen_ed"
      WHEN program_code in (79) THEN "instr_other"
      WHEN program_code in (97) THEN "district_support"
      WHEN program_code in (54, 56, 57, 58, 59, 61, 62, 67, 68, 69) THEN "compensatory"
      WHEN program_code in (64, 65) THEN "ble"
      WHEN program_code in (55) THEN "lap"
      WHEN program_code in (21, 22, 23, 24, 25, 26, 29) THEN "spec_ed"
      WHEN program_code in (51, 52, 53) THEN "title1"
      WHEN program_code in (31, 34, 38, 39, 45, 46, 47) THEN "voc"
      ELSE "other"
    END prog_category
  FROM `{project}.safs_f19x.general_fund_expenditures`
  WHERE ccddd = 17001
    AND data_type = "actuals"
    AND has_school = TRUE
    AND school_code IS NOT NULL
),

exp_pivoted AS (
  -- Equivalent to the original's ByProgCategory + PIVOT.  Within a category
  -- that has rows, compensation is object_code 2/3/4 and everything else is
  -- non-compensation, each defaulting to 0; a category with no rows at all
  -- stays NULL, which is what the PIVOT produced.
  --
  -- NOTE: unlike the original, 'voc' IS included -- see the file header.
  SELECT
    class_of,
    school_code,
    school,
    SUM(IF(prog_category = "gen_ed", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_gen_ed,
    SUM(IF(prog_category = "gen_ed", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_gen_ed,
    SUM(IF(prog_category = "spec_ed", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_spec_ed,
    SUM(IF(prog_category = "spec_ed", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_spec_ed,
    SUM(IF(prog_category = "compensatory", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_compensatory,
    SUM(IF(prog_category = "compensatory", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_compensatory,
    SUM(IF(prog_category = "lap", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_lap,
    SUM(IF(prog_category = "lap", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_lap,
    SUM(IF(prog_category = "title1", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_title1,
    SUM(IF(prog_category = "title1", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_title1,
    SUM(IF(prog_category = "ble", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_ble,
    SUM(IF(prog_category = "ble", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_ble,
    SUM(IF(prog_category = "instr_other", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_instr_other,
    SUM(IF(prog_category = "instr_other", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_instr_other,
    SUM(IF(prog_category = "district_support", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_district_support,
    SUM(IF(prog_category = "district_support", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_district_support,
    SUM(IF(prog_category = "other", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_other,
    SUM(IF(prog_category = "other", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_other,

    -- BUG FIX vs the original.  expenditures_by_school.sql computed a 'voc'
    -- category (programs 31, 34, 38, 39, 45, 46, 47 -- Vocational Basic /
    -- Federal / Other-Categorical, Middle School CTE, and Skill Center
    -- Basic / Federal / Facility-Upgrades) and then silently discarded it,
    -- because its PIVOT listed only the nine categories above.  Vocational
    -- spend therefore never reached vitals.csv and was missing from
    -- comp_amount, non_comp_amount and total_spend.  It is kept here.
    SUM(IF(prog_category = "voc", IF(object_code IN (2,3,4), amount, 0), NULL)) comp_amount_voc,
    SUM(IF(prog_category = "voc", IF(object_code IN (2,3,4), 0, amount), NULL)) non_comp_amount_voc
  FROM exp_simplified
  GROUP BY class_of, school_code, school
),

exp_by_school AS (
  SELECT
    *,
    (COALESCE(comp_amount_gen_ed, 0) +
     COALESCE(comp_amount_spec_ed, 0) +
     COALESCE(comp_amount_compensatory, 0) +
     COALESCE(comp_amount_lap, 0) +
     COALESCE(comp_amount_title1, 0) +
     COALESCE(comp_amount_ble, 0) +
     COALESCE(comp_amount_instr_other, 0) +
     COALESCE(comp_amount_district_support, 0) +
     COALESCE(comp_amount_other, 0) +
     COALESCE(comp_amount_voc, 0)
    ) comp_amount,
    (COALESCE(non_comp_amount_gen_ed, 0) +
     COALESCE(non_comp_amount_spec_ed, 0) +
     COALESCE(non_comp_amount_compensatory, 0) +
     COALESCE(non_comp_amount_lap, 0) +
     COALESCE(non_comp_amount_title1, 0) +
     COALESCE(non_comp_amount_ble, 0) +
     COALESCE(non_comp_amount_instr_other, 0) +
     COALESCE(non_comp_amount_district_support, 0) +
     COALESCE(non_comp_amount_other, 0) +
     COALESCE(non_comp_amount_voc, 0)
    ) non_comp_amount
  FROM exp_pivoted
),

-- ======================= scratch.s275_school_summary =======================
-- s275_school_summary.sql, inlined.

duty_summary AS (
  SELECT
    r.class_of,
    a.school_code,
    a.duty_root_code,
    a.duty_suffix_code,
    sum(pa.assignment_salary) assignment_salary,
    sum(a.fte_in_assignment) fte,
    sum(pa.c_est_total_compensation) c_est_total_compensation,
    sum(pa.c_est_total_final_salary) c_est_total_final_salary
  FROM `{project}.safs_s275.assignment` a
  JOIN `{project}.safs_s275.report` r ON (r.report_id = a.report_id)
  JOIN `{project}.safs_s275.private_assignment` pa ON (pa.assignment_id = a.assignment_id)
  WHERE r.ccddd = 17001
  GROUP BY r.class_of, a.school_code, a.duty_root_code, a.duty_suffix_code
),

distinct_teachers AS (
  SELECT DISTINCT r.class_of, a.school_code, a.report_employee_id
  FROM `{project}.safs_s275.assignment` a
  JOIN `{project}.safs_s275.report` r ON (r.report_id = a.report_id)
  WHERE r.ccddd = 17001
    AND a.duty_root_code in (31, 32)
),

classroom_teacher_stats AS (
  SELECT
    t.class_of,
    t.school_code,
    -- The original used APPROX_QUANTILES(experience_years, 100)[OFFSET(n)],
    -- a sketch, which returns the neighbouring order statistic on some group
    -- sizes.  Return the raw sorted values instead; bigsheet.py takes the
    -- exact order statistic in numpy and replaces this column with
    -- class_teacher_exp_50pctile / class_teacher_exp_80pctile in place.
    ARRAY_AGG(re.experience_years IGNORE NULLS
              ORDER BY re.experience_years) AS class_teacher_exp_years,
    AVG(re.experience_years) class_teacher_exp_avg,
    count(t.report_employee_id) num_class_teachers,
    SUM(CASE WHEN re.highest_degree = "B" THEN 1 ELSE 0 END) num_class_teachers_bachelors,
    SUM(CASE WHEN re.highest_degree = "M" THEN 1 ELSE 0 END) num_class_teachers_masters,
    SUM(CASE WHEN re.highest_degree = "D" THEN 1 ELSE 0 END) num_class_teachers_doctors
  FROM distinct_teachers t
  LEFT JOIN `{project}.safs_s275.report_employee` re
    ON (re.report_employee_id = t.report_employee_id)
  GROUP BY t.class_of, t.school_code
),

class_teacher AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) class_teacher_assignment_salary,
    sum(t.fte) class_teacher_fte,
    sum(t.c_est_total_compensation) class_teacher_c_est_total_compensation,
    sum(t.c_est_total_final_salary) class_teacher_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (31, 32)
  GROUP BY t.class_of, t.school_code
),

aides AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) aide_assignment_salary,
    sum(t.fte) aide_fte,
    sum(t.c_est_total_compensation) aide_c_est_total_compensation,
    sum(t.c_est_total_final_salary) aide_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (91)
  GROUP BY t.class_of, t.school_code
),

other_teacher AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) other_teacher_assignment_salary,
    sum(t.fte) other_teacher_fte,
    sum(t.c_est_total_compensation) other_teacher_c_est_total_compensation,
    sum(t.c_est_total_final_salary) other_teacher_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (33, 34)
  GROUP BY t.class_of, t.school_code
),

principal AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) principal_assignment_salary,
    sum(t.c_est_total_compensation) principal_c_est_total_compensation,
    sum(t.c_est_total_final_salary) principal_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (21, 23)
  GROUP BY t.class_of, t.school_code
),

distinct_principals AS (
  SELECT DISTINCT r.class_of, a.school_code, a.report_employee_id
  FROM `{project}.safs_s275.assignment` a
  JOIN `{project}.safs_s275.report` r ON (r.report_id = a.report_id)
  WHERE r.ccddd = 17001
    AND a.duty_root_code in (21, 23)
),

principal_stats AS (
  SELECT
    t.class_of,
    t.school_code,
    -- Same as class_teacher_exp_years above: raw sorted values, turned into
    -- principal_exp_50pctile / principal_exp_80pctile in numpy.
    ARRAY_AGG(re.experience_years IGNORE NULLS
              ORDER BY re.experience_years) AS principal_exp_years,
    AVG(re.experience_years) principal_exp_avg,
    count(t.report_employee_id) num_principal,
    SUM(CASE WHEN re.highest_degree = "B" THEN 1 ELSE 0 END) num_principal_bachelors,
    SUM(CASE WHEN re.highest_degree = "M" THEN 1 ELSE 0 END) num_principal_masters,
    SUM(CASE WHEN re.highest_degree = "D" THEN 1 ELSE 0 END) num_principal_doctors
  FROM distinct_principals t
  LEFT JOIN `{project}.safs_s275.report_employee` re
    ON (re.report_employee_id = t.report_employee_id)
  GROUP BY t.class_of, t.school_code
),

assistant_principal AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) asst_principal_assignment_salary,
    sum(t.fte) asst_principal_fte,
    sum(t.c_est_total_compensation) asst_principal_c_est_total_compensation,
    sum(t.c_est_total_final_salary) asst_principal_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (22, 24)
  GROUP BY t.class_of, t.school_code
),

counselor AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) counselor_assignment_salary,
    sum(t.fte) counselor_fte,
    sum(t.c_est_total_compensation) counselor_c_est_total_compensation,
    sum(t.c_est_total_final_salary) counselor_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (42, 44)
  GROUP BY t.class_of, t.school_code
),

librarian AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) librarian_assignment_salary,
    sum(t.fte) librarian_fte,
    sum(t.c_est_total_compensation) librarian_c_est_total_compensation,
    sum(t.c_est_total_final_salary) librarian_c_est_total_final_salary
  FROM duty_summary t
  WHERE t.duty_root_code in (41)
  GROUP BY t.class_of, t.school_code
),

all_roles AS (
  SELECT
    t.class_of, t.school_code,
    sum(t.assignment_salary) assignment_salary,
    sum(t.fte) fte,
    sum(t.c_est_total_compensation) c_est_total_compensation,
    sum(t.c_est_total_final_salary) c_est_total_final_salary
  FROM duty_summary t
  GROUP BY t.class_of, t.school_code
),

s275_school_summary AS (
  SELECT
    t.*,
    c.* EXCEPT (class_of, school_code),
    dts.* EXCEPT (class_of, school_code),
    a.* EXCEPT (class_of, school_code),
    o.* EXCEPT (class_of, school_code),
    p.* EXCEPT (class_of, school_code),
    ps.* EXCEPT (class_of, school_code),
    ap.* EXCEPT (class_of, school_code),
    co.* EXCEPT (class_of, school_code),
    l.* EXCEPT (class_of, school_code)
  FROM all_roles t
  LEFT OUTER JOIN class_teacher c ON (t.class_of = c.class_of AND t.school_code = c.school_code)
  LEFT OUTER JOIN aides a ON (t.class_of = a.class_of AND t.school_code = a.school_code)
  LEFT OUTER JOIN other_teacher o ON (t.class_of = o.class_of AND t.school_code = o.school_code)
  LEFT OUTER JOIN principal p ON (t.class_of = p.class_of AND t.school_code = p.school_code)
  LEFT OUTER JOIN assistant_principal ap ON (t.class_of = ap.class_of AND t.school_code = ap.school_code)
  LEFT OUTER JOIN counselor co ON (t.class_of = co.class_of AND t.school_code = co.school_code)
  LEFT OUTER JOIN librarian l ON (t.class_of = l.class_of AND t.school_code = l.school_code)
  LEFT OUTER JOIN classroom_teacher_stats dts ON (dts.class_of = t.class_of AND dts.school_code = t.school_code)
  LEFT OUTER JOIN principal_stats ps ON (ps.class_of = t.class_of AND ps.school_code = t.school_code)
)

-- ================================ vitals_org ===============================

SELECT
  t.class_of,
  t.school_code,
  ds.type,
  ds.is_regular,
  ds.region,
  ds.school,
  ds.ms_assignment_code,
  ds.ms_assignment,

  (e.comp_amount + e.non_comp_amount) total_spend,
  (e.comp_amount_gen_ed + e.non_comp_amount_gen_ed) total_spend_gen_ed,
  (e.comp_amount_spec_ed + e.non_comp_amount_spec_ed) total_spend_spec_ed,
  (e.comp_amount_compensatory + e.non_comp_amount_compensatory) total_spend_compensatory,
  (e.comp_amount_lap + e.non_comp_amount_lap) total_spend_lap,
  (e.comp_amount_title1 + e.non_comp_amount_title1) total_spend_title1,
  (e.comp_amount_ble + e.non_comp_amount_ble) total_spend_ble,
  (e.comp_amount_instr_other + e.non_comp_amount_instr_other) total_spend_instr_other,
  (e.comp_amount_district_support + e.non_comp_amount_district_support) total_spend_district_support,
  (e.comp_amount_other + e.non_comp_amount_other) total_spend_other,
  (e.comp_amount_voc + e.non_comp_amount_voc) total_spend_voc,

  (e.comp_amount + e.non_comp_amount) / NULLIF(t.all_students, 0) spend_per_pupil,
  (e.comp_amount_gen_ed + e.non_comp_amount_gen_ed) / NULLIF(t.all_students, 0) spend_gen_ed_per_pupil,
  (e.comp_amount_spec_ed + e.non_comp_amount_spec_ed) / NULLIF(t.all_students, 0) spend_spec_ed_per_pupil,
  (e.comp_amount_compensatory + e.non_comp_amount_compensatory) / NULLIF(t.all_students, 0) spend_compensatory_per_pupil,
  (e.comp_amount_lap + e.non_comp_amount_lap) / NULLIF(t.all_students, 0) spend_lap_per_pupil,
  (e.comp_amount_title1 + e.non_comp_amount_title1) / NULLIF(t.all_students, 0) spend_title1_per_pupil,
  (e.comp_amount_ble + e.non_comp_amount_ble) / NULLIF(t.all_students, 0) spend_ble_per_pupil,
  (e.comp_amount_instr_other + e.non_comp_amount_instr_other) / NULLIF(t.all_students, 0) spend_instr_other_per_pupil,
  (e.comp_amount_district_support + e.non_comp_amount_district_support) / NULLIF(t.all_students, 0) spend_district_support_per_pupil,
  (e.comp_amount_other + e.non_comp_amount_other) / NULLIF(t.all_students, 0) spend_other_per_pupil,
  (e.comp_amount_voc + e.non_comp_amount_voc) / NULLIF(t.all_students, 0) spend_voc_per_pupil,

  (ss.fte) / NULLIF(t.all_students, 0) fte_per_pupil,
  t.* except (ccddd, school_code, class_of),
  e.* except (school_code, class_of),
  ss.* except (school_code, class_of)

FROM demographics_by_school t

LEFT OUTER JOIN exp_by_school e ON (e.class_of = t.class_of AND e.school_code = t.school_code)
LEFT OUTER JOIN s275_school_summary ss ON (ss.class_of = t.class_of AND ss.school_code = t.school_code)
LEFT OUTER JOIN `{project}.safs_domains.d_school` ds ON (ds.ccddd = 17001 AND ds.school_code = t.school_code)

ORDER BY school_code, class_of
