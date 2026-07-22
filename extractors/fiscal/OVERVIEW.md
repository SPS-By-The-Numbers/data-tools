# Fiscal data — output overview

This file is the top-of-funnel for anyone who wants to consume the CSV
outputs produced by `extractors/fiscal/`. Read it first to build a mental
model of what's captured, how the tables fit together, and where the
analytical value lives. For per-table specifics see
[CSV_GUIDE.md](CSV_GUIDE.md); for what's *not* captured (with rationale)
see [TODO.md](TODO.md).

## Before you use these tables: check SAFS raw first

**Most top-level fiscal analysis does not need the PDF path.** The
SAFS canonical avros in `safs_prod/f19x/` cover almost every dimension
these fiscal PDF tables carry — usually with more grain (per-school,
NCES, sub-fund) and always with pre-decoded labels — and they're
faster to iterate on because they don't require re-parsing PDFs.

**Rule of thumb:** start at
[DATA_SOURCE_DIVERGENCE.md](DATA_SOURCE_DIVERGENCE.md), which lists
what each path covers side-by-side and which one to reach for. Come
back to this file only when you need one of the dimensions that
genuinely doesn't exist in SAFS raw:

- Per-duty-code salary detail (`fiscal_f195_salary_exhibits`)
- FTE staff counts per activity (`fiscal_f195_staff_by_activity`)
- Debt / long-term liabilities detail (`fiscal_f195_debt_service_bonds`,
  `fiscal_f195_long_term_financing`, `fiscal_f196_long_term_liabilities`)
- Balance sheet (`fiscal_f196_balance_sheet`)
- Mid-year revised (Final) Budget column (`fiscal_f196_budgetary_comparison`)
- Federal Indirect Cost Rate calculation (`fiscal_f196_indirect_rate*`)
- Fiduciary funds, data-quality edit report, data requirements
- Any apportionment / 1191 / F-780 / 1191SI sub-report
- Non-district entities (state institutions, ESD allocations, tech
  colleges) that don't flow through SAFS at all

## What this is

Washington state's Office of Superintendent of Public Instruction (OSPI)
publishes ~200K PDFs of fiscal reports per year covering K-12 school
district budgets, actuals, apportionment, and related programs. The
scraper at `docs/contentscripts/scrappers/ospi-funding-reports.js` pulls
them into `data/fiscal/`, and [`reorg.py`](reorg.py) reshapes them into a
consistent directory tree. This module then turns those PDFs into
**long-form fact tables** (CSV files under `out_fiscal/`) that are joinable
across sources.

The output tables trace the full lifecycle of district funding:

- **Original Budget** — the district's start-of-year filing (F-195)
- **Estimated Apportionment** — OSPI's monthly interim estimates (1191)
- **Final Apportionment** — the year-end final calculation (1191F)
- **Actuals** — the audited year-end financials (F-196)

Any given expenditure or revenue line item can be traced across these
four snapshots. The join keys are almost always `(school_year, ccddd)`
plus a table-specific dimension (fund, program, activity, object, account
code, or month).

## Reading order

If you're building analytics on this data, orient yourself in this order:

1. Read this file (OVERVIEW.md) for the map.
2. Skim [CSV_GUIDE.md](CSV_GUIDE.md) — it has one row per fact CSV with
   the schema, row count, join key, and the analytical quirks each
   table absorbs from OSPI's source PDFs.
3. Consult [TODO.md](TODO.md) when a specific dimension seems to be
   missing — it documents deferred sub-reports and coverage gaps with
   rationale.
4. For any specific column semantic, read the corresponding schema
   module under [`schemas/`](schemas/) — schemas are the definitive
   source-of-truth for field docs.

## Data model

Two things dominate the shape of these tables:

**Dimensions.** Every fact table keys on `(school_year, ccddd)` — an
OSPI school-year string (`'2018-2019'`) and a 5-digit district code
(`21232` for Winlock). `class_of` is the end-year integer (`2019`) and is
redundant with `school_year` but useful for numeric filtering. Larger
tables add form-specific dimensions: `fund`, `program_code`,
`activity_code`, `object_code`, `account_code`, `month`, `data_year_offset`
(for budget forecasts).

