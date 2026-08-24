# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Scripts and tools for ingesting Seattle Public Schools / OSPI data (budgets, actuals, personnel, assessments, enrollment) from heterogeneous source formats (Access `.accdb`/`.mdb`, Excel, CSV, AVRO, PDF) into normalized AVRO files that are uploaded to GCS and loaded into BigQuery.

## Repository layout

- `extractors/`, `bigquery/` — pipeline source code (`bigquery/` is legacy, pre-SAFS).
- `marts/` — pointer only: the `bigsheet` per-school data mart migrated to the website repo (see Marts section).
- `scripts/`, `tools/` — shell entry points and ad-hoc analysis scripts.
- `docs/` — documentation index (`docs/README.md` — start there), generated BigQuery data dictionary (`docs/DATA_DICTIONARY.md`), repo backlog (`docs/BACKLOG.md`), dev guides (`docs/guides/`), GitHub Pages site + scrapers (`docs/index.html`, `docs/contentscripts/`).
- `data/` — raw source, syncs to GCS via `scripts/push_data_to_gcs.sh` / `pull_data_from_gcs.sh`. Read-only for tooling; only the owner adds to it. See README.md for the subtree breakdown and sizes.
- `reference/` — human reference only, gitignored, never cleaned by tooling (`input/`, `olddata/`, `regress/`, `stats/`, `analysis/`, `scratch/`, `prr/`).
- `attic/` — pending owner triage; see `attic/MANIFEST.md`.
- `safs_prod/`, `output/`, `out_*/` — generated, gitignored in place. TODO: `safs_prod/`, `output/`, `out_*` should move under one output root; requires coordinated updates to `scripts/load_safs.sh` and fiscal/stars extractor paths (see `docs/BACKLOG.md`).

## Setup

```console
$ python3 -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt
$ brew install pdftotext mdbtools     # pdftotext for P223; mdbtools for .accdb/.mdb
```

A local PostgreSQL server is required for the SAFS pipeline (used as a staging RDBMS — connections go to `localhost`, see `extractors/safs/db_connection.py`). `tr` (already on macOS) is also required for P223.

There is no need to `source venv/bin/activate`. Activation only edits `PATH`/`$VIRTUAL_ENV` for an interactive shell; it changes nothing about how scripts run. Instead, invoke the venv interpreter directly — `venv/bin/python3 -m extractors.safs.from_raw_file ...`, `venv/bin/pytest`, `venv/bin/pip` — and it will use the venv's site-packages regardless. The `python3`/`pytest` commands shown below assume the venv is on `PATH` (i.e. activated); prefix them with `venv/bin/` to skip activation.

## Common commands

Run tests:
```console
$ pytest                                         # all tests
$ pytest extractors/safs/data_reader_test.py     # one file
$ pytest extractors/safs/data_reader_test.py::test_tables   # one test
```

Run the full SAFS pipeline (loads raw files → Postgres → final tables → AVRO → GCS → BigQuery):
```console
$ ./scripts/load_safs.sh
```

Run individual pipeline stages as modules (always from repo root, since they use package-relative imports):
```console
$ python3 -m extractors.safs.from_raw_file --db-drop-first --db-name=safs_prod <files...>
$ python3 -m extractors.safs.generate_final_tables --db-name=safs_prod <datasets...>
$ python3 -m extractors.safs.dump_tables --db-name=safs_prod --outdir=safs_prod <datasets...>
$ python3 -m extractors.safs.gcloud_load_tables --upload-to-gcs --load-bq-from-gcs --outdir=safs_prod <datasets...>
```

Valid `datasets` values: `domain enrollment sqss f19x s275 assessment`. Order matters in `from_raw_file` — `scripts/load_safs.sh` loads newest-to-oldest so newer schemas win when older sources are missing columns.

Extract P223 enrollment PDFs:
```console
$ python3 extractors/p223_pdf_batch.py my/input/dir my/output/dir          # batch
$ pdftotext -layout p223_sep24.pdf -f 2 - | tr -s ' ' > squished.txt       # single, step 1
$ python3 extractors/p223_pdf_to_csv.py squished.txt out.csv               # single, step 2
```

## Architecture

