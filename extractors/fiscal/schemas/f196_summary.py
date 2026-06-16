"""Schema for the `fiscal_f196_summary` fact table.

Source: OSPI Form F-196 "Annual Financial Statements -- Summary" -- per
district per fiscal year. Only the page-2 REPORT F-196 SUMMARY table is
captured: a 7-fund x 7-item matrix of audited actual totals. The
remaining 37-39 pages of the report (Balance Sheet, Long-Term Liabilities,
Object/Activity reports, etc.) are deferred to a future parser.

Long-form: one row per (school_year, ccddd, item_code, fund).

Note: F-196 Summary is only published from 2021-22 onward (1,277 files
across 4 years in the corpus); earlier years had no equivalent split-out
summary.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_SUMMARY = {
    "name": "fiscal_f196_summary",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-196 Annual "
        "Financial Statements, page 2 (REPORT F-196 SUMMARY). 7 fund "
        "columns x 7 line items per file."
    ),
    "fields": [
        {
            "name": "fiscal_f196_summary_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Positional canonical identifier for the line item, in "
                "form order. Stable across years even when the printed "
                "label varies (e.g. 'Prior Year(s) Corrections or "
                "Restatements' vs 'Accounting Changes and Error Corrections')."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'general', 'asb', 'debt_service', 'capital_projects', "
                "'transportation_vehicle', 'permanent', or 'total'. "
                "'total' is the printed cross-fund sum (useful as a "
                "cross-check on the per-fund values)."
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
                "Parsed numeric value. Always printed to 2 decimal places "
                "on Form F-196 (audited actuals)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_SUMMARY]
