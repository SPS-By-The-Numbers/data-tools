"""Schema for the `fiscal_f195_staff_by_activity` fact table.

Source: `SUMMARY OF FTE CERTIFICATED AND CLASSIFIED STAFF COUNTS BY
ACTIVITY` sub-report of OSPI Form F-195 Budget and F-195 Budget Overview
(commonly labeled `GF15`).

Per-district per-OSPI-activity-code snapshot of budgeted FTE staff for
the current fiscal year, decomposed into certificated vs classified,
each with a companion `% to Total` column. **Current-year budget
only** -- unlike `fiscal_f195_budget[fund_summary]` this sub-report
does not carry a 3-column Actual/Budget/Budget history, so there is
no `data_year_offset` dimension.

Row-count expectation: ~30 activity rows + 5 per-group TOTAL rows +
1 grand TOTAL FTE STAFF row per file. All rows have all 4 value columns;
XXXXX (parsed to NULL) marks activities that don't apply to one of the
two staff categories (e.g. building operations doesn't have
certificated FTE; instructional development doesn't have classified
FTE).

The activity code space is IDENTICAL to
`fiscal_f195_budget[expenditure_by_activity_summary]` (GF11) -- rows
join on `(school_year, ccddd, activity_code)`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_STAFF_BY_ACTIVITY = {
    "name": "fiscal_f195_staff_by_activity",
    "doc": (
        "Per-district per-OSPI-activity-code budgeted FTE staff snapshot "
        "from OSPI Form F-195 Budget sub-report GF15 (SUMMARY OF FTE "
        "CERTIFICATED AND CLASSIFIED STAFF COUNTS BY ACTIVITY). Current-"
        "year budget only; no data-year history."
    ),
    "fields": [
        {
            "name": "fiscal_f195_staff_by_activity_id",
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
                "OSPI activity group slug. Values: "
                "'teaching_activities' (activity codes 27, 28), "
                "'teaching_support' (22, 24, 25, 26, 31, 32, 33, 34, 35), "
                "'other_support_activities' (44, 52, 53, 58, 62-65, 67, "
                "72, 73, 74, 75, 91), "
                "'unit_administration' (23), "
                "'central_administration' (12, 13, 14, 15, 21, 41, 51, "
                "61), or 'summary' (per-group TOTAL rows and the "
                "grand TOTAL FTE STAFF row)."
            ),
        },
        {
            "name": "activity_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit activity code as printed ('27', '28', "
                "'44'). Per-group TOTAL rows carry a slug of the group "
                "name ('total_teaching_activities', ...). The final "
                "grand-total row uses `activity_code='total_fte_staff'`. "
                "The activity code space matches "
                "fiscal_f195_budget[expenditure_by_activity_summary] "
                "-- join on `(school_year, ccddd, activity_code)` to "
                "compare per-activity budget (in expenditure_by_activity_"
                "summary) with per-activity FTE (here)."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the 5 per-group TOTAL rows and the 1 grand "
                "TOTAL FTE STAFF row. Detail rows are False."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Activity label as printed (whitespace normalized). "
                "Labels drift across vintages (e.g. 'Extracuricular' "
                "has been printed with 1 or 2 r's) -- use `activity_code` "
                "for cross-year joins, not `item_label`."
            ),
        },
        {
            "name": "certificated_fte",
            "field_type": "decimal",
            "doc": (
                "Budgeted FTE of certificated staff assigned to this "
                "activity. NULL when the form prints `XXXXX` (activity "
                "doesn't apply to certificated staff, e.g. building "
                "operations, warehousing)."
            ),
        },
        {
            "name": "certificated_pct_of_total",
            "field_type": "decimal",
            "doc": (
                "Certificated FTE as a percentage of TOTAL FTE STAFF "
                "certificated. Stored as printed (43.20 means 43.20%, "
                "not 0.4320). NULL when the form prints `XXXXX`."
            ),
        },
        {
            "name": "classified_fte",
            "field_type": "decimal",
            "doc": (
                "Budgeted FTE of classified staff assigned to this "
                "activity. NULL when the form prints `XXXXX` (activity "
                "doesn't apply to classified staff, e.g. teaching, "
                "guidance and counseling)."
            ),
        },
        {
            "name": "classified_pct_of_total",
            "field_type": "decimal",
            "doc": (
                "Classified FTE as a percentage of TOTAL FTE STAFF "
                "classified. Stored as printed. NULL when the form "
                "prints `XXXXX`."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "section", "activity_code",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_STAFF_BY_ACTIVITY]
