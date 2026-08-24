-- Actual General Fund expenditure by program and object, one district/year.
-- Objects 2 and 3 are salaries, 4 is benefits; everything else (5 supplies,
-- 7 purchased services, 8 travel, 9 capital) buys something other than
-- people. The ratio per program is what stops a revenue stream that mostly
-- buys contracted service -- transportation above all -- from being charged
-- against the handful of staff coded to it.
SELECT
  program_code,
  ANY_VALUE(program) AS program,
  ROUND(SUM(IF(object_code IN (2, 3), amount, 0)), 2) AS salary,
  ROUND(SUM(IF(object_code = 4, amount, 0)), 2)       AS benefits,
  ROUND(SUM(amount), 2)                               AS total
FROM `sps-btn-data.safs_f19x.general_fund_expenditures`
WHERE ccddd = @ccddd
  AND school_year = @school_year
  AND data_type = 'actuals'
GROUP BY program_code
ORDER BY program_code
