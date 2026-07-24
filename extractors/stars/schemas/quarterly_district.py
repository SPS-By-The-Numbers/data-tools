"""Schema for the STARS Quarterly District Detail fact table.

OSPI publishes three reports per district per school year (`FALL`, `WINTER`,
`SPRING`). Each file aggregates the district's pupil-transportation activity
for that quarter:

  STUDENT DETAIL  -- ridership counts by program (basic vs. special-ed
                     subcategories: bilingual, gifted, homeless, early ed).
  ROUTE SUMMARY   -- number of routes by program plus total destinations,
                     total buses, and average route distance.
  BUS SUMMARY     -- number of buses by program plus total destinations
                     and total buses (per-bus rollup; can differ slightly
                     from the route-summary numbers when a single bus
                     serves multiple route types).

The per-route detail section (one row per individual bus route) is *not*
covered by this schema; if needed it would be a separate `stars_quarterly_route`
table.

Long-form: one row per (school_year, ccddd, quarter, metric_code).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


QUARTERLY_DISTRICT_METRICS = (
    # STUDENT DETAIL -- Basic Program ride-equivalent subdivision
    # (trips + issued transit passes, not distinct students).
    "basic_ride_equivalents_on_bus",
    "basic_rides_in_walk_zone",
    "basic_transit_passes_issued",
    "basic_program_total",
    # STUDENT DETAIL -- Special Program ride-equivalent subdivision.
    "special_rides_special_ed",
    "special_rides_bilingual",
    "special_rides_gifted",
    "special_rides_homeless",
    "special_rides_early_ed",
    "special_program_total",
    # ROUTE SUMMARY -- route counts by program plus totals.
    "routes_basic",
    "routes_special",
    "routes_bilingual",
    "routes_gifted",
    "routes_homeless",
    "routes_early_ed",
    "routes_total",
    "route_summary_destinations",
    "route_summary_total_buses",
    "route_summary_avg_stop_to_dest_distance",
    # BUS SUMMARY -- bus counts by program plus totals.
    "buses_basic",
    "buses_special",
    "buses_bilingual",
    "buses_gifted",
    "buses_homeless",
    "buses_early_ed",
    "bus_summary_destinations",
    "bus_summary_total_buses",
)


STARS_QUARTERLY_DISTRICT = {
    "name": "stars_quarterly_district",
    "doc": ("STARS Quarterly District Detail summary metrics per district "
            "per school year per quarter. Long-form: one row per metric."),
    "fields": [
        {
            "name": "stars_quarterly_district_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "quarter",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "One of 'FALL', 'WINTER', 'SPRING'.",
        },
        {
            "name": "metric_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Metric identifier. One of "
                    + ", ".join(QUARTERLY_DISTRICT_METRICS) + "."),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": ("Metric value (counts and averages). NULL when the "
                    "section's data row was absent from the report (small "
                    "districts that reported no transportation activity, "
                    "or charter schools whose ROUTE SUMMARY has no average "
                    "distance because they have no routes). Distinguishes "
                    "'reported zero' (value=0) from 'not reported' (NULL)."),
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_QUARTERLY_DISTRICT]