### The SAFS pipeline (`extractors/safs/`)

This is the bulk of the code and the part most likely to need modification. It's a four-stage ETL with PostgreSQL as a staging area:

1. **`from_raw_file.py`** — reads each input file, normalizes column names, parses values into typed AVRO-shaped records, and inserts them into per-source raw tables in Postgres. The shape of input matters:
   - `XlsxRawReader` / `CsvRawReader` / `MdbRawReader` (uses `mdb-tables` and `mdb-export` subprocesses) / `AvroRawReader` are picked based on file extension.
   - `datatype()` on each reader returns one of `f195`, `f196`, `s275`, `assessment`, `sqss`, `enrollment`, `historical-enrollment-summary`, `spsbtn`, `f196-codes`. Filename conventions (`YYYY-YYYY-<datatype>-<table>.csv`, `YYYY-YYYY-<datatype>.xlsx`, `YYYY-YYYY-<datatype>.avro`) drive both school-year and datatype inference. For `.accdb`/`.mdb`, datatype is inferred from table names inside the database.
   - Per-datatype config in `data_reader_config/` declares header→schema mapping and table-name normalization. `DataReader` (in `data_reader.py`) glues a raw reader to a config.
   - Each loaded row gets injected `_source_table` and `_source` columns, and `school_year` is back-filled from filename or table-name conventions in `_get_additional_school_year`.

2. **`generate_final_tables.py`** — reads from the raw staging tables and writes denormalized/cleaned "final" tables back into Postgres. Final-table SQLAlchemy schemas live in `schemas/` (`f19x.py`, `s275.py`, `assessment.py`, `domains.py`, `enrollment.py`, `sqss.py`, each exporting `ALL_SCHEMAS`). The transformation logic for each dataset lives in `transforms/`. **s275 has by far the most complex transform** — it merges denormalized payroll rows from different OSPI departments with different update cadences (see `extractors/safs/README.md` for context).

3. **`dump_tables.py`** — serializes the Postgres final tables back out to AVRO files (zstandard-compressed) under `<outdir>/<dataset>/<table>.avro`.

4. **`gcloud_load_tables.py`** — uploads AVRO files to GCS and loads them into BigQuery. Dataset routing in `bq_dataset_name`: `assessment` and `sqss` go to BigQuery dataset `ospi`; everything else goes to `safs_<dataset>`. Files whose name contains `private` are routed to the `sps-btn-data-private` GCS bucket; others go to `sps-btn-data-all-data`. The GCP project is `sps-btn-data`.

### Schema system

Schemas are plain Python dicts with a custom shape (see `data_reader.py:212` and `schemas/`):
```
{
  'name': 'table_name',
  'fields': [
    {'name': 'col', 'source': 'Raw Col Name', 'field_type': 'decimal'|'string'|'int'|'boolean'|'timestamp'|'auto_primary_key',
     'doc': '...', 'is_primary_key': bool, 'is_logical_key': bool, 'foreign_key': '...', 'extractor': fn},
    ...
  ],
  'unique': [['col1', 'col2'], ...],
}
```
The same schema dict is converted to SQLAlchemy `Table` (via `orm.py:make_table`) and to AVRO (via `avro_schema.py:to_avro_schema`). When adding a column, modify the schema in `schemas/` rather than touching SQL or AVRO code separately.

### Data type conventions (from README.md)

- Prefer **DECIMAL** over IEEE floats. BigQuery DECIMAL is uniformly `precision=38, scale=9` (`DECIMAL_PRECISION` / `DECIMAL_SCALE` in `avro_schema.py`).
- Codes that *look* numeric but have rare non-numeric values (e.g. S-275 Activity/Program columns with `"SB"`, `"CP"`) are encoded as integers using sentinels in the negative range. NULLs likewise use sentinel values (`_NULL_NUMBER = -931415926`) so that UNIQUE constraints behave correctly across the staging RDBMS; sentinels are unwound back to real nulls in `to_avro_value` when exporting AVRO.

### Other extractors

