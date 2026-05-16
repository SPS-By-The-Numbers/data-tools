# extractors/stars

Parsers for the published OSPI STARS (Student Transportation Allocation
Reporting System) reports. PDFs and DOCXs are scraped into
`data/stars/<report_type>/` by `docs/contentscripts/scrappers/ospi-stars-reports.js`
(see [the scraper page](https://sps-by-the-numbers.github.io/data-tools/)).

Five report types live under `data/stars/`:

- `operations_allocation/` -- Operations Allocation Detail
- `kpi/`                   -- Key Performance Indicators
- `quarterly_district/`    -- Quarterly District Detail
- `efficiency/`            -- Efficiency Detail
- `efficiency_review/`     -- Efficiency Review (only for districts that
                              crossed a threshold; sub-categorized by band)

Filenames follow the scraper convention
`{school_year} - {report_type} - [{org_type} - ]{org_label}(ccddd) - {orig}.{ext}`.
`filename.py` parses this into structured fields; the ccddd suffix is the
stable anchor since both district names and OSPI's original filenames
sometimes contain ` - `.

## What's in the data

OSPI publishes the STARS reports yearly (typically around April) to give
each district a snapshot of their pupil-transportation operations. The
data feed comes from the STARS reporting system itself: districts log
ridership counts, bus counts, and operating expenditures, OSPI aggregates
and reports back the derived efficiency metrics. The same input data
drives both the per-district printed reports we parse here and the
internal STARS efficiency rating used for transportation allocation.

Coverage and known gaps are tracked in [TODO.md](TODO.md).

## Reports & schemas

Schemas live under `schemas/` and reuse
`extractors.safs.schemas.common.SCHOOL_YEAR_DISTRICT_FIELDS` so every
STARS fact table joins to `d_ccddd` / `d_school` on `(class_of, ccddd)`
exactly the same as the SAFS budget/actuals tables.

### `stars_kpi` (parsed from `kpi/`)

Long-form per district per published-report-year per KPI per trailing
data year. Each PDF contributes 12 rows: 3 metrics x 3 trailing data
years (9 value rows) + 3 year-over-year change-pct rows.

| column             | type                | meaning |
|--------------------|---------------------|---------|
| `stars_kpi_id`     | auto_primary_key    | surrogate key. |
| `school_year`      | string (LK)         | School year of the *published report* (e.g. `2024-2025`). |
| `class_of`         | int                 | Ending year of `school_year` as an int (e.g. 2025). Convenience for sorting/joins. |
| `ccddd`            | int (LK)            | OSPI county-and-district code. Joins to `d_ccddd`. |
| `county`           | string              | County name. Empty in the parser output; populated via `d_ccddd` join. |
| `district`         | string              | District name (from the filename's org label). |
| `metric_code`      | string (LK)         | One of the six metric codes listed below. |
| `data_class_of`    | int (LK)            | Ending year (int) of the data year this row describes. |
| `data_school_year` | string              | Normalized `YYYY-YYYY` for `data_class_of`. Redundant convenience. |
| `value`            | decimal             | The metric value. NULL when the source cell was blank or `-`. |
| `_source`          | string              | Originating PDF filename. |
| `_source_table`    | string              | Always `stars_kpi`. |

Logical key (unique constraint): `(school_year, ccddd, metric_code, data_class_of)`.

Metric codes -- the report shows three KPIs, three trailing data years
each, with a year-over-year change percentage on the latest:

| `metric_code`                | what it measures                                                                                            | source line in PDF |
|------------------------------|-------------------------------------------------------------------------------------------------------------|--------------------|
| `basic_rider_kpi`            | Basic-program riders per basic-program bus. Total basic ridership / 2 (AM+PM) divided by basic bus count.   | page 4 sec. 1 |
| `sped_rider_kpi`             | Special-education riders per special-education bus. Same shape but for special-ed routes.                   | page 4 sec. 2 |
| `cost_per_rider`             | Average operating cost per transported rider (dollars per student per year).                                | page 5 sec. 3 |
| `basic_rider_kpi_change_pct` | Year-over-year change in `basic_rider_kpi` from the second-latest data year to the latest. `data_class_of` = latest data year. | sec. 1 last column |
| `sped_rider_kpi_change_pct`  | Same, for `sped_rider_kpi`.                                                                                 | sec. 2 last column |
| `cost_per_rider_change_pct`  | Same, for `cost_per_rider`. Negative is more efficient.                                                     | sec. 3 last column |

Notes on the values:

- **Data years lag report year by one.** A 2025-2026 report is published
  April 2026 and shows data through 2024-2025; the three trailing data
  years inside it are 2022-23, 2023-24, 2024-25.
- **COVID-era gaps.** 2023-2024 and 2022-2023 reports skip the
  2020-21 data year and substitute the pre-COVID year (e.g.
  `2019-20, 2021-22, 2022-23`). The parser reads year labels directly
  from the PDF rather than assuming a contiguous trailing window, so
  `data_school_year` is accurate even with the gap.
- **NULLs.** OSPI prints `-` in cells where a district had no rideship
  in a category (no special-ed transportation, for instance) or the
  metric was unreportable. The parser preserves these as `NULL` in
  `value` rather than coercing to zero.
- **Change-pct sign convention.** Positive change for the rider KPIs
  means *more* efficient (more riders per bus). Positive change for
  `cost_per_rider` means *less* efficient (cost rose).
- **Cohort tables are skipped.** The PDF's pages 6-9 list 21 cohort
  districts each with their own KPI values; we don't re-extract those
  since every cohort district's data is in its own PDF anyway.

The cohort *rankings* (the `+10`...`-10` column on those tables) are
the one piece of cohort-specific information that isn't recoverable
elsewhere -- they're not currently extracted; revisit if needed.

### `stars_operations_allocation` (parsed from `operations_allocation/`)

Long-form per district per school year per line item. OSPI's Operations
Allocation Detail Report (form 1026A) is a single page (PDF) or single
document (DOCX) per district per year with a fixed 30-item layout
organized into four sections (see schema doc). Each district-year emits
30 rows.

Column reference (in addition to `SCHOOL_YEAR_DISTRICT_FIELDS`):

| column            | type        | meaning |
|-------------------|-------------|---------|
| `section_code`    | string      | `A` / `B` / `C` / `D` — which section the item is in. |
| `item_code`       | string (LK) | Canonical snake_case identifier (e.g. `land_area`, `a6_calculated_expected_allocation`, `d8_actual_allocation_amount`). 30 distinct codes. |
| `item_label`      | string      | Raw label from the PDF/DOCX. |
| `item_value`      | decimal     | Section A detail input value (Land Area square miles, Basic Program enrollment, etc.). NULL on summary / dollar rows. |
| `coefficient`     | decimal     | Per-item coefficient/rate. Set for Section A detail rows and C.1 Alt Calendar Modifier. |
| `calculated_value`| decimal     | Unitless calculated value: Section A detail products + A.1-A.3 / A.5 summary rows. NULL on dollar rows. |
| `amount`          | decimal     | Dollar amount (Section A.4 / A.6 and every B / C / D row). |
| `running_total`   | decimal     | Cumulative dollar running total on B.6, C.1, C.3 (rows that print both an adjustment and its resulting subtotal). |

Logical key: `(school_year, ccddd, item_code)`.

Notes on the values:

- **Same data driven from formula inputs.** Section A details are the
  inputs (per-district land area, ridership counts) plus annual
  coefficients OSPI publishes; Sections B-D layer in fixed adjustments
  and the final amount. The numbers we care about for analysis are
  almost always `a6_calculated_expected_allocation` (what the formula
  produced), `d2_prior_year_expenditures` (what the district actually
  spent the previous year), and `d8_actual_allocation_amount` (the
  bottom-line transportation allocation the district receives).
- **COVID dip.** 2020-2021 allocations crash because pupil
  transportation was largely suspended; the `d2_prior_year_expenditures`
  trail shows the recovery over the following years.
- **`item_value` for Non-High rows.** OSPI prints a Yes/No flag in the
  "Value" column of `non_high_yes` / `non_high_no`. We capture only the
  numeric coefficient and `calculated_value`; the yes/no answer is
  effectively encoded in `calculated_value` being nonzero.
- **Tribal compacts and charter schools use a different form** (1026A
  COMPACT) and are skipped (logged at INFO level, 143 of 2,908 files in
  the corpus). See TODO.md for details.

### `stars_quarterly_district` (parsed from `quarterly_district/`)

Long-form per district per school year per quarter per metric. OSPI
publishes one Quarterly District Detail report per quarter (FALL / WINTER
/ SPRING) with three summary sections that this parser captures
(STUDENT DETAIL, ROUTE SUMMARY, BUS SUMMARY). Each (school_year, ccddd,
quarter) tuple emits 28 rows, one per metric.

| column           | type        | meaning |
|------------------|-------------|---------|
| `stars_quarterly_district_id` | auto_primary_key | surrogate key |
| `school_year`    | string (LK) | School year of the report (e.g. `2024-2025`). |
| `class_of`       | int         | End year of the school year as an int. |
| `ccddd`          | int (LK)    | OSPI county-and-district code. Joins to `d_ccddd`. |
| `county`         | string      | County name (filled via `d_ccddd` join). |
| `district`       | string      | District name from the filename. |
| `quarter`        | string (LK) | `FALL` / `WINTER` / `SPRING`, extracted from the filename's original-name segment. |
| `metric_code`    | string (LK) | One of 28 metric identifiers (see schema). |
| `value`          | decimal     | Metric value. NULL when the source's data row was absent. |
| `_source`        | string      | Originating PDF/DOCX filename. |
| `_source_table`  | string      | `stars_quarterly_district`. |

Logical key: `(school_year, ccddd, quarter, metric_code)`.

The 28 metrics split into:

- **STUDENT DETAIL** (10): basic-program rider counts (`basic_students_*`:
  `on_buses`, `in_walk_areas`, `transit_buses`, `total`) and special-program
  rider subdivisions (`special_students_*`: `special_ed`, `bilingual`,
  `gifted`, `homeless`, `early_ed`, `total`).
- **ROUTE SUMMARY** (10): route counts by program (`routes_basic`,
  `routes_special`, `routes_bilingual`, `routes_gifted`, `routes_homeless`,
  `routes_early_ed`, `routes_total`) plus `route_summary_destinations`,
  `route_summary_total_buses`, and `route_summary_average_distance`.
- **BUS SUMMARY** (8): bus counts by program (`buses_*` with the same
  six programs) plus `bus_summary_destinations`, `bus_summary_total_buses`.

Notes on the values:

- **Per-route ROUTE DETAIL is not extracted.** Every report has a
  trailing per-route section with one row per individual bus route
  (route number, bus, state bus, destination, stop count, total stops,
  average distance). Voluminous (hundreds of rows for larger districts)
  and not needed for current analyses; could be its own
  `stars_quarterly_route` table later.
- **COVID dip is preserved as zero, not NULL.** Districts that genuinely
  reported zero transportation in 2020-2021 (Seattle FALL 2020-2021 has
  `basic_students_total = 0`) keep the literal zero so consumers can
  compute the recovery curve.
- **NULL vs 0.** OSPI sometimes generates a report where the data row
  is entirely absent (small districts that didn't transport anyone, or
  charter schools whose ROUTE SUMMARY has no average distance because
  they have no routes). The parser keeps the row coverage and fills
  unparsable metric slots with NULL to distinguish "reported zero"
  from "not reported".
- **Quarter detection.** The parser reads FALL / WINTER / SPRING out of
  the filename's last segment (e.g. `Almira FALL` -> `FALL`). Case-
  insensitive search, so `AlmiraWinter` also works if it ever shows up.

## Pipeline (current state)

1. **Filename parse** (`filename.py`) -- strict on the `(NNNNN)` ccddd
   anchor, lenient about adjacent segments.
2. **Per-report-type extraction** (`parsers/<report>.py`) -- pdfplumber
   text + heuristics, producing dicts matching `schemas/<report>.py`.
3. **CLI driver** (`extract_<report>.py`) -- walks a directory, dispatches
   to the right parser, emits CSV / JSON / summary.

Currently implemented: `kpi`, `operations_allocation`, `quarterly_district`.
Efficiency and Efficiency Review are pending.
