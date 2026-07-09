"""Schema for the `fiscal_f196_edit_report` fact table.

Source: the Financial Edit Report sub-report (pp 82-84 typical) of
each F-196 All Pages PDF. This is OSPI's post-submission data-quality
report -- a list of automated checks OSPI ran against the district's
filing, grouped by fund, that either passed (cleared) or flagged a
concern with an accompanying explanation and up to 2 supporting
amounts.

**The unique analytical contribution is the data-quality dimension.**
No other captured report exposes OSPI's post-submission edit checks.
Consumers can filter to `edit_type='warning'` or `'error'` to
identify potentially misfiled reports; `is_cleared=True` on all funds
signals a clean audit.

Long-form: one row per (school_year, ccddd, fund, edit_seq).
`edit_seq` is a 0-based sequence per fund per year (order in which
the edits appear on the printed report). Funds with no edits emit a
single `is_cleared=True` row with edit_seq=0.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_EDIT_REPORT = {
    "name": "fiscal_f196_edit_report",
    "doc": (
        "OSPI Financial Edit Report entries per district per fund per "
        "year -- automated data-quality checks that either cleared or "
        "flagged a concern. Covers 2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_edit_report_id",
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
                "One of 'general', 'asb', 'debt_service', "
                "'capital_projects', 'transportation_vehicle', "
                "'permanent', or 'fiduciary'. Canonicalized from the "
                "printed fund header ('GENERAL FUND', 'ASSOCIATED "
                "STUDENT BODY FUND', etc). 'fiduciary' covers the "
                "'PRIVATE PURPOSE TRUST / OTHER TRUST FUND' section (a "
                "single grouping in this sub-report even though it "
                "spans two fiduciary fund types elsewhere)."
            ),
        },
        {
            "name": "edit_seq",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "0-based sequence within (school_year, ccddd, fund) in "
                "the order edits are printed on the report. A fund "
                "with no edits emits a single is_cleared=True row with "
                "edit_seq=0."
            ),
        },
        {
            "name": "edit_type",
            "field_type": "string",
            "doc": (
                "'informational', 'warning', 'error', or 'cleared' "
                "(sentinel for the 'Cleared all edits' marker on a fund "
                "with no other rows)."
            ),
        },
        {
            "name": "edit_number",
            "field_type": "string",
            "doc": (
                "OSPI edit identifier like '1.588', '3.500'. The "
                "leading integer typically groups related edits by "
                "fund/topic. Empty string on 'cleared' rows."
            ),
        },
        {
            "name": "message",
            "field_type": "string",
            "doc": (
                "Full edit message (multi-line joined). Explains what "
                "OSPI checked and, on flagged edits, what the district "
                "should investigate or confirm."
            ),
        },
        {
            "name": "is_cleared",
            "field_type": "boolean",
            "doc": (
                "True on the sentinel row emitted for a fund with no "
                "flagged edits (the 'Cleared all edits' printed line). "
                "False for actual edit rows."
            ),
        },
        {
            "name": "amount_1",
            "field_type": "decimal",
            "doc": (
                "First supporting amount printed to the right of the "
                "message. Interpretation varies by edit -- typically "
                "either the value the check was comparing against, or "
                "the current-year subject amount. NULL when the form "
                "left the cell blank or on 'cleared' rows."
            ),
        },
        {
            "name": "amount_2",
            "field_type": "decimal",
            "doc": (
                "Second supporting amount. Often the prior-year "
                "comparable when the edit compares year-over-year "
                "(e.g. MOE checks). NULL when blank or on 'cleared' "
                "rows."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "fund", "edit_seq"]],
}


ALL_SCHEMAS = [FISCAL_F196_EDIT_REPORT]
