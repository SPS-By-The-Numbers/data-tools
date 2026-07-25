# STARS — open work

Open items only. The durable catalog of known data gaps, missing
(year × report_type) cells, and parser-absorbed quirks lives in
[COVERAGE.md](COVERAGE.md).

- [ ] Verify the remaining "probable not-published" cells against the live
      STARS page: 2016-17 (all but efficiency_review), 2018-19
      efficiency_review, 2020-21/2021-22 efficiency_review, 2025-26
      efficiency_review (see COVERAGE.md for context).
- [ ] Re-scrape any that turn out to be real misses with
      `OSPI_SCRAPER_START`/`END` to bound the range.
- [ ] Have the extract drivers log any (year, report_type) for which
      parsing produced zero rows so silent-empty PDFs/DOCXs get flagged
      (today only per-file anchors-not-found warnings surface them).
