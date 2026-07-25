# STARS data coverage — known gaps and quirks

What is and isn't in the `stars_*` tables: which (year × report_type) cells
OSPI never published, which districts fall out of individual years, and the
per-file anomalies the parsers absorb. Read this before concluding a district
or year is "missing" from your query — most holes are OSPI's, not ours.
Schemas and join recipes live in [CSV_GUIDE.md](CSV_GUIDE.md); open work items
live in [TODO.md](TODO.md).

The STARS dropdown offers ten school years (2016-2017 through 2025-2026).
"Missing" here means zero files were scraped for that combination. Some of
these gaps reflect reports OSPI never published; some are likely re-scrape
candidates.

## Missing entire (year, report_type) cells

Legend: `-` = no files scraped, `✓` = files present (count). The full grid:

| year      | efficiency | efficiency_review | kpi   | operations_allocation | quarterly_district |
|-----------|-----------:|------------------:|------:|----------------------:|-------------------:|
| 2016-2017 |          - |               84  |    -  |                    -  |                  - |
| 2017-2018 |       287  |               88  |  282  |                  316  |                925 |
| 2018-2019 |       312  |                -  |  278  |                  315  |                816 |
| 2019-2020 |       315  |              100  |  280  |                  315  |                948 |
| 2020-2021 |          - |                -  |    -  |                  318  |                954 |
| 2021-2022 |          - |                -  |    -  |                  323  |                969 |
| 2022-2023 |       295  |               77  |  278  |                  328  |                984 |
| 2023-2024 |       330  |               83  |  279  |                  331  |                993 |
| 2024-2025 |       331  |               72  |  278  |                  331  |                662 |
| 2025-2026 |       331  |                -  |  278  |                  331  |                662 |

### Confirmed re-scrape candidates

None obvious — the empty cells line up with COVID transit shutdowns and
likely-not-published reports. Verify these against the live STARS page
before scraping; if the dropdown offers downloads for these (year, report)
combinations and we just missed them, re-scrape with
`window.OSPI_SCRAPER_START` / `OSPI_SCRAPER_END` set to that combination.

### Confirmed not-published-by-OSPI

- **2020-2021 and 2021-2022 for `efficiency` and `kpi`.** Verified
  2026-05-17 against the live STARS dropdown -- neither year offers
  Efficiency Detail or KPI report types. Consistent with the COVID
  shutdown: buses didn't run, so efficiency/KPI metrics weren't
  computed. `operations_allocation` and `quarterly_district` were
  still produced because allocations and quarterly accounting continued.

### Probable not-published-by-OSPI (not yet verified)

- **2016-2017 for `efficiency`, `kpi`, `operations_allocation`,
  `quarterly_district`.** Only `efficiency_review` has 2016-17 data.
  STARS as a reporting program likely launched 2017-2018; the 2016-17
  efficiency_review is probably a retrospective comparison file.
- **2020-2021 and 2021-2022 for `efficiency_review`.** Probably no
  reviews because there were no efficiency ratings during COVID;
  verify same way as the efficiency/KPI cells above.
- **2018-2019 for `efficiency_review`.** Worth a manual check on the live
  page; could be a real gap.
- **2025-2026 for `efficiency_review`.** Current school year — review
  hasn't been generated yet.

## Within-year shortfalls (districts, not whole cells)

Washington has ~331 reportable entities (school districts + ESDs + tribal
compacts + charter schools). Reports with fewer files are either smaller
by design or have real per-district gaps.

- **`efficiency`** ramps 287 → 331 over time. The early-year shortfalls
  (2017-18, 2018-19) are likely OSPI excluding districts that didn't meet
  the reporting threshold; the 2022-23 dip to 295 is more suspicious and
  worth a spot-check.
- **`kpi`** is steady around 278-282 across all present years. About 50
  fewer entities than the dropdown's full org count — KPI may exclude
  ESDs/tribal compacts/some charters by design.
- **`efficiency_review`** counts vary by year because the report only
  includes districts that crossed thresholds. Year-to-year variation
  here is feature, not bug.
- **`operations_allocation`** ramps 316 → 331; the growth tracks new
  charter authorizations over time.

## `quarterly_district` per-(district, year) shape

Most (district, year) tuples have all three quarters: `FALL`, `WINTER`,
`SPRING`. Outliers:

- **331 districts in 2024-2025 with only 2 quarters** — SPRING is
  typically published end-of-school-year; current year hasn't completed.
- **331 districts in 2025-2026 with only 2 quarters** — same reason.
- **129 districts in 2018-2019 with only 2 quarters.** Worth verifying.
- **4 districts in 2017-2018 with only 2 quarters.** Likely OSPI gaps.
- **8 (year, district) singletons** — new charters / tribal compacts in
  their first reporting year. Examples:
    - 2017-2018: First Place Scholar Charter District (17901),
      Impact Public Schools (17911), Inchelium School District (10070),
      Quileute Tribal School District (05903),
      Willow Public Charter School (36901).
    - 2019-2020: Catalyst Public Schools (18901), Impact Salish Sea
      (17916), Lummen High School (32903).
- **Lind School District (01158) 2023-2024** originally had 6 files
  (2× each quarter) — 3 pairs of byte-identical duplicates from the
  scraper running twice; the `(1)`-suffixed copies were deleted, so the
  corpus now has the normal 3.

## Other anomalies

- **`operations_allocation` 2022-2023+** has 15-21 `.docx` files per year
  alongside the bulk `.pdf`s. These are tribal compacts, charter schools,
  and some ESDs that submit a different format. Parser must handle both.
- **A few origname strings are truncated** ("hiefLeschiTribalCompact"
  missing leading "C", "ummiTribalAgency" missing leading "L", etc.).
  Cosmetic — `ccddd` and district name come from the structured org-label
  segment, not the origname, so this doesn't affect joins.

## Per-file anomalies surfaced by parsers

### KPI

- **`2025-2026 - Key Performance Indicators - Winlock School District (21232) - Winlock.pdf`**
  is truncated by OSPI -- only 4 pages (Tables 1-4 cohort comparison)
  with no "District KPI" block on pages 4-5. Verified 2026-05-17:
  Winlock isn't in the orgs dropdown for 2025-26 KPI, so OSPI didn't
  publish a full version. Permanent hole for (Winlock, 2025-26, KPI).
  The parser logs `'District KPI' anchor not found` and emits 0 rows.

### Operations Allocation Detail

- **143 files (out of 2,908) use a non-standard 1026A variant** for tribal
  compacts and charter schools: `Operations Allocation Detail Report 1026A
  (COMPACT)` / `(CHARTER)` / `Charter Schools (9/2020)` / `Revised` are
  the cover-page variants. These are now handled by the
  `stars_operations_allocation_compact` table with its own parser. The
  standard 1026A parser silently skips them; the compact parser
  silently skips standard 1026A files. Together they cover all 2,908
  files in the corpus.
