# extractors/fiscal -- known gaps and quirks

## Parsers not yet built

Within `apportionment/` (147,244 files), the District / College / State
Agency monthly Statement table (51,985 files, page 1 only) is parsed.
Outstanding:

- **Apportionment allocation forms** -- ~3,732 files remaining.
  `Final Apportionment Summary` (3,732) is its own form -- the
  year-end version of monthly Apportionment pages 2+ (per-account
  derivation -- complex compound doc).
  Done:
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
- **Report 1220TR ESD SpEd Transfer of Allocation** -- ~120 ESD-path
  files (2013-14 through 2016-17 only; replicated per-member, dedup
  needed). This is the ESD-level companion to district 1220 -- a
  tabular per-member-district breakdown of 3121 / 4121 / 4122
  transfers. Distinct enough from district 1220 to warrant a
  parallel `fiscal_1220_sped_transfer` table.
- **ESD-aggregate 1251 enrollment** -- ~3,800 unique ESD-level files
  after dedup (replicated under every member subdir, so ~45K duplicates
  before dedup). The format is a multi-district aggregate; per-ESD
  enrollment rollup wouldn't fit `fiscal_1251_enrollment`'s
  per-district shape. Build a parallel `fiscal_1251_enrollment_esd`
  table if needed.
- **Pages 2+ of the monthly Statement** -- the 40+ pages of per-account
  computation detail (school-generated entitlement formulas, etc.) we
  currently skip via `read_pdf_lines(max_pages=1)`. The headline
  Allotment for {Month} number is already captured; pages 2+ would add
  derivation transparency but bulk up the schema substantially.

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
- **F-196 All Pages -- Phase 2c+ (remaining sub-reports)**: planned.
  - **Statement of Revenues, Expenditures, and Changes in Fund Balance**
    (pp 5-6, 2 pages) -- intermediate-granularity rollup per fund x 7
    funds. Mostly redundant with SUMMARY + Revenues; defer unless a
    specific use case appears.
  - **Balance Sheet** (pp 3-4) -- assets, liabilities, fund balance
    by G.L. code per fund x 7 funds. Solvency / working-capital
    analysis; no current pair.
  - **Schedule of Long-Term Liabilities** (pp 19-22) -- bonds, leases,
    OPEB.
  - **Statement of Fiduciary Net Position + Changes** (pp 17-18) --
    ASB Trust / Permanent Fund accounting.
  - **Program/Activity/Object Report + per-PROGRAM detail** (pp 30-65,
    ~33 programs per district) -- expenditure detail by program x
    activity x object. Heavy schema; pairs with eventual F-195 GF9-XX
    per-program detail. Likely the highest-value Phase 2c target.
  - **Federal Indirect Cost Rate / MOE / Resource-to-Program / NCES
    schedules** (pp 66-80) -- supplemental schedules; some
    overlap with State Recovery Rate calculations.
  - **Financial Edit Report** (pp 82-84) -- OSPI-detected
    inconsistencies; useful as a data-quality dimension but not core.

The **F-195 Budget (full)** parser landed (-> `fiscal_f195_budget`) but
only captures the SUMMARY OF X FUND BUDGET sub-reports (Phase 1, all 5
funds: GF2, ASB1, DS1, CP1, TVF1). Same parser runs against the F-195
Budget Overview as well, so both source kinds populate the table. The
remaining ~25 sub-reports per F-195 Budget PDF are not yet captured:

- **Per-fund revenue detail** (GF4, DS2, CP3, TVF3 portion) -- detailed
  revenue line items grouped by OSPI 4-digit account code. Will fold
  into `fiscal_f195_budget` as `sub_report = 'fund_revenue_detail'`.
- **EXPENDITURE BY PROGRAM** (GF8) -- per-program expenditures, 3-col
  same shape. -> `sub_report = 'expenditure_by_program'`.
- **SUMMARY OF GENERAL FUND EXPENDITURES BY OBJECT** (GF10) -- 6-col
  (Actual / %Total) x 3 years cross-tab.
- **SUMMARY OF GENERAL FUND EXPENDITURES BY ACTIVITY** (GF11) -- 6-col
  similar.
- **FY ENROLLMENT AND STAFF COUNTS** (GF1) -- 3-col enrollment +
  certificated/classified staff counts.
- **GENERAL FUND FINANCIAL SUMMARY** (Budget Summary) -- 6-col headline
  rollup (enrollment, financial summary, program-group breakdown,
  activity-group breakdown).
