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
  COMPACT / CHARTER) and are handled by `stars_operations_allocation_compact`
  (next section). The standard parser silently skips them; the compact
  parser silently skips standard 1026A files. Together they cover all
  2,908 files in the corpus.

### `stars_operations_allocation_compact` (parsed from `operations_allocation/`)

Tribal compact schools and charter school districts use a different
1026A form than regular school districts. Their allocation is computed
from a host district's per-rider allocation multiplied by the
compact/charter's own eligible ridership prorated across the year:

  - Section A: host district's per-student allocation (A.1 total
    eligible riders, A.2 operations allocation, A.3 depreciation, A.4
    total funding = A.2+A.3, A.5 per-rider = A.4/A.1).
  - Section B: compact/charter's eligible riders by season (B.1 Spring,
    B.2 Fall, B.3 Winter, B.4 prorated = (B.1*3/8)+(B.2*2/8)+(B.3*3/8)).
  - Section C: final allocation = A.5 * B.4.

One row per (school_year, ccddd).

| column                              | type        | meaning |
|-------------------------------------|-------------|---------|
| `stars_operations_allocation_compact_id` | auto_primary_key | surrogate key |
| `school_year` / `class_of` / `ccddd` / `county` / `district` | | from `SCHOOL_YEAR_DISTRICT_FIELDS` |
| `report_type`                       | string      | `COMPACT` (tribal) or `CHARTER`. |
| `school_name`                       | string      | School/compact name as printed on the cover page; may differ from the filename district. |
| `host_district`                     | string      | Host district name (e.g. `North Kitsap`, `Ferndale`, `SPOKANE Public Schools`). |
| `host_data_year`                    | string      | School year of the host's data used for the per-rider calc. |
| `host_total_eligible_riders`        | decimal     | A.1. |
| `host_operations_allocation`        | decimal     | A.2 ($). |
| `host_depreciation`                 | decimal     | A.3 ($); for charters this is the A.3.c total of in-lieu + bus depreciation. |
| `host_total_transportation_funding` | decimal     | A.4 ($, = A.2+A.3). |
| `host_per_rider_allocation`         | decimal     | A.5 ($, = A.4/A.1). |
| `spring_riders`                     | int         | B.1. |
| `fall_riders`                       | int         | B.2. |
| `winter_riders`                     | int         | B.3. |
| `prorated_riders`                   | decimal     | B.4. |
| `final_allocation`                  | decimal     | Section C ($, = A.5 * B.4). |

Logical key: `(school_year, ccddd)`.

Notes on parsing:

- **Detection** is by the unique Section A header pattern
  (`Calculation of YYYY-YY per Student Allocation for ...`) -- not the
  cover-page tag, which has multiple variants: `Report 1026A (COMPACT)`,
  `Report 1026A (CHARTER)`, `Report 1026A Charter Schools (9/2020)`,
  or just `Report 1026A Revised` for older revisions.
- **Type classification** falls back through: explicit tag -> filename
  keyword (`Tribal`/`Compact` -> COMPACT, `Charter` -> CHARTER) -> body
  keyword. If everything fails, defaults to COMPACT with a warning.
- **Parenthesized formula text** like `((B.1*3/8) + (B.2*2/8) + (B.3*3/8))`
  is stripped before regex matching so the formula digits don't pollute
  the value scan. The `(COMPACT)` / `(CHARTER)` cover-page tag is
  detected BEFORE that stripping happens.
- **Dollar-amount fields are anchored on `$`** so embedded host-district
  reference years (e.g. `From Ferndale 2016-17 1191TRNF $2,243,521.03`)
  don't get captured instead of the actual amount.

Coverage: 143 of 2,908 operations_allocation files (48 COMPACT + 95
CHARTER); the other 2,765 are standard 1026A handled by the sibling
`stars_operations_allocation` table.

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

- **Per-route ROUTE DETAIL** lives in the companion
  `stars_quarterly_district_route` table -- one row per individual bus
  route -- documented in the next section.
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

