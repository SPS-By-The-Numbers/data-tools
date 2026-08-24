-- Every General Fund revenue line for one district/year, F-196 actuals.
-- `program_code` is taken from the revenue code's last two digits, so each
-- line already says which S-275 program its money pays for; program 0 means
-- unrestricted, which spreads across all staff.
SELECT
  category_code,
  category,
  revenue_code,
  revenue,
  program_code,
  program,
  ROUND(SUM(amount), 2) AS amount
FROM `sps-btn-data.safs_f19x.general_fund_revenues`
WHERE ccddd = @ccddd
  AND school_year = @school_year
  AND data_type = 'actuals'
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY category_code, revenue_code
