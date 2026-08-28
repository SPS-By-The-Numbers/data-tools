-- Average salary and estimated total compensation, SPS 2024-25.
--
-- Benefits are NOT taken from the S-275 (its insurance/benefits columns do not
-- reflect actual employer cost). They are estimated by scaling the F-196
-- object 4 total across the S-275 salary base:
--     object 4 (employee benefits + payroll taxes)  $240,895,971
--   / S-275 salary paid (total_final_salary + other_salary)  $755,553,117
--   = 0.318835 per dollar of salary paid.
-- Applying it districtwide reproduces the object 4 total exactly.
--
--   sped       = program 21 or 24;  teacher = duty root 31-34;  aide = 91
--   elementary = assignment grade P,K,1-6;  secondary = M,H
-- Each person lands in the bucket holding the plurality of their FTE across a
-- full partition of their time; their whole person-year is then counted, so
-- supplemental pay sitting on zero-FTE rows is included rather than dropped.
WITH bucket AS (
  SELECT a.report_employee_id AS emp, a.fte_in_assignment AS fte,
         CASE
           WHEN a.duty_root_code = 91 AND a.program_code IN (21,24) THEN '4 Aide - special education'
           WHEN a.duty_root_code = 91 THEN '5 Aide - other programs'
           WHEN a.duty_root_code BETWEEN 31 AND 34 THEN
             CASE WHEN a.program_code NOT IN (21,24) THEN '3 Teacher - not special education'
                  WHEN a.grade IN ('P','K','1','2','3','4','5','6') THEN '1 Sped teacher - elementary'
                  WHEN a.grade IN ('M','H') THEN '2 Sped teacher - secondary'
                  ELSE '9 other' END
           ELSE '9 other' END AS grp
  FROM assignment a JOIN report r USING (report_id)
  WHERE r.ccddd = 17001 AND r.school_year = '2024-2025' AND r.report_type = 'final'
),
ranked AS (
  SELECT emp, grp, sum(fte) AS grp_fte,
         row_number() OVER (PARTITION BY emp ORDER BY sum(fte) DESC, grp) AS rn
  FROM bucket GROUP BY emp, grp
),
person AS (
  SELECT k.emp, k.grp,
         (SELECT sum(fte) FROM bucket b WHERE b.emp = k.emp) AS total_fte,
         pre.total_final_salary AS base,
         pre.other_salary       AS suppl,
         pre.total_final_salary + pre.other_salary AS paid
  FROM ranked k
  JOIN private_report_employee pre ON pre.report_employee_id = k.emp
  WHERE k.rn = 1 AND k.grp <> '9 other'
)
SELECT grp, count(*) AS people, round(sum(total_fte),1) AS fte,
       round(avg(base))                       AS avg_base_salary,
       round(avg(suppl))                      AS avg_supplemental,
       round(avg(paid))                       AS avg_salary_paid,
       round(avg(paid) * 0.318835)            AS avg_benefits_est,
       round(avg(paid) * 1.318835)            AS avg_total_comp,
       round(sum(paid)/sum(total_fte))        AS salary_paid_per_fte,
       round(sum(paid)*1.318835/sum(total_fte)) AS comp_per_fte
FROM person GROUP BY grp
UNION ALL
SELECT 'ALL TEACHERS (duty 31-34)', count(*), round(sum(total_fte),1),
       round(avg(base)), round(avg(suppl)), round(avg(paid)),
       round(avg(paid)*0.318835), round(avg(paid)*1.318835),
       round(sum(paid)/sum(total_fte)), round(sum(paid)*1.318835/sum(total_fte))
FROM person WHERE grp LIKE '%teacher%' OR grp LIKE '%Teacher%'
UNION ALL
SELECT 'ALL AIDES (duty 91)', count(*), round(sum(total_fte),1),
       round(avg(base)), round(avg(suppl)), round(avg(paid)),
       round(avg(paid)*0.318835), round(avg(paid)*1.318835),
       round(sum(paid)/sum(total_fte)), round(sum(paid)*1.318835/sum(total_fte))
FROM person WHERE grp LIKE '%Aide%'
ORDER BY 1;
