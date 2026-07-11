"""Schema for the `fiscal_f195_budget` fact table.

Source: OSPI Form F-195 "Budget" (the full document; the trimmed F-195
Budget Overview shares the same sub-report shapes for the pages it
includes, so both source kinds populate this table).

A single F-195 Budget PDF is a compound document with ~30 distinct
sub-reports. This schema is a long-form fact table keyed on
`sub_report`, so additional sub-reports can be folded in without a
migration.

Sub-reports currently populated:

  - sub_report = 'fund_summary'  (SUMMARY OF X FUND BUDGET, all 5 funds)
    -- per-fund budget summary; sections REVENUES, EXPENDITURES,
       OTHER FINANCING USES, BEGINNING / ENDING FUND BALANCE.
       3-column layout: Actual (-2) / Budget (-1) / Budget (0).
  - sub_report = 'expenditure_by_program'  (GF8)
    -- General Fund expenditures per OSPI program code (2-digit),
       grouped into program-group sections. 3-column layout matching
       fund_summary.
  - sub_report = 'expenditure_by_object_summary'  (GF10)
    -- General Fund expenditures per OSPI object code (0..9), 6-column
       cross-tab: value + `pct_of_total` per data year.
  - sub_report = 'expenditure_by_activity_summary'  (GF11)
    -- General Fund expenditures per OSPI activity code (2-digit),
       grouped into activity-group sections. 6-column cross-tab like
       GF10.
  - sub_report = 'enrollment_and_staff_counts'  (GF1)
    -- FTE enrollment counts (by grade) and staff counts. 3-column
       layout, column_kind is 'average' / 'budget' / 'budget'. Values
       are decimals (not dollars).
  - sub_report = 'financial_summary'  (GENERAL FUND FINANCIAL SUMMARY)
    -- Headline General Fund rollup: enrollment + financial summary +
       expenditure by program-group / activity-group / object. Mixed
       row shapes: the top two sub-sections carry 3 trailing values;
       the bottom three carry 6 (value + `pct_of_total`).
  - sub_report = 'fund_revenue_detail'  (GF4 / DS2 / CP3 / TVF revenue
       sub-report of each fund) -- per-OSPI-4-digit-account-code
       revenue detail per fund. 3-column layout matching fund_summary.
       Section slugs match fiscal_f196_revenues (`local_taxes`,
       `state_general_purpose`, ...), so the budget-per-account
       (this table) joins to actuals-per-account
       (`fiscal_f196_revenues`) on `(section, item_code, fund)` for
       budget-vs-actuals per revenue account.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_BUDGET = {
    "name": "fiscal_f195_budget",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-195 Budget "
        "sub-reports. Populates the SUMMARY OF X FUND BUDGET for all 5 "
        "funds (`fund_summary`), plus 4 General-Fund sub-reports "
        "(`expenditure_by_program` / `expenditure_by_object_summary` / "
        "`expenditure_by_activity_summary` / `enrollment_and_staff_counts`) "
        "and the top-level `financial_summary` rollup."
    ),
    "fields": [
        {
            "name": "fiscal_f195_budget_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "sub_report",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which F-195 Budget sub-report this row came from. "
                "Current values: 'fund_summary', "
                "'fund_revenue_detail', "
                "'expenditure_by_program', "
                "'expenditure_by_object_summary', "
                "'expenditure_by_activity_summary', "
                "'enrollment_and_staff_counts', 'financial_summary'."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Fund context: 'general', 'asb', 'debt_service', "
                "'capital_projects', or 'transportation_vehicle'. All "
                "General-Fund-only sub-reports (expenditure_by_program, "
                "expenditure_by_object_summary, "
                "expenditure_by_activity_summary, "
                "enrollment_and_staff_counts, financial_summary) carry "
                "fund='general'."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Subsection within the sub-report. For fund_summary: "
                "'revenues', 'expenditures', 'beginning_fund_balance', "
                "'ending_fund_balance', 'summary' (section-letter total "
                "rows). For expenditure_by_program (GF8): OSPI program "
                "group slug ('regular_instruction', 'special_education_"
                "instruction', ...), or 'summary' for per-group and "
                "grand-total rows. For expenditure_by_object_summary "
                "(GF10): 'objects' or 'summary' for TOTAL EXPENDITURES. "
                "For expenditure_by_activity_summary (GF11): OSPI "
                "activity group slug ('teaching_activities', "
                "'teaching_support', 'other_support_activities', "
                "'unit_administration', 'central_administration'), or "
                "'summary'. For enrollment_and_staff_counts (GF1): "
                "'enrollment_counts' (Section A) or 'staff_counts' "
                "(Section B), 'summary' for K-12 SUBTOTAL/TOTAL rows. "
                "For financial_summary: 'enrollment_and_staffing', "
                "'financial', 'program_groups', 'activity_groups', "
                "'objects', 'summary'."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Identifier derived from the PDF line prefix. Possible "
                "shapes: OSPI account code ('1000', '4400'), expenditure "
                "program code ('00', '10', '20', '50 and 60'), G.L. code "
                "('G.L.810'), section letter ('A', 'B', 'H'), or a "
                "slug-derived id for prefix-less labels (e.g. Debt "
                "Service Fund items like 'matured_bond_expenditures')."
            ),
        },
        {
            "name": "data_year_offset",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Column offset from the report's current school year. "
                "For the 3-column fund_summary tables: -2 (prior "
                "actual), -1 (prior budget), 0 (current budget)."
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
            "name": "column_kind",
            "field_type": "string",
            "doc": (
                "What the column represents on the form: 'actual' (the "
                "prior-prior year's audited / final figures), 'budget' "
                "(prior or current budget adopted), or 'average' (used "
                "on the enrollment_and_staff_counts prior-actual "
                "column, which the form labels 'Average' not 'Actual')."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Line item label as printed (whitespace normalized). "
                "Multi-line labels are joined."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL when the form prints "
                "'XXXX' / 'XXXXX' marking a column that doesn't apply "
                "(e.g. ASB has no 'transfers out' line in some sections)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
        {
            "name": "pct_of_total",
            "field_type": "decimal",
            "doc": (
                "The '% of Total' companion column, present only on the "
                "6-column cross-tab sub-reports (expenditure_by_object_"
                "summary, expenditure_by_activity_summary, and the "
                "expenditure sub-sections of financial_summary). "
                "Stored as printed (e.g. 43.20 means 43.20%, not "
                "0.4320). NULL when the form prints 'XXXX' / 'XXXXX' "
                "for the pct column (Debit/Credit transfer rows) or "
                "when the sub-report has no companion column."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "sub_report", "fund", "section",
        "item_code", "data_year_offset",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_BUDGET]
