With DemographicsBySchool AS (
  SELECT
  t.*,

  # Living situation
  t.military_parent / NULLIF(t.all_students, 0) pct_military_parent,
  t.migrant / NULLIF(t.all_students, 0) pct_migrant,
  t.low_income / NULLIF(t.all_students, 0) pct_low_income,
  t.homeless / NULLIF(t.all_students, 0) pct_homeless,
  t.foster_care / NULLIF(t.all_students, 0) pct_foster_care,
  t.mobile / NULLIF(t.all_students, 0) pct_mobile,
  t.section_504 / NULLIF(t.all_students, 0) pct_section_504,

  # Learning type
  t.highly_capable / NULLIF(t.all_students, 0) pct_highly_capable,
  t.english_language_learners / NULLIF(t.all_students, 0) pct_english_language_learners,
  t.students_with_disabilities / NULLIF(t.all_students, 0) pct_students_with_disabilities,

  # Gender
  t.female / NULLIF(t.all_students, 0) pct_female,
  t.male / NULLIF(t.all_students, 0) pct_male,
  t.gender_x / NULLIF(t.all_students, 0) pct_gender_x,
  
  # Race
  t.white / NULLIF(t.all_students, 0) pct_white,
  t.black_african_american / NULLIF(t.all_students, 0) pct_black_african_american,
  t.native_hawaiian_other_pacific / NULLIF(t.all_students, 0) pct_native_hawaiian_other_pacific,
  t.american_indian_alaskan_native / NULLIF(t.all_students, 0) pct_american_indian_alaskan_native,
  t.hispanic_latino_of_any_race / NULLIF(t.all_students, 0) pct_hispanic_latino_of_any_race,
  t.asian / NULLIF(t.all_students, 0) pct_asian,
  t.two_or_more_races / NULLIF(t.all_students, 0) pct_two_or_more_races,
  
  FROM `ospi.rc_enrollment` t
  WHERE
   ccddd=17001
   AND grade = "All Grades"
)

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

(ss.fte) / NULLIF(t.all_students, 0) fte_per_pupil,
t.* except (ccddd, school_code, class_of),
e.* except (school_code, class_of),
ss.* except (school_code, class_of)

FROM DemographicsBySchool t

LEFT OUTER JOIN `scratch.exp_by_school` e ON (e.class_of = t.class_of AND e.school_code = t.school_code)
LEFT OUTER JOIN `scratch.s275_school_summary` ss ON (ss.class_of = t.class_of AND ss.school_code = t.school_code)
LEFT OUTER JOIN `safs_domains.d_school` ds ON (ds.ccddd = 17001 AND ds.school_code = t.school_code)

ORDER BY school_code, class_of
