"""Schema for the `fiscal_f780_levy` fact table.

Source: OSPI Report F-780 "Levy Authority and Local Effort Assistance
(LEA) Payable". One short report per (school district, levy year, status)
where status is 'Initial' (published ~October before levy collection
year) or 'Final' (~April of levy collection year). The form has 4
sections (SUMMARY + SCHEDULE I/II/III) and ~22 letter-prefixed line
items capturing assessed valuation, enrollment, levy per-pupil/per-tax
caps, rollback, and LEA payable.

Long-form: one row per (school_year, ccddd, levy_year, status, section,
item_code). Page 2 of the report is boilerplate explanatory text and is
not parsed.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F780_LEVY = {
    "name": "fiscal_f780_levy",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-780 Levy "
        "Authority. Captures the SUMMARY plus SCHEDULE I (Estimated "
        "Levy Revenue), II (Maximum LEA), and III (LEA Payable)."
    ),
    "fields": [
        {
            "name": "fiscal_f780_levy_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "levy_year",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Calendar year the levy is collected (parsed from the "
                "filename, e.g. 2025 from 'F-780 Initial 2025 Levy "
                "Authority.pdf'). Distinct from `school_year`: the "
                "Initial F-780 for levy year 2025 is published in "
                "October 2024 (school year 2024-2025); the Final F-780 "
                "for the same levy year is published in April 2025 "
                "(same school year 2024-2025)."
            ),
        },
        {
            "name": "status",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'Initial' (~October before levy year, before voter-"
                "approval and certification) or 'Final' (~April of levy "
                "year, after certification). Same form shape; the "
                "underlying values get updated."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'summary' | 'schedule_i' (Estimated Levy Revenue) | "
                "'schedule_ii' (Maximum LEA) | 'schedule_iii' (LEA Payable)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Letter from the form (A, B, C, ...) for top-level items, "
                "or a slug-derived identifier for the small number of "
                "sub-items in Schedule I (enrollment_without_transfers, "
                "high_nonhigh_enrollment_transfers, ...)."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": "Full item label as printed (whitespace normalized).",
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. Dollar amounts, enrollment counts, "
                "ratios, and rates are all stored as decimals -- consumers "
                "use `item_code` / `item_label` to interpret units. "
                "Parenthesized negatives (Schedule III rollback) parse "
                "to negative decimals."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "levy_year", "status",
                "section", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_F780_LEVY]