**Fact rows.** Each row is one printed line-item value from one source
PDF. The parsers deliberately preserve OSPI's printed structure
(section letters, item codes, subtotal rows) so consumers can filter
to whichever grain matters. `row_kind` or `is_total` fields distinguish
detail rows from subtotal / grand-total rows where present.

`_source` on every row identifies the source PDF path (rewritten to an
integer `_source_id` by [`build_sources.py`](build_sources.py) after
all fact tables are generated). Joining to `d_fiscal_source.csv` gives
you the org type, school year, and other file metadata.

## Source docs → fact tables

Each doc kind published by OSPI populates one or more fact tables. This
diagram is organised by the OSPI form:

### F-195 Budget (original budget filing, ~Sep-Oct of the school year)

The 100+ page F-195 Budget PDF (or its shorter cousin F-195 Budget
Overview) contains the district's start-of-year budget in ~30 sub-reports.

| Sub-report (OSPI code) | Fact table |
|---|---|
| SUMMARY OF X FUND BUDGET (GF2/ASB1/DS1/CP1/TVF1) | `fiscal_f195_budget[sub_report='fund_summary']` |
| EXPENDITURE BY PROGRAM (GF8) | `fiscal_f195_budget[sub_report='expenditure_by_program']` |
| EXPENDITURE BY OBJECT (GF10) | `fiscal_f195_budget[sub_report='expenditure_by_object_summary']` |
| EXPENDITURE BY ACTIVITY (GF11) | `fiscal_f195_budget[sub_report='expenditure_by_activity_summary']` |
| ENROLLMENT AND STAFF COUNTS (GF1) | `fiscal_f195_budget[sub_report='enrollment_and_staff_counts']` |
| GF FINANCIAL SUMMARY | `fiscal_f195_budget[sub_report='financial_summary']` |
| Per-fund revenue detail (GF4/DS2/CP3) | `fiscal_f195_budget[sub_report='fund_revenue_detail']` |
| PROGRAM SUMMARY BY OBJECT (GF9) | `fiscal_f195_program_summary_by_object` |
| OBJECTS OF EXPENDITURE per program (GF9-XX) | `fiscal_f195_program_activity_object_detail` |
| SALARY EXHIBITS (GF9-201-XX / GF9-301-XX / CP-7 / CP-8) | `fiscal_f195_salary_exhibits` |
| FTE STAFF COUNTS BY ACTIVITY (GF15) | `fiscal_f195_staff_by_activity` |
| REVENUE WORKSHEET (GF13/DS3/CP5/TVF3) | `fiscal_f195_revenue_worksheet` |
| LONG-TERM FINANCING (GF14/CP9/TVF4) | `fiscal_f195_long_term_financing` |
| DEBT SERVICE OUTSTANDING BONDS (DS4) | `fiscal_f195_debt_service_bonds` |
| BUDGET AND EXCESS LEVY SUMMARY (Overview p1) | `fiscal_f195_overview` |
| Four-year Budget Summary Plan (F-195F) | `fiscal_f195_four_year` |

Parsers: [`parsers/f195_budget.py`](parsers/f195_budget.py),
[`parsers/f195_program_activity_object_detail.py`](parsers/f195_program_activity_object_detail.py),
[`parsers/f195_salary_exhibits.py`](parsers/f195_salary_exhibits.py), and
sibling `f195_*.py` files. Each has a CLI driver at
`extract_f195_*.py` at the fiscal root.

### F-196 All Pages (year-end actuals filing, ~Dec of the following calendar year)

The 90-120 page F-196 All Pages PDF is the audited year-end financial
report. Its ~15 sub-reports fully cover accrual-basis actuals.

