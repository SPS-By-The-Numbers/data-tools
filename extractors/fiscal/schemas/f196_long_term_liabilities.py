"""Schema for the `fiscal_f196_long_term_liabilities` fact table.

Source: the Schedule of Long-Term Liabilities sub-report of each F-196
All Pages PDF. Reports the per-liability-item beginning outstanding
debt, amount issued/increased, amount redeemed/decreased, ending
outstanding debt, and amount due within one year for each item type
(bonds, leases, notes, compensated absences, pension liabilities, ...).

**Two form vintages, both captured**:

  - **Per-fund layout** (2013-14 through 2018-19, 4 pages): a separate
    schedule prints for each of the 4 governmental funds that can hold
    long-term debt (General / Debt Service / Capital Projects /
    Transportation Vehicle). 2013-14 forms carry an explicit
    'GENERAL FUND' / 'DEBT SERVICE FUND' / ... suffix in the banner;
    2015-16 through 2018-19 forms drop the suffix so the parser
    attributes fund by page order (1st = general, 2nd = debt_service,
    3rd = capital_projects, 4th = transportation_vehicle).
  - **Combined layout** (2019-20 through 2024-25, 1 page): all
    liabilities consolidate into a single schedule with no per-fund
    attribution. These rows carry `fund='combined'`.

**GASB drift**:
  - **Net Pension Liabilities** (TRS 1, TRS 2/3, SERS 2/3, PERS 1)
    entered the schedule in 2015-16 with GASB 68 adoption. Not present
    on 2013-14 or 2014-15 forms. Pension rows carry only 4 values
    (beginning / increased / decreased / ending) -- the printed
    'Amount Due Within One Year' column is blank on pension rows and
    emits `amount_due_within_one_year = NULL`.
  - **Leases** (GASB 87) entered the schedule in 2022-23; earlier
    forms used 'Capital Leases' and 'Non-Cancellable Operating Leases'
    as separate items.
  - **OPEB** is explicitly excluded per a form footnote in newer
    vintages ("Other postemployment benefits other than pensions
    (OPEB) liabilities are not presented in the Schedule of Long Term
    Liabilities.") -- no OPEB rows are emitted.

**The unique analytical contribution** is the debt roll-forward
dimension: no other captured sub-report tracks the beginning +
issued - redeemed = ending flow, or the current portion of long-term
debt (Amount Due Within One Year). Complements Balance Sheet
(period-end stocks only) and Budgetary Comparison (annual debt
service payments only).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_LONG_TERM_LIABILITIES = {
    "name": "fiscal_f196_long_term_liabilities",
    "doc": (
        "Long-term liability roll-forward per district per liability "
        "item from the Schedule of Long-Term Liabilities sub-report of "
        "OSPI Form F-196 All Pages. Captures beginning outstanding + "
        "issued - redeemed = ending outstanding, plus the current "
        "portion (Amount Due Within One Year). Covers 2013-14 through "
        "2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_long_term_liabilities_id",
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
                "For per-fund vintages (2013-14 through 2018-19): one "
                "of 'general', 'debt_service', 'capital_projects', "
                "'transportation_vehicle'. For combined vintages "
                "(2019-20+): 'combined'. Consumers doing cross-year "
                "roll-ups should sum per-fund rows on the old form to "
                "align with combined rows on the new form."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'voted_debt', 'non_voted_debt_and_liabilities', "
                "'other_liabilities', 'net_pension_liabilities', or "
                "'summary' (for the TOTAL row). Voted Debt is only "
                "populated on the Debt Service Fund page in per-fund "
                "vintages (2013-14 through 2018-19) and on the "
                "combined page in newer vintages. Net Pension "
                "Liabilities is populated starting 2015-16 (GASB 68)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Slug of the item label. Common values: "
                "'voted_bonds', 'non_voted_bonds', "
                "'local_program_proceeds', 'capital_leases' (pre-2022-23), "
                "'leases' (post-2022-23; GASB 87), 'contracts_payable', "
                "'non_cancellable_operating_leases' (pre-2022-23), "
                "'claims_judgements', 'compensated_absences', "
                "'long_term_notes', 'anticipation_notes_payable', "
                "'lines_of_credit', 'other_non_voted_debt', "
                "'non_voted_notes_not_recorded_as_debt', "
                "'net_pension_liabilities_trs_1', "
                "'net_pension_liabilities_trs_2_3', "
                "'net_pension_liabilities_sers_2_3', "
                "'net_pension_liabilities_pers_1', and "
                "'total_long_term_liabilities' for the TOTAL row."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the 'Total Long-Term Liabilities' row on each "
                "page. False for detail rows. Per-fund vintages emit one "
                "TOTAL row per fund; combined vintages emit one TOTAL "
                "row per file."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed on the form (whitespace normalized). "
                "Multi-line labels are joined (e.g. 'LOCAL Program "
                "Proceeds Issued in Lieu of Bonds')."
            ),
        },
        {
            "name": "beginning_outstanding",
            "field_type": "decimal",
            "doc": (
                "Beginning Outstanding Debt as of September 1 (start of "
                "the fiscal year). NULL when the form left the cell "
                "blank."
            ),
        },
        {
            "name": "amount_increased",
            "field_type": "decimal",
            "doc": (
                "'Amount Issued / Increased' during the fiscal year. "
                "NULL when the cell is blank."
            ),
        },
        {
            "name": "amount_decreased",
            "field_type": "decimal",
            "doc": (
                "'Amount Redeemed / Decreased' during the fiscal year. "
                "NULL when the cell is blank."
            ),
        },
        {
            "name": "ending_outstanding",
            "field_type": "decimal",
            "doc": (
                "Ending Outstanding Debt as of August 31 (end of fiscal "
                "year). The roll-forward identity: "
                "ending_outstanding = beginning_outstanding + "
                "amount_increased - amount_decreased. NULL when the "
                "cell is blank."
            ),
        },
        {
            "name": "amount_due_within_one_year",
            "field_type": "decimal",
            "doc": (
                "Portion of Ending Outstanding Debt classified as "
                "current (due within one year). **Consistently NULL on "
                "Net Pension Liabilities rows** -- the form omits the "
                "current portion for pension liabilities. Also NULL "
                "when the cell is blank on other rows."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "fund", "section", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_F196_LONG_TERM_LIABILITIES]
