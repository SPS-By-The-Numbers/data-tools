CREATE OR REPLACE TABLE

`scratch.s275_school_summary`

CLUSTER BY
class_of,
school_code

AS

WITH DutySummary AS (
  SELECT
    r.class_of,
    a.school_code,
    a.duty_root_code,
    a.duty_suffix_code,
    sum (pa.assignment_salary) assignment_salary,
    sum (a.fte_in_assignment) fte,
    sum (pa.c_est_total_compensation) c_est_total_compensation,
    sum (pa.c_est_total_final_salary) c_est_total_final_salary,

  FROM `safs_s275.assignment` a
  JOIN `safs_s275.report` r ON (r.report_id = a.report_id)
  JOIN `safs_s275.private_assignment` pa ON (pa.assignment_id = a.assignment_id)

  WHERE
  r.ccddd = 17001

  GROUP BY
  r.class_of,
  a.school_code,
  a.duty_root_code,
  a.duty_suffix_code

),

DistinctTeachers AS (
  SELECT
    distinct
    r.class_of,
    a.school_code,
    a.report_employee_id,
  FROM `safs_s275.assignment` a
  JOIN `safs_s275.report` r ON (r.report_id = a.report_id)
  WHERE
    r.ccddd = 17001
    AND a.duty_root_code in (31,32)
),

ClassroomTeachersStats AS (
  SELECT
    t.class_of,
    t.school_code,
    APPROX_QUANTILES(re.experience_years, 100)[OFFSET(50)] AS class_teacher_exp_50pctile,
    APPROX_QUANTILES(re.experience_years, 100)[OFFSET(80)] AS class_teacher_exp_80pctile,
    AVG(re.experience_years) class_teacher_exp_avg,
    count(t.report_employee_id) num_class_teachers,
    SUM(CASE WHEN re.highest_degree = "B" THEN 1 ELSE 0 END) num_class_teachers_bachelors,
    SUM(CASE WHEN re.highest_degree = "M" THEN 1 ELSE 0 END) num_class_teachers_masters,
    SUM(CASE WHEN re.highest_degree = "D" THEN 1 ELSE 0 END) num_class_teachers_doctors,
  FROM DistinctTeachers t
  LEFT JOIN `safs_s275.report_employee` re ON (re.report_employee_id = t.report_employee_id)
  GROUP BY
    t.class_of,
    t.school_code
),

ClassTeacher AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) class_teacher_assignment_salary,
    sum (t.fte) class_teacher_fte,
    sum (t.c_est_total_compensation) class_teacher_c_est_total_compensation,
    sum (t.c_est_total_final_salary) class_teacher_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (31,32)
  GROUP BY
    t.class_of,
    t.school_code

),

Aides AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) aide_assignment_salary,
    sum (t.fte) aide_fte,
    sum (t.c_est_total_compensation) aide_c_est_total_compensation,
    sum (t.c_est_total_final_salary) aide_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (91)
  GROUP BY
    t.class_of,
    t.school_code

),

OtherTeacher AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) other_teacher_assignment_salary,
    sum (t.fte) other_teacher_fte,
    sum (t.c_est_total_compensation) other_teacher_c_est_total_compensation,
    sum (t.c_est_total_final_salary) other_teacher_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (33, 34)
  GROUP BY
    t.class_of,
    t.school_code

),

Principal AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) principal_assignment_salary,
    sum (t.c_est_total_compensation) principal_c_est_total_compensation,
    sum (t.c_est_total_final_salary) principal_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (21, 23)
  GROUP BY
    t.class_of,
    t.school_code
),

DistinctPrincipals AS (
  SELECT DISTINCT
    r.class_of,
    a.school_code,
    a.report_employee_id,
  FROM `safs_s275.assignment` a
  JOIN `safs_s275.report` r ON (r.report_id = a.report_id)
  WHERE
    r.ccddd = 17001
    AND a.duty_root_code in (21, 23)
),

