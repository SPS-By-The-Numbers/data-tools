-- F-196 General Fund actuals, Object 7 (Purchased Services), summed per
-- (special-ed-or-not, NCES class) — the purchased-services "chopping block"
-- bubbles for the admin game. Special ed = OSPI programs 21 + 24.
--
--   bq query --project_id=sps-btn-data --use_legacy_sql=false \
--     --max_rows=1000 --format=csv \
--     --parameter=ccddd:INT64:17001 \
--     --parameter=school_year:STRING:2024-2025 \
--     < tools/salary_skyline/services_query.sql > out_salary_skyline/services.csv
--
-- Output columns: sped, nces, nces_name, amount
SELECT
  IF(program_code IN (21, 24), 1, 0)          AS sped,
  IFNULL(nces_code, -1)                       AS nces,
  IFNULL(ANY_VALUE(nces), '(no NCES class)')  AS nces_name,
  ROUND(SUM(amount), 2)                       AS amount
FROM `sps-btn-data.safs_f19x.general_fund_expenditures`
WHERE ccddd = @ccddd
  AND school_year = @school_year
  AND data_type = 'actuals'
  AND object_code = 7
GROUP BY 1, 2
HAVING amount > 0
ORDER BY sped, amount DESC
