"""Schema for the `fiscal_apportionment_monthly` fact table.

Source: OSPI monthly Statement of Apportionment PDFs (one per
district / college / state agency per month). Page 1 of each PDF is a
six-column table; pages 2+ are detailed per-account computations that
are deferred to a future parser.

Long-form: one row per (school_year, ccddd, org_type, month,
revenue_account).

**Coverage scope**: only `apportionment/<year>/{district,college,state_agency}/`
files are parsed here. ESD-level monthly apportionment files live under
`apportionment/<year>/esd/<esd>/<member_district>/` but are replicated
under every member-district subdirectory (the ESD's own apportionment
appears ~30 copies, one per member), so naive parsing would produce huge
LK collisions. ESD-level apportionment will get its own dedup pass.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_APPORTIONMENT_MONTHLY = {
    "name": "fiscal_apportionment_monthly",
    "doc": (
        "Long-form per-row capture of OSPI's monthly Statement of "
        "Apportionment (page 1). One row per (org, month, revenue "
        "account). Captures the six summary columns -- annual allotment, "
        "year-to-date adjustment, percent due, allot due, paid "
        "previously, and the month's actual payment."
    ),
    "fields": [
        {
            "name": "fiscal_apportionment_monthly_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "org_type",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'district', 'college', or 'state_agency'. Derived from "
                "the org-type segment in the path."
            ),
        },
        {
            "name": "month",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Month name as printed on the form: September, October, "
                "..., August. Apportionment runs Sept-Aug (the school "
                "fiscal year)."
            ),
        },
        {
            "name": "month_seq",
            "field_type": "int",
            "doc": "1-12 chronological position within the school year (Sept=1, Aug=12).",
        },
        {
            "name": "report_date_text",
            "field_type": "string",
            "doc": "Report date printed in the header (e.g. 'September 29, 2024'). Free text; not normalized.",
        },
        {
            "name": "revenue_account",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI revenue account code (e.g. '3100' = Regular "
                "Apportionment, '4121' = Special Education, '6113' = "
                "ESSER III). Two sentinel values: 'TOTALS' for the "
                "totals row at the bottom of the table, "
                "'GENERAL_FUND_ONLY_TOTAL' for the 'General Fund Only "
                "Total' net-summary line below the totals."
            ),
        },
        {
            "name": "revenue_description",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Account description as printed (whitespace normalized). "
                "Multi-line descriptions are joined. Part of the logical "
                "key because older years (2013-14 / 2014-15) have multiple "
                "sub-program rows under the same account code: '3100 FED "
                "FOREST', '3100 FIRE', '3100 REGULAR APPORTIONMENT' all "
                "carry account code '3100'."
            ),
        },
        {
            "name": "annual_allotment",
            "field_type": "decimal",
            "doc": "Column A: total annual allotment for this revenue account.",
        },
        {
            "name": "adjustment_allotment",
            "field_type": "decimal",
            "doc": "Column B: previous/current year adjustment to the allotment.",
        },
        {
            "name": "percent_due",
            "field_type": "decimal",
            "doc": (
                "Column C: percentage of annual allotment due in this "
                "month (printed as decimal, e.g. 0.0900 for the standard "
                "monthly Sept-May share of 9%). NULL on the Totals row."
            ),
        },
        {
            "name": "allot_due",
            "field_type": "decimal",
            "doc": "Column D: dollars due this month before deductions (= C*A + B).",
        },
        {
            "name": "paid_previously",
            "field_type": "decimal",
            "doc": "Column E: dollars previously paid this fiscal year toward Column D.",
        },
        {
            "name": "allotment_for_month",
            "field_type": "decimal",
            "doc": "Column F: dollars actually paid this month (the headline number).",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "org_type", "month",
                "revenue_account", "revenue_description"]],
}


ALL_SCHEMAS = [FISCAL_APPORTIONMENT_MONTHLY]
