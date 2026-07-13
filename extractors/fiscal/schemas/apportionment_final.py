"""Schema for the `fiscal_apportionment_final` fact table.

Source: OSPI Report 1191F Estimated Funding Report (Final), file leaf
"Final Apportionment Summary.pdf" under
`apportionment/YYYY-YYYY/district/{ccddd}_{slug}/`. One file per
district per year, ~3,732 files across 2013-14 through 2024-25.

The 1191F is a compound doc (~50-60 pages) containing per-Account
derivation of the district's final year-end apportionment: how the
General Apportionment (3100), Special Education (4121), Special Ed
Infants (4122), Food Service (4198/419801), Transportation (4199/4499),
and various pass-throughs (TBIP, LAP, Highly Capable, etc.) are
computed from staff mix, staffing units, salary bases, and per-pupil
formulas.

**This parser is HEADLINE-ONLY.** Rather than parse every intermediate
computation across all 60 pages, we capture the section banners
(`Apportionment Final Account XXXX`) plus the printed **final total
lines** per section: "Total Amount to be Paid Sept. YYYY - Aug. YYYY
in Account 3100 $", "Total Amount Due $" per non-3100 account,
"Calculated Allotment $" per sub-program, "Total Allocation for
Special Education Program 21 $", etc. These are the numbers analysts
actually use; the derivation detail is available in the source PDF
for anyone who needs to audit a specific district's calculation.

Long-form: one row per (source, account_code, item_ordinal). Multiple
rows per file, keyed by their positional appearance in the source PDF.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_APPORTIONMENT_FINAL = {
    "name": "fiscal_apportionment_final",
    "doc": (
        "Per-district year-end final apportionment totals per Account "
        "from OSPI Report 1191F Estimated Funding Report (Final). "
        "Headline totals only -- the intermediate per-item derivation "
        "captured in the 60-page source PDF is NOT parsed. 2013-14 "
        "through 2024-25 (~3,732 files)."
    ),
    "fields": [
        {
            "name": "fiscal_apportionment_final_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "sub_report",
            "field_type": "string",
            "doc": (
                "Sub-report code as printed near the top of each "
                "page banner: '1191F' (main 3100 flow), '1191EEF' "
                "(Elementary), '1191MSCTEF' (MS CTE), '1191SCF' "
                "(Skill Center), '1191FSF' (Food Service), '1191SEF' "
                "(Special Education), '1191TRNF' (Transportation), "
                "'1191CTER' (CTE Indirect Cost Recovery). Blank when "
                "the sub-report is inferred from a plain '1191F' "
                "header."
            ),
        },
        {
            "name": "account_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI revenue account: '3100' (general apportionment), "
                "'3121' (SpEd General App), '4121' (SpEd), '4122' "
                "(SpEd Infants), '4165' (TBIP), '4174' (LAP), "
                "'4198' (School Lunch), '4199' (Transportation "
                "Operations), '4499' (Transportation Depreciation), "
                "'419801' (Free & Reduced Breakfasts), etc. Parsed "
                "from 'Apportionment Final Account XXXX' banners. "
                "Empty string when the total line lives outside a "
                "known banner scope."
            ),
        },
        {
            "name": "item_ordinal",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Positional order of this total line within its "
                "(source, account_code) group. Zero-indexed. Some "
                "accounts have multiple sub-totals (Calculated "
                "Allotment / Total Amount Due) so a single positional "
                "index keeps them stable."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Examples: "
                "'10. Total Amount to be Paid Sept. 2018 - Aug. 2019 "
                "in Account 3100', 'D. Calculated Allotment', "
                "'F. Total Amount Due', 'Total Allocation for Special "
                "Education Program 21'."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Dollar amount printed at the end of the label line."
            ),
        },
        {
            "name": "page_number",
            "field_type": "int",
            "doc": (
                "1-indexed page number in the source PDF where the "
                "line was found. Useful for cross-reference to the "
                "source doc."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "account_code", "item_ordinal"]],
}


ALL_SCHEMAS = [FISCAL_APPORTIONMENT_FINAL]