- **PROGRAM SUMMARY BY OBJECT OF EXPENDITURE** (GF9) -- wide cross-tab
  of program x object. Distinct schema; consider a separate
  `fiscal_f195_budget_program_object` table.
- **OBJECTS OF EXPENDITURE per program** (GF9-XX, ~60 pages per PDF for
  large districts) -- per-program activity x object detail.
- **SALARY EXHIBITS -- CERTIFICATED / CLASSIFIED** (GF9-201-XX,
  GF9-301-XX, CP7, CP8) -- per-program salary tables. Large -- consider
  a `fiscal_f195_salary_exhibits` table.
- **REVENUE WORK SHEET--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX**
  (GF13, DS3, CP5, TVF3) -- short worksheet, levy collection math.
- **LONG-TERM FINANCING -- CONDITIONAL SALES CONTRACTS** (GF14, CP9,
  TVF4) -- bond/contract detail by fund.
- **SUMMARY OF FTE STAFF COUNTS BY ACTIVITY** (GF15) -- 4-col
  certificated/classified FTE by activity.
- **DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS** (DS4) --
  bond inventory.
- **CAPITAL PROJECTS FUND--PROJECT DESCRIPTION** (CP6) -- free-text
  project descriptions (low analytical value as structured data).
- **Budget Edit Report / Revenue Edit Report / ESD review / derivation
  formulas** (p170+ of each F-195 Budget PDF) -- appendix material;
  low priority.

Outside `fiscal/`, 6 report types remain (149,772 files):

- **`apportionment/`** -- 147,244 files. Biggest bucket. Per-district /
  ESD / college / state-agency monthly and one-off apportionment PDFs.
  Doc kinds: monthly `Apportionment for {Month}.pdf` (~50K), `1735T
  Special Education`, `1251 FTE`, `1251H Headcount`, `1191FG Grants
  Administration`, `Final Apportionment Summary`, `1220 Special
  Education Allocation`, `Non-High Billing`, `K12 Staff Ratios`, `F-196
  Unaudited`, multi-year `F-780 Levy Authority` (Initial / Final per
  year). Likely needs at least 3 distinct parsers (monthly summaries
  vs. allocation detail vs. F-780 levy).
- **`state_agencies_schools_colleges/`** -- 751 files. Mostly named just
  `PDF (N)` from the OSPI source; content type is unclear without
  opening each. 155 are timestamped scraper-rerun duplicates.
- **`county_treasurer/`** -- 624 files. Same `PDF (N)` / `XLS (N)`
  generic naming pattern. Worth a content-extraction pass to attribute
  each PDF to a county before designing a schema.
- **`technical_colleges/`** -- 402 files. Same generic-naming issue.
- **`esd_allocations/`** -- 38 files. Smallest bucket; named documents
  (`ESD Core Allocations`, `ESD K20 Allocations`, etc.) per year per
  ESD.

## Coverage gaps in current fact tables

- **`fiscal_food_service`** stops at 2018-19. OSPI stopped publishing
  the Report 1800SUM Food Service Program Summary after that year. The
  data may have moved into a different report or into F-196 detail
  pages; verify when the F-196 All Pages parser lands.
- ~~**`fiscal_f196_summary`** starts at 2021-22.~~ RESOLVED: the F-196
  All Pages parser now populates `fiscal_f196_summary` from 2013-14
  onward, replacing the standalone F-196 Summary parser. The combined
  table covers 2013-14 through 2024-25 (3,724 files).
- ~~**6 files (0.07% of corpus) are missing the `ending_total_fund_balance`
  row in `fiscal_f196_summary`**~~ may have been resolved by the parser
  rewrite (the positional column-anchor approach handles cell-blanking
  and value-wrap shapes the trailing-7-tokens heuristic missed).
  Re-verify against the latest fact-table run.
- **3 source PDFs in `fiscal_f196_revenues` have a section subtotal
  that does not reconcile with the section's own line items**
  (Inchelium 2015-16 + Dieringer 2015-16, both `9000 TOTAL OTHER
  FINANCING SOURCES capital_projects`; Central Kitsap 2019-20,
  `6000 TOTAL FEDERAL, SPECIAL PURPOSE general`). These are OSPI
  form-internal data-entry errors -- per-fund grand totals still
  reconcile to `fiscal_f196_summary` to the cent. Not parser bugs.
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
