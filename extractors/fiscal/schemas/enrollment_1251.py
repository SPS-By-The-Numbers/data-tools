"""Schema for the `fiscal_1251_enrollment` fact table.

Source: OSPI Reports 1251 (FTE) and 1251H (Head-count), both summarizing
P-223 monthly enrollment per district per school year. Identical
structural shape modulo unit (decimal FTE vs integer headcount), so
unified into one fact table with a `report_kind` discriminator.

Each report contains multiple per-grade tables:
  - K-12 Basic Education (per grade)
  - K-12 By Grade Span (Kindergarten + 5 spans + totals)
  - ALE Total (FTE only)
  - Transition To Kindergarten (headcount only)
  - Running Start (headcount only)
  - Open Doors (headcount only)
  - TBIP -- Transitional Bilingual Instructional Program (FTE + headcount)

Long-form: one row per (school_year, ccddd, report_kind, section, grade, month).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_1251_ENROLLMENT = {
    "name": "fiscal_1251_enrollment",
    "doc": (
        "Long-form per-grade per-month enrollment capture of OSPI Reports "
        "1251 (FTE) and 1251H (Head-count). One row per (section, grade, "
        "month) value."
    ),
    "fields": [
        {
            "name": "fiscal_1251_enrollment_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "report_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "'fte' (Report 1251) or 'headcount' (Report 1251H).",
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Canonical section identifier derived from the table "
                "title: e.g. 'k12_total_including_ale', 'ale_total', "
                "'k12_by_grade_span', 'transition_to_kindergarten', "
                "'running_start', 'open_doors', 'tbip'. Section "
                "membership varies by report_kind."
            ),
        },
        {
            "name": "grade",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Grade label as slug: kindergarten, first, second, ..., "
                "twelfth, totals, grades_1_3, grade_4, grades_5_6, "
                "grades_7_8, grades_9_12, total_tk_hc, total_rs, "
                "rs_only, open_doors, tbip_tk, tbip_k_6, tbip_7_12, ..."
            ),
        },
        {
            "name": "month",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Column label, all-caps as printed: SEPTEMBER, OCTOBER, "
                "..., JUNE, plus optionally JULY / AUGUST for sections "
                "that run year-round (Running Start, Open Doors, TK). "
                "AVERAGE is the trailing summary column on every section."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed value. Decimals for FTE (1251), integers for "
                "headcount (1251H) -- but stored as decimal either way "
                "to keep the schema uniform."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "report_kind", "section", "grade", "month"]],
}


ALL_SCHEMAS = [FISCAL_1251_ENROLLMENT]
