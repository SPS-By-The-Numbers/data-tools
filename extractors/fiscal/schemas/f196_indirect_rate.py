"""Schema for the `fiscal_f196_indirect_rate` fact table.

Source: the two Federal Indirect Cost Rate Schedule sub-reports on
F-196 All Pages PDFs -- Restricted (pp 72-73) and Unrestricted
(pp 74-75). Each schedule is a 2-page report:

  - Page 1: 7-column expenditures breakdown per program / Program-97
    activity (Total Expenditures, Excluded Capital Outlay, Excluded
    Debt Service, Excluded Distorting Items, Excluded [Added to Base]
    Unallowable, [Pool] Indirect, [Base] Direct). This detail is
    NOT captured -- structurally similar to
    fiscal_f196_program_activity_object; capture the summary rows
    only.
  - Page 2: 14-line rate calculation showing the two-year fixed-with-
    carry-forward computation. This IS captured (the headline
    output).

**The unique analytical contribution is the calculated indirect rate**
per district per year (both Restricted and Unrestricted flavors),
plus the intermediate calculation lines so consumers can audit the
rate.

Long-form: one row per (school_year, ccddd, rate_kind, line_number).
`rate_kind` is 'restricted' or 'unrestricted'. `line_number` is '1'
through '14' matching the printed rate calculation.

The calculated rates -- the ones federal grants actually use -- are:
  - line 5: the base-FY rate applied in the current filing FY
  - line 14: the newly-calculated rate to apply in a future FY
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_INDIRECT_RATE = {
    "name": "fiscal_f196_indirect_rate",
    "doc": (
        "Federal Indirect Cost Rate 14-line calculation per district "
        "per year, both Restricted and Unrestricted rate flavors, "
        "from the Schedule for Determining School District Federal "
        "Restricted / Unrestricted Indirect Cost Rate sub-reports of "
        "OSPI Form F-196 All Pages. Covers 2013-14 through 2024-25 "
        "(3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_indirect_rate_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "rate_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'restricted' or 'unrestricted'. The Restricted rate "
                "excludes certain indirect activities (Public "
                "Relations, some administrative functions) and is "
                "used on federal programs subject to the "
                "supplement-not-supplant rule (ESEA/ESSA Title I "
                "etc). The Unrestricted rate is used on federal "
                "programs without that restriction. Both are "
                "computed on every district's F-196 filing."
            ),
        },
        {
            "name": "line_number",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Line number in the rate calculation, '1' through "
                "'14'. Line 5 is the base-FY rate applied in this "
                "filing FY; Line 14 is the newly-calculated rate "
                "to apply in a future FY."
            ),
        },
        {
            "name": "line_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined. Common formulas: 'FY YY-YY "
                "INDIRECT EXPENDITURES', 'CALCULATED FY YY-YY "
                "<Kind> INDIRECT RATE TO BE USED IN FY YY-YY'."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "The line's calculated value. For lines 1-4 and 6-13: "
                "dollar amounts (indirect / direct expenditures, "
                "adjusted pool, over/under recovery). For lines 5 "
                "and 14: the indirect rate itself as a decimal "
                "(e.g. 0.0168 means 1.68%). For line 3, the value "
                "may be negative (over-recovery)."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "rate_kind", "line_number"]],
}


ALL_SCHEMAS = [FISCAL_F196_INDIRECT_RATE]