### `stars_quarterly_district_route` (parsed from `quarterly_district/`)

Companion table to `stars_quarterly_district`. Each Quarterly District
Detail report has a ROUTE DETAIL section listing every individual bus
route the district operated that quarter, grouped under one of six
program codes. Larger districts run hundreds of routes per quarter
(Seattle: 709 in 2017-18, Kent: 628 in 2025-26).

Long-form: one row per `(school_year, ccddd, quarter, program, route_number)`.

| column            | type        | meaning |
|-------------------|-------------|---------|
| `stars_quarterly_district_route_id` | auto_primary_key | surrogate key |
| `school_year`     | string (LK) | School year of the report. |
| `class_of`        | int         | End year of the school year as an int. |
| `ccddd`           | int (LK)    | OSPI county-and-district code. |
| `county`          | string      | County name (via `d_ccddd` join). |
| `district`        | string      | District name. |
| `quarter`         | string (LK) | `FALL` / `WINTER` / `SPRING`. |
| `program`         | string (LK) | `basic`, `special_ed`, `bilingual`, `gifted`, `homeless`, or `early_ed`. |
| `route_number`    | string (LK) | District route identifier. String because some districts use suffixed forms (`0079-I`, `0405-T`) while small districts use bare integers (`1`, `7`). |
| `district_bus_number` | int     | District-assigned bus identifier. |
| `state_bus_number` | int        | OSPI state bus identifier (typically 6 digits). |
| `destination_name` | string     | Free-text destination as printed (e.g. `Kimball Elementary`, `Robert Eagle Staff M.S.`). |
| `stop_count`      | int         | Number of stops on this route. |
| `total_stops`     | int         | Total stops including pickups and dropoffs. |
| `average_distance` | decimal    | Average per-stop distance in miles. |
| `_source`         | string      | Originating PDF/DOCX filename. |
| `_source_table`   | string      | `stars_quarterly_district_route`. |

Notes on parsing:

- **PDF format**: each route is one space-separated line, optionally
  prefixed with `Basic Program (A)` / `Special Ed Program (S)` / etc.
  on the first route of each program group on each page. Parser walks
  lines after `ROUTE DETAIL`, skips page chrome (`STF-N`, `Page X of
  Y`, re-printed section/column headers, district banner caps),
  picks up program labels, and emits one route per recognized data line.
- **DOCX format**: route detail is an 8-column table where cell 0 holds
  the program label on the first row of each program group (empty on
  continuation rows) and cells 1-7 are the route fields. Parser
  iterates the underlying `<w:tr>` XML rows directly because
  per-paragraph extraction drops empty cells and misaligns the
  grouping (Seattle 2017-18 routes had blank route_number / bus
  cells on some continuation rows -- iterating cells preserves them).
- **Counts cross-check the summary table.** For every (school_year,
  ccddd, quarter), `count(*) where program='basic'` matches
  `routes_basic` from `stars_quarterly_district`, etc. Used as
  the parser correctness check (Seattle 2017-18 FALL: 225 basic +
  344 special_ed + 12 bilingual + 68 gifted + 13 homeless + 47
  early_ed = 709 routes, matches `routes_total = 709`).

### `stars_efficiency` + `stars_efficiency_cohort` (parsed from `efficiency/`)

The Efficiency Detail Report (form STF-8) compares each district's
transportation operations against a cohort of peer districts and
publishes a final Relative Efficiency Rating (RER, percentage where
100% = on-target with the cohort weighting). Each report is one page
per district per school year and lays out:

  - One subject row with the district's own metrics.
  - 0..N `Cohort <Peer>` rows, each with a peer's metrics and a cohort
    weight (cohort weights sum to ~100%).
  - One `Target <Subject> Target 100%` row carrying the cohort-weighted
    target expenditure and bus count.
  - A `Relative Efficiency Rating <pct>%` footer.