| Sub-report | Fact table |
|---|---|
| Page-2 SUMMARY (7 items x 7 funds) | `fiscal_f196_summary` |
| Report of Revenues and Other Financing Sources | `fiscal_f196_revenues` |
| Budgetary Comparison Schedule (Final Budget / Actual / Variance) | `fiscal_f196_budgetary_comparison` |
| Program/Activity/Object roll-up | `fiscal_f196_program_activity_object` |
| Per-PROGRAM Program/Activity/Object cross-tab detail | `fiscal_f196_program_activity_object_detail` |
| Balance Sheet - Governmental Funds | `fiscal_f196_balance_sheet` |
| Schedule of Long-Term Liabilities | `fiscal_f196_long_term_liabilities` |
| Resource to Program Expenditure | `fiscal_f196_resource_to_program` |
| NCES Object Expenditure Summary (2019-20+) | `fiscal_f196_nces_object` |
| Fiduciary Funds (Net Position + Changes) | `fiscal_f196_fiduciary` |
| General Fund By Sub-Fund (2019-20+) | `fiscal_f196_gf_by_subfund` |
| Financial Edit Report | `fiscal_f196_edit_report` |
| Data Requirements (Supplemental + Apportionment + Indirect Cost) | `fiscal_f196_data_requirements` |
| Federal Indirect Cost Rate calculation (pp 72-75) | `fiscal_f196_indirect_rate` |
| Federal Indirect Cost Rate p1 expenditures partition (pp 72 / 74) | `fiscal_f196_indirect_rate_detail` |

Parsers: [`parsers/f196_summary.py`](parsers/f196_summary.py) (dispatches to
[`parsers/f196_all_pages.py`](parsers/f196_all_pages.py) for the SUMMARY
block) plus one file per sub-report at
[`parsers/f196_*.py`](parsers/). CLI drivers at
[`extract_f196_*.py`](extract_f196_all_pages.py).

### Apportionment (monthly + year-end final)

The apportionment corpus is bigger than the F-195/F-196 corpora combined
(~150K files vs ~20K). Every school district gets one Statement of
Apportionment per month plus a compound Estimated Funding Report per
month, plus a year-end Final version of the same Estimated Funding
Report.

| Doc kind | Fact table |
|---|---|
| Monthly Apportionment page 1 (Statement of Apportionment 900) | `fiscal_apportionment_monthly` |
| Monthly Apportionment pages 3+ (1191 Estimated Funding Report) | `fiscal_apportionment_monthly_estimated` |
| Final Apportionment Summary (1191F, year-end final) | `fiscal_apportionment_final` |
| F-780 Levy Authority (Initial + Final per calendar year) | `fiscal_f780_levy` |
| 1191FG Grants Administration | `fiscal_1191fg_grants` |
| 1220 Special Education Allocation (district-level) | `fiscal_1220_sped` |
| 1220TR Special Ed Transfer of Allocation (ESD-level, 2013-14 to 2016-17) | `fiscal_1220_sped_transfer` |
| 1251 FTE + 1251H Headcount | `fiscal_1251_enrollment` |
| 1735T Special Education Enrollment | `fiscal_1735t_sped_enrollment` |
| Non-High Billing (F-483N / F-483H) | `fiscal_nonhigh_billing` |
| 1159 K12 Staff Ratios (2013-14 to 2015-16) | `fiscal_1159_staff_ratio` |
| F-196 Unaudited (2013-14 to 2014-15) | `fiscal_f196_unaudited_summary` |

Parsers: [`parsers/apportionment_monthly.py`](parsers/apportionment_monthly.py),
[`parsers/apportionment_monthly_estimated.py`](parsers/apportionment_monthly_estimated.py),
[`parsers/apportionment_final.py`](parsers/apportionment_final.py), plus
one file per doc kind under [`parsers/`](parsers/).

### State institutions

Report 1191SI Statement of State Institution Apportionment covers ~50
adult jails, juvenile detention centers, and similar facilities served
by school districts under contract.

