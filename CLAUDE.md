# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Scripts and tools for ingesting Seattle Public Schools / OSPI data (budgets, actuals, personnel, assessments, enrollment) from heterogeneous source formats (Access `.accdb`/`.mdb`, Excel, CSV, AVRO, PDF) into normalized AVRO files that are uploaded to GCS and loaded into BigQuery.

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
$ ./load_safs.sh
```

Run individual pipeline stages as modules (always from repo root, since they use package-relative imports):
```console
$ python3 -m extractors.safs.from_raw_file --db-drop-first --db-name=safs_prod <files...>
$ python3 -m extractors.safs.generate_final_tables --db-name=safs_prod <datasets...>
$ python3 -m extractors.safs.dump_tables --db-name=safs_prod --outdir=safs_prod <datasets...>
$ python3 -m extractors.safs.gcloud_load_tables --upload-to-gcs --load-bq-from-gcs --outdir=safs_prod <datasets...>
```

Valid `datasets` values: `domain enrollment sqss f19x s275 assessment`. Order matters in `from_raw_file` — `load_safs.sh` loads newest-to-oldest so newer schemas win when older sources are missing columns.

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

### Top-level scripts

`analyze.py`, `bigsheet.py`, `plot.py`, `scatter.py`, `boxplot.py`, `to_boss.py`, `odd_salary.py`, `avro_to_csv.py` are ad-hoc analysis/visualization scripts that operate on the CSV/AVRO outputs of the pipeline — they are not part of the production pipeline.

## Working in this repo

- Many `.csv`, `.avro`, `.pdf`, `.txt`, `.json`, `.accdb` files at the repo root are working data, not source — they're untracked and not checked in. `data/`, `input/`, `output/`, `olddata/`, `safs_prod/`, `regress/`, `stats/` are also working/output directories and gitignored. Don't treat anything outside `extractors/`, `bigquery/`, the top-level analysis `.py` files, and shell scripts as source.
- Run the SAFS modules as `python3 -m extractors.safs.<name>` from the repo root; they use package-relative imports and will fail if invoked as plain scripts from inside the package directory.
