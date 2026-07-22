# Enrollment Report Ingestion — Handoff Notes

_Last updated: 2026-06-09. For the next session (incl. a fresh model deciding how to proceed)._

## What was asked

Ingest **all** SPS Annual Enrollment Report PDFs in `data/sps/enrollment/`
(2010-11 → 2024-25, 14 files; 2022-23 is missing/never downloaded) and output
data files. Priority: **Section 4 origin-destination (OD)** data; **Table 1-D
per-school enrollment** also wanted. Processing code must be a **standalone
Python script**. Caveat the user gave: file format drifts, especially the early
cover pages.

## State: COMPLETE and verified. Script works end-to-end.

`extractors/enrollment_reports.py` (standalone — uses `pdftotext` + pandas, no
package imports). Run:

```console
$ venv/bin/python3 extractors/enrollment_reports.py            # all PDFs -> out_enrollment/
$ venv/bin/python3 extractors/enrollment_reports.py --year 2024-25 --outdir /tmp/x
```
(No need to `source venv/bin/activate` — see CLAUDE.md.)

Outputs to `out_enrollment/`, all combined across years with a `year` column
(school-year label, e.g. `2024-25`):

| file | rows | grain |
|---|---|---|
| `section4_od.csv` | 20,977 | `year, level, grade_band, residence_area, school, n` — area residents → schools (OD matrix rows) |
| `section4_attendees.csv` | 14,079 | `year, level, grade_band, school, residence_area, n` — school attendees by residence (OD columns) |
| `section4_option_draw.csv` | 5,465 | `year, level, school, grade_band, residence_area, n` — option/K-8 draw-only blocks |
| `enrollment_by_school.csv` | 1,340 | `year, service_area, school_name, prior_enrollment, projected_enrollment, enrollment, change` (Table 1-D) |

## Quality (already validated this session)

- **0 duplicate cells** in all 4 outputs (verified by groupby).
- **Section 4**: only **2 malformed row-names total**, both in 2010-11 and both
  caused by the *source PDF itself* garbling text (pdftotext split "McClure" →
  "M"+"cClure"). Not fixable in-parser. Everything else clean.
- **Table 1-D**: 100% internal cross-check (`change == enrollment − prior`) in
  every year that has the table.
- `level` ∈ {ES, MS, HS}. `grade_band` is non-null only for K-8 blocks
  (`K-5`/`6-8`); NaN otherwise. Diagonal/transpose spot-checks matched source.
- Names are kept RAW (title-names like "Thurgood Marshall" vs row-names "T.
  Marshall"; "John Stanford Intl" vs "J. Stanford Intl"). Normalization to a
  canonical school_id is intentionally NOT done here — left to downstream.

## Format drift the parser handles (the hard-won part)

- Unicode hyphens; `(PreK-5)`/`(K-5)`/`(6-8)` band labels.
- HS table is **4-D in 2010-11** (no 4-E) but **4-E from 2011-12 on**;
  `_level_map` derives this per file. Summary tables 4-B (and 4-D when 4-E
  exists) are ignored.
- TOC lists "Table 4-A" too → whole-doc scan with active-level reset on any
  other-section marker, instead of a fragile region slice.
- **Two layouts**: older reports (2011–2022) pack **two paired blocks side by
  side = four sub-columns** (`Attendance Area | School | Attendance Area |
  School`); 2023-25 use one block (two sub-columns). Parser treats every
  sub-column independently (classify by its title), then groups by school/area —
  layout-count-agnostic.
- Cramped columns where a single space separates one column's number from the
  next column's name (`1090 Ballard`): rows are parsed by **anchoring on the
  numeric values** and assigning each cell by its **midpoint** (value
  right-edges and name left-edges both drift onto neighbors' boundaries; the
  midpoint doesn't). A number only counts as a value if space-delimited, so
  digits in names ("Orca K-8", "AS #1") are safe.
- Page breaks mid-table (banner line appears between rows); cell-internal name
  wrapping (take fragment after last 2+-space gap); a `Grandt Total` source typo
  (fuzzy `_GRAND_TOTAL_RE`).
- Modern Section-1 summary (1-A/1-B/1-C) is **bar charts with numbers as chart
  labels** — deliberately NOT parsed. 2016-17 dropped Table 1-D entirely
  (chart-only) → that year is skipped for `enrollment_by_school.csv` and noted
  in the run output.

## Known residual / cosmetic (all minor, judged acceptable)

- A few "N tables w/o Grand Total" notes per year (max 6, in 2021-22). These
  tables' rows ARE captured; only the terminator line wasn't detected (title/name
  wrapping). The run prints these as flags — not data loss in practice.
- The 2 garbled 2010-11 names are dropped by the `_is_bad_name` filter.

## Open decisions for next session (this is where the fresh model picks up)

1. **gitignore**: `out_enrollment/` is NOT gitignored, nor are the input PDFs in
   `data/sps/enrollment/` (note `data/` IS gitignored per CLAUDE.md, so inputs
   are already ignored; outputs in `out_enrollment/` are not). User was asked and
   hasn't answered whether to gitignore `out_enrollment/`. `out_stars/` is the
   precedent (gitignored). **Likely action: add `out_enrollment/` to .gitignore.**
2. **Commit?** Nothing committed yet. The script `extractors/enrollment_reports.py` is the
   only thing worth committing (it's source). Branch first if asked (currently on
   `main`). Co-author trailer per CLAUDE.md.
3. **Possible follow-ons the user might want** (not requested yet): emit AVRO
   instead of/in addition to CSV to match the SAFS pipeline; load to BigQuery;
   reconcile Section-4 title-names ↔ row-names to a canonical school id; chase the
   ~3 "w/o Grand Total" tables in 2024-25 (John Stanford Intl, TOPS K-8, James
   Baldwin) if perfect terminator coverage is desired.
4. Prior related work: `reference/analysis/montecarlo/section4_seattle.py` parsed ONLY
   Section 4 for ONLY 2024-25 (for the ridership Monte Carlo). The new
   `extractors/enrollment_reports.py` supersedes it for all-years extraction but does NOT
   replace the montecarlo module's loaders. Don't delete the montecarlo one.

## Don't redo

Don't re-explore the PDF formats from scratch — the drift map above is complete
and the parser already encodes it. If extending, read `extractors/enrollment_reports.py`'s
module docstring + the inline comments in `_feed_rows` / `_parse_section4` first.
