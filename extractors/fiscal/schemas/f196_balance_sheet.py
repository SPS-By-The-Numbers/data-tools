"""Schema for the `fiscal_f196_balance_sheet` fact table.

Source: the Balance Sheet - Governmental Funds sub-report (pp 3-5) of
each F-196 All Pages PDF. This is the district's period-end financial
position: assets, deferred outflows, liabilities, deferred inflows, and
fund balance, broken out per fund (7 columns: General / ASB / Debt
Service / Capital Projects / Transportation Vehicle / Permanent /
Total).

**The unique analytical add is the assets / liabilities / fund balance
dimension.** No other captured F-196 sub-report exposes G.L.-code-level
balance-sheet items -- SUMMARY and Revenues capture flows; this table
captures stocks. Enables working-capital, solvency, and inter-fund
receivable/payable analysis per district per year.

Long-form: one row per (school_year, ccddd, section, item_code, fund).
Section labels group items into their balance-sheet role; item_code is
a slug of the printed item label (positional and stable across years);
fund is one of the 7 fund columns.

Sub-report vintage drift:

  - 2013-14 has NO 'DEFERRED OUTFLOWS OF RESOURCES' section (GASB 65/68
    adopted mid-decade). The parser produces no rows for that section
    on those files.
  - Older vintages leave inapplicable cells truly blank; newer vintages
    fill with explicit 0.00. Positional column-anchor extraction
    absorbs both shapes (blank cells emit value=NULL).
  - The two 'combined-total' rows (TOTAL ASSETS AND DEFERRED OUTFLOWS
    OF RESOURCES; TOTAL LIABILITIES, DEFERRED INFLOWS, AND FUND BALANCE)
    live under `section='summary'`. They reconcile to each other -- the
    fundamental accounting identity, on every file.

**The `ending_total_fund_balance` cross-check.** Per fund, the sum of
FUND BALANCE items (Nonspendable + Restricted + Committed + Assigned +
Unassigned) equals fiscal_f196_summary.value where
item_code='ending_total_fund_balance' and matching fund. Consumers
should verify this reconciliation for the funds they care about.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


_SECTION_DOC = (
    "One of 'assets', 'deferred_outflows', 'liabilities', "
    "'deferred_inflows', 'fund_balance', or 'summary'. The 'summary' "
    "section holds the two combined-total rows that cap the assets side "
    "(TOTAL ASSETS AND DEFERRED OUTFLOWS OF RESOURCES) and the "
    "liabilities+fund-balance side (TOTAL LIABILITIES, DEFERRED INFLOWS "
    "OF RESOURCES, AND FUND BALANCE). Those two rows reconcile to each "
    "other (the fundamental accounting identity)."
)


FISCAL_F196_BALANCE_SHEET = {
    "name": "fiscal_f196_balance_sheet",
    "doc": (
        "Period-end balance sheet per district per fund, sourced from the "
        "Balance Sheet - Governmental Funds sub-report of OSPI Form F-196 "
        "All Pages. Each row is one (section, item, fund) combination -- "
        "e.g. Assets / Cash and Cash Equivalents / General Fund. Covers "
        "2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_balance_sheet_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": _SECTION_DOC,
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Slug of the item label (e.g. 'cash_and_cash_equivalents', "
                "'due_from_other_funds', 'nonspendable_fund_balance'). "
                "TOTAL rows use 'total_<section>' (e.g. 'total_assets', "
                "'total_fund_balance'). The combined-total rows use "
                "'total_assets_and_deferred_outflows_of_resources' and "
                "'total_liabilities_deferred_inflows_and_fund_balance'. "
                "**Positional and stable across years.**"
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'general', 'asb', 'debt_service', "
                "'capital_projects', 'transportation_vehicle', 'permanent', "
                "'total'. The 'total' column is the printed cross-fund sum."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for TOTAL rows within a section (total_assets, "
                "total_deferred_outflows, total_liabilities, "
                "total_deferred_inflows, total_fund_balance) and for both "
                "rows in section='summary'. False for detail line items."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed on the form (whitespace normalized). "
                "Multi-line labels are joined (e.g. 'Investments/Cash With "
                "Trustee', 'Investments-Deferred Compensation'). Slight "
                "label drift across years -- consumers cross-year should "
                "join on `item_code`."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Amount as printed. NULL when the fund/item cell is blank "
                "on the form (older vintages leave inapplicable cells "
                "truly blank rather than printing 0.00). 'Minus Warrants "
                "Outstanding' is consistently negative -- it is a "
                "contra-asset."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": (
                "Raw value text before numeric parsing. Empty string when "
                "the cell is blank on the form."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_BALANCE_SHEET]
