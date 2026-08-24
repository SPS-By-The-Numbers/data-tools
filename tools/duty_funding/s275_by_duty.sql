-- Per-duty-title S-275 rollup for one district/year.
-- Salary is attributed to the assignment level:
--   * assignment_salary            = private_assignment.assignment_salary (as reported)
--   * total_final_salary           = private_assignment.c_est_total_final_salary
--     (report_employee.total_final_salary pro-rated across that employee's
--      assignments; the raw column lives on the employee, not the assignment,
--      so summing it per duty title would multi-count multi-duty staff)
--   * fte_in_assignment            = assignment.fte_in_assignment  <- real FTE
--     (assignment_fte.certificated_fte/classified_fte are per-employee markers
--      repeated on every assignment row and over-count ~5x)
SELECT
  dr.duty_root                             AS duty_root_code,
  dr.duty_name                             AS duty_title,
  dr.duty_name_category                    AS duty_category,
  ds.duty_contract_type                    AS contract_type,
  COUNT(DISTINCT a.report_employee_id)     AS employees,
  COUNT(*)                                 AS assignments,
  ROUND(SUM(pa.c_est_total_final_salary), 2) AS total_final_salary,
  ROUND(SUM(pa.assignment_salary), 2)      AS assignment_salary,
  ROUND(SUM(a.fte_in_assignment), 3)       AS assignment_fte
FROM `sps-btn-data.safs_s275.report` r
JOIN `sps-btn-data.safs_s275.assignment` a
  ON a.report_id = r.report_id
LEFT JOIN `sps-btn-data.safs_s275.private_assignment` pa
  ON pa.assignment_id = a.assignment_id
LEFT JOIN `sps-btn-data.safs_domains.d_duty_root` dr
  ON dr.duty_root = a.duty_root_code
LEFT JOIN `sps-btn-data.safs_domains.d_duty_suffix` ds
  ON ds.duty_suffix = a.duty_suffix_code
WHERE r.ccddd = @ccddd
  AND r.school_year = @school_year
  AND r.report_type = 'final'
GROUP BY 1, 2, 3, 4
ORDER BY total_final_salary DESC
