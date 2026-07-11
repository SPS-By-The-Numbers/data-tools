"""Schema for the `fiscal_f195_revenue_worksheet` fact table.

Source: `REVENUE WORK SHEET--<FUND>--LOCAL EXCESS LEVIES AND TIMBER
EXCISE TAX` sub-report (labeled GF13 / DS3 / CP5 / TVF3 depending on
fund) of OSPI Form F-195 Budget. One page per applicable fund
(General, Debt Service, Capital Projects, Transportation Vehicle).

The worksheet computes the district's budgeted collection of Local
Excess Levies (Revenue Account 1100) and Timber Excise Tax (Revenue
Account 1500) by splitting the annual amount into fall + spring
collection windows, applying a per-window collection percentage, and
summing. Layout per fund page:

  PART I: LOCAL PROPERTY TAX COLLECTIONS
    Fall <yy>   <excess_levy> <est_timber_offset> <net_levy> <coll_pct> <amount_budgeted>
    Spring <yy+1> <excess_levy> <est_timber_offset> <net_levy> <coll_pct> <amount_budgeted>
    1100 TOTAL LOCAL TAXES: <amount_budgeted_sum>
  PART II: TIMBER EXCISE TAX
    Fall <yy>   <assessed_valuation> <dollars_per_thousand> <est_timber_levy> <coll_pct> <amount_budgeted>
    Spring <yy+1> <assessed_valuation> <dollars_per_thousand> <est_timber_levy> <coll_pct> <amount_budgeted>
    1500 TIMBER EXCISE TAXES: <amount_budgeted_sum>

Column semantics differ between Part I and Part II but are structurally
analogous (starting-basis / rate-or-offset / adjusted-basis /
collection-pct / final-budgeted). The schema uses generic `amount_1`,
`amount_2`, `amount_3` column names with per-section documentation.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_REVENUE_WORKSHEET = {
    "name": "fiscal_f195_revenue_worksheet",
    "doc": (
        "Per-district per-fund per-collection-window revenue worksheet "
        "for Local Excess Levies (Account 1100) and Timber Excise Tax "
        "(Account 1500) from OSPI Form F-195 Budget sub-reports GF13 "
        "(General Fund), DS3 (Debt Service), CP5 (Capital Projects), "
        "TVF3 (Transportation Vehicle)."
    ),
    "fields": [
        {
            "name": "fiscal_f195_revenue_worksheet_id",
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
                "Fund context: `general` (GF13), `debt_service` (DS3), "
                "`capital_projects` (CP5), or `transportation_vehicle` "
                "(TVF3)."
            ),
        },
        {
            "name": "part",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which part of the worksheet the row is from: "
                "`local_property_tax` (Part I -- Account 1100), "
                "`timber_excise_tax` (Part II -- Account 1500)."
            ),
        },
        {
            "name": "period",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Collection window: `fall`, `spring`, or `total` (for "
                "the `1100 TOTAL LOCAL TAXES:` and `1500 TIMBER EXCISE "
                "TAXES:` section-total rows)."
            ),
        },
        {
            "name": "period_label",
            "field_type": "string",
            "doc": (
                "As-printed label. Examples: `Fall 2024`, `Spring "
                "2025`, `1100 TOTAL LOCAL TAXES`, `1500 TIMBER EXCISE "
                "TAXES`."
            ),
        },
        {
            "name": "amount_1",
            "field_type": "decimal",
            "doc": (
                "Column 1 amount. In `part='local_property_tax'`: the "
                "Excess Levy Amount for the collection window (annual "
                "dollars). In `part='timber_excise_tax'`: the Timber "
                "Assessed Valuation. NULL on `period='total'` rows."
            ),
        },
        {
            "name": "amount_2",
            "field_type": "decimal",
            "doc": (
                "Column 2 amount. In `part='local_property_tax'`: the "
                "estimated Timber Levy offset (deducted from Excess "
                "Levy to compute Net Levy). In "
                "`part='timber_excise_tax'`: Dollars Per Thousand (the "
                "3-decimal-place rate applied to the Timber Assessed "
                "Valuation). NULL on `period='total'` rows."
            ),
        },
        {
            "name": "amount_3",
            "field_type": "decimal",
            "doc": (
                "Column 3 amount. In `part='local_property_tax'`: the "
                "Net Levy Amount (Col 1 - Col 2). In "
                "`part='timber_excise_tax'`: the Est. Timber Levy "
                "(Col 1 x Col 2 / 1000). NULL on `period='total'` rows."
            ),
        },
        {
            "name": "collection_pct",
            "field_type": "decimal",
            "doc": (
                "Collection percentage for the window (Col 4). Stored "
                "as printed (`45.32` means 45.32%, not 0.4532). NULL "
                "on `period='total'` rows."
            ),
        },
        {
            "name": "amount_budgeted",
            "field_type": "decimal",
            "doc": (
                "Amount budgeted for this collection window (Col 5 = "
                "Col 3 x Col 4 / 100). On section-total rows "
                "(`period='total'`), this is the sum of the fall + "
                "spring `amount_budgeted` values from the section, "
                "representing the district's budgeted collection into "
                "Revenue Account 1100 (Part I) or 1500 (Part II) for "
                "this fund. NULL when the form prints `XXXXX` (e.g. "
                "the Timber Excise Tax fall row's Amount Budgeted is "
                "consistently `XXXXX` because timber excise "
                "distributions land in a single spring payment)."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "fund", "part", "period",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_REVENUE_WORKSHEET]
