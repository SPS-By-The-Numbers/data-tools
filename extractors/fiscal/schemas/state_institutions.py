"""Schema for the `fiscal_state_institutions` fact table.

Source: OSPI Form 1191SI, one PDF per (school year, served-by district,
institution) plus a `00000 State Summary` aggregate per year. The form's
shape drifts across years (Section B grew from 8 items in 2013-14 to 5
items in 2024-25, with intermediate revisions in between), so the parser
captures items verbatim rather than coercing into a canonical layout.

Logical key: (school_year, ccddd, revenue_account, institution_name,
              section_code, section_seq, item_path).

(`institution_name` is needed in the LK because multiple institutions can
share a (ccddd, revenue_account) pair -- the served-by district + the
state-institution category code are not by themselves unique. E.g. in
2013-14 ccddd 13165 has Sunrise Community Facility and Sunrise Group
Home, both under revenue_account 4156.)

`section_seq` disambiguates the two "K" sections (page 1 is "TOTAL
ALLOCATION" with 3 items; page 2 is "YEAR END ALLOCATION ADJUSTMENT"
with 3 items). `item_path` is the printed numbering ("1", "1.A", etc.)
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_STATE_INSTITUTIONS = {
    "name": "fiscal_state_institutions",
    "doc": (
        "Long-form per-line-item capture of OSPI Form 1191SI (State "
        "Institution allocations). One row per item printed on the form. "
        "Includes the 00000 State Summary aggregate as ccddd=0."
    ),
    "fields": [
        {
            "name": "fiscal_state_institutions_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "institution_name",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Institution name, derived from the leaf filename's middle "
                "segment (`{ccddd} <name> 1191SI`). The body of the PDF "
                "uses several different formats across years for this info "
                "(`X served by Y (ccddd)`, `CCDDD ALL CAPS NAME`, just the "
                "summary title) so the filename is more reliable. Free "
                "text; not a canonical FK."
            ),
        },
        {
            "name": "revenue_account",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Revenue account code printed in the header (e.g. '4159'). "
                "Older state-summary files combine multiple accounts in one "
                "PDF and print them joined with '&' (e.g. '4156&4126&4159&34'). "
                "For the per-year state summary, this can also be the literal "
                "string 'State Summary' if no account list is given."
            ),
        },
        {
            "name": "allocation_status",
            "field_type": "string",
            "doc": (
                "Header status word -- 'Initial', 'Revised', or '' if "
                "neither was printed. Initial reports are pre-fiscal-year "
                "projections; Revised reports post-date the school year."
            ),
        },
        {
            "name": "section_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Section letter on the form (A through M).",
        },
        {
            "name": "section_seq",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "1 for the first appearance of `section_code` in the document, "
                "2 for the second, etc. Form 1191SI prints two 'K' sections "
                "(page 1 = Total Allocation, page 2 = Year-End Adjustment)."
            ),
        },
        {
            "name": "section_title",
            "field_type": "string",
            "doc": "Section title printed on the form (e.g. 'TOTAL 2024-25 ALLOCATION').",
        },
        {
            "name": "item_path",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Item identifier within the section as printed: '1', '2', "
                "'1.A', '1.B', etc. The form uses single-digit numbers at "
                "the top level and letter sub-numbering in Section E."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Full item label as printed in the PDF (whitespace "
                "normalized). Cross-year mapping to canonical concepts is "
                "deferred to a future domain table; for now, join on "
                "lowercased / stripped label for multi-year analyses."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL if the PDF printed 'N/A', '-', or "
                "the field was missing (e.g. per-institution files have empty "
                "page-2 carryover sections)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": (
                "Raw value text as printed in the PDF before numeric parsing. "
                "Lets consumers distinguish '0.00' from '-' from 'N/A' if "
                "the `value` NULL doesn't carry enough information."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "revenue_account", "institution_name",
        "section_code", "section_seq", "item_path",
    ]],
}


ALL_SCHEMAS = [FISCAL_STATE_INSTITUTIONS]