PrincipalStats AS (
  SELECT
    t.class_of,
    t.school_code,
    APPROX_QUANTILES(re.experience_years, 100)[OFFSET(50)] AS principal_exp_50pctile,
    APPROX_QUANTILES(re.experience_years, 100)[OFFSET(80)] AS principal_exp_80pctile,
    AVG(re.experience_years) principal_exp_avg,
    count(t.report_employee_id) num_principal,
    SUM(CASE WHEN re.highest_degree = "B" THEN 1 ELSE 0 END) num_principal_bachelors,
    SUM(CASE WHEN re.highest_degree = "M" THEN 1 ELSE 0 END) num_principal_masters,
    SUM(CASE WHEN re.highest_degree = "D" THEN 1 ELSE 0 END) num_principal_doctors,

  FROM DistinctPrincipals t
  LEFT JOIN `safs_s275.report_employee` re ON (re.report_employee_id = t.report_employee_id)

  GROUP BY
    t.class_of,
    t.school_code
),


AssistantPrincipal AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) asst_principal_assignment_salary,
    sum (t.fte) asst_principal_fte,
    sum (t.c_est_total_compensation) asst_principal_c_est_total_compensation,
    sum (t.c_est_total_final_salary) asst_principal_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (22, 24)
  GROUP BY
    t.class_of,
    t.school_code
),

Counselor AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) counselor_assignment_salary,
    sum (t.fte) counselor_fte,
    sum (t.c_est_total_compensation) counselor_c_est_total_compensation,
    sum (t.c_est_total_final_salary) counselor_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (42, 44)
  GROUP BY
    t.class_of,
    t.school_code
),

Librarian AS (

  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) librarian_assignment_salary,
    sum (t.fte) librarian_fte,
    sum (t.c_est_total_compensation) librarian_c_est_total_compensation,
    sum (t.c_est_total_final_salary) librarian_c_est_total_final_salary
  FROM DutySummary t
  WHERE
    t.duty_root_code in (41)
  GROUP BY
    t.class_of,
    t.school_code
  ), AllRoles AS (
  SELECT
    t.class_of,
    t.school_code,
    sum (t.assignment_salary) assignment_salary,
    sum (t.fte) fte,
    sum (t.c_est_total_compensation) c_est_total_compensation,
    sum (t.c_est_total_final_salary) c_est_total_final_salary
  FROM DutySummary t
  GROUP BY
    t.class_of,
    t.school_code
)


SELECT
t.*,
c.* EXCEPT (class_of, school_code),
dts.* EXCEPT (class_of, school_code),
a.* EXCEPT (class_of, school_code),
o.* EXCEPT (class_of, school_code),
p.* EXCEPT (class_of, school_code),
ps.* EXCEPT (class_of, school_code),
ap.* EXCEPT (class_of, school_code),
co.* EXCEPT (class_of, school_code),
l.* EXCEPT (class_of, school_code)
FROM AllRoles t
LEFT OUTER JOIN ClassTeacher c ON (t.class_of = c.class_of AND t.school_code = c.school_code)
LEFT OUTER JOIN Aides a ON (t.class_of = a.class_of AND t.school_code = a.school_code)
LEFT OUTER JOIN OtherTeacher o ON (t.class_of = o.class_of AND t.school_code = o.school_code)
LEFT OUTER JOIN Principal p ON (t.class_of = p.class_of AND t.school_code = p.school_code)
LEFT OUTER JOIN AssistantPrincipal ap ON (t.class_of = ap.class_of AND t.school_code = ap.school_code)
LEFT OUTER JOIN Counselor co ON (t.class_of = co.class_of AND t.school_code = co.school_code)
LEFT OUTER JOIN Librarian l ON (t.class_of = l.class_of AND t.school_code = l.school_code)
LEFT OUTER JOIN ClassroomTeachersStats dts ON (dts.class_of = t.class_of AND dts.school_code = t.school_code)
LEFT OUTER JOIN PrincipalStats ps ON (ps.class_of = t.class_of AND ps.school_code = t.school_code)

  

/*
SELECT

t.class_of,
t.school_code,
sum (t.assignment_salary) assignment_salary,
sum (t.fte) fte,
sum (t.c_est_total_compensation) c_est_total_compensation,
sum (t.c_est_total_final_salary) c_est_total_final_salary

FROM DutySummary t

GROUP BY
t.class_of,
t.school_code*/
