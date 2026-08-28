-- Verifies the three district-side counts used in the chart markup.
-- SPS (ccddd 17001), 2024-25 S-275 final.
--   fte_in_assignment is the ONLY additive FTE column. Do not use
--   assignment_fte.certificated_fte / classified_fte -- those are per-employee
--   markers repeated on every assignment row and over-count ~5x.
SELECT
  CASE
    WHEN a.duty_root_code BETWEEN 31 AND 34   THEN 'Teachers (duty 31-34)'
    WHEN a.duty_root_code IN (91, 94)         THEN 'Paras + office (duty 91, 94)'
    WHEN a.duty_root_code IN (11, 12, 13)     THEN 'Central certificated admin (duty 11-13)'
  END                                            AS category,
  COUNT(DISTINCT a.report_employee_id)           AS people,
  ROUND(SUM(a.fte_in_assignment), 3)             AS reported_fte
FROM `sps-btn-data.safs_s275.report` r
JOIN `sps-btn-data.safs_s275.assignment` a
  ON a.report_id = r.report_id
WHERE r.ccddd = 17001
  AND r.school_year = '2024-2025'
  AND r.report_type = 'final'
  AND (a.duty_root_code BETWEEN 31 AND 34
       OR a.duty_root_code IN (91, 94, 11, 12, 13))
GROUP BY category
ORDER BY reported_fte DESC
