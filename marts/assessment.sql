-- Assessment input for marts/bigsheet.py, reconstructed from BigQuery.
--
-- Reproduces the pre-baked `assessment.csv` that used to be passed via
-- --assessment. Verified to agree exactly (0 mismatches on all 92,090
-- overlapping rows) with the last such CSV, which is preserved at
-- attic/assessment.csv.
--
-- Row filter: Seattle Public Schools (ccddd 17001), district-wide
-- 'All Grades' rows only. Those two predicates alone reproduce the CSV's
-- row count exactly; the per-grade rows in rc_assessment were never part
-- of this input.
--
-- The two derived columns did not exist in BigQuery and are recomputed
-- here from the pct_met_standard string:
--   pct_met_standard_numeric       -- percent as a fraction; bounded markers
--                                     ("<10%", ">90%") ARE converted, using the
--                                     bound itself. NULL for suppression
--                                     markers ("Suppressed: N<10", "N<10",
--                                     "No Students", "N<10 (Count Protected)").
--   pct_met_standard_numeric_nodat -- same, but bounded markers are ALSO NULL,
--                                     so only exact percentages survive.
SELECT
  class_of,
  school_code,
  grade_level,
  test_administration,
  test_subject,
  student_group,
  pct_noscore,
  pct_alternative,
  SAFE_CAST(REGEXP_EXTRACT(TRIM(pct_met_standard),
                           r'^[<>]?\s*([0-9]+(?:\.[0-9]+)?)\s*%$')
            AS FLOAT64) / 100 AS pct_met_standard_numeric,
  SAFE_CAST(REGEXP_EXTRACT(TRIM(pct_met_standard),
                           r'^([0-9]+(?:\.[0-9]+)?)\s*%$')
            AS FLOAT64) / 100 AS pct_met_standard_numeric_nodat
FROM `{project}.ospi.rc_assessment`
WHERE ccddd = 17001
  AND grade_level = 'All Grades'
-- BigQuery results are unordered. Sort so the pivoted column order in
-- bigsheet.py is reproducible from run to run.
ORDER BY class_of, school_code, test_administration, test_subject,
         student_group

