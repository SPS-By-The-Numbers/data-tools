"""Schema for the `fiscal_f196_budgetary_comparison` fact table.

Source: the Budgetary Comparison Schedule sub-report inside each F-196
All Pages PDF (typically pp 7-16 -- 2 pages per fund x 5 funds).
Captures per-fund per-line-item Final Budget / Actual / Variance values.

Long-form: one row per (school_year, ccddd, fund, section, sub_section,
item_code, column_kind). column_kind cycles through 'final_budget',
'actual', 'variance' for every line item.

**Why this table matters**: this is the only sub-report that captures
the **Final Budget** -- the budget after mid-year revisions. The F-195
Budget doc captures the Original Budget (the start-of-year filing); the
F-196 SUMMARY and Revenues capture Actuals. Final Budget is the new
datum here. Combined with the existing tables, consumers can trace any
line item from Original Budget -> Final Budget -> Actual -> Variance.

The 5 funds are: General Fund, Associated Student Body Fund, Debt
Service Fund, Capital Projects Fund, Transportation Vehicle Fund.
Permanent Fund is omitted (it has its own Statement of Fiduciary Net
Position instead, deferred to a later phase).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_BUDGETARY_COMPARISON = {
    "name": "fiscal_f196_budgetary_comparison",
    "doc": (
        "Per-fund Final Budget / Actual / Variance line items from the "
        "Budgetary Comparison Schedule sub-report of OSPI Form F-196 "
        "All Pages. 5-fund x ~25-item-per-fund x 3-column matrix per "
        "file. 2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_budgetary_comparison_id",
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
                "'general', 'asb', 'debt_service', 'capital_projects', "
                "or 'transportation_vehicle'. 5 funds (no Permanent -- "
                "covered by the Statement of Fiduciary Net Position "
                "sub-report instead, deferred)."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Top-level section: 'revenues', 'expenditures', "
                "'other_financing_sources_uses', 'summary' "
                "(revenues-over-under / excess / total rows), or "
                "'fund_balance' (beginning / corrections / ending)."
            ),
        },
        {
            "name": "sub_section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Sub-grouping within section='expenditures': 'current', "
                "'capital_outlay', or 'debt_service'. Empty string "
                "otherwise."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Semantic slug for the line item. F-196 Budgetary "
                "Comparison does NOT print OSPI account codes -- only "
                "labels -- so the slug is derived from the label and "
                "stable across vintages (e.g. 'regular_instruction', "
                "'special_education', 'principal', 'transfers_in'). "
                "Section/sub-section totals use 'total' "
                "(with is_section_total=True). The grand summary rows "
                "use unique slugs: 'total_revenues', 'total_expenditures', "
                "'revenues_over_under_expenditures', "
                "'total_other_financing_sources_uses', "
                "'excess_over_under', 'beginning_total_fund_balance', "
                "'corrections_or_restatements', 'ending_total_fund_balance'."
            ),
        },
        {
            "name": "column_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which of the 3 printed columns: 'final_budget' (the "
                "budget after mid-year revisions -- the NEW datum vs "
                "F-195 budget), 'actual' (matches F-196 SUMMARY / "
                "Revenues), or 'variance' (the printed POSITIVE/"
                "NEGATIVE column). "
                "**Variance sign is 'favorable'**, not a fixed "
                "arithmetic: positive = favorable to the district. "
                "For revenues / OFS / fund_balance rows, "
                "variance = actual - final_budget (more inflow = "
                "favorable). For expenditures rows, "
                "variance = final_budget - actual (less spent = "
                "favorable). Consumers that re-derive variance should "
                "apply the section-aware formula -- do NOT compute "
                "final_budget - actual unconditionally."
            ),
        },
        {
            "name": "is_section_total",
            "field_type": "boolean",
            "doc": (
                "True when this row is a section subtotal (TOTAL "
                "REVENUES, TOTAL EXPENDITURES, TOTAL OTHER FINANCING "
                "SOURCES (USES)). False for detail items and summary/"
                "fund_balance rows."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL when the form left the "
                "cell blank -- the common case, since many items don't "
                "apply to certain funds (e.g. ASB Fund has no Debt "
                "Service items, Capital Projects has limited CURRENT "
                "expenditures). The 'corrections_or_restatements' row "
                "consistently omits the variance column (always NULL "
                "for column_kind='variance')."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing; empty for blank cells.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "fund", "section", "sub_section",
                "item_code", "column_kind"]],
}


ALL_SCHEMAS = [FISCAL_F196_BUDGETARY_COMPARISON]
