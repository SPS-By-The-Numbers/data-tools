# SAFS raw vs Fiscal PDF: what each covers, and what to reach for first

OSPI publishes the same district financial data twice — once as raw
tables in Microsoft Access `.accdb`/`.mdb` files (the **SAFS raw**
path), and once as printed PDFs (the **fiscal PDF** path). This repo
extracts both, but they capture **different slices** of the underlying
data.

**Start with SAFS raw.** Almost all top-level analysis — budget vs
actuals, per-(program × activity × object × NCES × school × sub-fund)
expenditures, per-account revenues with pre-attributed target programs,
four-year forecasts — is available from the SAFS pipeline outputs
under `safs_prod/f19x/`. That path is faster, more stable, updates on
OSPI's filing cadence, and has richer analytical dimensions than the
PDF path (per-school, sub-fund, NCES).

Only reach for the fiscal PDF path when you need one of the dimensions
that only lives on the printed forms: salary/staff detail per duty
code, balance sheet, long-term debt, mid-year revised (Final) Budget,
federal indirect rate calculation, edit-check quality flags, or any of
the smaller apportionment/1191/F-780/1191SI reports. Those are documented
in [OVERVIEW.md](OVERVIEW.md) and cataloged in [CSV_GUIDE.md](CSV_GUIDE.md).

## The two paths at a glance

```
     Districts submit ---> OSPI
                            |
                            +--> SAFS Access .accdb  ---> extractors/safs/  ---> Postgres staging
                            |                              orm.py / transforms/     |
                            |                                                       v
                            |                                             safs_prod/f19x/*.avro
                            |                                             (canonical, decoded,
                            |                                              per-school + NCES + sub-fund)
                            |
                            +--> Published PDFs      ---> extractors/fiscal/ ---> CSV out_fiscal/
                                (F-195 Budget,                                    fiscal_f195_*, fiscal_f196_*,
                                 F-196 All Pages,                                 fiscal_apportionment_*
                                 Apportionment,
                                 1191*, F-780, etc)
```

