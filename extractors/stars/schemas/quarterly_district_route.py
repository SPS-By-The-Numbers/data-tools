"""Schema for the STARS Quarterly District Detail per-route table.

Companion to stars_quarterly_district. Each Quarterly District Detail
report has a ROUTE DETAIL section listing every individual bus route the
district operated that quarter, grouped under one of six program codes
(Basic / Special Ed / Bilingual / Gifted / Homeless / Early Ed). For
larger districts this section can run hundreds of rows; the summary
table aggregates these into per-program counts.

Long-form: one row per (school_year, ccddd, quarter, program, route_number).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


QUARTERLY_DISTRICT_ROUTE_PROGRAMS = (
    "basic",
    "special_ed",
    "bilingual",
    "gifted",
    "homeless",
    "early_ed",
)


STARS_QUARTERLY_DISTRICT_ROUTE = {
    "name": "stars_quarterly_district_route",
    "doc": ("STARS Quarterly District Detail per-route table. One row "
            "per individual bus route per district per quarter."),
    "fields": [
        {
            "name": "stars_quarterly_district_route_id",
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
            "name": "program",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Program canonical name. One of "
                    + ", ".join(QUARTERLY_DISTRICT_ROUTE_PROGRAMS) + "."),
        },
        {
            "name": "route_number",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("District-assigned route identifier. Stored as a string "
                    "because some districts use suffixed identifiers (e.g. "
                    "'0079-I', '0405-T') while small districts use bare "
                    "integers (e.g. '1', '2', '7')."),
        },
        {
            "name": "district_bus_number",
            "field_type": "int",
            "doc": "District-assigned bus identifier.",
        },
        {
            "name": "state_bus_number",
            "field_type": "int",
            "doc": "OSPI state bus identifier (typically 6 digits).",
        },
        {
            "name": "destination_name",
            "field_type": "string",
            "doc": ("Free-text destination name as printed (e.g. 'Kimball "
                    "Elementary', 'Robert Eagle Staff M.S.', 'Mercer M.S. "
                    "TEMP CONST'). Often joinable to d_school by name but "
                    "not guaranteed."),
        },
        {
            "name": "stop_count",
            "field_type": "int",
            "doc": "Number of stops on this route.",
        },
        {
            "name": "total_stops",
            "field_type": "int",
            "doc": ("Total stops including pickups and dropoffs (typically "
                    "equal to stop_count, but can differ on combined routes)."),
        },
        {
            "name": "average_distance",
            "field_type": "decimal",
            "doc": "Average per-stop distance in miles.",
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_QUARTERLY_DISTRICT_ROUTE]
