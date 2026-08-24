-- F-196 actual General Fund salaries and benefits for one district/year.
-- Object 2 = certificated salaries, 3 = classified salaries, 4 = employee
-- benefits and payroll taxes. The S-275 carries no benefits at all, so the
-- ratio 4 / (2 + 3) is what scales a duty title's salary up to compensation.
SELECT
  object_code,
  ANY_VALUE(object) AS object,
  ROUND(SUM(amount), 2) AS amount
FROM `sps-btn-data.safs_f19x.general_fund_expenditures`
WHERE ccddd = @ccddd
  AND school_year = @school_year
  AND data_type = 'actuals'
  AND object_code IN (2, 3, 4)
GROUP BY object_code
ORDER BY object_code
