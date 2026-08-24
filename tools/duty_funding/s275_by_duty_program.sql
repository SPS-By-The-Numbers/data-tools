-- Per duty title x program code, for one district/year `final` report.
-- Program code is what lets apportionment revenue accounts be attributed to
-- staff: the state funds special education under Account 4121, and the S-275
-- says which assignments sit in program 21.
--
-- Salary/FTE conventions match s275_by_duty.sql -- see the notes there.
SELECT
  dr.duty_root                               AS duty_root_code,
  dr.duty_name                               AS duty_title,
  dr.duty_name_category                      AS duty_category,
  a.program_code                             AS program_code,
  p.program                                  AS program,
  ROUND(SUM(a.fte_in_assignment), 6)         AS assignment_fte,
  ROUND(SUM(pa.c_est_total_final_salary), 2) AS total_final_salary,
  ROUND(SUM(pa.assignment_salary), 2)        AS assignment_salary,
  COUNT(*)                                   AS assignments
FROM `sps-btn-data.safs_s275.report` r
JOIN `sps-btn-data.safs_s275.assignment` a
  ON a.report_id = r.report_id
LEFT JOIN `sps-btn-data.safs_s275.private_assignment` pa
  ON pa.assignment_id = a.assignment_id
LEFT JOIN `sps-btn-data.safs_domains.d_duty_root` dr
  ON dr.duty_root = a.duty_root_code
LEFT JOIN `sps-btn-data.safs_domains.d_program` p
  ON p.program_code = a.program_code
WHERE r.ccddd = @ccddd
  AND r.school_year = @school_year
  AND r.report_type = 'final'
GROUP BY 1, 2, 3, 4, 5
ORDER BY duty_root_code, program_code
