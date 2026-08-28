-- SPS 2024-25 S-275 final, rolled up to duty root.
-- Salary: private_assignment.c_est_total_final_salary (the assignment-attributed
--   form; raw total_final_salary lives on the employee and would multi-count).
-- FTE:    assignment.fte_in_assignment (the only additive FTE column; the
--   assignment_fte cert/class columns are per-employee markers, ~5x over-count).
SELECT
  a.duty_root_code                            AS duty_root,
  ANY_VALUE(dr.duty_name)                     AS duty_title,
  COUNT(DISTINCT a.report_employee_id)        AS employees,
  ROUND(SUM(a.fte_in_assignment), 3)          AS fte,
  ROUND(SUM(pa.c_est_total_final_salary), 0)  AS total_final_salary
FROM `sps-btn-data.safs_s275.report` r
JOIN `sps-btn-data.safs_s275.assignment` a
  ON a.report_id = r.report_id
LEFT JOIN `sps-btn-data.safs_s275.private_assignment` pa
  ON pa.assignment_id = a.assignment_id
LEFT JOIN `sps-btn-data.safs_domains.d_duty_root` dr
  ON dr.duty_root = a.duty_root_code
WHERE r.ccddd = 17001
  AND r.school_year = '2024-2025'
  AND r.report_type = 'final'
GROUP BY 1
ORDER BY 1
