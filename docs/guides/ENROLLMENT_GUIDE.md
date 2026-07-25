# SPS Annual Enrollment Reports — data guide

`extractors/enrollment_reports.py` ingests the SPS Annual Enrollment Report
PDFs in `data/sps/enrollment/` (2010-11 → 2024-25, 14 files; 2022-23 was
never published/downloaded) into four combined CSVs. It is a standalone
script (uses `pdftotext` + pandas, no package imports):

```console
$ venv/bin/python3 extractors/enrollment_reports.py            # all PDFs -> out_enrollment/
$ venv/bin/python3 extractors/enrollment_reports.py --year 2024-25 --outdir /tmp/x
```

## Outputs

All files land in `out_enrollment/` (gitignored), combined across years with
a `year` column (school-year label, e.g. `2024-25`):

| file | rows | grain |
|---|---|---|
| `section4_od.csv` | 20,977 | `year, level, grade_band, residence_area, school, n` — area residents → schools (OD matrix rows) |
| `section4_attendees.csv` | 14,079 | `year, level, grade_band, school, residence_area, n` — school attendees by residence (OD columns) |
| `section4_option_draw.csv` | 5,465 | `year, level, school, grade_band, residence_area, n` — option/K-8 draw-only blocks |
| `enrollment_by_school.csv` | 1,340 | `year, service_area, school_name, prior_enrollment, projected_enrollment, enrollment, change` (Table 1-D) |

Semantics: `level` ∈ {ES, MS, HS}. `grade_band` is non-null only for K-8
blocks (`K-5`/`6-8`); NaN otherwise. School/area names are kept RAW
(title-names like "Thurgood Marshall" vs row-names "T. Marshall") —
normalization to a canonical school id is intentionally left to downstream.

## Validation status

- **0 duplicate cells** in all 4 outputs (verified by groupby).
- **Section 4**: only 2 malformed row-names total, both in 2010-11 and both
  caused by the source PDF itself garbling text (pdftotext split "McClure" →
  "M"+"cClure"); dropped by the `_is_bad_name` filter. Not fixable in-parser.
- **Table 1-D**: 100% internal cross-check (`change == enrollment − prior`)
  in every year that has the table. 2016-17 dropped Table 1-D entirely
  (chart-only) → that year is absent from `enrollment_by_school.csv`.
- Diagonal/transpose spot-checks against the source matched.
- Residual cosmetic flags: a few "N tables w/o Grand Total" notes per year
  (max 6, in 2021-22) — those tables' rows ARE captured; only the terminator
  line wasn't detected. Printed as flags at run time; not data loss.

## Format drift the parser handles

Don't re-explore the PDF formats from scratch — this map is complete and the
parser already encodes it. If extending, read the module docstring plus the
inline comments in `_feed_rows` / `_parse_section4` first.

- Unicode hyphens; `(PreK-5)`/`(K-5)`/`(6-8)` band labels.
- HS table is **4-D in 2010-11** (no 4-E) but **4-E from 2011-12 on**;
  `_level_map` derives this per file. Summary tables 4-B (and 4-D when 4-E
  exists) are ignored.
- TOC lists "Table 4-A" too → whole-doc scan with active-level reset on any
  other-section marker, instead of a fragile region slice.
- **Two layouts**: older reports (2011–2022) pack two paired blocks side by
  side = four sub-columns (`Attendance Area | School | Attendance Area |
  School`); 2023-25 use one block (two sub-columns). The parser treats every
  sub-column independently (classify by its title), then groups by
  school/area — layout-count-agnostic.
- Cramped columns where a single space separates one column's number from
  the next column's name (`1090 Ballard`): rows are parsed by anchoring on
  the numeric values and assigning each cell by its **midpoint** (value
  right-edges and name left-edges both drift onto neighbors' boundaries; the
  midpoint doesn't). A number only counts as a value if space-delimited, so
  digits in names ("Orca K-8", "AS #1") are safe.
- Page breaks mid-table (banner line appears between rows); cell-internal
  name wrapping (take fragment after last 2+-space gap); a `Grandt Total`
  source typo (fuzzy `_GRAND_TOTAL_RE`).
- Modern Section-1 summary (1-A/1-B/1-C) is bar charts with numbers as chart
  labels — deliberately NOT parsed.

## Related

- Follow-ons (AVRO/BigQuery load, canonical school-id reconciliation) are
  tracked in `docs/BACKLOG.md`.
- `reference/analysis/montecarlo/section4_seattle.py` parsed only Section 4
  for only 2024-25 (for the ridership Monte Carlo). This extractor
  supersedes it for all-years extraction but does not replace the montecarlo
  module's loaders.