The data splits cleanly into two tables:

**`stars_efficiency`** -- one row per (school_year, ccddd). Carries the
subject district's own metrics, the target's expenditure + bus count,
and the RER.

| column                          | type        | meaning |
|---------------------------------|-------------|---------|
| `stars_efficiency_id`           | auto_primary_key | surrogate key |
| `school_year`                   | string (LK) | School year of the report |
| `class_of` / `ccddd` / `county` / `district` | (from `SCHOOL_YEAR_DISTRICT_FIELDS`) | |
| `prior_year_expenditures`       | decimal     | Subject's prior-year total transportation expenditures, in dollars. |
| `buses`                         | int         | Buses operated. |
| `basic_riders`                  | int         | Basic program riders. |
| `special_riders`                | int         | Special education riders. |
| `avg_distance`                  | decimal     | Average route distance, miles. |
| `num_destinations`              | int         | Distinct destinations. |
| `land_area`                     | decimal     | District land area, square miles. |
| `k_rte`                         | int         | OSPI "K Rte" column. Almost always 0; meaning not documented publicly. |
| `road_miles_per_sq_mile`        | decimal     | Road miles per square mile of district area. |
| `students_per_road_mile`        | decimal     | Riders per road mile (density). |
| `target_prior_year_expenditures`| decimal     | Cohort-weighted target expenditure. |
| `target_buses`                  | int         | Cohort-weighted target bus count. |
| `relative_efficiency_rating`    | decimal     | RER as a percentage (e.g. `74.95` means 74.95%). |

Logical key: `(school_year, ccddd)`.

**`stars_efficiency_cohort`** -- one row per (subject, peer). Each
cohort peer's metrics are denormalized (also available via that peer's
own `stars_efficiency` row).

| column            | type        | meaning |
|-------------------|-------------|---------|
| `stars_efficiency_cohort_id` | auto_primary_key | surrogate key |
| `school_year` / `class_of` / `ccddd` / `county` / `district` | | subject district |
| `cohort_district` | string (LK) | Peer district name as printed in the report (short name). |
| `weight_pct`      | decimal     | Cohort weight percentage. Weights sum to ~100% for a given subject. |
| (10 metric columns same as `stars_efficiency`) | | Peer's metrics. |

Logical key: `(school_year, ccddd, cohort_district)`.

Notes on the values:

- **DOCX side**: the data table is a 13-cell `<w:tr>` (col 0 = role
  marker like `Cohort`/`Target`/blank, col 1 = district name, col 2 =
  weight, cols 3-12 = the 10 metrics). Parsed via direct XML iteration.
- **PDF side**: each row is one space-separated line; the parser
  classifies by leading token (`Cohort`, `Target`, `Relative Efficiency
  Rating`, or otherwise a self row whose name precedes the first `$`).
- **Districts with no transportation** (tribal compacts, charter
  schools without buses) produce a subject row of all zeros and zero
  cohort peers -- their RER is left NULL because OSPI doesn't compute
  one for these cases.

### `stars_efficiency_review` (parsed from `efficiency_review/`)

OSPI's Regional Transportation Coordinators (RTCs) publish a written
review for any district whose Relative Efficiency Rating (RER) crossed
the 90% threshold versus the prior year, or that remained below 90%
for multiple years. Each report is a multi-page **narrative** document
-- mostly prose, not structured tables -- so this parser extracts
just the executive-summary numerics + the metadata that is reliably
present in every report.

One row per (school_year, ccddd).

