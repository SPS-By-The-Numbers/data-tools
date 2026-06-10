# Seattle STARS intermediates (ccddd 17001)

Seattle-only slice of OSPI STARS data, produced by
`analysis/montecarlo/stars_seattle.py` from the gitignored `out_stars/`
directory. **These CSVs are checked in** so future sessions don't need
`out_stars/` present. Regenerate with:

    python3 -m analysis.montecarlo.stars_seattle --build

Coverage: school years **2017-2018 .. 2025-2026**. Use the matching loader in
`stars_seattle.py` (e.g. `load_routes()`) rather than reading these by hand.

## Files

| File | Rows | What |
|---|---|---|
| `routes.csv` | 13,259 | Per-route detail: `destination_name` (school), `program`, `route_number`, `stop_count`, `total_stops`, `average_distance`, by `school_year`+`quarter`. The richest layer. |
| `routes_by_school_year.csv` | 1,750 | Routes/stops/avg-distance rolled up per destination × program × year. |
| `quarterly_metrics.csv` | 672 | District student/route/bus counts by program & quarter (long: `school_year, quarter, metric_code, value`). Decode `metric_code` via `d_stars_quarterly_metric.csv`. |
| `efficiency.csv` | 7 | Annual buses, basic/special riders, avg distance, destinations, relative efficiency rating. |
| `efficiency_cohort.csv` | 7 | Peer-cohort comparison rows for the efficiency calc. |
| `kpi.csv` | 84 | Riders/bus and cost/rider KPIs by year. Decode via `d_stars_kpi_metric.csv`. |
| `operations_allocation.csv` | 270 | STARS funding-formula line items by year. Decode via `d_stars_ops_allocation_section.csv` / `_item.csv`. |
| `destinations.csv` | 154 | Distinct route destination names + years seen. `school_id` column is **NA — to be filled** by fuzzy-matching to `parse_shapes` school names in a later stage. |
| `d_*.csv` | — | Dimension/lookup tables copied verbatim from `out_stars/`. |

## Known quirks
- **Missing years in efficiency:** COVID years 2020-2021 and 2021-2022 are
  absent from `efficiency`/`efficiency_cohort`/`kpi` (only 7 of 9 years), but
  `routes` and `quarterly_metrics` *do* include them. 2020-2021 route data is
  sparse (209 rows) — remote-learning year.
- **Messy destination names:** e.g. "Clevland H.S." (sic), "Chief Sealth
  International H.S.". 154 distinct names need normalization → `school_id`.
  This is why `destinations.csv` exists as a mapping seed.
- **`basic_riders` is misleading** — it conflates yellow-bus and transit-pass
  riders. The efficiency table shows 20,473 (2017-18) → 8,556 (2024-25), but
  most of that "drop" is the transit-pass (ORCA) program going to **0 from
  2022-2023**, not yellow-bus demand. For ridership, split via
  `quarterly_metrics`: `basic_students_on_buses` (yellow bus, the thing to
  model: ~12,118 → ~9,171) vs `basic_students_transit_buses` (transit pass).
  Identity: `basic_students_total = on_buses + transit_buses − in_walk_areas`.
  See `../plot_ridership.py` and `../ridership_bus_vs_transit.png`.
  Avg route distance fell 2.42 → 2.16 mi.