| Doc kind | Fact table |
|---|---|
| 1191SI State Institution allocation | `fiscal_state_institutions` |
| Food Service Program Summary (Report 1800SUM, 2013-14 to 2018-19) | `fiscal_food_service` |

## Analytical join patterns

The reason the tables are shaped this way is that they support these
core query patterns:

**Budget vs Actuals per (program, activity, object).** Join
`fiscal_f195_program_activity_object_detail` (budget-side) with
`fiscal_f196_program_activity_object_detail` (actuals-side) on
`(school_year, ccddd, program_code, activity_code)`. Both tables are at
the deepest breakdown available in the corpus — one row per
(program, activity, object) — and cover 2013-14 through 2025-26.

**Original -> Final -> Actual -> Variance trace.** A specific budget
line item can be traced through:
- **Original Budget**: `fiscal_f195_budget` (per-item budget from Sept
  filing)
- **Final Budget**: `fiscal_f196_budgetary_comparison[column_kind='final_budget']`
  (post-revision budget as reported in the actuals filing)
- **Actual**: `fiscal_f196_budgetary_comparison[column_kind='actual']`
  or `fiscal_f196_program_activity_object_detail`
- **Variance**: `fiscal_f196_budgetary_comparison[column_kind='variance']`
  (favorable-to-district sign convention -- see the parser's docstring)

**Apportionment progression across the year.** Every account (3100
general apportionment, 4121 special ed, 4174 LAP, etc.) has 12 monthly
estimates plus a year-end final. Join
`fiscal_apportionment_monthly_estimated` with
`fiscal_apportionment_final` on `(school_year, ccddd, account_code)` to
see how estimates evolved. Note that the August (year-end) row of
monthly_estimated exactly matches the corresponding Final row on all
accounts.

**Rate calculation reproduction.** Federal Indirect Cost Rate for
grants can be reproduced from
`fiscal_f196_indirect_rate_detail` (per-activity expenditures partition)
+ `fiscal_f196_data_requirements[report_kind='indirect_rate']` (input
values for distorting items and adjustments). Compare against the
calculated line 14 in `fiscal_f196_indirect_rate`.

**Revenue account cross-check.** Per-account revenue can be joined
across budget (`fiscal_f195_budget[sub_report='fund_revenue_detail']`)
and actuals (`fiscal_f196_revenues`) on
`(school_year, ccddd, fund, section, item_code)` for
budget-vs-actuals per 4-digit OSPI revenue account code.

**Per-object salary detail.** `fiscal_f195_salary_exhibits` has per-
`(program, activity, duty)` salary line items with FTE and salary
rates. Join to `fiscal_f195_program_activity_object_detail` on
`(program_code, activity_code)` to allocate the salary budget across
positions.

## Coverage

Row counts assuming the corpus scrape state as of this session. See
CSV_GUIDE.md for authoritative live counts.

| Table | Rows | Coverage |
|---|--:|---|
| `fiscal_f195_budget` | 1M+ | 2013-14 through 2025-26 |
| `fiscal_f195_four_year` | 2.5M | 2013-14+ |
| `fiscal_f195_program_activity_object_detail` | 1.9M | 2013-14+ |
| `fiscal_f195_salary_exhibits` | 800K+ | 2013-14+ (state/local split 2019-20+) |
| `fiscal_f196_summary` | 182K | 2013-14 through 2024-25 |
| `fiscal_f196_program_activity_object_detail` | 730K | 2013-14+ |
| `fiscal_f196_budgetary_comparison` | 200K+ | 2013-14+ |
| `fiscal_f196_indirect_rate` | 104K | 2013-14+ |
| `fiscal_f196_indirect_rate_detail` | 166K | 2013-14+ |
| `fiscal_apportionment_monthly` | 984K | 2013-14+ (partial 2025-26) |
| `fiscal_apportionment_monthly_estimated` | ~1M | 2013-14+ |
| `fiscal_apportionment_final` | 77K | 2013-14 through 2024-25 |

`class_of` covers most tables from 2014 through 2025 (i.e., school years
`2013-2014` through `2024-2025`). F-195 Budget also has 2025-2026
coverage. Newer doc kinds (NCES Object, GF By Sub-Fund) start at
2019-20. Older doc kinds (1159 Staff Ratios, F-196 Unaudited, Food
Service) stopped being published mid-corpus.

## Data type conventions

- **Decimals over IEEE floats.** All money and rate values use
  `decimal` (BigQuery `NUMERIC` = precision 38, scale 9). Consumers who
  need to sum across large districts should stay in `Decimal` too
  rather than round-tripping to float.
- **Negative signs are printed.** OSPI credits use a leading `-` in the
  source PDF; the parsers preserve sign. Credit Transfer object codes
  (object 1) are consistently negative.
- **NULL vs 0.** Newer form vintages fill non-applicable cells with
  `0.00`; older ones leave them blank. Parsers preserve the distinction
  where it matters (blank -> NULL `value`, `0.00` -> Decimal 0).
- **Codes as strings.** OSPI codes (`program_code`, `activity_code`,
  `object_code`, `account_code`) are stored as strings rather than
  integers because some codes have leading zeros or non-numeric
  characters ("419801", "SB", "CP"). Sort as strings.

## Data quality — form-internal errors

The parsers pass identity checks on ~100% of files where the source
PDFs are internally consistent, but OSPI's forms carry some data-entry
errors and vintage-transition quirks. See TODO.md's "Coverage gaps"
section for the complete list. Highlights:

- 177 F-195 salary_exhibits source PDFs (4.5%) have duplicate
  `PP-AA-DDD` duty-code rows within an activity; the parser's
  logical-key dedup keeps the first row.
- ~32 F-195 expenditure_by_program source PDFs (2014-15 vintage
  transition) have duplicate `code=45`/`code=46` rows in the Skill
  Center section.
- ~9% of `fiscal_f196_indirect_rate_detail` files have Total Program
  97 identity mismatches -- OSPI form-internal data-entry errors on
  specific activity rows.
- `fiscal_food_service` stops at 2018-19 (OSPI discontinued the
  report). `fiscal_1159_staff_ratio` stops at 2015-16
  (McCleary/prototypical-school funding rewrite).
- 2,842 `fiscal_apportionment_monthly` source PDFs (5.5%) produce
  0 rows -- OSPI cover-memo PDFs sharing the filename convention.

None of the above are parser bugs; they are documented so consumers
can filter out or flag anomalies without doubting the parsers.

## Regenerating the CSVs

Each fact table has a top-level driver script `extract_*.py` at the
fiscal root that walks the corpus and emits CSV to stdout. Typical
invocation:

```console
$ venv/bin/python3 -m extractors.fiscal.extract_f196_all_pages \
    data/fiscal/fiscal/ --format csv \
    > out_fiscal/fiscal_f196_summary.csv
```

Drivers use [`parallel.py`](parallel.py) for a multiprocessing.Pool
sized to `ncpu-1`. Big corpora (F-196 All Pages, monthly Apportionment)
take 30-70 minutes on a modern laptop. The F-195 Budget corpus takes
~35 minutes.

After all fact CSVs are generated, run
[`build_sources.py`](build_sources.py) once to write
`d_fiscal_source.csv` (the source-dimension table) and rewrite each
fact CSV's `_source` string column to an integer `_source_id` foreign
key.

## Related documentation

- [CSV_GUIDE.md](CSV_GUIDE.md) — per-table schema, join key, and
  parser notes (the reference).
- [TODO.md](TODO.md) — deferred sub-reports and per-table coverage
  gaps with rationale.
- [`schemas/`](schemas/) — Python schema modules that are the source
  of truth for field docs (converted to SQLAlchemy `Table` and to AVRO
  by the SAFS pipeline's `orm.py` and `avro_schema.py`).
- [`parsers/common.py`](parsers/common.py) — shared PDF-parsing
  helpers (dash normalization, digit-fragmentation repair,
  parenthesized-negative parsing, dot-leader handling).
