"""Schema for the `fiscal_f196_revenues` fact table.

Source: the 'Report of Revenues and Other Financing Sources' sub-report
inside each F-196 All Pages PDF (pp 23-29 in Seattle 2018-19, 7-9 pages
total per file). Captures per-OSPI-4-digit-account-code revenue detail
per fund -- the actuals counterpart to F-195's per-account budget line
items.

Long-form: one row per (school_year, ccddd, section, revenue_account,
fund). NULL `value` when the form left the cell blank (every account is
fund-restricted; most accounts apply to only 1-3 of the 4 funds).

Funds: only 4 (no ASB, no Permanent, no Total -- the sub-report only
covers tax-funded operational funds). The cross-fund Total is NOT
printed (unlike the SUMMARY block).

Pairs directly with `fiscal_f195_budget` at line-item granularity once
the F-195 fund-revenue-detail parser lands (currently TODO -- F-195
only captures section totals like '1000'/'2000'/'3000'/etc. so far).
Budget-vs-actual joins at the SUMMARY level work today:
  f195_budget.item_code = f196_revenues.revenue_account
  for revenue_account in ('1000','2000','3000',...,'9000')
  with f196_revenues.is_section_total = True.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_REVENUES = {
    "name": "fiscal_f196_revenues",
    "doc": (
        "Per-OSPI-4-digit-account-code revenue detail from the Report "
        "of Revenues and Other Financing Sources sub-report of OSPI Form "
        "F-196 All Pages. 4-fund x ~50-account-code matrix per file "
        "(most cells are NULL -- accounts are fund-restricted). 2013-14 "
        "through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_revenues_id",
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
                "Section slug: 'local_taxes', 'local_support_nontax', "
                "'state_general_purpose', 'state_special_purpose', "
                "'federal_general_purpose', 'federal_special_purpose', "
                "'revenues_from_other_school_districts', "
                "'revenues_from_other_entities', 'other_financing_sources', "
                "'grand_total'. The first 9 are the printed section "
                "groupings; 'grand_total' is for the final TOTAL "
                "REVENUES AND OTHER FINANCING SOURCES row."
            ),
        },
        {
            "name": "revenue_account",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 4-digit revenue account code as printed -- "
                "'1100' (Local Property Tax), '3100' (Apportionment), "
                "'4121' (Special Education), '6151' (ESEA Disadvantaged), "
                "etc. Section subtotal rows use the section's anchor "
                "code: '1000' for TOTAL LOCAL TAXES, '2000' for TOTAL "
                "LOCAL SUPPORT NONTAX, etc. The grand-total row uses "
                "the sentinel 'GRAND_TOTAL'. Codes are stable across "
                "years (the form's column-grouping has been consistent "
                "since 2013-14)."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'general', 'debt_service', 'capital_projects', or "
                "'transportation_vehicle'. Four columns only -- the "
                "form omits ASB and Permanent (no tax-funded revenue) "
                "and prints no cross-fund Total column."
            ),
        },
        {
            "name": "is_section_total",
            "field_type": "boolean",
            "doc": (
                "True when this row is the section's subtotal "
                "(e.g. '1000 TOTAL LOCAL TAXES'). Section subtotals "
                "share the section's anchor code in `revenue_account` "
                "and have item_label starting with 'TOTAL'. Useful for "
                "joining at the SUMMARY level against existing "
                "`fiscal_f195_budget` rows whose `item_code` is also "
                "the 4-digit anchor."
            ),
        },
        {
            "name": "is_grand_total",
            "field_type": "boolean",
            "doc": (
                "True for the single 'TOTAL REVENUES AND OTHER "
                "FINANCING SOURCES' row at the very end of the "
                "sub-report. revenue_account='GRAND_TOTAL', "
                "section='grand_total'."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Item label as printed (whitespace normalized). "
                "Multi-line labels are joined. Account labels drift "
                "across years (e.g. account 2188 has been 'Day Care "
                "Tuitions and Fees' -> 'Child Care Tuitions and Fees' "
                "-> 'Early Learning Tuitions and Fees') so don't "
                "label-match across years -- use `revenue_account`."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL when the form left the "
                "cell blank -- the common case, since most accounts "
                "are fund-restricted (e.g. 3100 Apportionment is "
                "General Fund only). Parenthesized negatives parse to "
                "negative decimals."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing; empty for blank cells.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "revenue_account", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_REVENUES]
