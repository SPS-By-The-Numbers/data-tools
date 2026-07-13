# extractors/fiscal -- known gaps and quirks

## Fact-table coverage (current)

Twenty-two fiscal fact tables now exist; see `CSV_GUIDE.md` for the
full catalog. F-196 All Pages sub-report coverage is essentially
complete for the analytically-important dimensions:

| Sub-report / phase | Table | Coverage |
|---|---|---|
| Page-2 SUMMARY (Phase 1) | `fiscal_f196_summary` | 2013-14+ |
| F-195 Budget: SUMMARY OF X FUND BUDGET (Phase 1) | `fiscal_f195_budget[fund_summary]` | 2013-14+ |
| F-195 Budget: EXPENDITURE BY PROGRAM (GF8) | `fiscal_f195_budget[expenditure_by_program]` | 2013-14+ |
| F-195 Budget: SUMMARY OF GF EXPENDITURES BY OBJECT (GF10) | `fiscal_f195_budget[expenditure_by_object_summary]` | 2013-14+ |
| F-195 Budget: SUMMARY OF GF EXPENDITURES BY ACTIVITY (GF11) | `fiscal_f195_budget[expenditure_by_activity_summary]` | 2013-14+ |
| F-195 Budget: FY ENROLLMENT AND STAFF COUNTS (GF1) | `fiscal_f195_budget[enrollment_and_staff_counts]` | 2013-14+ |
| F-195 Budget: GENERAL FUND FINANCIAL SUMMARY | `fiscal_f195_budget[financial_summary]` | 2013-14+ |
| F-195 Budget: FTE Staff Counts by Activity (GF15) | `fiscal_f195_staff_by_activity` | 2013-14+ |
| F-195 Budget: Per-fund revenue detail (GF4/DS2/CP3) | `fiscal_f195_budget[fund_revenue_detail]` | 2013-14+ |
| F-195 Budget: Long-Term Financing (GF14/CP9/TVF4) | `fiscal_f195_long_term_financing` | 2013-14+ |
| F-195 Budget: Debt Service Outstanding Bonds (DS4) | `fiscal_f195_debt_service_bonds` | 2013-14+ |
| F-195 Budget: Revenue Worksheet (GF13/DS3/CP5/TVF3) | `fiscal_f195_revenue_worksheet` | 2013-14+ |
| F-195 Budget: Program-by-Object cross-tab (GF9) | `fiscal_f195_program_summary_by_object` | 2013-14+ |
| F-195 Budget: Salary Exhibits (GF9-201-XX cert / GF9-301-XX class / CP-7 / CP-8) | `fiscal_f195_salary_exhibits` | 2013-14+ |
| F-195 Budget: Objects-of-Expenditure per program (GF9-XX) | `fiscal_f195_program_activity_object_detail` | 2013-14+ |
| Report of Revenues (Phase 2a) | `fiscal_f196_revenues` | 2013-14+ |
| Budgetary Comparison Schedule (Phase 2b) | `fiscal_f196_budgetary_comparison` | 2013-14+ |
| Program/Activity/Object Roll-up (Phase 2c-i) | `fiscal_f196_program_activity_object` | 2013-14+ |
| Program/Activity/Object per-PROGRAM cross-tab (Phase 2c-ii+) | `fiscal_f196_program_activity_object_detail` | 2013-14+ |
| Balance Sheet - Governmental Funds (Phase 2c-ii-BS) | `fiscal_f196_balance_sheet` | 2013-14+ |
| Schedule of Long-Term Liabilities (Phase 2c-ii-LTL) | `fiscal_f196_long_term_liabilities` | 2013-14+ |
| Resource to Program Expenditure (Phase 2c-ii-R2P) | `fiscal_f196_resource_to_program` | 2013-14+ |
| NCES Object Expenditure (Phase 2c-ii-NCES) | `fiscal_f196_nces_object` | 2019-20+ |
| Fiduciary Funds (Phase 2c-ii-FID) | `fiscal_f196_fiduciary` | 2013-14+ |
| GF By Sub-Fund (Phase 2c-ii-SFB) | `fiscal_f196_gf_by_subfund` | 2019-20+ |
| Financial Edit Report (Phase 2c-ii-EDIT) | `fiscal_f196_edit_report` | 2013-14+ |
| Data Requirements (Phase 2c-ii-DR) | `fiscal_f196_data_requirements` | 2013-14+ |
| Federal Indirect Cost Rate (Phase 2c-ii-IR) | `fiscal_f196_indirect_rate` | 2013-14+ |
| Federal Indirect Cost Rate p1 expenditures partition (Phase 2c-ii-IR-DTL) | `fiscal_f196_indirect_rate_detail` | 2013-14+ |

The remaining un-parsed F-196 sub-reports are documented below with
deferral rationale. Every parser above has passed its per-file
identity checks (accounting, roll-forward, funding-source,
cross-checks against `fiscal_f196_summary`); the tiny number of
mismatches are OSPI form-internal errors, not parser bugs.

## Parsers not yet built

Within `apportionment/` (147,244 files), the District / College / State
Agency monthly Statement table (51,985 files, page 1 only) is parsed.
Outstanding:

- **Apportionment allocation forms** -- coverage below.
  Done:
  - `Final Apportionment Summary` (3,732 district-level files)
    -> `fiscal_apportionment_final`. **Headline-only** parser (as
    the "Deferred" section previously indicated the compound doc
    was too big to fully parse). Captures per-Account "Total Amount
    to be Paid / Total Amount Due / Calculated Allotment" lines,
    keyed by (source, account_code, item_ordinal). Sub-report codes
    (1191F/1191EEF/1191MSCTEF/1191SCF/1191FSF/1191SEF/1191TRNF/
    1191CTER) are captured but positional -- the intermediate
    per-item derivation (staffing units, per-pupil formulas) is NOT
    captured; consumers should reference the source PDF directly for
    a specific district's audit. Account attribution on the joint
    "Account XXXX & YYYY" banners (4198 & 419801; 4199 & 4499) uses
    the first account code -- 4499 lines merge into the 4199 group
    for the Transportation section.
  - `Non-High Billing` (1,584 files) -> `fiscal_nonhigh_billing`.
  - `1191FG Grants Administration` (~4,200 unique-after-ESD-dedup
    files; ~7,700 raw including ESD replication) ->
    `fiscal_1191fg_grants`.
  - `1220 Special Education Allocation` (2,122 district-level files)
    -> `fiscal_1220_sped`.
  - `1159 K12 Staff Ratios` (901 district-level files, 2013-14
    through 2015-16; OSPI discontinued after McCleary funding
    rewrite) -> `fiscal_1159_staff_ratio`.
  - `F-196 Unaudited` (594 district-level files, 2013-14 and
    2014-15 only; later years' unaudited filings live under
    `data/fiscal/fiscal/` as `F-196 All Pages`) ->
    `fiscal_f196_unaudited_summary` (page-2 SUMMARY block only).
- **Report 1220TR ESD SpEd Transfer of Allocation** -- **DONE**.
  Parser populates `fiscal_1220_sped_transfer` (2013-14 through
  2016-17). The corpus has 1220TR files for **ESD 112 only**;
  the other 8 ESDs' scrapes did not pull the 1220TR form (all
  ESD-path 1220 files are for 06801 ESD 112 across 4 years). 120
  raw files, 4 unique (year, ESD) reports after dedup. Per-member-
  district breakdown of Accounts 3121 / 4121 / 4122 transfers plus
  TOTAL TRANSFERRED / SAFETY NET / GRAND TOTAL summary rows. Sum
  identity `TOTAL 4121 + SAFETY NET = GRAND TOTAL` reconciles on
  all 4 files.
