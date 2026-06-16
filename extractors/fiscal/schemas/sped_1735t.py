"""Schema for the `fiscal_1735t_sped_enrollment` fact table.

Source: OSPI Report 1735T "Special Education Enrollment as Reported on
Form P223H" -- a tiny per-district per-school-year report with a single
monthly table broken down by age/tier groups. Across years the row
breakdown varies: 2018-19 prints Ages 0-2 / 3-5 / K-21 / TOTAL; 2024-25
prints Ages 3-5 / Tier TK variants / Tier K-21 variants / TOTAL.

Long-form: one row per (school_year, ccddd, grade, month) value.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_1735T_SPED_ENROLLMENT = {
    "name": "fiscal_1735t_sped_enrollment",
    "doc": (
        "Long-form per-age-group per-month special education enrollment "
        "from OSPI Report 1735T (P223H counts). One row per (grade, "
        "month) value."
    ),
    "fields": [
        {
            "name": "fiscal_1735t_sped_enrollment_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "grade",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Age/tier group as slug. Older years (2018-19 and earlier): "
                "`ages_0_2`, `ages_3_5`, `ages_k_21`. Newer years (2024-25): "
                "`ages_3_5`, `tier_14_18_tk`, `other_tier_tk`, `tier_1_k_21`, "
                "`other_tier_k_21` (label wraps to '_21' on a separate line "
                "in the source, so the slug may drop the suffix; verify "
                "against `item_label` for cross-year comparisons). All "
                "years print a `total` row."
            ),
        },
        {
            "name": "month",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "All-caps month label: SEPTEMBER through JUNE, plus AVERAGE.",
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. Headcount values are integers but "
                "stored as decimal because the AVERAGE column carries "
                "fractional values (9-month means)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "grade", "month"]],
}


ALL_SCHEMAS = [FISCAL_1735T_SPED_ENROLLMENT]
