"""Schema for the `fiscal_f195_four_year` fact table.

Source: OSPI Form F-195F, the "Four-year Budget Summary Plan" -- a
multi-page PDF per district per school year with the current budget
plus 3-year forecasts across 5 funds (General, ASB, Debt Service,
Capital Projects, Transportation Vehicle), plus an enrollment + staff
counts table on the first page.

Long-form: one row per (school_year, ccddd, fund, section, item_code,
data_year_offset). Each value-bearing source line yields 4 rows (current
year + 3 forecasts).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_FOUR_YEAR = {
    "name": "fiscal_f195_four_year",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-195F "
        "Four-year Budget Summary Plan. One row per (line item, "
        "data year column)."
    ),
    "fields": [
        {
            "name": "fiscal_f195_four_year_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Fund context the item belongs to: 'general', 'asb', "
                "'debt_service', 'capital_projects', "
                "'transportation_vehicle', or 'enrollment_staff' "
                "(page 1's pre-fund enrollment + staff-count table)."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Subsection within the fund: 'revenues', "
                "'expenditures', 'beginning_balance', "
                "'ending_balance', 'summary' (totals A./B./C./...), or "
                "'enrollment' / 'staff' (for the enrollment_staff fund)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Identifier from the PDF line prefix. Possible shapes: "
                "OSPI account code ('1000', '4400', '6000'), "
                "G.L. code ('G.L.810', 'G.L.840'), section letter ('A', "
                "'B', 'H'), or a small-int item number (the '14' from "
                "'14. SUBTOTAL'). Empty if no recognizable prefix."
            ),
        },
        {
            "name": "data_year_offset",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "0 = the report's published school year (Current column); "
                "1, 2, 3 = the three Forecast columns in order."
            ),
        },
        {
            "name": "data_school_year",
            "field_type": "string",
            "doc": "The data column's school year, e.g. '2024-2025'.",
        },
        {
            "name": "data_class_of",
            "field_type": "int",
            "doc": "End year of `data_school_year` as int.",
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Line item label as printed in the PDF (whitespace "
                "normalized). May be truncated for items whose label "
                "wrapped across multiple printed lines -- the value-bearing "
                "line is captured but post-value continuation text is not."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": "Parsed numeric value for this (item, data_year_offset).",
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "fund", "section", "item_code", "data_year_offset",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_FOUR_YEAR]
