"""Schema for the `fiscal_f195_debt_service_bonds` fact table.

Source: `DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS`
sub-report (DS4) of OSPI Form F-195 Budget. Per-district per-bond
inventory of outstanding voted and non-voted debt service bonds,
listed by issue date, original amount, and estimated amount
outstanding as of September 1 of the fiscal year.

Layout per page:
  A. VOTED BONDS
    <date_of_issue> <amount_original> <amount_outstanding>
    ...
    TOTAL VOTED BONDS <amount_original_total> <amount_outstanding_total>
  B. NONVOTED BONDS
    <date_of_issue> <amount_original> <amount_outstanding>
    ...
    TOTAL NONVOTED BONDS <amount_original_total> <amount_outstanding_total>
  TOTAL ALL BONDS <combined_original> <combined_outstanding>

The GF/CP/TVF Long-Term Financing pages (Conditional Sales Contracts)
live in a separate table `fiscal_f195_long_term_financing`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_DEBT_SERVICE_BONDS = {
    "name": "fiscal_f195_debt_service_bonds",
    "doc": (
        "Per-district per-bond inventory of outstanding voted and "
        "non-voted debt-service bonds from OSPI Form F-195 Budget "
        "sub-report DS4. Complements "
        "`fiscal_f196_long_term_liabilities` (bond roll-forward from "
        "the audited-financials side)."
    ),
    "fields": [
        {
            "name": "fiscal_f195_debt_service_bonds_id",
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
                "Which section the row is from: `voted_bonds` (A -- "
                "bonds approved by voter referendum), `nonvoted_bonds` "
                "(B -- bonds issued without voter approval), or "
                "`summary` (the final `TOTAL ALL BONDS` row combining "
                "A + B)."
            ),
        },
        {
            "name": "item_seq",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Sequential index within the section, starting at 1 "
                "for the first per-bond detail row. Section TOTAL "
                "rows (`TOTAL VOTED BONDS`, `TOTAL NONVOTED BONDS`, "
                "`TOTAL ALL BONDS`) use `item_seq=0`."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the per-section TOTAL rows and the combined "
                "`TOTAL ALL BONDS`. False for per-bond detail rows."
            ),
        },
        {
            "name": "date_of_issue",
            "field_type": "string",
            "doc": (
                "Bond issue date as printed, typically `MM-DD-YYYY` "
                "(e.g. `07-30-2007`, `04-17-2020`). NULL on TOTAL rows."
            ),
        },
        {
            "name": "amount_original",
            "field_type": "decimal",
            "doc": (
                "Amount of the original bond issue at time of "
                "issuance. TOTAL rows carry the sum across bonds in "
                "the section."
            ),
        },
        {
            "name": "amount_outstanding",
            "field_type": "decimal",
            "doc": (
                "Estimated amount outstanding as of September 1 of "
                "the fiscal year (start of FY). TOTAL rows carry the "
                "sum across bonds in the section."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "section", "item_seq",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_DEBT_SERVICE_BONDS]
