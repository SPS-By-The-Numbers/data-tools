"""Schema for the STARS Key Performance Indicators fact table.

One row per (report school_year, ccddd, metric_code, data_class_of).

The three KPIs reported per district -- basic riders per basic bus, special
education riders per special education bus, and average cost per rider --
each show three trailing data years on the published report, plus a
year-over-year change percentage from the second-latest to the latest.

Storing the values long-form (one row per metric per data_year) keeps the
schema flat and joinable with safs tables on (class_of, ccddd). The
change_pct shows up as a synthetic metric_code suffixed with
"_change_pct"; its data_class_of refers to the latest data year (the year
the percentage is measured against the prior year for).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


KPI_METRIC_CODES = (
    "basic_rider_kpi",
    "sped_rider_kpi",
    "cost_per_rider",
    "basic_rider_kpi_change_pct",
    "sped_rider_kpi_change_pct",
    "cost_per_rider_change_pct",
)


STARS_KPI = {
    "name": "stars_kpi",
    "doc": ("STARS Key Performance Indicators per district per report year. "
            "Long-form: one row per metric per data year."),
    "fields": [
        {
            "name": "stars_kpi_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "metric_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Metric identifier. One of " + ", ".join(KPI_METRIC_CODES)
                    + ". The _change_pct variants carry the YoY change for "
                    "the latest data year vs the prior data year."),
        },
        {
            "name": "data_class_of",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("Class-of int for the data year this row describes. "
                    "Joins to d_school / safs facts on class_of."),
        },
        {
            "name": "data_school_year",
            "field_type": "string",
            "doc": ("School year string of the data, normalized to "
                    "'YYYY-YYYY'. Convenience -- redundant with "
                    "data_class_of."),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": ("Metric value. NULL if the PDF cell was blank, '-', or "
                    "otherwise unparseable."),
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_KPI]
