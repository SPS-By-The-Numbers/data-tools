"""Schema for the `fiscal_f196_resource_to_program` fact table.

Source: the Resource to Program Expenditure Report - General Fund
sub-report (pp 76-77 typical, position varies with district size) of
each F-196 All Pages PDF. Reports per-program General-Fund
expenditures decomposed by funding source:

    program_expenditures = state_resources + federal_resources
                         + other_resources

**The unique analytical contribution is the funding-source dimension**
per program. `fiscal_f196_program_activity_object` reports total
expenditures per program (breakdown_kind='program') but does not
attribute those totals to their funding source.
`fiscal_f196_revenues` reports revenues per OSPI 4-digit account code
but not per program. This table joins the two dimensions -- program x
funding source.

**Section drift**: 2013-14 through ~2015-16 forms use 'BASIC EDUCATION
PROGRAMS' / 'TOTAL BASIC EDUCATIONAL PROGRAMS' as the first section
label; 2016-17+ forms use 'REGULAR INSTRUCTIONAL PROGRAMS' / 'TOTAL
REGULAR INSTRUCTIONAL PROGRAMS'. The parser canonicalizes both to
`section='regular_instructional'`. Other sections (Other
Instructional, Other Programs) are stable.

Long-form: one row per (school_year, ccddd, section, item_code).
`item_code` is the printed 2-digit program code (01, 02, 09, 11, ...,
99). Section totals use `item_code='TOTAL'`; the whole-report grand
total uses `section='summary'`, `item_code='total'`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_RESOURCE_TO_PROGRAM = {
    "name": "fiscal_f196_resource_to_program",
    "doc": (
        "Per-program General-Fund expenditures decomposed by funding "
        "source (state / federal / other) from the Resource to Program "
        "Expenditure Report sub-report of OSPI Form F-196 All Pages. "
        "Covers 2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_resource_to_program_id",
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
                "One of 'regular_instructional' (canonical for both the "
                "older 'BASIC EDUCATION PROGRAMS' and newer 'REGULAR "
                "INSTRUCTIONAL PROGRAMS' labels), 'other_instructional', "
                "'other_programs', or 'summary' (whole-report totals)."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit program code (e.g. '01' Basic Education, "
                "'09' Transition to Kindergarten, '21' Special Education "
                "Supplemental State, '51' ESEA Disadvantaged, '97' "
                "Districtwide Support, '99' Pupil Transportation). "
                "Section totals use 'TOTAL' (paired with a specific "
                "section); the whole-report grand total uses "
                "`section='summary'` and item_code='total'."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the 4 total rows (per-section TOTAL + grand "
                "TOTAL row). False for the ~50 program-detail rows."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined (e.g. 'Special Education - Infants "
                "and Toddlers - State'). Labels drift across years as "
                "programs are added or renamed."
            ),
        },
        {
            "name": "program_expenditures",
            "field_type": "decimal",
            "doc": (
                "Total General-Fund expenditures for this program. "
                "Equals the sum of state_resources + federal_resources + "
                "other_resources (the funding-source decomposition "
                "invariant)."
            ),
        },
        {
            "name": "state_resources",
            "field_type": "decimal",
            "doc": (
                "Portion of program_expenditures funded by state "
                "resources (state general apportionment, categorical "
                "grants like Special Education Supplemental State, "
                "Transitional Bilingual, LAP, etc)."
            ),
        },
        {
            "name": "federal_resources",
            "field_type": "decimal",
            "doc": (
                "Portion of program_expenditures funded by federal "
                "resources (IDEA, ESEA/ESSA Titles I-IV, ESSER stimulus, "
                "USDA School Food, etc)."
            ),
        },
        {
            "name": "other_resources",
            "field_type": "decimal",
            "doc": (
                "Portion of program_expenditures funded by other "
                "resources (local excess levies, private grants, "
                "tuition, other). Absorbs anything not classified as "
                "state or federal."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_F196_RESOURCE_TO_PROGRAM]
