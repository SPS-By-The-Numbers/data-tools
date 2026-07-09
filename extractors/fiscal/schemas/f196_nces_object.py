"""Schema for the `fiscal_f196_nces_object` fact table.

Source: the NCES Object Expenditure Summary sub-report (pp 34-37) of
each F-196 All Pages PDF. Introduced in 2019-20; **not present on
2013-14 through 2018-19 files** -- the parser produces no rows for
those years.

**The unique analytical contribution is standardized federal reporting
categories.** OSPI's own object codes
(`fiscal_f196_program_activity_object.breakdown_kind='object'`,
10 codes: 2 Cert Salaries, 3 Class Salaries, 4 Employee Benefits, 5
Supplies, 7 Purchased Services, 8 Travel, 9 Capital Outlay, plus 0/1
transfer sentinels) roll up expenditures into WA-specific buckets.
The NCES object codes are a much finer-grained decomposition of the
same total, using federal / NCES-standard categories that enable
cross-state comparison and USDOE reporting.

Long-form: one row per (school_year, ccddd, section, nces_code).
`nces_code` is the printed 4-digit NCES code. The grand-total row
uses `section='summary'` and `nces_code='TOTAL'`.

**Scope: General Fund only.** The sub-report title is 'NCES Object
Expenditure Summary' with no fund label; the values sum to the
General Fund total_expenditures (matches
`fiscal_f196_summary.total_expenditures[general]` to the cent).
Other funds are not covered by this sub-report.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_NCES_OBJECT = {
    "name": "fiscal_f196_nces_object",
    "doc": (
        "Per-NCES-code General-Fund expenditures from the NCES Object "
        "Expenditure Summary sub-report of OSPI Form F-196 All Pages. "
        "Uses the federal NCES Financial Accounting Handbook (Fin13) "
        "object codes rather than OSPI-specific object codes, enabling "
        "cross-state comparison. Covers 2019-20 through 2024-25 "
        "(~1,860 files); the sub-report did not exist before 2019-20."
    ),
    "fields": [
        {
            "name": "fiscal_f196_nces_object_id",
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
                "One of 'certificated_salaries' (codes 2110-2170), "
                "'classified_salaries' (3110-3160), "
                "'employee_benefits_payroll_taxes' (4212-4293), "
                "'supplies_non_capital' (5610-5650), "
                "'purchased_services' (7310-7960), "
                "'travel' (8580 only), "
                "'capital_outlay' (9710-9960), "
                "or 'summary' for the grand-total row."
            ),
        },
        {
            "name": "nces_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "4-digit NCES object code (e.g. '2110' Salaries of "
                "Regular Employee - Certificated, '4212' Group "
                "Insurance - Certificate, '5610' General Supplies, "
                "'7310' Office and Administrative Services, '8580' "
                "Travel/Meals/Lodging, '9720' Buildings). Grand total "
                "row uses the sentinel 'TOTAL'."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the single 'TOTAL ALL NCES OBJECT OF "
                "EXPENDITURE' grand-total row. False for detail rows."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined (e.g. '7520 Insurance (Other Than "
                "Employee Benefits) (Property, Liability, Vehicle, "
                "etc.)')."
            ),
        },
        {
            "name": "amount",
            "field_type": "decimal",
            "doc": (
                "Expenditure amount for the fiscal year. Always "
                "General Fund. **The grand total (nces_code='TOTAL') "
                "matches fiscal_f196_summary.total_expenditures where "
                "fund='general' to the cent on 100% of files.**"
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "nces_code"]],
}


ALL_SCHEMAS = [FISCAL_F196_NCES_OBJECT]
