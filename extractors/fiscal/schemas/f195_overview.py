"""Schema for the `fiscal_f195_overview` fact table.

Source: OSPI Form F-195 "Budget Overview" -- per-district, per-year. Only
**page 1** is captured: the 5-fund BUDGET AND EXCESS LEVY SUMMARY (Section
A: budget by fund; Section B: excess levies by fund). The remaining 40
pages are a near-duplicate of the F-195 Budget full document and are
deferred to a future parser.

Long-form: one row per (school_year, ccddd, section, item_code, fund).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_OVERVIEW = {
    "name": "fiscal_f195_overview",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-195 Budget "
        "Overview, page 1 (BUDGET AND EXCESS LEVY SUMMARY). One row per "
        "(item, fund). Captures only the first-page multi-fund summary; "
        "the deeper per-fund detail in this report duplicates the F-195 "
        "Budget full document."
    ),
    "fields": [
        {
            "name": "fiscal_f195_overview_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "'a_budget_summary' or 'b_excess_levies'.",
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Stable snake_case identifier derived from the item label. "
                "Section B collection-year references are stripped so the "
                "code matches across years (e.g. 'Excess levies approved "
                "by voters for 2025 collection' -> "
                "'excess_levies_approved_by_voters_for_collection')."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'general', 'asb', 'debt_service', 'capital_projects', "
                "or 'transportation_vehicle'. Always the same fund order "
                "as printed on the form."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Full item label as printed (whitespace normalized). "
                "Multi-line labels are joined."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL when the form printed 'XXXX' "
                "/ 'XXXXX' for a fund-column that the line item doesn't "
                "apply to (e.g. ASB excess levies)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F195_OVERVIEW]