- **ESD-aggregate 1251 enrollment** -- DEFERRED. The 1251 FTE PDFs
  under `apportionment/YYYY/esd/{esd_dir}/{member}/` do carry ESD-
  level aggregate data (63 pages of monthly enrollment breakdowns
  per grade / program / grade span / etc.), but the same data can
  be derived by summing member districts in `fiscal_1251_enrollment`.
  The value-add is bounded to reconciling OSPI's ESD-level totals
  against the district-level sums (~117 unique ESD-year files after
  dedup). If a specific reconciliation use case appears, build
  `fiscal_1251_enrollment_esd` with a minimal parser that captures
  only the p1 K-12 grade table (the main headline data point).
- **Pages 2+ of the monthly Statement** -- DEFERRED. The 40+ pages of
  per-account computation detail (school-generated entitlement
  formulas, etc.) we currently skip via `read_pdf_lines(max_pages=1)`.
  The headline Allotment for {Month} number is already captured; the
  year-end Final version of the same per-account derivation is now
  captured (headline-only) as `fiscal_apportionment_final`. Full
  per-item derivation is not captured -- extremely low ratio of
  parsing complexity to analytical value; consumers should reference
  the source PDF directly for a specific district's audit.

Within `fiscal/` (17,101 files), one high-volume doc kind remains
**partially parsed** (Phase 1 done):

- **F-196 All Pages -- Phase 1 (page-2 SUMMARY block)**: DONE. Parser
  populates `fiscal_f196_summary` across all 12 years (2013-14 through
  2024-25, 3,724 files). Replaces the standalone F-196 Summary parser
  (which only covered 2021-22+). Extends backward coverage to 2013-14.
- **F-196 All Pages -- Phase 2a (Report of Revenues and Other Financing
  Sources)**: DONE. Parser populates `fiscal_f196_revenues` -- per-OSPI
  4-digit revenue account code per fund (4 funds: general, debt_service,
  capital_projects, transportation_vehicle). 7-9 pages per PDF (pp ~23-31
  typical). 2013-14 through 2024-25.
- **F-196 All Pages -- Phase 2b (Budgetary Comparison Schedule)**: DONE.
  Parser populates `fiscal_f196_budgetary_comparison` -- per-fund Final
  Budget / Actual / Variance line items (5 funds: general, asb,
  debt_service, capital_projects, transportation_vehicle). ~10 pages
  per PDF (2 pages per fund). 2013-14 through 2024-25. **The Final
  Budget column is the unique contribution -- the budget after mid-year
  revisions, not captured anywhere else in the corpus.** Pairs with
  fiscal_f195_budget to trace original -> final -> actual -> variance.
- **F-196 All Pages -- Phase 2c-i (Program/Activity/Object Report
  roll-up)**: DONE. Parser populates
  `fiscal_f196_program_activity_object` -- three side-by-side General
  Fund expenditure breakdowns (per program, per activity, per object)
  per district. 2 pages per PDF (pp 30-31). 2013-14 through 2024-25.
  Delivers the **per-Object breakdown** (Cert Salaries / Class Salaries
  / Employee Benefits / Supplies / Purchased Services / etc) that is
  not available in any other captured sub-report.
- **F-196 All Pages -- Phase 2c-ii-BS (Balance Sheet)**: DONE. Parser
  populates `fiscal_f196_balance_sheet` -- per-fund period-end assets,
  deferred outflows, liabilities, deferred inflows, and fund balance
  from the Balance Sheet - Governmental Funds sub-report (pp 3-5).
  2013-14 through 2024-25, 3,724 files, 1,173,585 rows. **This is the
  balance-sheet dimension of the corpus** -- no other captured
  sub-report exposes stocks (assets/liabilities); SUMMARY and Revenues
  capture flows. Enables working-capital, solvency, and inter-fund
  receivable/payable analysis.
- **F-196 All Pages -- Phase 2c-ii-LTL (Long-Term Liabilities)**: DONE.
  Parser populates `fiscal_f196_long_term_liabilities` -- per-district
  long-term debt roll-forward (beg + issued - redeemed = end) plus
  the current portion (Amount Due Within One Year), per liability
  item (bonds, leases, notes, compensated absences, pension
  liabilities). 2013-14 through 2024-25, 3,724 files, 107,622 rows.
  Handles both form vintages: per-fund (2013-14 through 2018-19,
  4 pages) and combined (2019-20+, 1 page). Fund attributed by
  banner label in 2013-14, by page order in 2015-16 through 2018-19,
  and set to 'combined' in newer vintages. **The unique analytical
  contribution** is the debt roll-forward dimension -- no other
  captured sub-report tracks the beg-to-end flow or the current
  portion of long-term debt.
- **F-196 All Pages -- Phase 2c-ii-R2P (Resource-to-Program)**: DONE.
  Parser populates `fiscal_f196_resource_to_program` -- per-program
  General-Fund expenditures decomposed by funding source (state /
  federal / other). 2013-14 through 2024-25, 3,724 files, 203,637 rows.
  **The unique analytical contribution** is the funding-source
  dimension per program -- `fiscal_f196_program_activity_object`
  reports totals per program but not per funding source, and
  `fiscal_f196_revenues` reports revenues per account code but not
  per program. Grand-total cross-check against
  `fiscal_f196_summary.total_expenditures[general]` matches to the
  cent on 100% of files. Handles trailing-digit value-wrap on
  Seattle-scale 10-figure General Fund totals.
- **F-196 All Pages -- Phase 2c-ii-NCES (NCES Object Expenditure)**:
  DONE. Parser populates `fiscal_f196_nces_object` -- per-NCES-4-digit-
  object-code General-Fund expenditures using the federal NCES
  Financial Accounting Handbook (Fin13) categories. 2019-20 through
  2024-25, 1,902 files, 184,814 rows (**sub-report did not exist
  before 2019-20**; older files correctly produce no rows). 7 sections
  (Certificated Salaries, Classified Salaries, Employee
  Benefits/Payroll Taxes, Supplies Non-Capital, Purchased Services,
  Travel, Capital Outlay) plus a single grand-total. **The unique
  analytical contribution** is federally-standardized object codes
  that enable cross-state comparison, distinct from
  `fiscal_f196_program_activity_object`'s OSPI-specific 10-code
  object list. Detail-sum matches grand total on 100% of files;
  grand total matches
  `fiscal_f196_summary.total_expenditures[general]` on 100%.
- **F-196 All Pages -- Phase 2c-ii-DR (Data Requirements)**: DONE.
  Parser populates `fiscal_f196_data_requirements` -- three combined
  Data Requirements sub-reports: Supplemental Reports (p 66),
  End-of-Year Reporting to Apportionment + State Recovery Rate (p 67),
  and Federal Indirect Cost Data (pp 68-71). 2013-14 through 2024-25,
  3,724 files, 159,680 rows. **The unique analytical contribution**
  is the district-input dimension that feeds the indirect cost rate
  and state recovery rate calculations. `report_kind` distinguishes
  the three sub-reports; captures numeric AND textual values
  (e.g. 'Yes'/'No' on the Inflationary Adjustment Index
  certification). The State Recovery Rate itself (item 2 of
  apportionment_recovery, SYSTEM CALCULATED) is a valuable
  analytical output.
