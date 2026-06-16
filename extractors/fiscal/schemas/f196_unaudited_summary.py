"""Schema for the `fiscal_f196_unaudited_summary` fact table.

Source: OSPI Form F-196 Annual Financial Statements -- UNAUDITED vintage,
published mid-December of the year following the fiscal year end. Only
the page-2 REPORT F-196 SUMMARY table is captured (7-fund x 7-item
matrix). The remaining ~26 pages of the report (Balance Sheet,
Statement of Revenues/Expenditures, Budgetary Comparison, Schedule of
Long-Term Liabilities, Object/Activity reports, etc.) are deferred to
the planned F-196 All Pages parser.

The F-196 Unaudited document is only published for 2013-14 and 2014-15;
the 'F-196 All Pages' document under data/fiscal/fiscal/ supersedes it
for later years, and the split-out 'F-196 Summary' doc carries audited
SUMMARY data from 2021-22+ as `fiscal_f196_summary`.

Long-form: one row per (school_year, ccddd, item_code, fund). NULL
`value` indicates the form left the cell blank (most commonly on the
'Other Financing Uses' row, which omits ASB and Permanent in older
vintages).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_UNAUDITED_SUMMARY = {
    "name": "fiscal_f196_unaudited_summary",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-196 Annual "
        "Financial Statements UNAUDITED page 2 (REPORT F-196 SUMMARY). "
        "7 fund columns x 7 line items per file. 2013-14 and 2014-15 only "
        "(594 files); later years' Unaudited filings live under "
        "data/fiscal/fiscal/ as 'F-196 All Pages'."
    ),
    "fields": [
        {
            "name": "fiscal_f196_unaudited_summary_id",
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
                "form order: total_revenues_and_other_financing_sources, "
                "total_expenditures, other_financing_uses, "
                "excess_of_revenues_over_expenditures, "
                "beginning_total_fund_balance, corrections_or_restatements, "
                "ending_total_fund_balance. Matches the codes in "
                "`fiscal_f196_summary` so the tables can be UNION'd."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'general', 'asb', 'debt_service', 'capital_projects', "
                "'transportation_vehicle', 'permanent', or 'total'. "
                "'total' is the printed cross-fund sum."
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
                "Parsed numeric value. NULL when the form left the cell "
                "blank -- most commonly on 'Other Financing Uses' where "
                "ASB and Permanent are omitted in older vintages. The "
                "audited 2021-22+ 'F-196 Summary' doc fills those with "
                "explicit 0.00."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing; empty for blank cells.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_UNAUDITED_SUMMARY]
