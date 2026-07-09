"""Schema for the `fiscal_f196_fiduciary` fact table.

Sources: two adjacent sub-reports on each F-196 All Pages PDF
(pp 20-21 typical, pp 17-18 in 2013-14):

  - **Statement of Fiduciary Net Position** -- balance-sheet-shape:
    Assets / Liabilities / Net Position per fund column.
  - **Statement of Changes in Fiduciary Net Position** --
    income-statement-shape: Additions (contributions, investment
    income, other) / Deductions / net change / beginning balance /
    corrections / ending balance per fund column.

Both are captured into this single table with `statement` distinguishing
them.

**The unique analytical contribution is the fiduciary-fund dimension.**
Governmental Balance Sheet
(`fiscal_f196_balance_sheet`) covers 6 governmental funds; the
fiduciary funds here are held in trust for others (private donations,
student activity money, scholarship endowments) and use accrual-basis
accounting.

**GASB 84 vintage drift** (effective FY 2019-20): the older form had
two columns 'Private Purpose Trust' + 'Other Trust'; the newer form
has 'Custodial Funds' + 'Private Purpose Trust' -- both COLUMN NAMES
CHANGED and COLUMN ORDER SWAPPED. The parser canonicalizes to two
funds:

  - `private_purpose_trust` (same in both vintages)
  - `custodial_funds` (was 'Other Trust' pre-GASB-84; conceptually the
    same fund type, per GASB reclassification)

Consumers reading this table cross-year should treat `custodial_funds`
uniformly; the pre-GASB-84 rows for that fund carry the same semantic
content under a different printed label.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_FIDUCIARY = {
    "name": "fiscal_f196_fiduciary",
    "doc": (
        "Per-fund fiduciary balance sheet + income statement per district "
        "per year from the Statement of Fiduciary Net Position and "
        "Statement of Changes in Fiduciary Net Position sub-reports of "
        "OSPI Form F-196 All Pages. Covers 2013-14 through 2024-25 "
        "(3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_fiduciary_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "statement",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which sub-report the row comes from: 'net_position' "
                "(Statement of Fiduciary Net Position -- balance-sheet "
                "shape: assets/liabilities/net_position) or 'changes' "
                "(Statement of Changes in Fiduciary Net Position -- "
                "income-statement shape: additions/deductions/net_change/"
                "balances)."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "For statement='net_position': one of 'assets', "
                "'liabilities', 'net_position', 'summary'. "
                "For statement='changes': one of 'additions', "
                "'deductions', 'summary' (net change, beginning balance, "
                "corrections, ending balance)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Slug of the item label. TOTAL rows use `total_<section>` "
                "(e.g. `total_assets`, `total_liabilities`, "
                "`total_net_position`, `total_additions`, "
                "`total_deductions`, `total_contributions`). The summary "
                "section carries items like `net_increase_decrease`, "
                "`beginning_balance`, `corrections`, `ending_balance`. "
                "2020-21 (GASB 84 transition year) also emits "
                "`prior_year_manual_revision` and "
                "`intermediate_net_position_total` in the summary "
                "section -- OSPI split the beginning-balance row into "
                "three transitional rows that year only."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Canonical fund name. One of 'private_purpose_trust' or "
                "'custodial_funds'. 'custodial_funds' was printed as "
                "'Other Trust' pre-GASB-84 (through 2018-19) and as "
                "'Custodial Funds' post-GASB-84 (2019-20+). The parser "
                "detects the column mapping per file and normalizes."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for TOTAL rows and the summary-section balance/"
                "change rows. False for detail rows."
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
                "Amount as printed. NULL when the fund/item cell is "
                "blank on the form (many items apply to only one of the "
                "two funds -- e.g. 'Employer' contributions only appear "
                "for private_purpose_trust)."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "statement", "section", "item_code", "fund"]],
}


ALL_SCHEMAS = [FISCAL_F196_FIDUCIARY]
