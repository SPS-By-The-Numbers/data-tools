-- One row per SPS 2024-25 district-administrator / director person-year.
-- Duty roots: 11 superintendent, 12 deputy/assistant superintendent,
-- 13 other district administrator (certificated), 99 director or supervisor
-- (classified). Used to rebuild SEA's job-category buckets, which are not
-- S-275 categories -- the buckets are matched by salary tier against the
-- headcounts on the SPS leadership pages, since S-275 carries no names.
SELECT
  a.duty_root_code                            AS duty_root,
  a.report_employee_id                        AS emp,
  ROUND(SUM(a.fte_in_assignment), 3)          AS fte,
  ROUND(SUM(pa.c_est_total_final_salary), 0)  AS salary
FROM `sps-btn-data.safs_s275.report` r
JOIN `sps-btn-data.safs_s275.assignment` a
  ON a.report_id = r.report_id
LEFT JOIN `sps-btn-data.safs_s275.private_assignment` pa
  ON pa.assignment_id = a.assignment_id
WHERE r.ccddd = 17001
  AND r.school_year = '2024-2025'
  AND r.report_type = 'final'
  AND a.duty_root_code IN (11, 12, 13, 99)
GROUP BY 1, 2
ORDER BY 1, salary DESC
