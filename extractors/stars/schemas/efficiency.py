"""Schemas for the STARS Efficiency Detail report.

The OSPI Efficiency Detail Report (form STF-8) compares a district's
transportation operations against a cohort of "peer" districts and
publishes a final Relative Efficiency Rating (RER, a percentage where
100% = on-target). The report is one page per district per school year
and lays out a small data table:

  - One row for the subject district's own metrics
  - Zero or more "Cohort <Peer>" rows with the peer's metrics and a
    weight percentage (cohort weights sum to ~100%)
  - One "Target <District> Target 100%" row carrying the target
    expenditure and target bus count
  - A footer "Relative Efficiency Rating <pct>%" line

For analytical convenience we split the per-file data into two tables:

  stars_efficiency             -- one row per (school_year, ccddd) carrying
                                  the subject's own metrics, the target's
                                  metrics, and the headline RER.
  stars_efficiency_cohort      -- one row per (school_year, ccddd, peer)
                                  carrying each cohort peer's metrics
                                  and weight.

A subject's cohort members appear in the cohort table; their own metrics
also appear independently in the subject table when each peer's own
Efficiency Detail report is parsed -- so peer values are recoverable
two ways for cross-check.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


# Column order in the data table after district name + weight.
EFFICIENCY_METRIC_FIELDS = [
    {
        "name": "prior_year_expenditures",
        "field_type": "decimal",
        "doc": "Total prior-year transportation expenditures, in dollars.",
    },
    {
        "name": "buses",
        "field_type": "int",
        "doc": "Number of buses operated.",
    },
    {
        "name": "basic_riders",
        "field_type": "int",
        "doc": "Basic program riders (combined AM + PM count divided by two).",
    },
    {
        "name": "special_riders",
        "field_type": "int",
        "doc": "Special education program riders.",
    },
    {
        "name": "avg_distance",
        "field_type": "decimal",
        "doc": "Average route distance, miles.",
    },
    {
        "name": "num_destinations",
        "field_type": "int",
        "doc": "Number of distinct destinations served.",
    },
    {
        "name": "land_area",
        "field_type": "decimal",
        "doc": "District land area, square miles.",
    },
    {
        "name": "k_rte",
        "field_type": "int",
        "doc": ("OSPI 'K Rte' column. Almost always 0 in observed reports; "
                "meaning not documented in publicly available materials."),
    },
    {
        "name": "road_miles_per_sq_mile",
        "field_type": "decimal",
        "doc": "Road miles per square mile of district area.",
    },
    {
        "name": "students_per_road_mile",
        "field_type": "decimal",
        "doc": "Riders per road mile (a density measure).",
    },
]


STARS_EFFICIENCY = {
    "name": "stars_efficiency",
    "doc": ("STARS Efficiency Detail Report per district per school year. "
            "Carries the subject district's own metrics, the cohort-weighted "
            "target's metrics, and the headline Relative Efficiency Rating."),
    "fields": [
        {
            "name": "stars_efficiency_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        *EFFICIENCY_METRIC_FIELDS,
        {
            "name": "target_prior_year_expenditures",
            "field_type": "decimal",
            "doc": ("Cohort-weighted target prior-year expenditures, from "
                    "the 'Target' row of the report."),
        },
        {
            "name": "target_buses",
            "field_type": "int",
            "doc": "Cohort-weighted target bus count.",
        },
        {
            "name": "relative_efficiency_rating",
            "field_type": "decimal",
            "doc": ("Relative Efficiency Rating as a percentage (e.g. 74.95 "
                    "means 74.95%). 100% = on-target; lower indicates "
                    "less-efficient than the cohort weighting predicts."),
        },
    ] + AUDIT_FIELDS,
}


STARS_EFFICIENCY_COHORT = {
    "name": "stars_efficiency_cohort",
    "doc": ("One row per (subject district, cohort peer) for the Efficiency "
            "Detail Report. Peer metrics are denormalized here for "
            "single-table queries; they also appear as the peer's own "
            "stars_efficiency row."),
    "fields": [
        {
            "name": "stars_efficiency_cohort_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "cohort_district",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Cohort peer district name as printed in the report "
                    "(short name, e.g. 'Benge', 'Mary M Knight'). May or "
                    "may not match a d_ccddd district name exactly; join "
                    "to d_ccddd by name with care."),
        },
        {
            "name": "weight_pct",
            "field_type": "decimal",
            "doc": ("Cohort weight as a percentage. Cohort weights sum to "
                    "~100% across all rows for a given (school_year, ccddd) "
                    "subject."),
        },
        *EFFICIENCY_METRIC_FIELDS,
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_EFFICIENCY, STARS_EFFICIENCY_COHORT]