- `extractors/p223_pdf_batch.py` + `p223_pdf_to_csv.py` — Seattle Public Schools monthly P223 enrollment PDFs.
- `extractors/budget/` — Seattle Public Schools "purple book" budget PDFs / school-allocation breakdowns.
- `extractors/purplebook/` — companion parsers for purple-book sections.
- `extractors/odata/` — OSPI OData endpoints (e.g. `ospi-odata-load.py`).
- `extractors/2023_budget_school_breakdown_to_csv.py`, `2024_budget_school_breakdown_to_csv.py` — year-specific one-off scripts.

### Marts

**MIGRATED (2026-07-25):** `bigsheet` — the joined per-school wide sheet —
lives entirely in the website repo as a BigQuery Cloud Function
(`sps-by-the-numbers-website/functions/src/bigsheet/`), the single source of
truth. The Python implementation was deleted from this tree (recover from git
history if needed); `marts/README.md` is the pointer. Column
naming/structure: the website's `NAMING.md`; legacy→current mapping:
`COLUMN_MAPPING.csv` there.

This repo still owns the seven `data/sps` static inputs, published to
BigQuery external tables via `scripts/publish_bigsheet_inputs.sh` then
`create_bigsheet_input_tables.sh` (in that order — schemas are positional
over the CSVs); re-run both whenever those CSVs change, then bump
`BIGSHEET_SQL_VERSION` in the website (the export cache does not
auto-invalidate on CSV content changes).

### The bqload pipeline (`extractors/bqload/`)

Loads the parsed fiscal + STARS PDF outputs into BigQuery, reusing the SAFS
schema/AVRO stack. It is **seed-first**: it stages the already-parsed
`out_fiscal/`/`out_stars/` CSVs into Postgres (`fiscal_prod`/`stars_prod`),
exports zstandard AVRO, and loads BigQuery datasets `ospi_fiscal` / `ospi_stars`
(project `sps-btn-data`). It does **not** re-parse the ~142GB PDF corpus —
assume the fiscal/stars extractors already produced their CSVs.

- Family registries (`extractors/{fiscal,stars}/registry.py`) auto-build one
  `TableSpec` per schema and annotate the 8 fiscal tables that duplicate SAFS
  (see `extractors/fiscal/DATA_SOURCE_DIVERGENCE.md`).
- Core modules: `staging.py` (Postgres seed + `_bqload_manifest` idempotence),
  `export.py` (AVRO + meta.json skip), `gcs_bq.py` (upload + WRITE_TRUNCATE
  load + column descriptions), `run.py` (CLI), `gen_dictionary.py`
  (`docs/DATA_DICTIONARY.md`).

```console
$ scripts/load_fiscal.sh                                  # local: seed,export
$ STAGES=seed,export,upload,load scripts/load_fiscal.sh   # + GCS + BigQuery
$ scripts/load_stars.sh
$ python3 -m extractors.bqload.run --family fiscal --stages seed,export --tables fiscal_f196_summary
```

Numeric fidelity is exact end-to-end (CSV → `Decimal` → Postgres `DECIMAL(38,9)`
→ AVRO decimal bytes → BigQuery NUMERIC). AVRO exports land in
`out_<family>/tables/` (gitignored). `docs/DATA_DICTIONARY.md` is generated —
edit the schema modules, not the Markdown.

### Top-level scripts

`tools/analyze.py`, `tools/plot.py`, `tools/scatter.py`, `tools/boxplot.py`, `tools/to_boss.py`, `tools/odd_salary.py`, `tools/avro_to_csv.py` are ad-hoc analysis/visualization scripts that operate on the CSV/AVRO outputs of the pipeline — they are not part of the production pipeline.

## Working in this repo

- Root data files, `input/`, `olddata/`, `regress/`, `stats/`, `analysis/`, and root `scratch_*` files now live under `reference/` (gitignored, human reference only, moved as-is — never edited or cleaned by tooling). `attic/` holds parked root clutter awaiting owner triage; `data/` is raw source, read-only for tooling. `output/`, `safs_prod/` are still generated/gitignored in place. Don't treat anything outside `extractors/`, `bigquery/`, `marts/`, `tools/`, `scripts/`, and `docs/` as source.
- Run the SAFS modules as `python3 -m extractors.safs.<name>` from the repo root; they use package-relative imports and will fail if invoked as plain scripts from inside the package directory.
