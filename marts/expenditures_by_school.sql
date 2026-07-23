CREATE OR REPLACE TABLE

`scratch.exp_by_school`

CLUSTER BY
class_of,
school_code

AS

WITH Simplified AS (
  SELECT
  t.*,
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

  FROM `sps-btn-data.safs_f19x.general_fund_expenditures` t

  WHERE
  ccddd=17001
  AND data_type = "actuals"
  AND has_school = TRUE
and school_code IS NOT NULL
),

ByProgCategory AS (
  SELECT 
  class_of,
  school_code,
  school,
  prog_category,

  sum(CASE 
    WHEN object_code in (2,3,4) then amount
    ELSE 0
  END) comp_amount,

  sum(CASE 
    WHEN object_code in (2,3,4) then 0
    ELSE amount
  END) non_comp_amount,

  FROM Simplified

  GROUP BY
  class_of,
  school_code,
  school,
  prog_category
),

Pivoted AS (
  SELECT 
  *
  FROM ByProgCategory

  PIVOT(
    SUM(COALESCE(comp_amount, 0)) AS comp_amount,
    SUM(COALESCE(non_comp_amount, 0)) AS non_comp_amount
    FOR prog_category IN ('gen_ed', 'spec_ed', 'compensatory', 'lap', 'title1', 'ble', 'instr_other', 'district_support', 'other')
  )
)

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
   COALESCE(comp_amount_other, 0)
  ) comp_amount,
  (COALESCE(non_comp_amount_gen_ed, 0) +
   COALESCE(non_comp_amount_spec_ed, 0) +
   COALESCE(non_comp_amount_compensatory, 0) +
   COALESCE(non_comp_amount_lap, 0) +
   COALESCE(non_comp_amount_title1, 0) +
   COALESCE(non_comp_amount_ble, 0) +
   COALESCE(non_comp_amount_instr_other, 0) +
   COALESCE(non_comp_amount_district_support, 0) +
   COALESCE(non_comp_amount_other, 0)
  ) non_comp_amount
FROM
Pivoted