- **F-196 All Pages -- Phase 2c-ii-IR (Indirect Cost Rate)**: DONE.
  Parser populates `fiscal_f196_indirect_rate` -- the 14-line rate
  calculation from both the Restricted (pp 72-73) and Unrestricted
  (pp 74-75) Federal Indirect Cost Rate Schedules. 2013-14 through
  2024-25, 3,724 files, 104,272 rows (exactly 14 restricted +
  14 unrestricted lines per file). **The unique analytical
  contribution** is the calculated indirect rate itself -- Line 5
  is the base-FY rate applied in this filing FY, and Line 14 is the
  newly-calculated rate to apply in a future FY. Both flavors
  captured for every year. Per-program/activity expenditures
  breakdown on page 1 of each schedule is NOT captured -- structurally
  similar to fiscal_f196_program_activity_object; defer to future
  work if needed.
- **F-196 All Pages -- Phase 2c-ii-EDIT (Financial Edit Report)**:
  DONE. Parser populates `fiscal_f196_edit_report` -- per-fund
  per-edit data-quality check results (edit type / number / message
  / 2 supporting amounts) plus is_cleared markers for funds with no
  flagged edits. 2013-14 through 2024-25, 3,724 files, 55,820 rows
  (36,715 informational + 180 warnings + 18,925 cleared). **The
  unique analytical contribution** is the data-quality dimension --
  no other captured report exposes OSPI's post-submission edit
  checks. Consumers can filter to `edit_type='warning'` to identify
  potentially misfiled reports. Handles both vintage abbreviation
  (2013-14 `Info` → canonicalized to `informational`; 2013-14
  `Warn` → `warning`) and per-vintage column x-position drift
  (message column x0=164 pre-2020 vs x0=215 post-2020). All 7
  fund sections (general, asb, debt_service, capital_projects,
  transportation_vehicle, permanent, fiduciary) represented on
  100% of files.
- **F-196 All Pages -- Phase 2c-ii-SFB (GF By Sub-Fund)**: DONE.
  Parser populates `fiscal_f196_gf_by_subfund` -- General Fund
  broken out by Sub-Fund 10 (Basic Education) vs Sub-Fund 11
  (Non-Basic-Education) vs General Fund total from the 'Statement of
  Revenues, Expenditures, and Changes in Fund Balance - General Fund,
  By Sub-Fund' sub-report (pp 8-9). 2019-20 through 2024-25, 1,902
  files, 170,247 rows (**sub-report did not exist before 2019-20**;
  older files correctly produce no rows). **The unique analytical
  contribution** is the sub-fund decomposition -- no other captured
  report splits the General Fund into Basic-Ed vs Non-Basic-Ed
  spending, which is a fundamental K-12 funding-analysis dimension.
  Additivity `SF10 + SF11 = GF` holds on 100% of 51,043 cross-fund
  checks; ending_total_fund_balance matches
  `fiscal_f196_summary.ending_total_fund_balance[general]` on 100%
  of files.
- **F-196 All Pages -- Phase 2c-ii-FID (Fiduciary Funds)**: DONE.
  Parser populates `fiscal_f196_fiduciary` -- per-fund balance sheet
  + income statement for fiduciary funds (custodial + private
  purpose trust). Combines the two adjacent sub-reports (Statement
  of Fiduciary Net Position + Statement of Changes in Fiduciary Net
  Position) into a single fact table with a `statement` field.
  2013-14 through 2024-25, 3,724 files, 352,970 rows. **The unique
  analytical contribution** is the fiduciary-fund dimension --
  governmental Balance Sheet covers 6 governmental funds; the
  fiduciary funds tracked here (private donations, student activity,
  scholarship endowments) use accrual-basis accounting. GASB 84
  vintage drift handled: pre-2019-20 form printed 'Private Purpose
  Trust + Other Trust'; 2019-20+ prints 'Custodial Funds + Private
  Purpose Trust' -- BOTH the column NAMES and ORDER changed. The
  parser detects column mapping per file and canonicalizes to
  `private_purpose_trust` / `custodial_funds` (with 'Other Trust'
  mapped to `custodial_funds` per GASB reclassification). Net-
  position identity (TA - TL = TNP) and changes roll-forward (beg
  + net_change + corrections = end) hold on **100%** of 7,448
  file×fund combos.
