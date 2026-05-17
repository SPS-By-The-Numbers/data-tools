"""Schema for the COMPACT / CHARTER variant of the Operations Allocation Detail.

Tribal compact schools and charter school districts use a different
1026A form than regular school districts -- their allocation is based
on a host district's per-rider allocation multiplied by the
compact/charter's own eligible ridership prorated across the year:

  Section A. Host district's per-student allocation calculation
    A.1  Host total eligible riders
    A.2  Host operations allocation ($)
    A.3  Host depreciation ($) -- charters split this into A.3.a/b/c
    A.4  Host total transportation funding ($)  (= A.2 + A.3)
    A.5  Host per-rider allocation ($)          (= A.4 / A.1)

  Section B. Compact/charter eligible riders
    B.1  Spring riders         (combined AM + PM, fall of prior year)
    B.2  Fall riders           (current year)
    B.3  Winter riders         (current year)
    B.4  Prorated riders       = (B.1*3/8) + (B.2*2/8) + (B.3*3/8)

  Section C. Final allocation ($) = A.5 * B.4

One row per (school_year, ccddd). Distinct from the standard
`stars_operations_allocation` because the field set is different and
each tribal/charter has only one entry per year.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


STARS_OPERATIONS_ALLOCATION_COMPACT = {
    "name": "stars_operations_allocation_compact",
    "doc": ("STARS Operations Allocation Detail (form 1026A COMPACT / "
            "CHARTER variant) per tribal compact or charter school "
            "district per school year."),
    "fields": [
        {
            "name": "stars_operations_allocation_compact_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "report_type",
            "field_type": "string",
            "doc": "'COMPACT' (tribal compact) or 'CHARTER' (charter school district).",
        },
        {
            "name": "school_name",
            "field_type": "string",
            "doc": ("School name as printed on the cover page (e.g. 'SUQUAMISH "
                    "COMPACT SCHOOL', 'PRIDE PREP CHARTER', 'Chief Kitsap "
                    "Academy Department'). May differ from the district name "
                    "in the filename."),
        },
        {
            "name": "host_district",
            "field_type": "string",
            "doc": ("Host district whose per-rider allocation is used to "
                    "compute this allocation (e.g. 'North Kitsap', 'Ferndale', "
                    "'SPOKANE Public Schools')."),
        },
        {
            "name": "host_data_year",
            "field_type": "string",
            "doc": ("School year of the host's data used for the "
                    "per-rider calculation (e.g. '2016-17', '2024-25'). "
                    "Typically one or two years before the report's school_year."),
        },
        {
            "name": "host_total_eligible_riders",
            "field_type": "decimal",
            "doc": "A.1: Host district total eligible riders.",
        },
        {
            "name": "host_operations_allocation",
            "field_type": "decimal",
            "doc": "A.2: Host district operations allocation, dollars.",
        },
        {
            "name": "host_depreciation",
            "field_type": "decimal",
            "doc": ("A.3: Host district depreciation, dollars. For charters "
                    "this is the A.3.c total (in-lieu + bus depreciation)."),
        },
        {
            "name": "host_total_transportation_funding",
            "field_type": "decimal",
            "doc": "A.4: Host district total transportation funding (= A.2 + A.3).",
        },
        {
            "name": "host_per_rider_allocation",
            "field_type": "decimal",
            "doc": "A.5: Host district per-rider allocation, dollars (= A.4 / A.1).",
        },
        {
            "name": "spring_riders",
            "field_type": "int",
            "doc": "B.1: Spring eligible riders (combined AM + PM, prior fall).",
        },
        {
            "name": "fall_riders",
            "field_type": "int",
            "doc": "B.2: Fall eligible riders (current year).",
        },
        {
            "name": "winter_riders",
            "field_type": "int",
            "doc": "B.3: Winter eligible riders (current year).",
        },
        {
            "name": "prorated_riders",
            "field_type": "decimal",
            "doc": ("B.4: Prorated rider count = "
                    "(B.1 * 3/8) + (B.2 * 2/8) + (B.3 * 3/8)."),
        },
        {
            "name": "final_allocation",
            "field_type": "decimal",
            "doc": "Section C: Final calculated allocation, dollars (= A.5 * B.4).",
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_OPERATIONS_ALLOCATION_COMPACT]
