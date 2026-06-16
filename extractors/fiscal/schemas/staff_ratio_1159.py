"""Schema for the `fiscal_1159_staff_ratio` fact table.

Source: OSPI Report 1159 "Calculation of {Year} Certificated
Instructional Staff Ratio". One single-page PDF per school district per
school year. The form derives a district's basic-education CIS ratio
(certificated instructional staff per 1000 K-12 students) and checks it
against the statutory floor of 46.

The form is short and stable across the three years it was published
(2013-14 through 2015-16; OSPI stopped issuing it after 2015-16 when
SHB 2261 / McCleary funding rewrote the staffing formula). Each line is
a labeled item with at most one numeric value:

  A. FTE Student Enrollment
    A.1 Selected month                      (text, e.g. "October 2015")
    A.2 K-12 FTE students less Running Start (decimal)
    A.3 K-12 FTE students in ALE             (decimal -- may be blank)
    A.4 K-12 FTE students less ALE           (decimal, = A.2 - A.3)
  B. FTE Certificated Instructional Staff
    B.1 CIS in basic education from S-275    (decimal)
    B.2 CIS in ALE from S-275                (decimal -- may be blank)
    B.3 CIS in basic education less ALE      (decimal, = B.1 - B.2)
    B.4 CIS in basic education from SPI 1158 (decimal -- usually blank)
    B.5 CIS in special education from S-275  (decimal -- may be blank)
    B.6 CIS in special education from SPI 1158 (decimal -- usually blank)
    B.7 SpEd % to basic education            (percentage as printed)
    B.8 Total K-12 FTE CIS                   (decimal)
  C. Calculated Basic Ed CIS Ratio           (decimal, = B.8 / A.4 * 1000)
  D. Did district maintain statutory ratio?  (text, "Yes" / "No")
    D.1 K-12 ratio shortfall                 (decimal -- blank when D=Yes)
    D.2 Penalty Basic Ed CIS FTE             (decimal -- "---" when D=Yes)

Long-form output: one row per item that has a printed value or text
answer. Blank-value items (e.g. B.4 / B.6 when the district didn't
file a Form SPI 1158 adjustment) still emit a row with NULL value and
empty value_text so consumers don't have to detect missing rows.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_1159_STAFF_RATIO = {
    "name": "fiscal_1159_staff_ratio",
    "doc": (
        "Per-district per-year capture of OSPI Report 1159 K-12 "
        "Certificated Instructional Staff Ratio. Coverage: 2013-14, "
        "2014-15, 2015-16 (OSPI discontinued the report after 2015-16)."
    ),
    "fields": [
        {
            "name": "fiscal_1159_staff_ratio_id",
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
                "'Final' for `1159(F)` reports (end-of-year reconciled) or "
                "'Revised' for `1159(R)` reports (intermediate snapshots, "
                "common in 2015-16 where many files were not yet finalized "
                "at scrape time). Parsed from the title-line suffix."
            ),
        },
        {
            "name": "report_date_text",
            "field_type": "string",
            "doc": "Run date as printed at the top of the report (e.g. '18-Aug-16').",
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Form section: 'enrollment' (A.1-A.4) | 'cis' (B.1-B.8) "
                "| 'ratio' (C) | 'compliance' (D, D.1, D.2)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Printed item identifier: 'A.1' through 'A.4', 'B.1' "
                "through 'B.8', 'C', 'D', 'D.1', 'D.2'. Stable across "
                "all three publication years -- the form letters its "
                "own cross-references the same way."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": "Item label as printed (whitespace normalized).",
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. FTE counts, the calculated ratio, "
                "percentages, and the penalty all share this column. "
                "Percentages are stored as the printed number (`27.09` "
                "for 27.09%, not 0.2709). NULL when the form printed no "
                "value (blank cell), when the value is non-numeric "
                "(`A.1` carries a month name; `D` carries 'Yes'/'No'), "
                "or for the `---` zero-placeholder used on `D.2` when "
                "no penalty applies."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": (
                "Raw value as printed. Carries the month name for A.1 "
                "(e.g. 'October 2015'), the Yes/No answer for D, the "
                "literal '---' for D.2 when no penalty applies, and "
                "the formatted numeric text (with `%` suffix for B.7) "
                "for everything else. Empty string when the form left "
                "the cell blank."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "status", "section", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_1159_STAFF_RATIO]