- **F-196 All Pages -- Phase 2c-ii+ (remaining sub-reports)**:
  - **Per-PROGRAM cross-tab detail** (pp 33+ typical, one page per
    General Fund program): **DONE.** Parser populates
    `fiscal_f196_program_activity_object_detail` -- per-district per-
    (program, activity, object) actual expenditures. 2013-14 through
    2024-25, 3,724 files, 730,094 rows. Ships as a **pair** with
    `fiscal_f195_program_activity_object_detail` (budget-side, GF9-XX)
    so consumers can query budget-vs-actuals per (program, activity,
    object). **The unique analytical contribution** is the deepest
    expenditure detail in the corpus -- previous captures had program
    OR activity OR object rollups (`fiscal_f196_program_activity_
    object`) but not the (program x activity x object) cross-tab.
    Parser handles two Seattle-scale wrap complexities that only
    appear on large districts' Program 97 (District-wide Support):
    (1) 10-figure values wrap 1-2 trailing digits to the next visual
    line, and (2) some columns wrap the whole value onto a follow-up
    line while their sign token remains on the parent line. Per-file
    per-program per-column identity (sum of details == program_total)
    reconciles on **100.000%** of 705,170 file×program×column checks
    (3 mismatches on 1 file -- Spokane 2022-23 program 97 debit
    transfer -- from an OSPI form-print truncation of the printed
    total row's trailing decimals).
  - **Rate Schedule per-program/activity breakdown** (pp 72 / 74, page
    1 of each Indirect Cost Rate schedule): **DONE.** Parser populates
    `fiscal_f196_indirect_rate_detail` (2013-14 through 2024-25, 3,724
    files, ~166,400 rows). Per-district per-rate_kind (restricted /
    unrestricted) 7-column partition per row_kind (programs_total /
    activity_detail / program_97_total). Positional column-anchor
    extraction handles blank cells across all vintages. Per-file per-
    rate_kind row-level sum identity `TOTAL = CAPITAL + DEBT +
    DISTORTING + UNALLOWABLE + INDIRECT + DIRECT` reconciles on
    ~91.2% of Total Program 97 rows; the ~8.8% failures are OSPI
    form-internal data-entry errors (activity-level row totals that
    don't match printed column values, e.g. Prosser 2013-14 activity
    14 Human Resources total=79,607.34 but printed indirect
    value=83,671.56). Not a parser bug -- the parser captures printed
    values verbatim.
  - **Statement of Revenues, Expenditures, and Changes in Fund Balance**
    (pp 5-6, 2 pages) -- intermediate-granularity rollup per fund x 6
    funds. **DEFERRED after re-review.** Structurally overlaps
    `fiscal_f196_budgetary_comparison[column_kind='actual']` (per-fund
    actuals across 5 funds) plus `fiscal_f196_summary` (fund_balance
    roll-forward) plus `fiscal_f196_revenues` (revenues by source).
    The unique add is per-fund CURRENT expenditures broken out by
    program-group (Regular Instruction / Special Ed / Vocational /
    Skill Center / Compensatory / Federal Stim / Community Services /
    Support Services / Student Activities) for the non-General funds
    -- which mostly zero out (ASB fund has only Student Activities,
    Debt Service fund has only DEBT SERVICE, Capital Projects fund
    has only CAPITAL OUTLAY, TVF has only Transportation Equipment).
    Permanent Fund actuals are the one novel dimension but are ~0 on
    all but a handful of districts. If a specific use case appears
    (e.g. auditing OSPI's fund-level rollup vs SUMMARY+Revenues
    reconciliation), build a minimal parser; otherwise defer.

The **F-195 Budget (full)** parser landed (-> `fiscal_f195_budget`) and
now captures **six sub-reports** covering the full breadth of General
Fund budget analysis plus the per-fund SUMMARY block for all 5 funds.
The same parser runs against F-195 Budget Overview (which contains the
same six sub-reports across its first ~30 pages), so both source kinds
populate the table.

Sub-reports done (2013-14 through 2025-26 coverage on all district-level
files):

- **`fund_summary`** -- SUMMARY OF X FUND BUDGET, all 5 funds (GF2, ASB1,
  DS1, CP1, TVF1). 3-col Actual/Budget/Budget.
- **`expenditure_by_program`** -- EXPENDITURE BY PROGRAM (GF8, pp 18-20
  typical). 3-col Actual/Budget/Budget. Per-OSPI-program-code General
  Fund expenditures grouped into program-group sections. **Provides the
  budget-side of `fiscal_f196_program_activity_object[breakdown_kind='program']`**
  -- enables budget-vs-actuals per program.
- **`expenditure_by_object_summary`** -- SUMMARY OF GENERAL FUND
  EXPENDITURES BY OBJECT OF EXPENDITURE (GF10). 6-col
  (Actual/%Total)x3-years cross-tab per OSPI object code (0..9).
  Budget-side of `fiscal_f196_program_activity_object[breakdown_kind='object']`.
- **`expenditure_by_activity_summary`** -- SUMMARY OF GENERAL FUND
  EXPENDITURES BY ACTIVITY (GF11). 6-col cross-tab per OSPI activity
  code, grouped into 5 activity-group sections. Budget-side of
  `fiscal_f196_program_activity_object[breakdown_kind='activity']`.
- **`enrollment_and_staff_counts`** -- FY ENROLLMENT AND STAFF COUNTS
  (GF1, p 7). 3-col Average/Budget/Budget enrollment counts per grade
  + certificated/classified staff FTE. Unique budget-side enrollment
  dimension; complements `fiscal_f195_four_year`.
- **`financial_summary`** -- GENERAL FUND FINANCIAL SUMMARY (pp 5-6).
  Mixed-shape (3-col + 6-col) headline rollup: enrollment + financial
  summary + expenditure-by-program-group / activity-group / object.
  High-density summary page useful for quick district-level comparisons.

The remaining ~24 sub-reports per F-195 Budget PDF are grouped below
by priority.

**Medium priority** (structurally larger, worth a dedicated table):

- ~~**Per-fund revenue detail** (GF4, DS2, CP3, TVF3 portion) --
  detailed revenue line items grouped by OSPI 4-digit account code.
  Budget-side of `fiscal_f196_revenues`. Will fold into
  `fiscal_f195_budget` as `sub_report = 'fund_revenue_detail'`.~~
  **DONE** for GF4/DS2/CP3 (general/debt_service/capital_projects funds).
  TVF revenues live inline on the SUMMARY OF TRANSPORTATION VEHICLE
  FUND BUDGET page, not a standalone sub-report -- captured as
  fund_summary detail rows already. Section slugs match
  `fiscal_f196_revenues` -- join on `(school_year, ccddd, fund,
  section, item_code)` for budget-vs-actuals per revenue account.
  Grand-total reconciles to fund_summary A. TOTAL REVENUES on 99.97%
  of 11,847 (file, fund) checks (4 OSPI form-internal discrepancies).
- ~~**PROGRAM SUMMARY BY OBJECT OF EXPENDITURE** (GF9, pp 21-24) --
  wide cross-tab of program x object.~~ **DONE** -- populates
  `fiscal_f195_program_summary_by_object` (235,365 rows across 3,961
  files). Value columns are per-object: `object_total`,
  `object_0_debit_transfer` ... `object_9_capital_outlay` (skipping
  the unused Object 6). Parsed via positional column-anchor
  extraction (anchors set from the first 10-value row seen in the
  PDF, typically the `OBJECT TOTALS` grand-total row); per-row
  identity `sum(9 objs) == object_total` on **100%** of detail rows.
  File-level identity `sum(details) == grand` holds on 92.5% of
  files -- 299 files (concentrated in 2015-16) have OSPI form-internal
  duplicate program-code rows (2 different programs printed with the
  same 2-digit code, e.g. two different `52` rows) which the parser's
  logical-key dedup collapses. This is the same class of form quirk
  as the 2014-15 Skill Center 45/46 duplicates in
  `fiscal_f195_budget[expenditure_by_program]`.
- ~~**SUMMARY OF FTE STAFF COUNTS BY ACTIVITY** (GF15) -- 4-col
  certificated/classified FTE by activity.~~ **DONE** -- populates
  `fiscal_f195_staff_by_activity` (120,918 rows across 3,963 files,
  2013-14 through 2025-26). Parsed via positional column-anchor
  extraction to handle the 2013-14/2014-15 form vintage's
  bare-blank-cell convention (older form prints blank instead of
  `XXXXX` for zero-staff activities, which a token-count parser would
  mis-bin). Sum-of-detail == grand total on 100% of files. Activity
  codes match `fiscal_f195_budget[expenditure_by_activity_summary]` --
  join on `(school_year, ccddd, activity_code)` for budget-per-FTE
  analysis.
- ~~**REVENUE WORK SHEET--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX**
  (GF13, DS3, CP5, TVF3) -- short worksheet, levy collection math.~~
  **DONE** -- populates `fiscal_f195_revenue_worksheet` (95,064 rows,
  24 per file × 3,961 files, 4 funds × 2 parts × 3 rows). Sections
  `local_property_tax` (Part I, Account 1100) and `timber_excise_tax`
  (Part II, Account 1500). TOTAL == fall + spring amount_budgeted
  reconciles exactly on ~93% of (file, fund, part) combos; the rest
  differ by $1-$2 (OSPI form-internal rounding, not parser bugs).
  Timber fall.amount_budgeted is consistently NULL by form design.
- ~~**LONG-TERM FINANCING -- CONDITIONAL SALES CONTRACTS** (GF14, CP9,
  TVF4) -- bond/contract detail by fund. Complements
  `fiscal_f196_long_term_liabilities`.~~ **DONE** -- populates
  `fiscal_f195_long_term_financing` (59,779 rows across 3,961 files,
  3 funds × 3-6 rows per fund per file). Sections: existing_contracts
  (A), new_contracts (B), summary (C). Value columns are
  section-neutral (`amount_beginning`, `principal_fy`, `interest_fy`,
  `amount_ending`) with per-section semantics in the schema doc.
  C.principal_fy / C.interest_fy / C.amount_ending reconcile to A+B on
  100% of files. 13 files (0.3%) have printed A.TOTAL amount_beginning
  != sum(A details) -- OSPI form-internal doubling on aggregated-
  contract detail rows (Pasco GF fund 2013-14 through 2023-24;
  Bainbridge Island GF fund 2024-25 and 2025-26).
- ~~**DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS** (DS4) --
  bond inventory.~~ **DONE** -- populates
  `fiscal_f195_debt_service_bonds` (15,312 rows across 3,391 files
  with outstanding bonds; the ~570 uncovered files have no bonds).
  Sections `voted_bonds` (A), `nonvoted_bonds` (B), `summary` (the
  combined TOTAL ALL BONDS row). All 6 identity checks (per-section
  TOTAL = sum of details; TOTAL ALL = V + NV, both amount columns)
  reconcile on 100% of files. Handles the ~4 files whose Section A
  detail row omits the date-of-issue token by relaxing to accept
  dateless 2-value rows within an active section.

**Deferred (large + paired):**

- ~~**OBJECTS OF EXPENDITURE per program** (GF9-XX, ~60 pages per PDF
  for large districts) -- per-program activity x object detail.~~
  **DONE** -- populates `fiscal_f195_program_activity_object_detail`.
  All 3,961 F-195 Budget PDFs covered (2013-14 through 2025-26),
  1,915,876 rows (1.72M detail + 125K program_total + 67K
  fte_program_staff). Per-district per-(program, activity, object)
  budgeted expenditures cross-tab; the deepest per-program budget
  breakdown available in the F-195. Ships as a **pair** with
  `fiscal_f196_program_activity_object_detail` (actuals-side, F-196
  per-PROGRAM cross-tab) so consumers can query budget-vs-actuals per
  (program, activity, object) with a single join on `(school_year,
  ccddd, program_code, activity_code)`. `row_kind` distinguishes
  activity detail (10 money columns per row), program subtotal (`Total`
  row for the program), and per-program FTE totals (`FTE Program
  Staff` row carrying `fte_cert` + `fte_class`). Parsed via
  **positional column-anchor extraction** (anchors derived from the
  first 10-value row across the PDF, using x1 binning so blank Credit
  Transfer / blank Cert Sal / blank Class Sal cells stay unbinned).
  Handles vintage drift: 2013-14 / 2014-15 print `NN Supv Inst`
  (space-separator), 2019-20+ print `NN | Supv Inst` (pipe-separator).
  Per-file per-program per-column identity (sum of details ==
  program_total) reconciles on **99.999%** of 1,252,240 checks (14
  mismatches on 1 file -- Bellevue 2019-20 has $1-off print rounding
  on the `activity_total` column of 7 programs; each printed activity
  row rounds independently, and the printed program total is computed
  from unrounded internals).
- ~~**SALARY EXHIBITS -- CERTIFICATED / CLASSIFIED** (GF9-201-XX,
  GF9-301-XX, CP7, CP8) -- per-program salary tables.~~ **DONE** --
  populates `fiscal_f195_salary_exhibits`. All 3,961 F-195 Budget PDFs
  covered (2013-14 through 2025-26). Per-district per-(fund, program,
  activity, duty) budgeted salary detail (title + FTE + high/low/avg
  rate + total salary + state/local decomposition), with per-activity
  `ACTIVITY CODE XX TOTAL` and per-program `PROGRAM TOTAL` subtotals
  captured via `row_kind` (`detail` / `activity_total` /
  `program_total`). Certificated rows carry annual $ rates; classified
  rows carry hourly $ rates and `number_of_hours`. **STATE / LOCAL
  split is 2019-20+ only** (post-McCleary form vintage); older files
  have NULL `state_annual_salary` / `local_annual_salary`. **The
  unique analytical contribution** is per-position salary detail --
  no other captured F-195 or F-196 sub-report exposes salary at the
  duty-code grain. Parsed via positional column-anchor extraction with
  wrap-body / wrap-tail merging (FTE `1,037.300` and HOURS `394,766.40`
  overflow their columns on large districts and wrap the trailing
  digit(s) to an adjacent visual line at the same x1). Anchors persist
  across a program's continuation pages so subtotal-only continuation
  pages (2013-14 / 2014-15 form vintage quirk -- e.g. Seattle's Program
  01 classified continuation on p85 opens on `ACTIVITY CODE 26 TOTAL`
  with no preceding detail row) don't drop rows. Per-program salary
  identity (sum of activity_totals == PROGRAM TOTAL) reconciles on
  **100%** of 3,961 files. Per-activity salary identity (sum of details
  == activity_total) reconciles on **95.5%** of files -- the 177 files
  with mismatches all carry OSPI form-internal duplicate `PP-AA-DDD`
  rows in the source PDF (e.g. Richland 2013-14 GF9-201-01 lists
  `01-22-412 LIBRARY MEDIA SPECIALIST SUPPLEMENTAL DAYS & HOURS`
  twice with different values; Puyallup 2018-19 GF9-201-01 lists
  `01-27-005`, `01-27-312`, `01-27-322`, `01-27-342` each twice).
  The parser's logical-key dedup collapses these to first-write-wins,
  which is the same class of quirk documented for
  `fiscal_f195_program_summary_by_object` (GF9) and
  `fiscal_f195_budget[expenditure_by_program]` (GF8). Not a parser
  bug. On 2019-20+ files ~18% of detail rows print `state=0 local=0`
  while `total > 0` -- OSPI form-internal data-entry inconsistency
  (some districts don't decompose salary into state/local funding
  sources for every row); federal-only programs (24, 51, 52) do this
  systematically, other programs sporadically. `state + local == total`
  reconciles on the ~82% of 2019-20+ rows where OSPI populated both
  fields; consumers who need the decomposition should filter for
  `state_annual_salary + local_annual_salary == total_annual_salary`
  to isolate reliable rows.

**Low priority (rarely-used) -- DEFERRED with rationale:**

- **CAPITAL PROJECTS FUND--PROJECT DESCRIPTION** (CP6) -- free-text
  project descriptions (low analytical value as structured data).
  Consumers who need Capital Projects detail can join
  `fiscal_f195_program_activity_object_detail` (budget-side) with
  `fiscal_f196_program_activity_object_detail` (actual-side) filtered
  to CP fund equivalents; the free-text descriptions in CP6 rarely
  drive analytical queries.
- **Budget Edit Report / Revenue Edit Report / ESD review / derivation
  formulas** (p170+ of each F-195 Budget PDF) -- appendix material.
  Edit-check results are captured for F-196 filings by
  `fiscal_f196_edit_report`; the F-195 pre-filing edit checks are
  intermediate state that OSPI resolves before publication and rarely
  matters for post-filing analysis.

Outside `fiscal/`, the following report types remain **DEFERRED with
rationale** after content survey:

- **`apportionment/`** -- ~147K files. All primary doc kinds are now
  parsed:
  - Monthly Apportionment page 1 (Statement of Apportionment) ->
    `fiscal_apportionment_monthly`.
  - 1191FG Grants, 1220 SpEd, 1220TR SpEd Transfer, 1251 FTE / 1251H
    (district), 1735T SpEd, F-780 Levy, Non-High Billing, F-196
    Unaudited, 1159 Staff Ratios -> individual `fiscal_*` tables.
  - Final Apportionment Summary (1191F) -> `fiscal_apportionment_final`
    (headline-only).
  Deferred: monthly Statement pages 2+, ESD-aggregate 1251 (see
  above).
- **`state_agencies_schools_colleges/`** -- 751 files. **Content
  survey**: PDFs are OSPI Report 1197 "Statement of Apportionment 900"
  -- the monthly apportionment analog for state agencies / schools /
  colleges (e.g. Peninsula College, Shoreline Community College).
  Same 1-page format as `Apportionment for {Month}.pdf`. Deferred
  because these entities are not K-12 school districts and don't
  participate in the SAFS / F-195 / F-196 flows the fiscal tables
  are optimized for. If K-14 analysis becomes a use case, refactor
  the existing `apportionment_monthly` parser to accept file leaves
  matching `PDF ({N})` under `state_agencies_schools_colleges/`.
- **`county_treasurer/`** -- 624 files (2018-19 through 2020-21 only).
  **Content survey**: PDFs are OSPI Report 1196A "Certificate of
  Apportionment" -- county-level certification listing per-district
  fund apportionment. Values are recoverable by summing from the
  district-side `fiscal_apportionment_monthly` grouped by county.
  Deferred unless a specific county-treasurer-side reconciliation
  use case appears.
- **`technical_colleges/`** -- 402 files. **Content survey**: mix of
  Report 1197 (Statement of Apportionment 900, same as
  state_agencies_schools_colleges) and Quarterly Funding Reports
  (per-district CTE vocational funding). The 1197 subset is same
  deferral rationale as state_agencies_schools_colleges. The
  Quarterly Funding Reports carry per-district CTE Voc allocations
  that could be a useful add if CTE vocational analysis is a use
  case; defer for now.
- **`esd_allocations/`** -- 38 files. **Content survey**: ~7 sub-
  reports per year (ESD Core, ESD PD, ESD K20, ESD Nurse Corp, ESD
  School Safety, ESD Suicide Prevention, ESD Core+PD Supplemental)
  for 3 years (2017-18, 2019-20, 2020-21). ESD-level line-item
  allocations (Staff Units, Salaries, Benefits, Insurance, etc). Not
  parsed. Very small volume; if ESD funding analysis becomes a use
  case, build a minimal per-line-item parser -- structurally simple.
## Coverage gaps in current fact tables

- **177 source PDFs (4.5%) in `fiscal_f195_salary_exhibits` have
  activity-total mismatches** because the source PDF prints the same
  `PP-AA-DDD` duty code more than once within a single activity, with
  different values on each occurrence. Examples: Richland 2013-14
  GF9-201-01 (`01-22-412 LIBRARY MEDIA SPECIALIST SUPPLEMENTAL DAYS &
  HOURS` twice, $36,990 and $1,097); Puyallup 2018-19 GF9-201-01
  (`01-27-005`, `01-27-312`, `01-27-322`, `01-27-342` all doubled,
  affected activity 27's sum by ~$608K); Thorp 2018-19 GF9-301-55
  (`55-27-910 AIDES` printed twice, once with a real rate and
  once with zeroes but a $29,875 total). The parser's logical-key
  dedup keeps the first row and drops subsequent duplicates. Per-file
  program-level identity (sum of activity_totals == PROGRAM TOTAL)
  still holds on **100%** of files -- OSPI's own activity_total
  captures the true sum. Consumers should prefer `activity_total` and
  `program_total` rows over `sum(detail)` when needed.
- **~18% of detail rows in `fiscal_f195_salary_exhibits` (2019-20+)
  print `state_annual_salary=0` and `local_annual_salary=0` even when
  `total_annual_salary > 0`**. OSPI form-internal data-entry
  inconsistency -- some districts didn't decompose salary into state-vs-
  local funding sources for every row. Federal-only programs (24, 51,
  52) do this systematically; other programs sporadically. The
  identity `state + local == total` reconciles on the ~82% of 2019-20+
  rows where OSPI populated both fields. Not a parser bug; filter on
  `state + local == total` to isolate rows with a reliable
  decomposition.
- **~32 source PDFs in `fiscal_f195_budget[expenditure_by_program]` have
  duplicated `code=45` / `code=46` rows in the Skill Center section**
  (concentrated in 2014-15 filings). OSPI's 2014-15 form printed BOTH
  the old naming ("Skills Center, Basic, State") and the new naming
  ("Skill Center, Basic, State") as separate rows sharing the same
  OSPI code. Each row has real values in a different subset of the 3
  data-year columns and `XXXXX` in the other subset. The parser's
  logical-key dedup collapses these to one row per code, silently
  losing the values from the discarded row. Aggregate impact: the
  per-group `TOTAL SKILL CENTER INSTRUCTION` row will overstate the
  sum-of-detail-items on affected files (Colville 2015 is the
  representative case: printed total = $4.06M, captured sum = $70k
  after dedup). Not a parser bug -- an OSPI form-vintage transition
  quirk. Consumers should prefer the TOTAL row over sum-of-details on
  2014-15 skill_center_instruction.
- **1 source PDF in `fiscal_f195_budget[enrollment_and_staff_counts]`
  has a K-12 SUBTOTAL that doesn't reconcile with the sum of grade
  items** (Muckleshoot Tribal Compact 2013-14, CCDDD 25200; printed
  SUBTOTAL = 56, sum of grades 1-13 = 60). OSPI form-internal
  data-entry error.
- Cross-tab identities `expenditure_by_object_summary` grand-total ==
  `expenditure_by_activity_summary` grand-total ==
  `fund_summary[general].B_TOTAL_EXPENDITURES` reconcile on **100%**
  of 3,963 files. `financial_summary.total_program_groups ==
  total_activity_groups` reconciles on **100%** as well.
- **`fiscal_food_service`** stops at 2018-19. OSPI stopped publishing
  the Report 1800SUM Food Service Program Summary after that year. The
  data may have moved into a different report or into F-196 detail
  pages; verify when the F-196 All Pages parser lands.
- ~~**`fiscal_f196_summary`** starts at 2021-22.~~ RESOLVED: the F-196
  All Pages parser now populates `fiscal_f196_summary` from 2013-14
  onward, replacing the standalone F-196 Summary parser. The combined
  table covers 2013-14 through 2024-25 (3,724 files).
- ~~**6 files missing `ending_total_fund_balance` in
  `fiscal_f196_summary`**~~ RESOLVED: verified against the latest
  fact-table run -- 0 files missing on all 3,724 files.
- **3 source PDFs in `fiscal_f196_revenues` have a section subtotal
  that does not reconcile with the section's own line items**
  (Inchelium 2015-16 + Dieringer 2015-16, both `9000 TOTAL OTHER
  FINANCING SOURCES capital_projects`; Central Kitsap 2019-20,
  `6000 TOTAL FEDERAL, SPECIAL PURPOSE general`). These are OSPI
  form-internal data-entry errors -- per-fund grand totals still
  reconcile to `fiscal_f196_summary` to the cent. Not parser bugs.
- **12 source PDFs in `fiscal_f196_balance_sheet` have a mismatched
  accounting identity on the `permanent` fund** -- all 12 are 2014-15
  files (CCDDDs 1158, 14068, 17403, 17404, 26056, 27343, 29103,
  31306, 32356, 32416, 38265, 38301). The printed
  `TOTAL ASSETS AND DEFERRED OUTFLOWS OF RESOURCES` and
  `TOTAL LIABILITIES, DEFERRED INFLOW OF RESOURCES, AND FUND BALANCE`
  disagree on the permanent-fund column (one side prints a value,
  the other prints 0.00). Component-level detail sums are correct in
  every case (Nonspendable+Restricted+Committed+Assigned+Unassigned =
  the printed TOTAL FUND BALANCE), so this is an OSPI form-internal
  data-entry error in the 2014-15 permanent-fund grand-total rows,
  not a parser bug. The `general` fund's accounting identity
  reconciles to the cent on all 3,724 files.
- **1 source PDF in `fiscal_f196_balance_sheet` has a 51-cent
  discrepancy** on the permanent fund's `total_fund_balance` vs
  `fiscal_f196_summary.ending_total_fund_balance` (Palisades 2017-18,
  CCDDD 19028). Same class of form-internal OSPI issue as the 2014-15
  permanent-fund identity mismatches.
- **2,842 files (5.5%) in `fiscal_apportionment_monthly` produce 0 rows**
  -- they are OSPI cover-memo PDFs that share the filename
  `Apportionment for <Month>.pdf` but contain narrative text rather
  than the Statement of Apportionment table. These are not parse
  failures; the parser correctly produces no rows. If the underlying
  Statement is published under a different filename for those (district,
  month) pairs, the scraper hasn't downloaded it.
- **14 files (0.9%) in `fiscal_nonhigh_billing` produce 0 rows** --
  OSPI-internal spreadsheet errors where every data cell prints `#N/A`
  and the district name renders as `0` (e.g. "07002 0 SCHOOL DISTRICT").
  Concentrated in 2024-25 and 2025-26 for a small set of districts
  (Dayton, Anacortes, Adna, Boistfort, Nespelem). These are not parse
  failures.
- **79 source PDFs in `fiscal_f196_resource_to_program` have per-row
  funding-source identity mismatches** (~0.04% of ~200K rows). Sample
  case: Ritzville 2015-16 programs 31 and 34 show state_resources +
  federal + other != program_expenditures per row -- the printed
  column values look transposed between the two rows (equal-and-
  opposite $22,921.56 offset). Section subtotals and grand totals
  still reconcile. These are OSPI form-internal data-entry errors,
  not parser bugs.
- **13 source PDFs in `fiscal_1191fg_grants` are corrupt** -- raw
  data files (not real PDFs) in the OSPI scrape, mostly in 2024-25.
  pdfplumber rejects them with "No /Root object!" and they are
  skipped. Re-scrape from OSPI if/when those districts' 1191FG data
  is needed.
- **2024-25 `fiscal_1191fg_grants` is partial** (138 PDFs with data
  vs ~330 in prior years). The corpus was scraped mid-year; the
  snapshot reflects an intermediate run of the report.
- **590 PDFs in `fiscal_1191fg_grants` are header-only placeholders**
  and produce 0 rows -- concentrated in `college` / `state_agency`
  files (most of those entities don't administer 1191FG grants).
  Not parse failures.
- **`fiscal_1220_sped` stops at 2019-20.** OSPI may have continued
  publishing the report past 2019-20 under a different filename or
  scraper path; the corpus only has files through 2019-20. Re-scrape
  may be warranted to extend the coverage window.
- **`fiscal_1159_staff_ratio` only covers 2013-14 through 2015-16.**
  OSPI discontinued the 1159 report after 2015-16 (SHB 2261 /
  McCleary rewrote the staffing formula -- the 46-CIS-per-1000-K-12
  statutory floor was superseded by the program-funded prototypical-
  school staffing model). For later-year staff ratios, derive from
  the S-275 (CIS FTE) and P-223 (enrollment) tables directly.
- **2015-16 `fiscal_1159_staff_ratio` files are all `Revised`** (307
  docs; none were re-pulled as `Final` before OSPI stopped publishing
  the report). 2013-14 (295 docs) and 2014-15 (299 docs) are entirely
  `Final`. Filter on `status = 'Final'` for finalized end-of-year
  analyses; include `Revised` to keep 2015-16 in the result.

## Form quirks specific to F-195 Budget

- **'Continued' banner shifts the title line.** On multi-page
  sub-reports (every fund's SUMMARY runs 2-3 pages), continuation
  pages insert a `Continued` line between the FY banner and the
  district name, pushing the title down. The parser scans the first 6
  lines for a recognized title rather than locking to a fixed index.
- **`merge_split_leading_digit` is NOT applied.** That helper (for
  1191SI's column-fragmented dollar values) misfires on F-195 Budget
  whenever the preceding column on a row is a single digit -- e.g.
  `1000 | Local Taxes 634 0 4,362,430` would wrongly merge the
  trailing `0 4,362,430` into a single token. The F-195 Budget parser
  uses raw pdfplumber output without that pass.
- **Multi-line footnotes within a page.** Forms terminate with
  multi-line footnote text (e.g. `2/ G.L.535 is an account... that
  received the debt proceeds...`). Once the parser sees a footnote
  starter (`N/ ...`) on a page, the rest of the page is treated as
  footnote text and skipped, preventing those lines from bleeding
  onto the last emitted item as label continuation.
- **TVF1 expenditure rows omit the `|` separator.** `33 Transportation
  Equipment Purchases` instead of `33 | Transportation Equipment
  Purchases`. The OSPI-code regex makes the `|` optional.
- **Section letter sequence varies per fund.** GF uses A-H, TVF1 uses
  A-J (extra letters for the 9900 TRANSFERS IN line that sits between
  REVENUES and the post-revenue totals). The parser tracks section
  letters as `summary` rows so totals don't collide with sibling items
  by `item_code`.

## Form quirks the parsers handle

The following quirks are already absorbed into the parsers / preprocessor;
listed here so a future debugger doesn't get surprised:

- **PDF text fragmentation of leading digits.** pdfplumber's column-based
  extraction sometimes renders dollar values as a fragmented sequence
  (`$18,673,029.13` -> `1 8,673,029.13`; `$843` -> `$ 8 43`). Handled by
  `merge_split_leading_digit` in `parsers/common.py`, with end-of-line
  lookahead so we don't accidentally merge label content like `Grade 1`
  with a following value.
- **Parenthesized negatives with internal whitespace.** `( 838,296.07)`
  parses as `-838296.07` via `collapse_numeric_paren_spaces`.
- **Dotted-leader values for `fiscal_1220_sped`.** Report 1220 uses
  dot-leaders between labels and values, and pdfplumber's standard
  `extract_text()` collapses leader+value into fragmented tokens like
  `'1..7..2.09'` for what's actually `'172.09'`. The 1220 parser
  bypasses this by using `extract_words(use_text_flow=True)` (which
  preserves dot-leaders as their own large tokens) and decomposes
  any residual `'label-prefix + leader + value'` tokens via a
  positional regex. Other fiscal parsers don't need this because
  their forms don't use dot-leaders.
- **Unicode dashes and hyphens.** OSPI PDFs use a wide variety: U+00AD
  SOFT HYPHEN (F-195F year headers 2018-21), U+2010 HYPHEN (1191SI year
  spans 2015-16), U+2013 EN DASH, U+2014 EM DASH, etc. All collapse to
  ASCII `-` in `parsers/common.py:normalize_pdf_text`.
- **`$ -` null markers.** Survives all digit-merge passes; collapsed to
  `$-` by the trailing `\$\s+` substitution so it becomes a single token.
- **Form 1191SI shape drift.** Section B grew from 8 items in 2013-14
  to 5 in 2024-25, with multiple intermediate revisions. The parser
  captures items verbatim by their printed section letter / item path
  rather than mapping to a canonical layout. See `CSV_GUIDE.md` for the
  per-year section-count matrix.
- **Form 1191SI typos.** `F. STATE INSTITUTiON PROFESSIONAL LEARNING
  DAYS` (lowercase i in INSTITUTION, 2018-19 only). The section-header
  detector tolerates up to 3 lowercase letters in the title.
- **Form 1191SI section-letter ordering.** 2013-14 / 2014-15 Section E
  sub-items are written in ALL-CAPS (`A. MAINTENANCE ALLOCATION [...]`),
  which would otherwise be misclassified as new Section A occurrences.
  The parser enforces monotonic section-letter ordering (only K is
  allowed to repeat between page 1 and page 2).
- **Form 1191SI page-2 K section.** Page 2's "K. YEAR END ALLOCATION
  ADJUSTMENT" re-uses the letter K; `section_seq=2` distinguishes it
  from the page-1 K (Total Allocation).
- **F-195 Overview multi-line labels.** Item labels wrap across 2-3
  source lines. The parser uses positional `item_code` so codes are
  stable even when the rejoined label varies; the printed `item_label`
  is best-effort.
- **F-195 Overview footnote suffixes.** Trailing `1/` / `2/` / etc.
  footnote markers are stripped from labels. The footnote bodies (e.g.
  "1/ Rollback of levies needs to be certified...") are skipped.
- **F-195F page boundaries re-print the fund header.** The parser
  detects same-fund header repetition and preserves the current section
  context across page breaks.
- **F-195F items with no OSPI code prefix.** Items like `Matured Bond
  Expenditures` (no leading 1000-9000 code) get a slug-derived
  `item_code` so siblings within a section don't collide on empty
  codes.
- **F-196 Unaudited blank cells vs F-196 Summary explicit 0.00.** The
  older (2013-14 / 2014-15) Unaudited form leaves non-applicable cells
  truly blank -- consistently, ASB and Permanent columns are blank on
  the `Other Financing Uses` row. pdfplumber's text-flow extraction
  drops blanks entirely, so a row with 5 values lands in the wrong
  columns under the trailing-7-tokens heuristic. The
  `f196_unaudited.py` and `f196_all_pages.py` parsers switch to
  positional extraction via `extract_words()` and bin each value by
  right-edge x1 against the column anchors derived from the first
  (always 7-column) value row. The 2021-22+ audited 'F-196 Summary'
  doc fills those cells with explicit 0.00 and so works under the
  simpler tokenizer.
- **F-196 All Pages value-wrap fragments (trailing-digit overflow).**
  On large districts (Seattle 2018-19 General Fund total revenues
  `$1,164,926,695.83` etc), a 10-figure value overflows its printed
  column width and the trailing digit(s) wrap to the next visual line
  at the same x1. `f196_all_pages.py` post-merges by matching the
  fragment's x1 to a column anchor with a truncated parent value (decimal
  suffix shorter than 2 digits) and appending the fragment text.
- **F-196 All Pages sign-placeholder wraps (full-body overflow).** When
  a negative value is too wide (e.g. Everett 2020-21 debt_service
  `-11,863,885.53` on Excess of Revenues), the leading `-` prints alone
  at the column on the parent row and the entire digit body wraps to
  the next line at the same x1. The parent column ends up with no value
  and a lone-`-` placeholder; `f196_all_pages.py` records the sign and
  consumes the next-line full value at the same x1, emitting `sign + body`
  as the merged decimal.
- **`E.S.D. SPI` banner for tribal compact schools.** ~44 tribal
  compact schools (Quileute, Muckleshoot, Suquamish, Chief Leschi,
  Wa He Lut, Lummi, Yakama Nation, etc -- CCDDD ending in 9XX) sit
  under direct OSPI oversight and print `E.S.D. SPI` in place of an
  ESD number on every sub-report banner. Parsers that anchor on the
  banner use `\w+` instead of `\d+` to match either form.
- **F-196 BC pdfplumber column-overlay bug.** On some pages of the
  Budgetary Comparison Schedule, the `FINAL BUDGET` / `ACTUAL` /
  `(NEGATIVE)` column-header row renders at the same y as a value row
  and pdfplumber's default `extract_words()` merges them char-by-char
  into garbage tokens (Seattle 2018-19 Capital Projects page 2:
  `85,307,151.46` emerges as `F8i5n,a3l0 7B,u1d5g1e.t4 6`).
  `f196_budgetary_comparison.py` uses `extract_words(use_text_flow=True)`
  which follows the natural PDF content stream and keeps the two
  text streams separate.
- **F-196 BC favorable-variance sign convention.** The form's variance
  column is NOT a fixed arithmetic of `final_budget - actual`: it
  encodes 'favorable to the district' as positive. For revenues / OFS
  / fund_balance rows variance = actual - final_budget; for
  expenditures rows variance = final_budget - actual. Consumers must
  apply the section-aware formula to re-derive variance; the parser
  captures the printed value verbatim.

## Filename / reorg quirks

- **`State Summary Spreadsheet.pdf` / `State Summary.pdf` are skipped**
  by `extract_state_institutions.py` (14 files total; one per year).
  These are non-1191SI companion docs with cross-institution tabular
  data. A future parser pass could capture them, but the per-institution
  rows mostly aggregate to the same numbers.
- **Apportionment-ESD inner districts don't carry CCDDD codes in their
  filenames.** The `reorg.py` script backfills the CCDDD onto those
  directory names via a cross-reference with the Apportionment-District
  branch. A handful of districts that exist only under the ESD cascade
  get a slug-only directory (`{slug}/`) instead of `{ccddd}_{slug}/`.
- **The 4 "flat label" report types** (`county_treasurer/`,
  `state_agencies_schools_colleges/`, `technical_colleges/`,
  `esd_allocations/`) keep their original OSPI filenames, often
  `PDF (3)` / `XLS (11)`. Future parsers will need to attribute these
  by PDF content, not filename.

## Build pipeline gaps

- **No incremental updates.** `build_sources.py` rewrites every fact
  CSV every run. Fine at current scale; revisit if the planned
  Apportionment / F-195 Budget full parsers push fact CSVs past ~1 GB.
- **No Postgres staging.** Per the handoff, `from_raw_file.py`-style
  staging may be worth it once multi-parser joins land. Currently
  everything flows to CSV.
- **Parser throughput is pdfplumber-bound.** Parallel extraction
  (`extractors/fiscal/parallel.py`) uses a multiprocessing.Pool sized
  to `ncpu-1`. The `read_pdf_lines(path, max_pages=N)` argument was
  added during the Apportionment monthly run -- it dropped per-file
  parse time ~20x for that doc (40-90 page PDFs where only page 1 is
  parsed) and brought the full 52K-file corpus to ~12 minutes. F-195
  Overview (3,959 PDFs x ~41 pages, page 1 only) still uses the
  whole-doc reader; should be retrofitted with `max_pages=1` for a
  similar speedup on next re-run.
- **Second-pass parsed-text cache.** For the still-unbuilt big parsers
  (F-195 Budget full, F-196 All Pages, the rest of apportionment), a
  one-time pdfplumber extraction to `.txt.zst` files per source --
  paired with a source-FK dimension keyed on `source_id` -- would let
  iterating parser logic skip pdfplumber on every re-run. Worth doing
  before the next round of compound-doc parsers.
