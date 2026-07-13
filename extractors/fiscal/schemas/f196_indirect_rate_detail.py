"""Schema for the `fiscal_f196_indirect_rate_detail` fact table.

Source: page 1 of each of the two Federal Indirect Cost Rate Schedule
sub-reports on F-196 All Pages PDFs -- Restricted (p 72 typical) and
Unrestricted (p 74 typical). Each schedule is a 2-page report; this
table captures the page-1 expenditures partition. Page 2 (the 14-line
rate calculation) is captured by `fiscal_f196_indirect_rate`.

**Structure of page 1.** Each row is one segment of district
expenditures partitioned into 7 columns:

    TOTAL = CAPITAL_OUTLAY + DEBT_SERVICE + DISTORTING_ITEMS
          + UNALLOWABLE + INDIRECT_POOL + DIRECT_BASE

The three "excluded" columns (Capital Outlay, Debt Service, Distorting
Items) drop out of the rate calculation entirely. Unallowable amounts
are added to the base. Indirect pool and Direct base drive the rate
numerator and denominator (line 6 of the calculation is the Indirect
Pool; line 4 is the Direct Base sum).

**Rows on page 1.**

  - `programs_total`  -- 1 row per file per rate_kind. The single-line
    "TOTAL PROGRAMS 01-89, 98, 99" roll-up of all direct-charge
    programs. UNALLOWABLE and INDIRECT columns are 0 by construction
    (direct-charge programs have neither).
  - `activity_detail` -- ~20 rows per file per rate_kind. One row per
    Program 97 activity code (11 Board of Directors, 12 Superintendent's
    Office, 13 Business Office, 14 Human Resources, 15 Public Relations,
    25 Pupil Management, 61-68 various operations, 72-75 various
    support, 83-85 debt). Most fall entirely in INDIRECT_POOL or
    DIRECT_BASE; activities 83/84/85 route to DEBT_SERVICE.
  - `program_97_total` -- 1 row per file per rate_kind. The "Total
    Program 97" roll-up of all activity_detail rows.

**Rate calculation cross-check.** The rate is roughly
`INDIRECT_POOL / (Total Program 97 DIRECT_BASE + programs_total
DIRECT_BASE + UNALLOWABLE)` -- see `fiscal_f196_indirect_rate` line 5
for the printed rate.

Coverage: 2013-14 through 2024-25 (3,724 files). Same file set as
`fiscal_f196_indirect_rate`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_INDIRECT_RATE_DETAIL = {
    "name": "fiscal_f196_indirect_rate_detail",
    "doc": (
        "Per-district per-year 7-column expenditures partition that "
        "feeds the Federal Indirect Cost Rate calculation, per rate "
        "flavor (restricted / unrestricted) and per row_kind "
        "(programs_total / activity_detail / program_97_total). Covers "
        "2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_indirect_rate_detail_id",
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
                "'restricted' or 'unrestricted'. See "
                "`fiscal_f196_indirect_rate.rate_kind` for the "
                "definitional difference between the two rate flavors."
            ),
        },
        {
            "name": "row_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'programs_total' (aggregate of programs "
                "01-89, 98, 99), 'activity_detail' (an individual "
                "Program 97 activity), or 'program_97_total' "
                "(aggregate of all Program 97 activities). "
                "Each rate_kind has exactly 1 programs_total row, "
                "~20 activity_detail rows, and 1 program_97_total row."
            ),
        },
        {
            "name": "activity_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "For row_kind='activity_detail': the 2-digit OSPI "
                "activity code (11=Board of Directors, 12=Superintendent's "
                "Office, 13=Business Office, 14=Human Resources, "
                "15=Public Relations, 25=Pupil Management, 35=Pupil "
                "Safety, 61=Supervision, 62=Grounds Maint, "
                "63=Operation of Buildings, 64=Maintenance, "
                "65=Utilities, 67=Building & Property Security, "
                "68=Insurance, 69=Depreciation Sub Fund, "
                "72=Information Systems, 73=Printing, 74=Warehousing, "
                "75=Motor Pool, 83=Interest, 84=Principal, "
                "85=Debt-Related Expenditures). For programs_total "
                "and program_97_total rows: sentinel '00'."
            ),
        },
        {
            "name": "activity_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined (e.g. 'Building and Property "
                "Security', 'Depreciation Sub Fund'). Labels drift "
                "slightly across vintages; join on `activity_code` "
                "for cross-year queries."
            ),
        },
        {
            "name": "total_expenditures",
            "field_type": "decimal",
            "doc": (
                "TOTAL PROGRAM EXPENDITURES column (leftmost data "
                "column). Sum of the 6 partition columns."
            ),
        },
        {
            "name": "capital_outlay",
            "field_type": "decimal",
            "doc": (
                "CAPITAL OUTLAY column (excluded from rate calc). "
                "Object 9 spending associated with the activity."
            ),
        },
        {
            "name": "debt_service",
            "field_type": "decimal",
            "doc": (
                "DEBT SERVICE column (excluded from rate calc). "
                "Populated only for activities 83 (Interest), 84 "
                "(Principal), and 85 (Debt-Related Expenditures)."
            ),
        },
        {
            "name": "distorting_items",
            "field_type": "decimal",
            "doc": (
                "DISTORTING ITEMS column (excluded from rate calc). "
                "Corresponds to Data Requirements items 1 (Flow-through "
                "funds programs 01-89/98/99) and 2 through ~10 "
                "(activity-specific flow-through funds / election "
                "expenses / etc). See "
                "`fiscal_f196_data_requirements[report_kind='indirect_rate']` "
                "for the per-district input values."
            ),
        },
        {
            "name": "unallowable",
            "field_type": "decimal",
            "doc": (
                "UNALLOWABLE (ADDED TO BASE) column. Federally-"
                "unallowable expenditures (lobbying, some legal, some "
                "board-of-directors costs). Reclassified as DIRECT_BASE "
                "for the rate denominator. Zero on most rows."
            ),
        },
        {
            "name": "indirect_pool",
            "field_type": "decimal",
            "doc": (
                "(POOL) INDIRECT EXPENDITURES column. The rate "
                "numerator base. Populated on most Program 97 "
                "activity rows; the sum equals line 6 of the rate "
                "calculation (`Total Indirect Cost Pool`)."
            ),
        },
        {
            "name": "direct_base",
            "field_type": "decimal",
            "doc": (
                "(BASE) DIRECT EXPENDITURES column. The rate "
                "denominator base (before UNALLOWABLE is added). "
                "Populated mostly on the `programs_total` row plus "
                "portions of certain Program 97 activities."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "rate_kind", "row_kind", "activity_code"]],
}


ALL_SCHEMAS = [FISCAL_F196_INDIRECT_RATE_DETAIL]
