# extractors/fiscal -- open work

Genuinely open build-pipeline work only. For the durable catalog of
unparsed sub-reports, coverage gaps, and form quirks, see
[COVERAGE.md](COVERAGE.md).

## Build pipeline gaps

- **Postgres staging + BigQuery loading now exist.** `extractors/bqload/`
  seeds `out_fiscal/*.csv` into a `fiscal_prod` Postgres database,
  exports zstd AVRO to `out_fiscal/tables/`, and loads BigQuery dataset
  `ospi_fiscal` (`WRITE_TRUNCATE`), run via `scripts/load_fiscal.sh`.
  It re-seeds wholesale from the fact CSVs on every run rather than
  updating incrementally -- see the next item.
- **No incremental per-file PDF re-parse.** `build_sources.py` /
  `extract_*.py` still rewrite every fact CSV from scratch each run,
  and `bqload` reseeds Postgres/BigQuery wholesale from those CSVs.
  Re-parsing only new or changed source PDFs (and re-seeding only the
  affected rows) is still unbuilt; revisit if the corpus grows enough
  that a full re-run becomes slow. `bqload` being seed-first doesn't
  solve this -- it still depends on `out_fiscal/*.csv` being fully
  regenerated upstream.
- **Parser throughput is pdfplumber-bound.** Parallel extraction
  (`extractors/fiscal/parallel.py`) uses a multiprocessing.Pool sized
  to `ncpu-1`. The `read_pdf_lines(path, max_pages=N)` argument was
  added during the Apportionment monthly run -- it dropped per-file
  parse time ~20x for that doc (40-90 page PDFs where only page 1 is
  parsed) and brought the full 52K-file corpus to ~12 minutes. F-195
  Overview (3,959 PDFs x ~41 pages, page 1 only) still uses the
  whole-doc reader (`parsers/f195_overview.py` calls `read_pdf_lines`
  with no `max_pages`); should be retrofitted with `max_pages=1` for a
  similar speedup on next re-run.
- **Second-pass parsed-text cache.** For any future big compound-doc
  parser (the current roster -- F-195 Budget full, F-196 All Pages,
  the rest of apportionment -- has all landed), a one-time pdfplumber
  extraction to `.txt.zst` files per source -- paired with a
  source-FK dimension keyed on `source_id` -- would let iterating
  parser logic skip pdfplumber on every re-run. Not currently planned
  since no new big parser is queued; worth revisiting if one is.
