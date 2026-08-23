-- Per-employee total_final_salary for one district / one S-275 report.
--
-- One row per person: the S-275 reports salary once per employee per report
-- (private_report_employee.total_final_salary), while assignments are one row
-- per duty/program/activity/school. So the duty title has to be *chosen*: we
-- take the duty root of the employee's major assignment, breaking ties on
-- summed FTE and then on assignment salary.
--
--   bq query --project_id=sps-btn-data --use_legacy_sql=false \
--     --max_rows=20000 --format=csv \
--     --parameter=ccddd:INT64:17001 \
--     --parameter=school_year:STRING:2024-2025 \
--     "$(cat tools/salary_skyline/query.sql)" > out_salary_skyline/staff.csv
--
-- Output columns: cat, duty, duty_name, salary, fte, pgroup
--   cat    — legacy band id, ignored downstream (banding now lives in salary_bands.py)
--   duty   — OSPI duty ROOT code of the major assignment; the real grouping key
--   fte    — sum of assignment.fte_in_assignment over ALL of the person's assignments
--   pgroup — program bucket by FTE PLURALITY over the person's assignments
--            (ties go to basic; zero-FTE staff use assignment-ROW plurality):
--              0 basic + everything else
--              1 LAP (program 55)
--              2 Title I (programs 51, 52, 53)
--              3 special education (programs 21+24 — combine both: duty-46
--                psychologists moved 24→21 in 2022-23)
WITH re AS (
  SELECT re.report_employee_id
  FROM `sps-btn-data.safs_s275.report` r
  JOIN `sps-btn-data.safs_s275.report_employee` re USING (report_id)
  WHERE r.ccddd = @ccddd
    AND r.school_year = @school_year
    AND r.report_type = "final"
),
a AS (
  SELECT a.report_employee_id, a.duty_root_code,
         SUM(a.fte_in_assignment)          AS fte,
         COUNTIF(a.is_major)               AS nmaj,
         SUM(IFNULL(pa.assignment_salary, 0)) AS sal
  FROM `sps-btn-data.safs_s275.assignment` a
  JOIN re USING (report_employee_id)
  LEFT JOIN `sps-btn-data.safs_s275.private_assignment` pa USING (assignment_id)
  GROUP BY 1, 2
),
pick AS (
  SELECT report_employee_id, duty_root_code,
         ROW_NUMBER() OVER (PARTITION BY report_employee_id
                            ORDER BY nmaj DESC, fte DESC, sal DESC, duty_root_code) AS rn
  FROM a
),
tot AS (
  -- total FTE per person: sum fte_in_assignment, NOT assignment_fte.certificated_fte
  SELECT a2.report_employee_id,
         SUM(a2.fte_in_assignment) AS total_fte,
         SUM(IF(a2.program_code IN (21, 24), a2.fte_in_assignment, 0))     AS sped_fte,
         SUM(IF(a2.program_code IN (51, 52, 53), a2.fte_in_assignment, 0)) AS t1_fte,
         SUM(IF(a2.program_code = 55, a2.fte_in_assignment, 0))            AS lap_fte,
         COUNT(*)                                     AS n_asgn,
         COUNTIF(a2.program_code IN (21, 24))         AS n_sped,
         COUNTIF(a2.program_code IN (51, 52, 53))     AS n_t1,
         COUNTIF(a2.program_code = 55)                AS n_lap
  FROM `sps-btn-data.safs_s275.assignment` a2
  JOIN re USING (report_employee_id)
  GROUP BY 1
)
SELECT
  0 AS cat,
  p.duty_root_code AS duty,
  d.duty_name,
  ROUND(CAST(pr.total_final_salary AS FLOAT64), 2) AS salary,
  ROUND(CAST(t.total_fte AS FLOAT64), 4)           AS fte,
  CASE WHEN t.total_fte > 0 THEN
    CASE GREATEST(t.total_fte - t.sped_fte - t.t1_fte - t.lap_fte,
                  t.lap_fte, t.t1_fte, t.sped_fte)
      WHEN t.total_fte - t.sped_fte - t.t1_fte - t.lap_fte THEN 0
      WHEN t.lap_fte  THEN 1
      WHEN t.t1_fte   THEN 2
      ELSE 3 END
  ELSE
    CASE GREATEST(t.n_asgn - t.n_sped - t.n_t1 - t.n_lap,
                  t.n_lap, t.n_t1, t.n_sped)
      WHEN t.n_asgn - t.n_sped - t.n_t1 - t.n_lap THEN 0
      WHEN t.n_lap THEN 1
      WHEN t.n_t1  THEN 2
      ELSE 3 END
  END                                                AS pgroup
FROM pick p
JOIN `sps-btn-data.safs_s275.private_report_employee` pr USING (report_employee_id)
JOIN tot t USING (report_employee_id)
LEFT JOIN `sps-btn-data.safs_domains.d_duty_root` d ON d.duty_root = p.duty_root_code
WHERE p.rn = 1
ORDER BY duty, salary DESC
