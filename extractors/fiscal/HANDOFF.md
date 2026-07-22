# Fiscal-data parser handoff

You're building parsers for OSPI SAFS / apportionment fiscal reports,
modeled on the existing STARS parsers in `extractors/stars/`. Same
shape as STARS but ~100x the volume (~167K files / 142 GB).

## Read first (in order)

1. `extractors/stars/CSV_GUIDE.md` -- the analyst-facing landscape of
   what the STARS pipeline produces. Mirror this shape for fiscal.
2. `extractors/stars/README.md` -- the parser architecture decisions
   (long-form fact tables, schema reuse with safs, domain + dimension
   tables, NULL vs 0 semantics).
3. `extractors/stars/parsers/common.py` -- PDF/DOCX line reader + value
   tokenization helpers. Reusable.
4. `extractors/stars/filename.py` -- filename parser for the scraper's
   output naming convention.
5. `extractors/stars/schemas/domains.py` -- the `d_<corpus>_source`
   dimension pattern that dedups repeated filenames; copy this for
   fiscal.
6. `extractors/safs/schemas/common.py` -- `SCHOOL_YEAR_DISTRICT_FIELDS`
   to reuse on every fact table (gives joinability to SAFS budget /
   actuals on `class_of, ccddd`).
7. `docs/contentscripts/scrappers/ospi-funding-reports.js` -- the
   already-built SAFS/apportionment scraper. Output uses the same
   `{year} - {report_type} - [{org_type} - ]{org_label}({ccddd}) - {orig}.{ext}`
   convention as STARS, but the cascade has up to 5 levels (year,
   report_type, optional org_type, optional org, optional district).

## Scale concerns (different from STARS)

- 167K files vs 15K, ~9 GB processed text vs negligible. Don't load
  everything into Python lists. Stream rows to CSV as you go.
- Consider whether Postgres staging (like
  `extractors/safs/from_raw_file.py`) is worth it for joins /
  incremental updates. CSV output works for STARS volume; may not
  scale here.
- Parallelize per-file parsing if possible (the existing
  `extract_*.py` scripts are single-threaded).

## Conventions to preserve from STARS

- **Long-form fact tables.** One row per logical record.
- **Reuse `SCHOOL_YEAR_DISTRICT_FIELDS`** from `safs/schemas/common.py`
  so every fact joins to SAFS / `d_ccddd` on `(class_of, ccddd)`.
- **`d_<corpus>_source` dimension table** for source filename dedup
  (replace `_source` filename with integer `_source_id` FK; saves
  ~40% on STARS, will save more here).
- **Domain tables for opaque codes** -- one per code column with a
  `description` and at least one categorical metadata column.
- **NULL vs 0 distinction is meaningful** -- "no data row in source"
  is NULL, "OSPI printed a zero" is 0. Don't conflate.
- **Free-text district / school name columns** (e.g. host_district,
  cohort_district, destination_name in STARS) are not canonical FKs;
  flag them in the CSV_GUIDE.
- **`out_<corpus>/` is gitignored.** Build artifacts only.
- **Write a `CSV_GUIDE.md` for downstream consumers** at the end, same
  shape as `extractors/stars/CSV_GUIDE.md`.

## Things to clarify with the user before starting

1. Source directory layout: where is the scraped corpus? (`data/safs/`,
   `data/apportionment/`, something else?)
2. Which fiscal report types are in scope? (`Apportionment`,
   `ESD Allocations`, `State Institutions`, `Fiscal`, `County Treasurer`
   were the 5 listed on the SAFS dropdown when the scraper was built;
   subset?)
3. Is there a pre-existing `data/.../README.md` with a table of
   contents like STARS has? If so, read it.
4. Should the output target CSV (like STARS), Postgres staging (like
   SAFS `from_raw_file.py`), or AVRO + GCS + BigQuery (like the full
   SAFS pipeline)?
5. Sample 1-2 representative files per report type before designing
   schemas -- the form may differ from STARS even though the cascade
   structure is similar.

## Done criteria

Match the STARS "all reports parsed, 0 errors, 0 warnings, full CSV
outputs + dimension tables + a CSV_GUIDE.md" finish line. Document
known gaps + parsing quirks in a `TODO.md` alongside.
