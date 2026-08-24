# sps_web — scrapers for SPS board meetings and district websites

Scrapers that pull content from Seattle Public Schools' own web properties
(as opposed to OSPI, which the other `extractors/` families cover):

- **Board meetings** — agendas, minutes, action reports, and attachments
  from the board-meeting portal (BoardDocs / seattleschools.org board pages).
- **District websites** — seattleschools.org pages and documents (budget
  pages, press releases, school pages, etc.).

## Current project: board-approved contracts

`PLAN.md` is the executable plan for the first project here — every contract
the Board approved, 2005 → present, in a spreadsheet with primary-source
citations. It contains the verified source map (which site generation /
archive holds which years and how to fetch from each), the pipeline stages,
and one task card per subagent with a recommended model.

## Layout

```
extractors/sps_web/
  README.md        this file
  PLAN.md          board-contracts project plan + verified source map
  __init__.py      package marker; run modules as `python3 -m extractors.sps_web.<name>`
```

Add one module per source (e.g. `board_meetings.py`, `site_pages.py`).
Follow the repo convention: run from the repo root with package-relative
imports.

## Output

Raw fetched pages/documents land under `out_sps_web/` (gitignored via the
`out_*` rule). Curated results that should be kept go to `data/sps/` — that
tree is owner-managed, so do not have tooling write there directly.

## Notes

- Be polite to the district servers: cache fetched pages locally, honor
  `robots.txt`, and rate-limit requests.
- Browser-side scrapers (content scripts for the GitHub Pages site) live in
  `docs/contentscripts/scrappers/`; this directory is for Python scrapers
  that run locally.
