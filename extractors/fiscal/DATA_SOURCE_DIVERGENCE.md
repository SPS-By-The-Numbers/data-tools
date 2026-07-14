# SAFS raw vs Fiscal PDF: two paths, different coverage

OSPI publishes the same district financial data twice — once as raw
tables in Microsoft Access `.accdb`/`.mdb` files (the **SAFS raw**
path), and once as printed PDFs (the **fiscal PDF** path). This repo
extracts both, but they capture **different slices** of the underlying
data. This doc explains what each path has, where they overlap, and
which one to prefer for a given question.

If you only need the top-level numbers (revenues per fund, expenditures
per program × activity × object, per-item totals) — **use the SAFS raw
path**. It's faster, more stable, and OSPI intends it as the machine-
readable interface. If you need staff/salary detail, balance sheets,
mid-year budget revisions, or anything that only appears on the printed
form — **you need the fiscal PDF path**.

## The two paths at a glance

```
     Districts submit ---> OSPI
                            |
                            +--> SAFS Access .accdb  ---> extractors/safs/  ---> BigQuery (safs_*)
                            |                                                    d_budget_item / d_actuals_item
                            |                                                    general_fund_expenditures / etc.
                            |
                            +--> Published PDFs      ---> extractors/fiscal/ ---> CSV out_fiscal/
                                (F-195 Budget,                                    fiscal_f195_*, fiscal_f196_*,
                                 F-196 All Pages,                                 fiscal_apportionment_*
                                 Apportionment,
                                 1191*, F-780, etc)
```

The SAFS raw path is fed by a few dozen `.accdb`/`.mdb` files per year
(one per form kind) plus sidecar `-item_dictionary.xlsx` and
`-codes.xlsx` reference tables. The fiscal PDF path is fed by ~200K
PDFs per year and produces ~35 fact CSVs (see
[OVERVIEW.md](OVERVIEW.md)).

## What's in the SAFS raw path

Every F-195 `.accdb` contains these tables (names carry a year prefix
like `2022-2023` or `1819`):

- `BudgetItemNumbers` — flat `(CCDDD, FUND, ITEM, AMOUNT)` — 180+
  unique item codes per year.
- `BudgetGeneralFundExpenditures` — **`(CCDDD, PROGRAM, ACTIVITY,
  OBJECT, AMOUNT)`** — this is the full budget-side per-program ×
  per-activity × per-object cross-tab.
- `BudgetCapitalProjectRevenues`, `BudgetDebtServiceRevenues`,
  `BudgetGeneralFundRevenues`, `BudgetTransVehicleRevenues` — per-fund
  revenue detail by 4-digit account code.
- `F-195F All Districts` — four-year budget forecast (base year +
  3 forecast years).
