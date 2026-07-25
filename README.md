# data-tools
Scripts and tools for ingesting Seattle Public Schools / OSPI data into
BigQuery (project `sps-btn-data`).

**📚 Documentation index: [docs/README.md](docs/README.md)** — what data is
available, what it implies, how to access it, and how it was generated. The
generated per-column dictionary of all BigQuery tables is
[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Repository layout

- `extractors/` — ETL source code: `safs/`, `fiscal/`, `stars/`, `budget/`,
  `purplebook/`, `odata/`, `prr/`, plus standalone extractors
  (`enrollment_reports.py`, `p223_pdf_batch.py`, ...).
- `bigquery/` — legacy pre-SAFS loaders, kept for reference.
- `marts/` — downstream joined datasets ("data marts"); `bigsheet.py` merges
  ALL per-school data we have (enrollment, spend, staffing, MAP, BEX
  building, S-275 churn, assessments, SQSS) into one wide sheet — one row per
  school per cohort year, ~1,240 columns. Reads from BigQuery by default, so
  it is reproducible and picks up new school years automatically:
  `venv/bin/python3 -m marts.bigsheet -o sheet.csv`. See `marts/README.md`.
- `scripts/` — shell entry points (`load_safs.sh`, `load_fiscal.sh`,
  `load_stars.sh`, `push_data_to_gcs.sh`, `pull_data_from_gcs.sh`, ...).
  Run from anywhere; they `cd` to the repo root themselves.
  `load_fiscal.sh`/`load_stars.sh` drive `extractors/bqload/`, which loads
  the parsed PDF outputs into BigQuery datasets `ospi_fiscal`/`ospi_stars`.
- `tools/` — ad-hoc analysis/CLI scripts operating on pipeline outputs; not
  part of the production pipeline.
- `docs/` — documentation index (`docs/README.md`), generated BigQuery data
  dictionary (`docs/DATA_DICTIONARY.md`), repo backlog (`docs/BACKLOG.md`),
  dev guides (`docs/guides/`), and the GitHub Pages site (`docs/index.html`
  + scrapers).
- `data/` — raw source data that syncs to
  `gs://sps-btn-data-all-data/raw/<subdir>` via `scripts/push_data_to_gcs.sh` /
  `scripts/pull_data_from_gcs.sh`. **Read-only for tooling** — nothing is ever
  written, moved, or renamed here by any script or by hand; only the owner
  adds to it. Subtrees (approximate sizes): `fiscal` (~142 GB), `safs`
  (~6.3 GB), `stars` (~1.4 GB), `transit` (~905 MB), `assessment` (~356 MB),
  `sps` (~327 MB), `sqss` (~233 MB), `census` (~41 MB), `map` (~20 MB),
  `enrollment` (~872 KB).
- `reference/` — gitignored, human reference material moved as-is
  (`input/`, `olddata/`, `regress/`, `stats/`, `analysis/`, `scratch/`,
  `prr/`); never cleaned or reorganized by tooling.
- `attic/` — gitignored parking lot for unclassified root clutter, pending
  owner triage. See `attic/MANIFEST.md`.
- `safs_prod/`, `output/`, `out_*/` — generated pipeline outputs, gitignored
  in place. **TODO:** these should move under one output root (e.g. `out/`);
  requires coordinated updates to `scripts/load_safs.sh` and the fiscal/stars
  extractor paths. See `docs/BACKLOG.md`.

## Two data paths: SAFS raw (start here) vs Fiscal PDF

OSPI publishes the same district financial data twice — once as raw
Microsoft Access `.accdb`/`.mdb` files (the **SAFS raw** path,
extracted by [`extractors/safs/`](extractors/safs/) into canonical
avros under `safs_prod/f19x/*.avro`) and once as printed PDFs (the
**Fiscal PDF** path, extracted by
[`extractors/fiscal/`](extractors/fiscal/) into
`out_fiscal/*.csv` and loaded into BigQuery dataset `ospi_fiscal` by
`extractors/bqload/`). Both extractors run in this repo, but they
capture **different slices** of the underlying data.

**Start with the SAFS canonical avros.** They cover almost every
top-level analysis you'd want — budget vs actuals, revenue
account → program → activity → object flows, per-school detail, NCES
categories, sub-fund breakouts, four-year forecasts — with decoded
labels and dimensions pre-joined. Two files are enough for most
work:
- `safs_prod/f19x/general_fund_expenditures.avro` — full P×A×O cube
  including NCES, sub-fund, per-school grain; both actuals and budget
  in one table (filter on `data_type`).
- `safs_prod/f19x/general_fund_revenues.avro` — per-account
  revenues with OSPI's own **`program_code` attribution baked in**
  (so revenue → program flows work without any PDF).

**Reach for the Fiscal PDF path** only when you need a dimension
that genuinely doesn't exist in the SAFS raw path: per-duty-code
salary detail, balance sheets, long-term liabilities, the mid-year
revised (Final) Budget column, federal indirect cost rate
calculation, edit-check quality flags, or any of the
apportionment / 1191 / F-780 / 1191SI sub-reports (~15 dimensions
total).

See [extractors/fiscal/DATA_SOURCE_DIVERGENCE.md](extractors/fiscal/DATA_SOURCE_DIVERGENCE.md)
for the complete per-dimension mapping, working recipes for the
SAFS-first pattern, and the plan for closing the remaining SAFS
`ITEMDIC` coverage gap.

For the fiscal PDF outputs specifically, start with
[extractors/fiscal/OVERVIEW.md](extractors/fiscal/OVERVIEW.md) (map
of every fact CSV) and
[extractors/fiscal/CSV_GUIDE.md](extractors/fiscal/CSV_GUIDE.md)
(per-table schema, join keys, quirks).

## P223 data

### Setup

**Note:** This has only been tested on macOS.

```console
$ brew install pdftotext
```

`tr` is also required, but `tr` should already be installed by the OS:

```console
$ which tr
/usr/bin/tr
```

### Extracting data from multiple P223 PDFs
To extract data from multiple PDFs in an input directory:

```console
$ python3 extractors/p223_pdf_batch.py my/input/directory my/output/directory
```

**TODO:** Add instructions for retrieving PDFs and cached outputs from Google Cloud.

### Extracting data from a single P223 PDF
```console
$ curl \
    https://www.seattleschools.org/wp-content/uploads/2024/09/P223_Sep24.pdf \
    -o p223_sep24.pdf
$ pdftotext -layout p223_sep24.pdf -f 2 - | tr -s ' ' > squished.txt
$ python3 extractors/p223_pdf_to_csv.py squished.txt out.csv
```

### Data types and formats
Decimals are prefered to IEEE floating points. Many codes and IDs lend
themselves to integers.  In the accounting system, "Activity" and "Program" in
particular look like integers. However, in inte S275 document they added two
character values "SB" and "CP" to represent ASB and Capital Projects Fund
assignments even though those are not officially part of the Activity and
Program domains.  For these situations, we will use a custom encoding of the
non-confirmant values ot map into an unused portion of the integer space
(typically negatives) to allow the schema to be integers.

We will use BigQuery Decimal defaults of precision=38 and scale=9.

Monetary values more standardly use precision=19 and scale=2, but to keep
everything uniform just using BQ's larger range.