**When code says "SAFS raw", prefer the canonical avros** in
`safs_prod/f19x/*.avro` over parsing `.accdb` files directly. The
avros have joined dimension tables, decoded labels for every code,
and `data_type` fields distinguishing actuals from budget in one
uniform place. See [Recipes](#recipes-from-safs-raw-only) below for
examples.

## What's in the SAFS canonical avros

Under `safs_prod/f19x/`:

**`general_fund_expenditures.avro`** — the P×A×O cube, plus NCES,
sub-fund, and per-school grain (2019-20+). Both `data_type='budget'`
and `data_type='actuals'` in one table. Every code carries its decoded
label alongside (`program_code` + `program`, `activity_code` +
`activity`, etc.). This single table replaces most of what the fiscal
`fiscal_f195_program_activity_object_detail` and
`fiscal_f196_program_activity_object_detail` PDFs give you.

**`general_fund_revenues.avro`** — per-account revenues with:
- `revenue_code` + `revenue` (4-digit OSPI account with label)
- `category_code` + `category` (State-General / State-Special /
  Federal-General / Federal-Special / Local-Taxes / Local-Non-Tax /
  Other-Financing / Revenues-from-Other-Entities / etc.)
- **`program_code` + `program` — target program per OSPI's 1191F
  apportionment methodology.** Value `0` with label
  `"[special] Unrestricted"` marks fungible accounts (e.g. Account
  3100 Apportionment, Account 1100 Local Property Tax). All others
  route to a specific program (e.g. Account 4121 → Program 21,
  Account 6151 → Program 51).
- `amount`

**This is a big deal.** The revenue→program attribution that we used
to have to derive from `fiscal_f196_resource_to_program` (a PDF-only
sub-report) is already baked into the SAFS canonical avros. That
means the revenue→program→activity→object Sankey (see
`analysis/sps_sankey_avro.py` `spao_safs_only_variant`) can be built
end-to-end from just these two avros — no PDFs needed.

**`capital_project_revenues.avro`, `debt_service_revenues.avro`,
`trans_vehicle_revenues.avro`** — the same shape but for CP / DS / TVF
funds.

**`budget_items.avro`, `actuals_items.avro`** — per-item totals (the
`ItemNumbers` roll-up) with decoded item-code labels.

Every avro table joins to the source `.accdb` via `_source` /
`_source_table` for traceability.

## Recipes (from SAFS raw only)

Use these patterns as the default. They avoid the fiscal PDF path
entirely and are faster to iterate on.

### Per-program actuals across P × A × O × NCES × school

```python
import fastavro
from decimal import Decimal
from collections import defaultdict

cube = defaultdict(Decimal)
with open("safs_prod/f19x/general_fund_expenditures.avro", "rb") as f:
    for r in fastavro.reader(f):
        if (r["ccddd"] == 17001                        # Seattle
                and r["school_year"] == "2024-2025"
                and r["data_type"] == "actuals"):
            key = (r["program_code"], r["activity_code"],
                   r["object_code"], r["nces_code"], r["school_code"])
            cube[key] += Decimal(r["amount"] or 0)
```

### Revenue → program attribution

```python
directed = []      # revenue accounts with OSPI-designated target program
fungible = []      # program_code == 0 "[special] Unrestricted"
with open("safs_prod/f19x/general_fund_revenues.avro", "rb") as f:
    for r in fastavro.reader(f):
        if r["ccddd"] == 17001 and r["school_year"] == "2024-2025" \
                and r["data_type"] == "actuals":
            row = {"revenue_code": r["revenue_code"], "amount": Decimal(r["amount"] or 0),
                   "program_code": r["program_code"], "category": r["category"]}
            (fungible if r["program_code"] in (0, None) else directed).append(row)
```

Then distribute `directed` amounts to their target programs directly,
and `fungible` amounts proportionally to remaining program capacity.
See the three-pass algorithm in
[`analysis/sps_sankey_avro.py:spao_safs_only_variant`](../../analysis/sps_sankey_avro.py)
for the reference implementation.

### Budget vs Actuals per (program, activity, object)

Both are in the same avro. Filter by `data_type` and diff:

```python
# Two passes: build the two cubes, then compare on the shared key.
def build(dtype):
    c = defaultdict(Decimal)
    with open("safs_prod/f19x/general_fund_expenditures.avro", "rb") as f:
        for r in fastavro.reader(f):
            if r["ccddd"] == 17001 and r["school_year"] == "2024-2025" \
                    and r["data_type"] == dtype:
                c[(r["program_code"], r["activity_code"], r["object_code"])] \
                    += Decimal(r["amount"] or 0)
    return c

budget = build("budget")
actual = build("actuals")
for key in sorted(set(budget) | set(actual)):
    b, a = budget.get(key, 0), actual.get(key, 0)
    print(key, f"budget={b}  actual={a}  variance={a - b}")
```

### Per-school breakdown

`general_fund_expenditures.avro` has `school_code` + `school` +
`is_district_office` on every row (per-school data via the underlying
`ActualsChildGeneralFundExpenditures` table for 2019-20+). Just
group by `school_code` — the fiscal PDF path does not carry per-
school grain.

### NCES-category breakdown

`nces_code` + `nces` (label) are on the same avro. Group by
`nces_code` for federal-comparable object categories (much finer
than the 7 OSPI object codes).

### Sub-fund (Basic Ed vs Non-Basic-Ed) breakdown

`sub_fund_code` + `sub_fund` are on the same avro (2019-20+). Group
by `sub_fund_code`. The PDF equivalent is `fiscal_f196_gf_by_subfund`
but you don't need it — the SAFS avro has more grain.

## What still needs the fiscal PDF path

These dimensions genuinely don't exist in SAFS raw. If you need them,
parse the PDFs (see [OVERVIEW.md](OVERVIEW.md) and
[CSV_GUIDE.md](CSV_GUIDE.md) for the tables).

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
number appears. Consumers doing tight budget-vs-actuals reconciliation
want it in addition to the SAFS-raw budget baseline.

## Previously PDF-only, now available from SAFS raw

Two dimensions moved off this list once we discovered that the SAFS
staging pipeline had already extracted them:

- **Per-program funding-source attribution** (state / federal / other):
  we used to derive from `fiscal_f196_resource_to_program`. Now use
  the `program_code` field on every row of
  `safs_prod/f19x/general_fund_revenues.avro` — OSPI's own 1191F
  attribution, encoded per revenue account.
- **Per-program × per-activity × per-object cube**: was thought to
  require `fiscal_f19{5,6}_program_activity_object_detail`; actually
  available in `general_fund_expenditures.avro` directly, with more
  grain (adds NCES, sub-fund, per-school).

If you find another dimension that's supposedly PDF-only but is
actually in the SAFS raw path, please update this table.

## When to still parse the fiscal PDFs

Beyond the "PDF-only" table above:

1. **Cross-validation.** The fiscal_* tables reconcile to the SAFS
   avros on overlapping dimensions to the penny. If a SAFS-based
   analysis gives a number that seems off, the fiscal PDF path is a
   useful independent check. Any known reconciliation gaps are in
   [TODO.md](TODO.md)'s coverage-gaps section, keyed to the specific
   file / district / year.
2. **Printed labels and formulas.** The PDF path preserves OSPI's
   printed section headers, item labels, and derivation formulas.
   For audit or explanation purposes those are useful even when the
   underlying number is in SAFS raw too.
3. **Non-district entities.** Certain data (Report 1191SI State
   Institutions, ESD allocations, Technical Colleges) doesn't flow
   through SAFS at all — it's only in the fiscal PDF path.

## Item domain completion

A minor known gap on the SAFS raw path: `ITEMDIC1` (F-195) and the
`-item_dictionary.xlsx` sidecar (F-196 2018-19+) have gaps.
Coverage of value codes appearing in `*ItemNumbers` value tables:

- F-195: 93-100% per year (0-14 codes missing description per year)
- F-196 (2013-14 through 2017-18, in-accdb Item Dictionary): ~100%
- F-196 (2018-19 onward, sidecar xlsx): 99.9%+ — **but the pipeline
  does not currently load the sidecar xlsx files**, so item
  descriptions for those years fall through the dedup logic in
  [`transforms/f19x.py`](../safs/transforms/f19x.py).

The biggest single lift to close this gap is to load the sidecar xlsx
files into the SAFS pipeline. Suggested plan:

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

Estimated effort: 3-5 engineering days for full 100% coverage.

## Case study: revenue → expenditure Sankey

The Sankey work in `analysis/sps_sankey_avro.py` demonstrates the
SAFS-first pattern end-to-end for Seattle 2024-25. Five variants use
only the two canonical avros above (`spao_safs_only_variant` is the
purest example) and reconcile every program's inflow to its outflow
to the penny, with a synthetic "Fund Balance Drawdown" node absorbing
the deficit-spending gap. Earlier variants that predate the discovery
of SAFS's `program_code` attribution use `fiscal_f196_resource_to_program`
via `out_fiscal/*.csv` and produce the same result — but require the
fiscal PDF pipeline to have been run first.

The lesson: when starting a new analysis, look at
`safs_prod/f19x/*.avro` first. If everything you need is there, skip
the fiscal PDF path entirely.