| column                       | type        | meaning |
|------------------------------|-------------|---------|
| `stars_efficiency_review_id` | auto_primary_key | surrogate key |
| `school_year`                | string (LK) | School year of the published review. |
| `class_of` / `ccddd` / `county` / `district` | | from `SCHOOL_YEAR_DISTRICT_FIELDS` |
| `subcategory`                | string      | Raw subcategory label from the filename, e.g. `Current above 90% Prior below 90%`. |
| `current_band`               | string      | `above_90` / `below_90`. RER band at this review. |
| `prior_band`                 | string      | `above_90` / `below_90`. RER band the year before. |
| `review_year_text`           | string      | School year being reviewed, as printed (e.g. `2015-16`). Typically one year before `school_year`. |
| `review_date`                | string      | Date the review was issued, as printed on the cover (free text, not normalized). |
| `rtc_name`                   | string      | RTC who conducted the review (NULL when the template's placeholder text was never filled in). |
| `rtc_esd`                    | string      | RTC's Educational Service District. Only populated for the older format with a `from <ESD>` suffix (16-17, 17-18 reports). |
| `fte_enrollment`             | decimal     | Full-time-equivalent enrollment. |
| `basic_riders`               | int         | Average daily basic-program riders. |
| `special_riders`             | int         | Average daily special-program riders. |
| `buses`                      | int         | School buses operated. |
| `total_cost`                 | decimal     | Total transportation expenditures. |
| `current_rer`                | decimal     | The report's headline RER percentage. |
| `prior_rer`                  | decimal     | RER from one year before. |
| `two_years_prior_rer`        | decimal     | RER from two years before. |

Logical key: `(school_year, ccddd)`.

Notes on the values:

- **Best-effort regex extraction.** Each field is independently extracted
  with a regex against the joined PDF text; when the pattern doesn't
  match (rare phrasing variants, template placeholders like "conducted
  by .", redacted/anonymized fields) the column is left NULL.
- **Fill rates in the current 504-file corpus**: school year / ccddd /
  band metadata / current_rer / prior_rer = 100%; review_date /
  two_years_prior_rer = 99%+; rtc_name / fte_enrollment = 95%+;
  buses / total_cost = 93%; basic_riders / special_riders = 74%
  (some reports phrase ridership differently); rtc_esd = 13% (only
  the older "from ESD" phrasing).
- **No structured cohort table.** The Efficiency Review's narrative
  cohort table varies in format too much to parse reliably; if you
  need cohort comparisons see `stars_efficiency_cohort` for the
  same school year, which has the same data more cleanly.

## Domain (lookup) tables

Six small reference tables in `schemas/domains.py` turn the opaque
string codes used on the fact tables into self-documenting joins.
Materialize them as CSVs with `extract_domains.py`:

```bash
python3 -m extractors.stars.extract_domains out_stars/
```

| table | rows | joins to |
|---|--:|---|
| `d_stars_kpi_metric`           |  6 | `stars_kpi.metric_code` |
| `d_stars_quarterly_metric`     | 28 | `stars_quarterly_district.metric_code` |
| `d_stars_route_program`        |  6 | `stars_quarterly_district_route.program` |
| `d_stars_quarter`              |  3 | `stars_quarterly_district.quarter`, `stars_quarterly_district_route.quarter` |
| `d_stars_ops_allocation_section` |  4 | `stars_operations_allocation.section_code` |
| `d_stars_ops_allocation_item`  | 30 | `stars_operations_allocation.item_code` |

Each carries a `description` column plus a few categorical metadata
columns (e.g. `unit`, `program`, `is_change_pct`) for grouping queries.
The data is small and stable across years, so it lives inline as Python
constants in `schemas/domains.py:ROWS_BY_TABLE` -- there's no separate
load step needed.

## Pipeline (current state)

1. **Filename parse** (`filename.py`) -- strict on the `(NNNNN)` ccddd
   anchor, lenient about adjacent segments.
2. **Per-report-type extraction** (`parsers/<report>.py`) -- pdfplumber
   text + heuristics, producing dicts matching `schemas/<report>.py`.
3. **CLI driver** (`extract_<report>.py`) -- walks a directory, dispatches
   to the right parser, emits CSV / JSON / summary.

Currently implemented: `kpi`, `operations_allocation`, `quarterly_district`,
`efficiency`, `efficiency_review`.
