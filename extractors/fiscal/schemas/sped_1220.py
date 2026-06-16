"""Schema for the `fiscal_1220_sped` fact table.

Source: OSPI Report 1220 "Special Education Allocations". One PDF per
school district per allocation snapshot, capturing the entire
calculation that flows from enrollment counts and BEA rate down to
the final per-account allocations (4121 Special Education, 3121
General Apportionment for SpEd, 4122 Infants & Toddlers).

The form is dense -- per-item printed letters run A through AA across
three account sections, with two wrapped-label items (F, G) and a
multi-sub-item parent (J → J.1, J.2, J.3). A serving-district
enrollment sub-table sits between the 4121 and 3121 sections,
distributing the focal district's enrollment across the high
districts that serve its students.

Long-form output: one row per printed line that has a numeric value,
keyed by `section` + `item_code`. Serving-district enrollment cells
get one row per `(subject_ccddd, item_code)` pair plus a TOTAL row
with `subject_ccddd = 0`.

ESD-level files (`apportionment/<year>/esd/...`) use a different form
(Report 1220TR Transfer of Allocation) -- not captured here; see
TODO.md for a possible parallel `fiscal_1220_sped_transfer` table.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_1220_SPED = {
    "name": "fiscal_1220_sped",
    "doc": (
        "Per-line-item capture of OSPI Report 1220 Special Education "
        "Allocations. District-level only; ESD-level 1220TR Transfer "
        "of Allocation files use a different form and are not "
        "currently captured."
    ),
    "fields": [
        {
            "name": "fiscal_1220_sped_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "status",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'Final' (the end-of-year reconciled snapshot, ~Jan/Feb "
                "of the following calendar year) or a date string like "
                "'2019-08-31' (intermediate snapshots taken during the "
                "school year). Parsed from the title line."
            ),
        },
        {
            "name": "report_date_text",
            "field_type": "string",
            "doc": "Run date as printed at the top of the report (e.g. '24-Jan-20').",
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Form section: 'account_4121' (items A-M) | "
                "'serving_district_enrollment' (per-counterparty A-D "
                "enrollment matrix) | 'account_3121' (items N-X) | "
                "'summary' (cross-section totals) | 'account_4122' "
                "(items Y-AA)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Printed letter (A, B, ..., AA) for top-level items. "
                "Sub-items under J use the J.1 / J.2 / J.3 form. "
                "Items that aren't letter-prefixed get a stable slug "
                "(`pld_portion_bea_rate` under H; "
                "`total_allocation_spe21`, `pld_pct`, `pld_portion` in "
                "the summary section)."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Item label as printed (whitespace normalized). For "
                "wrapped items (F, G) the parent line label and "
                "continuation are joined with ' / '."
            ),
        },
        {
            "name": "subject_ccddd",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "For `serving_district_enrollment` rows, the serving "
                "high district's CCDDD (5-digit). 0 on every other "
                "section's rows and on the TOTAL row of the serving-"
                "district matrix."
            ),
        },
        {
            "name": "subject_name",
            "field_type": "string",
            "doc": (
                "Serving high district name as printed. Empty on "
                "non-serving-district rows."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. Dollar amounts, AAFTE counts, "
                "and percentages all share this column. Percentages "
                "are stored as the printed number (`18.53` for 18.53%, "
                "not 0.1853). Parenthesized negatives parse to negative "
                "decimals. NULL for the printed '-' zero placeholder "
                "on items that have a `-` instead of `0.00`."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text as printed (with any `$` / `%` suffix).",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "status", "section",
                "item_code", "subject_ccddd"]],
}


ALL_SCHEMAS = [FISCAL_1220_SPED]
