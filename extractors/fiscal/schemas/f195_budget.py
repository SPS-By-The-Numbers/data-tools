"""Schema for the `fiscal_f195_budget` fact table.

Source: OSPI Form F-195 "Budget" (the full document; the trimmed F-195
Budget Overview shares the same sub-report shapes for the pages it
includes, so both source kinds populate this table).

A single F-195 Budget PDF is a compound document with ~30 distinct
sub-reports. This schema is a long-form fact table keyed on
`sub_report`, so additional sub-reports can be folded in without a
migration. The Phase-1 parser populates only:

  - sub_report = 'fund_summary'  (SUMMARY OF X FUND BUDGET, all 5 funds)
    -- the per-fund budget summary with sections REVENUES,
       EXPENDITURES, OTHER FINANCING USES, BEGINNING / ENDING FUND
       BALANCE. Each value line carries 3 columns:
         column_kind 'actual' -> data_year_offset -2  (prior actual)
         column_kind 'budget' -> data_year_offset -1  (prior budget)
         column_kind 'budget' -> data_year_offset  0  (current budget)

Future sub-reports the same table is shaped to accept:
  - fund_revenue_detail  (GF4 / DS2 / CP3 / TVF revenue detail)
  - expenditure_by_program  (GF8)
  - expenditure_by_object_summary  (GF10)
  - expenditure_by_activity_summary  (GF11)
  - enrollment_and_staff_counts  (GF1)
  - financial_summary  (GENERAL FUND FINANCIAL SUMMARY)
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_BUDGET = {
    "name": "fiscal_f195_budget",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-195 Budget "
        "sub-reports. Phase 1 covers SUMMARY OF X FUND BUDGET for all "
        "5 funds; future sub-reports will populate the same table with "
        "distinct `sub_report` values."
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
                "Phase 1: 'fund_summary'. Reserved for future: "
                "'fund_revenue_detail', 'expenditure_by_program', "
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
                "'capital_projects', or 'transportation_vehicle'."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Subsection within the sub-report. For fund_summary: "
                "'revenues', 'expenditures', "
                "'other_financing_uses_transfers_out', "
                "'other_financing_uses', 'excess_revenues_over_expenditures', "
                "'beginning_fund_balance', 'prior_year_corrections', "
                "'ending_fund_balance'."
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
                "prior-prior year's audited / final figures) or 'budget' "
                "(prior or current budget adopted)."
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
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "sub_report", "fund", "section",
        "item_code", "data_year_offset",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_BUDGET]
