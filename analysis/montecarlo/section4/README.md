# Section 4 intermediates — observed 2024-25 origin-destination flows

Parsed from `data/2024-25-section4.pdf` ("Comparison of Enrollment and
Attendance Areas", SPS 2024-25 Annual Enrollment Report) by
`analysis/montecarlo/section4_seattle.py`. The source PDF is local-only, so
**these CSVs are checked in**. Regenerate with:

    python3 -m analysis.montecarlo.section4_seattle --build

Use the loaders (`s4.load_od()`, `s4.load_attendees()`,
`s4.load_option_draw()`) rather than reading by hand.

This is the **observed assignment matrix** for the calibration baseline year:
for every attendance area, where its resident students actually enrolled
(2024-25 snapshot). It anchors the assignment stage's draw kernels with real
flows instead of fitted priors.

## Files

| File | Rows | What |
|---|---|---|
| `od.csv` | 1,386 | `level, grade_band, residence_area, school, n` — residents of each attendance area by school attended (the OD matrix rows). `grade_band` is set only for the two K-8 attendance schools (Broadview-Thomson, Catharine Blaine), split K-5 / 6-8. |
| `attendees.csv` | 851 | `level, grade_band, school, residence_area, n` — where each attendance-area school's enrollees live. The only table with **Out of District/Unknown** residences. |
| `option_draw.csv` | 408 | `level, school, grade_band, residence_area, n` — option/K-8 school draw by residence area. `grade_band` ∈ K-5 / 6-8 / all ("all" = single-table district-draw pages, e.g. Cascadia). |

Headline stay-rates (share of residents attending their area school, SPS
enrollees only): **ES 68.2%, MS 56.6%, HS 69.8%**.

## Semantics & quirks

- **SPS-only.** Students attending private school / homeschool / other
  districts are absent entirely. Each area's `od` Grand Total < true resident
  child count. Out-of-district *residents* attending SPS appear only in
  `attendees.csv`.
- **Names are RAW** from the PDF and mix conventions: "Daniel Bagley" vs
  shapefile "Bagley", "Bailey Gatzert" vs "Gatzert", "John Hay" vs "Hay",
  "Martin Luther King"/"Martin Luther King Jr." vs "MLK Jr.",
  "West Seattle ES"/"West Seattle Elem." vs "West Seattle Elem",
  "David T. Denny Intl" vs "Denny Intl", "Hamilton" vs "Hamilton Intl".
  Normalization to `school_id` happens in the school_directory stage.
- **K-8 attendance schools** (Broadview-Thomson, Catharine Blaine) have two
  paired blocks. In the 6-8 block, the *attendees* side is keyed by
  **middle-school** attendance areas while the *od* side is still the ES-area
  residents — different universes; don't transpose-join them.
- **Source-truncated pages:** three blocks are visually cut at the page
  border in the original PDF (no Grand Total; a few trailing 1-student rows
  lost): James Baldwin (right table), John Stanford Intl and TOPS K-8 (K-5
  draw tables).
- One source page (Rainier View) mislabels its left column header
  ("School" instead of "Attendance Area"); handled in the parser.
- `Grand Total` rows are dropped from all CSVs; recompute sums as needed.
- Validation at build: 80/80 blocks diagonal-consistent; 656/656
  od↔attendees transpose cells agree.

## Why this matters for the Monte Carlo

- Baseline assignment (stage 6) can now be **seeded with observed flows** at
  attendance-area granularity; IPF only has to distribute within-area down to
  block groups.
- `option_draw.csv` is the empirical option-school kernel: e.g. Cascadia
  (HCC) draws 535 students spread over 25 areas (max 49 from one area) while
  Thornton Creek (geozone option) draws 142 of 370 from View Ridge alone —
  the diffuse-vs-local contrast the scenario engine relies on.
- Stay-rates per area give the neighborhood-school retention parameter
  (opt-out propensity) per school, not just district-wide.
