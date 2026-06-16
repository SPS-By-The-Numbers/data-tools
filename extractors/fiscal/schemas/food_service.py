"""Schema for the `fiscal_food_service` fact table.

Source: OSPI Report 1800SUM, "Food Service Program - Summary of Results of
Operations" -- one single-page PDF per district per school year (kept under
`data/fiscal/fiscal/{year}/{ccddd}_{slug}/Food Service Program Summary.pdf`
post-reorg). The form has been stable across the 2013-14 -> 2024-25 corpus
modulo an extra subheader line ("Annual Net Balance Carryover (Deficit) /
New Balances") added in 2018-19.

Long-form: one row per (school_year, ccddd, section, item_code, subkey).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_FOOD_SERVICE = {
    "name": "fiscal_food_service",
    "doc": (
        "Long-form per-line-item capture of OSPI Report 1800SUM "
        "(Food Service Program Summary). One row per item printed on "
        "the form."
    ),
    "fields": [
        {
            "name": "fiscal_food_service_id",
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
                "Section the line item belongs to: 'revenues', "
                "'expenditures', 'indirect', 'summary', or 'carryforward'."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Canonical snake_case identifier for the line item. "
                "Stable across years."
            ),
        },
        {
            "name": "subkey",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Disambiguator within an item_code. For Expenditures: "
                "'direct' / 'object1_alloc' / 'net'. For carryforward "
                "annual balances: the data school year as YYYY-YYYY. "
                "Empty string otherwise."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": "Full label as printed on the PDF (whitespace normalized).",
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. NULL when the PDF printed '-' or "
                "the cell was empty. Percentages (indirect rate) are stored "
                "as the printed number (e.g. 18.16 means 18.16%)."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing (lets consumers distinguish '-' / 'N/A' / '0.00').",
        },
        {
            "name": "is_indirect_calc",
            "field_type": "boolean",
            "doc": (
                "True when the row was marked with `*` on the form "
                "(included in the indirect cost calculation per the "
                "footnote). Applies only to expenditure rows."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "item_code", "subkey"]],
}


ALL_SCHEMAS = [FISCAL_FOOD_SERVICE]
