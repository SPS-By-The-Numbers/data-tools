# Documentation index

Start here. This index answers four questions; each section links to the
authoritative doc rather than duplicating it. Convention: consumer/developer
guides live next to the code they describe (`extractors/<family>/`); this
file is the map; `DATA_DICTIONARY.md` is generated — edit schema modules,
not the Markdown.

## 1. What data is available

- **[DATA_DICTIONARY.md](DATA_DICTIONARY.md)** — generated dictionary of all
  88 BigQuery tables (fiscal, STARS, SAFS): location, provenance, canonical
  source, every column with type and description. The single most complete
  catalog.
- Per-dataset catalogs with row counts, grain, and join keys:
  - [`extractors/fiscal/CSV_GUIDE.md`](../extractors/fiscal/CSV_GUIDE.md) —
    the ~40 `fiscal_*` tables parsed from OSPI F-195/F-196/apportionment PDFs.
  - [`extractors/stars/CSV_GUIDE.md`](../extractors/stars/CSV_GUIDE.md) —
    the 15 `stars_*` pupil-transportation tables.
  - [`marts/README.md`](../marts/README.md) — pointer for `bigsheet`, the
    joined per-school wide sheet, now generated in the website repo (this repo
    still publishes its seven static input CSVs).
  - [`docs/guides/ENROLLMENT_GUIDE.md`](guides/ENROLLMENT_GUIDE.md) — SPS
    Annual Enrollment Report extracts (Section-4 origin/destination, Table 1-D).
  - [`docs/guides/BOARD_CONTRACTS.md`](guides/BOARD_CONTRACTS.md) — every
    Seattle School Board-approved contract action (new/amendment/change
    order/renewal/final acceptance) reconstructed from board minutes and
    agendas, 2004-05 → present: 1,894 board-action rows with a page-cited
    citation, from 6,452 segmented business items across 996 meetings.
    Crawl and extraction pipeline complete (see
    `extractors/sps_web/COVERAGE.md`); published spreadsheet is
    `out_sps_web/publish/contracts.csv`/`.xlsx`/`.jsonl` (BigQuery load
    pending — owner's call).
  - [`data/safs/f196/README.md`](../data/safs/f196/README.md) — raw F-196
    source-file inventory.
- Known holes: [`extractors/fiscal/COVERAGE.md`](../extractors/fiscal/COVERAGE.md),
  [`extractors/stars/COVERAGE.md`](../extractors/stars/COVERAGE.md), and
  [`extractors/sps_web/COVERAGE.md`](../extractors/sps_web/COVERAGE.md) —
  which years/districts/sub-reports are missing and why. Check before
  concluding data is absent.

## 2. What it implies (semantics, caveats, canonical source)

- **[`extractors/fiscal/DATA_SOURCE_DIVERGENCE.md`](../extractors/fiscal/DATA_SOURCE_DIVERGENCE.md)**
  — read first for financial data. OSPI publishes the same district
  financials twice (SAFS Access DBs vs printed PDFs); this decides which
  path is canonical for which facts. TL;DR: prefer `safs_f19x`; the fiscal
  PDF tables are canonical only for PDF-only dimensions (salary exhibits,
  budgeted FTE, mid-year Final Budget, balance sheet, apportionment,
  non-district entities).
- [`docs/guides/STAFFING_ANALYSIS_GUIDE.md`](guides/STAFFING_ANALYSIS_GUIDE.md)
  — S-275 staffing/salary analysis: joins, report_id→year map, and 15
  gotchas (per-person vs per-assignment salary, duty-code history, FTE
  summation traps).
- [`docs/guides/COMP_SPLIT_RECONSTRUCTION.md`](guides/COMP_SPLIT_RECONSTRUCTION.md)
  — the School vs District Office compensation split (Teaching / Student
  Support / Building Support / Other): activity buckets, the Budget Book /
  Purple Book carve, chronic-underspend corrections, and why F-196 building
  codes and S-275 building codes disagree about support staff. Scripts:
  `tools/bb_summary_from_db.py`, `tools/pb_actuals_reconcile.py`.
- [`docs/guides/DUTY_FUNDING.md`](guides/DUTY_FUNDING.md) — how much of the
  payroll the state pays for: the 1191F CIS/CAS/CLS staff units and the
  1191EDF per-role staffing units set against S-275 pay, by staff class,
  model role and duty title. Covers the four attribution traps (headline-only
  apportionment table, FTE vs payroll basis, revenue that buys contracted
  service, and what "state apportionment" actually means), and the open
  salary-only question. Scripts: `tools/duty_funding/`.
- [`tools/sea_chart_critique/README.md`](../tools/sea_chart_critique/README.md)
  — the SEA "Average Reported Salaries by Job Category vs. State Funded
  Salaries by Staff Type" graphic, marked up with its errors and replaced with
  three charts that hold up. Reconstructs all three of its benchmark bars from
  the 1191F to the cent (including the professional-learning add-on hidden in
  the yellow one), and records the 0.77-FTE central-administrator reporting
  convention that inflates any per-FTE administrator figure. Builds a
  standalone HTML page.
- [`docs/guides/S275_SALARY_SKYLINE.md`](guides/S275_SALARY_SKYLINE.md) —
  per-employee `total_final_salary` charted one bar per person, and the duty
  banding it uses: which OSPI duty roots count as central office vs school
  administration vs classified support, and why `is_classified` is not the
  test. Scripts: `tools/salary_skyline/`.
- [`docs/guides/S275_SALARY_PER_FTE.md`](guides/S275_SALARY_PER_FTE.md) —
  `total_final_salary` per FTE for every WA district, pooled 2013-14…2024-25,
  at district and district × duty-title grain: column dictionary, the
  apportionment used to split a person-year's salary across duty titles, why
  `is_teacher` is narrower than OSPI's `duty_name_category`, and 10 caveats.
  Queries: `tools/s275_salary_per_fte_by_district*.sql`.
- NULL conventions and anti-patterns: dedicated sections at the end of each
  CSV_GUIDE (e.g. STARS `value = NULL` means "row absent from source" while
  `0` is a reported zero).
- STARS naming: the allocation-formula inputs are **ride-equivalents**
  (trips + issued transit passes), not distinct riders; only the KPI report
  measures actual riders. See the STUDENT DETAIL notes in
  [`extractors/stars/README.md`](../extractors/stars/README.md).

## 3. How to access it

- **BigQuery (preferred):** project `sps-btn-data`, location `us-west1`.
  Datasets: `ospi_fiscal`, `ospi_stars` (parsed PDFs), `safs_f19x`,
  `safs_s275`, `safs_domains`, `safs_enrollment`, `safs_sqss` (Access-DB
  extracts), `ospi` (assessments). Needs Application Default Credentials
  (`gcloud auth application-default login`).
- **The bigsheet mart:** generated by the website repo's Cloud Function
  (`GET /bigsheet?ccddd=NNNNN` → cached AVRO; per-district CSV download in the
  dashboard UI). See [`marts/README.md`](../marts/README.md).
- **Local artifacts (offline fallback):** `out_fiscal/`, `out_stars/`,
  `out_enrollment/` CSVs and `out_*/tables/*.avro`; SAFS AVRO under
  `safs_prod/`. All gitignored — regenerate per the pipeline docs below, or
  pull from GCS (`gs://sps-btn-data-all-data`).

## 4. How it was generated from primary source

Provenance chain, per family:

| family | primary source | scrape/fetch | raw store | parse/extract | load |
|---|---|---|---|---|---|
| fiscal | OSPI F-195/F-196/apportionment PDFs | [`index.html`](index.html) + [`contentscripts/scrappers/ospi-funding-reports.js`](contentscripts/scrappers/ospi-funding-reports.js) | `data/fiscal/` (142 GB, GCS-mirrored) | [`extractors/fiscal/OVERVIEW.md`](../extractors/fiscal/OVERVIEW.md) | `scripts/load_fiscal.sh` → `ospi_fiscal` |
| STARS | OSPI STARS report PDFs/DOCX | same page + [`ospi-stars-reports.js`](contentscripts/scrappers/ospi-stars-reports.js) | `data/stars/` | [`extractors/stars/README.md`](../extractors/stars/README.md) | `scripts/load_stars.sh` → `ospi_stars` |
| SAFS | OSPI Access DBs (F-195/F-196/S-275) + enrollment/assessment files | manual download | `data/safs/` | [`extractors/safs/README.md`](../extractors/safs/README.md) + CLAUDE.md §SAFS pipeline | `scripts/load_safs.sh` → `safs_*` |
| enrollment | SPS Annual Enrollment Report PDFs | manual download | `data/sps/enrollment/` | [`guides/ENROLLMENT_GUIDE.md`](guides/ENROLLMENT_GUIDE.md) | (local CSV only — see BACKLOG) |
| board contracts | seattleschools.org board minutes/agendas/BARs (WordPress + SharePoint) and Wayback Machine captures of two prior site generations | [`extractors/sps_web/inventory_wp.py`](../extractors/sps_web/inventory_wp.py) + `inventory_wayback.py` + `fetch.py` | `out_sps_web/raw/` (gitignored, not yet promoted to `data/`) | [`extractors/sps_web/PLAN.md`](../extractors/sps_web/PLAN.md) + [`guides/BOARD_CONTRACTS.md`](guides/BOARD_CONTRACTS.md) | `out_sps_web/publish/` CSV/XLSX/JSONL/AVRO (`publish.py`) — BigQuery `sps_board.*` load not yet run (owner's call, `--bq`) |

- The fiscal/STARS → BigQuery loader (`extractors/bqload/`) is seed-first:
  Postgres staging → zstd AVRO → GCS → BigQuery WRITE_TRUNCATE, with exact
  NUMERIC(38,9) end-to-end. See the `extractors/bqload/run.py` docstring and
  CLAUDE.md § bqload pipeline.
- `data/` is read-only for tooling and rsynced with GCS via
  `scripts/push_data_to_gcs.sh` / `pull_data_from_gcs.sh`.

## Open work

Cross-cutting items: [BACKLOG.md](BACKLOG.md). Per-dataset:
[`extractors/fiscal/TODO.md`](../extractors/fiscal/TODO.md),
[`extractors/stars/TODO.md`](../extractors/stars/TODO.md).
