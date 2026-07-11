"""Schema for the `fiscal_f195_long_term_financing` fact table.

Source: `<FUND> - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS
AND NOTES` sub-reports of OSPI Form F-195 Budget (labeled GF14 /
CP9 / TVF4 depending on fund). One page per fund (General, Capital
Projects, Transportation Vehicle). Debt Service fund has a distinct
`DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS` sub-report
(DS4) captured in a separate table.

Layout per page:
  Section A -- existing conditional-sale contracts entered in prior
    years. Per-instrument detail row: `<label> <length_months>
    <balance_sept1> <prin_fy> <interest_fy> <balance_aug31>`. Section
    total row: `A. TOTAL <balance_sept1> <prin_fy> <interest_fy>
    <balance_aug31>` (skips the length column).
  Section B -- new conditional-sale contracts to be entered in the
    upcoming fiscal year. Per-instrument detail row: `<label>
    <length_months> <contract_purchase> <prin_fy> <interest_fy>
    <ltf_9500>`. Section total: same shape as A but interpreted in
    Section B's column semantics.
  Section C -- combined summary. `C. TOTAL for Both Sections (A+B)
    <prin_fy_total> <interest_fy_total> <balance_end_total>` (3
    values).

Column semantics differ between A and B, so the schema names the
value columns generically. Consumers filtering by section can apply
the correct interpretation:

  section='existing_contracts' (A):
    amount_beginning  = outstanding balance at Sept 1 of the fiscal year
    principal_fy      = principal payments in FY
    interest_fy       = interest payments in FY
    amount_ending     = outstanding balance at Aug 31 of the fiscal year
  section='new_contracts' (B):
    amount_beginning  = contract purchase amount (net of down payments)
    principal_fy      = principal payments in FY
    interest_fy       = interest payments in FY
    amount_ending     = Long-Term Financing revenue budgeted in Rev. Acct 9500
  section='summary' (C):
    amount_beginning  = NULL (form omits)
    principal_fy      = sum(A.principal_fy + B.principal_fy)
    interest_fy       = sum(A.interest_fy + B.interest_fy)
    amount_ending     = sum(A.amount_ending + B.amount_ending)
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_LONG_TERM_FINANCING = {
    "name": "fiscal_f195_long_term_financing",
    "doc": (
        "Per-fund per-instrument conditional-sales-contract inventory "
        "from OSPI Form F-195 Budget sub-reports GF14 (General Fund) / "
        "CP9 (Capital Projects) / TVF4 (Transportation Vehicle). "
        "Complements `fiscal_f196_long_term_liabilities` (which tracks "
        "the same debt from the audited-financials side)."
    ),
    "fields": [
        {
            "name": "fiscal_f195_long_term_financing_id",
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
                "Fund context: `general` (GF14), `capital_projects` "
                "(CP9), or `transportation_vehicle` (TVF4). Debt Service "
                "bonds live in a separate table (`fiscal_f195_debt_"
                "service_bonds`, from DS4)."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which section the row is from: `existing_contracts` "
                "(A -- purchased in prior years), `new_contracts` (B -- "
                "to be entered in the new FY), or `summary` (C -- "
                "combined A+B total plus the per-section TOTAL rows)."
            ),
        },
        {
            "name": "item_seq",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Sequential index within the (fund, section) tuple, "
                "starting at 1 for the first per-instrument detail row. "
                "Section TOTAL rows use `item_seq=0` (or, for the "
                "combined C total, use section='summary' with "
                "`item_seq=0`)."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the per-section TOTAL rows (`A. TOTAL`, "
                "`B. TOTAL`) and the combined `C. TOTAL for Both "
                "Sections (A+B)`. False for per-instrument detail rows."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed. For per-instrument detail rows this "
                "is the contract description (e.g. 'SAP (Business "
                "Systems) Contract'). Empty on placeholder rows where "
                "the fund has no active contract (form prints '0 0 0 "
                "0 0' with no leading label). TOTAL rows use their "
                "printed marker (`A. TOTAL`, `B. TOTAL`, `C. TOTAL for "
                "Both Sections (A+B)`)."
            ),
        },
        {
            "name": "contract_length_months",
            "field_type": "decimal",
            "doc": (
                "Term of the contract in months. NULL on all TOTAL "
                "rows (Section A / B / C -- the form omits the length "
                "column on those). Zero on placeholder-only rows."
            ),
        },
        {
            "name": "amount_beginning",
            "field_type": "decimal",
            "doc": (
                "Section A: outstanding contract balance at Sept 1 of "
                "the fiscal year. Section B: contract purchase amount "
                "net of down payments. Section C (summary): NULL "
                "(the form omits this column on the combined-total row)."
            ),
        },
        {
            "name": "principal_fy",
            "field_type": "decimal",
            "doc": (
                "Principal payments made in the fiscal year. Stable "
                "semantics across all three sections."
            ),
        },
        {
            "name": "interest_fy",
            "field_type": "decimal",
            "doc": (
                "Interest payments made in the fiscal year. Stable "
                "semantics across all three sections."
            ),
        },
        {
            "name": "amount_ending",
            "field_type": "decimal",
            "doc": (
                "Section A: outstanding contract balance at Aug 31 of "
                "the fiscal year (== amount_beginning - principal_fy). "
                "Section B: Long-Term Financing revenue budgeted in "
                "Rev. Acct 9500 (== amount_beginning of the new "
                "contract). Section C (summary): combined ending "
                "balance for both sections (Section A ending + Section "
                "B LTF 9500)."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "fund", "section", "item_seq",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_LONG_TERM_FINANCING]