- `ITEMDIC1` — item dictionary (code → description). Coverage varies
  93-100%; missing entries mostly show up as rows with empty
  `DESCRIPTION`. See [item domain notes](#item-domain-completion) below.
- `TL-ACTIVITY`, `TL-COUNTY`, `TL-FUND`, `TL-OBJECT`, `TL-PROGRAM`,
  `TL-REVENUE`, `TL-CCDDD` — dimension tables.

Every F-196 `.accdb` contains the parallel actuals tables:

- `ActualsItemNumbers` — flat item totals.
- `ActualsGeneralFundExpenditures` — full actuals-side `(CCDDD,
  FundCode, ProgramCode, ActivityCode, ObjectCode, Amount)`.
- `ActualsChildGenerlFundExpenditures` (2019-20+) — **per-school**
  breakdown with `SchoolCode`, `SubFundCode`, and `NCESCode` columns —
  a finer grain than the fiscal PDF tables capture.
- `ActualsRevenuesAndExpenditures` — union of all revenue + expenditure
  detail with `RevenueCode`, `ItemCode`, `ProgramCode`, `ActivityCode`,
  `ObjectCode` columns.
- `Actuals*Revenues` per fund.
- `Item Dictionary` (2013-14 through 2017-18 only; later years use
  sidecar `.xlsx` files).

The pipeline is orchestrated by [`load_safs.sh`](../../load_safs.sh) and
reads through [`extractors/safs/from_raw_file.py`](../safs/from_raw_file.py)
with per-form config in
[`extractors/safs/data_reader_config/f195.py`](../safs/data_reader_config/f195.py)
and [`extractors/safs/data_reader_config/f196.py`](../safs/data_reader_config/f196.py).
Transforms and dedup rules live in
[`extractors/safs/transforms/f19x.py`](../safs/transforms/f19x.py).

## What's in the fiscal PDF path

Everything documented in [OVERVIEW.md](OVERVIEW.md). ~35 fact tables
covering:

- All the same top-level dimensions the SAFS raw path has.
- Plus 15+ analytical dimensions that the SAFS raw does not carry (see
  next section).

## Coverage divergence

The fiscal PDF path was built because it captures dimensions the SAFS
raw path does not expose. Concretely:

### In SAFS raw and in fiscal PDF (both paths available)

For these questions, **prefer SAFS raw** — it's faster and more stable.

| Question | SAFS raw table | Fiscal PDF table |
|---|---|---|
| Budget per (program, activity, object) | `BudgetGeneralFundExpenditures` | `fiscal_f195_program_activity_object_detail` |
| Actuals per (program, activity, object) | `ActualsGeneralFundExpenditures` | `fiscal_f196_program_activity_object_detail` |
| Program × object cross-tab (budget) | derivable by pivot | `fiscal_f195_program_summary_by_object` |
| Program / activity / object roll-ups (actuals) | derivable by aggregation | `fiscal_f196_program_activity_object` |
| Revenues per 4-digit account (budget) | `Budget*Revenues` per fund | `fiscal_f195_budget[fund_revenue_detail]` |
| Revenues per 4-digit account (actuals) | `Actuals*Revenues` per fund | `fiscal_f196_revenues` |
| Item totals per fund | `BudgetItemNumbers` / `ActualsItemNumbers` | `fiscal_f195_budget[fund_summary]` / `fiscal_f196_summary` |
| Four-year budget forecast (F-195F) | `F-195F All Districts` | `fiscal_f195_four_year` |
| NCES-object expenditures per school | `ActualsChildGenerlFundExpenditures` (2019-20+, per-school!) | `fiscal_f196_nces_object` (district roll-up) |

Note that `ActualsChildGenerlFundExpenditures` in the SAFS raw path
gives you **per-school** granularity that the fiscal PDF path does not
capture — the fiscal_* tables are district-level only.

### Only in fiscal PDF path (SAFS raw does not carry the dimension)

These are the reason the fiscal PDF path exists. There is no SAFS raw
equivalent — you must parse the PDFs.

| Dimension | Fiscal PDF table |
|---|---|
| Per-duty-code salary detail (title, FTE, high/low/avg rate, state/local split) | `fiscal_f195_salary_exhibits` |
| FTE staff counts per activity (cert + class) | `fiscal_f195_staff_by_activity` |
| Debt service bond inventory (issue date, original amount, outstanding) | `fiscal_f195_debt_service_bonds` |
| Conditional sales contracts / long-term financing detail | `fiscal_f195_long_term_financing` |
| Levy math intermediates (fall/spring split, collection %) | `fiscal_f195_revenue_worksheet` |
| Balance Sheet (assets, deferred outflows, liabilities, fund balance) | `fiscal_f196_balance_sheet` |
| Long-term liabilities roll-forward (beg + issued − redeemed = end) | `fiscal_f196_long_term_liabilities` |
| **Mid-year revised (Final) Budget column** | `fiscal_f196_budgetary_comparison` |
| Per-program funding-source split (state / federal / other) | `fiscal_f196_resource_to_program` |
| Fiduciary funds (custodial + private purpose trust) | `fiscal_f196_fiduciary` |
| Data-quality edit-check results | `fiscal_f196_edit_report` |
| Data Requirements input items (indirect rate inputs, state recovery rate) | `fiscal_f196_data_requirements` |
| Federal Indirect Cost Rate calculation (the printed 14-line formula) | `fiscal_f196_indirect_rate` |
| Rate Schedule per-activity expenditures partition | `fiscal_f196_indirect_rate_detail` |
| Monthly Apportionment Statement (1197) | `fiscal_apportionment_monthly` |
| Monthly and Final 1191 Estimated Funding Report | `fiscal_apportionment_monthly_estimated`, `fiscal_apportionment_final` |
| Grants Administration (1191FG), SpEd (1220, 1220TR), Enrollment (1251), Transportation (F-780), Non-High Billing, State Institutions (1191SI), ESD allocations | `fiscal_1191fg_grants`, `fiscal_1220_sped`, `fiscal_1220_sped_transfer`, `fiscal_1251_enrollment`, `fiscal_f780_levy`, `fiscal_nonhigh_billing`, `fiscal_state_institutions`, `fiscal_food_service` |

The **Final Budget column** in `fiscal_f196_budgetary_comparison`
is worth calling out separately — it's the budget after mid-year
revisions, and it's the only place in either source path where that
number appears. Consumers doing budget-vs-actuals analysis want it.

## Which path to use

Use the SAFS raw path when:
- You want top-level per-item / per-account / per-program-activity-object
  totals.
- You need per-school granularity (only ActualsChildGenerlFundExpenditures
  has it).
- Freshness matters — Access DBs are published closer to the filing
  cadence than the printed PDFs.
- Reliability matters — Access DB schema drift is bounded; PDF text
  extraction has more moving parts.

Use the fiscal PDF path when:
- You need any of the dimensions in the "Only in fiscal PDF" table
  above.
- You want the printed labels / formulas / section context, not just
  the raw numbers.
- You want to cross-check the SAFS numbers against what OSPI actually
  published — the fiscal PDF numbers reconcile to the SAFS numbers to
  the cent on the overlapping dimensions.

Use **both** when:
- You want the deepest analytical view. `fiscal_f195_*` and
  `fiscal_f196_*` add the dimensions the SAFS raw doesn't have, while
  SAFS raw gives you faster access to the totals.

## Item domain completion

A recurring pain point on the SAFS raw path: `ITEMDIC1` (F-195) and
the `-item_dictionary.xlsx` sidecar (F-196 2018-19+) have gaps.
Coverage of value codes appearing in `*ItemNumbers` value tables:

- F-195: 93-100% per year (0-14 codes missing description per year)
- F-196 (2013-14 through 2017-18, in-accdb Item Dictionary): ~100%
- F-196 (2018-19 onward, sidecar xlsx): 99.9%+ — **but the pipeline
  does not currently load the sidecar xlsx files**, so item
  descriptions for those years fall through the dedup logic in
  [`transforms/f19x.py`](../safs/transforms/f19x.py).

The biggest single lift for making the SAFS raw path a viable
standalone data source is to close this gap. Suggested plan:

1. **Load the sidecar xlsx files.** Add `data/safs/f196/*item_dictionary.xlsx`
   to [`load_safs.sh`](../../load_safs.sh) and update the F-196 config
   in [`extractors/safs/data_reader_config/f196.py`](../safs/data_reader_config/f196.py)
   to route the item-dictionary sheet into `f196_item_dict`. Expected
   coverage: 95-98%.
2. **Multi-year fallback.** Update the SQL in
   [`transforms/f19x.py:647`](../safs/transforms/f19x.py) to fall back
   to earlier years when a current-year dict entry has an empty
   description. Expected coverage: 98-99%.
3. **Back-fill from fiscal_* tables.** For SAFS item codes that map to
   specific line items in the fiscal_* tables, use the fiscal PDF-
   derived label as a source of truth. Expected coverage: 99.5%+.
4. **Manual annotation.** Small CSV committed to the repo for the
   residual codes.

Estimated effort: 3-5 engineering days for full 100% coverage. Once
complete, the SAFS raw path becomes a viable standalone pipeline for
the top-level numbers, with the fiscal PDF path handling the
dimensions in the "Only in fiscal PDF" table.

## Cross-validation

The overlapping tables (fiscal_f195_program_activity_object_detail vs
BudgetGeneralFundExpenditures, etc.) can be cross-checked against
each other. If the two paths disagree on the same
`(school_year, ccddd, program, activity, object)` triple, either:
- OSPI published inconsistent data across the two channels (rare but
  documented in [TODO.md](TODO.md)'s "Coverage gaps"), or
- One of the parsers has a bug.

Any known reconciliation gaps are recorded in TODO.md's coverage-gaps
section, keyed to the specific file / district / year where the
discrepancy occurs.
