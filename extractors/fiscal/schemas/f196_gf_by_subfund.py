"""Schema for the `fiscal_f196_gf_by_subfund` fact table.

Source: the 'Statement of Revenues, Expenditures, and Changes in Fund
Balance - General Fund, By Sub-Fund' sub-report (pp 8-9 typical) of
each F-196 All Pages PDF. **Introduced in 2019-20; not present on
earlier files** -- parser produces no rows for pre-2019-20 files.

**The unique analytical contribution is the sub-fund decomposition**
of the General Fund. `fiscal_f196_summary` and the Governmental
Statement of Rev/Exp/FB report per-fund totals but do not split the
General Fund into its sub-funds. Sub-Fund 10 (Basic Education) vs
Sub-Fund 11 (Non-Basic-Education) is the finest-grained
apportionment breakdown OSPI publishes at the district level -- it
distinguishes basic-education spending from everything else.

Long-form: one row per (school_year, ccddd, section, sub_section,
item_code, fund). Fund is one of:

  - `sub_fund_10` (Basic Education Sub-Fund)
  - `sub_fund_11` (Non-Basic-Education Sub-Fund)
  - `general_fund` (total; equals sub_fund_10 + sub_fund_11)
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_GF_BY_SUBFUND = {
    "name": "fiscal_f196_gf_by_subfund",
    "doc": (
        "General Fund broken out by sub-fund (Basic Ed vs Non-Basic-Ed) "
        "from the 'Statement of Revenues, Expenditures, and Changes in "
        "Fund Balance - General Fund, By Sub-Fund' sub-report of OSPI "
        "Form F-196 All Pages. Coverage: 2019-20 through 2024-25 "
        "(~1,900 files); the sub-report did not exist before 2019-20."
    ),
    "fields": [
        {
            "name": "fiscal_f196_gf_by_subfund_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'revenues', 'expenditures', "
                "'other_financing_sources_uses', or 'summary' (for the "
                "cross-section total rows: revenues_over_under_"
                "expenditures, excess_of_revenues_over_expenditures, "
                "beginning_total_fund_balance, "
                "corrections_or_restatements, ending_total_fund_balance)."
            ),
        },
        {
            "name": "sub_section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "For section='expenditures': one of 'current', "
                "'capital_outlay', 'debt_service' (the 3 sub-sections "
                "the form groups expenditure items into). Empty string "
                "for other sections."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Semantic slug of the line item (e.g. `local`, `state`, "
                "`federal`, `other` for revenues; `regular_instruction`, "
                "`special_education`, `principal` for expenditures; "
                "`transfers_in`, `long_term_financing`, `other` for OFS). "
                "TOTAL rows use `total_<section>` "
                "(`total_revenues`, `total_expenditures`, "
                "`total_other_financing_sources_uses`). Summary items "
                "carry their own slugs."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'sub_fund_10' (Basic Education), 'sub_fund_11' "
                "(Non-Basic-Education), or 'general_fund' (total; equals "
                "sub_fund_10 + sub_fund_11)."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for TOTAL rows and cross-section summary items. "
                "False for detail rows."
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
            "name": "amount",
            "field_type": "decimal",
            "doc": (
                "Amount as printed. NULL when the sub-fund/item cell is "
                "blank on the form (some Other Financing Sources items "
                "print only 2 values -- Sub-Fund 10 blank -- and the "
                "General Fund total)."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "sub_section", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_GF_BY_SUBFUND]
