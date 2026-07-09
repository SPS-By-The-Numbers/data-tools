"""Schema for the `fiscal_f196_data_requirements` fact table.

Combined source: three OSPI Data Requirements sub-reports on F-196
All Pages PDFs:

  - **Data Requirements for Supplemental Reports** (p 66) --
    items lettered A through G. Captures E-Rate, impact fees,
    mitigation fees, LAP breakdowns, and the Inflationary Adjustment
    Index certification.
  - **Data Requirements for End of Year Reporting to Apportionment
    and State Recovery Rate** (p 67) -- items 1 (Fire District
    Payment) and 2 (Indirect Rate for State Revenue Recoveries),
    the latter with sub-items a/b/c.
  - **Data Requirements for Calculating Federal Indirect Cost Rate
    Including Fixed with Carry-Forward** (pp 68-71) -- items 1
    through ~33 grouped into DISTORTING ITEMS + INDIRECT
    EXPENDITURES sections. Input data for the Restricted /
    Unrestricted rate calculations on pp 72-75.

**The unique analytical contribution is the district-input dimension**
that feeds the indirect cost rate calculations and the state
recovery rate. Consumers reproducing rate calculations from
`fiscal_f196_indirect_rate` need these input items.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_DATA_REQUIREMENTS = {
    "name": "fiscal_f196_data_requirements",
    "doc": (
        "OSPI Data Requirements items per district per year -- input "
        "data OSPI collects on each F-196 filing for supplementary "
        "reporting, apportionment reconciliation, and federal indirect "
        "cost rate calculations. Covers 2013-14 through 2024-25 "
        "(3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_data_requirements_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "report_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "One of 'supplemental_reports' (p 66), "
                "'apportionment_recovery' (p 67), "
                "'federal_indirect_cost_data' (pp 68-71). "
                "Distinguishes which sub-report the item is from."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "For report_kind='federal_indirect_cost_data': "
                "'distorting_items' (items 1-18 typical) or "
                "'indirect_expenditures' (items 19-33 typical). "
                "Empty string for the other two report kinds."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Item identifier: 'A' through 'G' on Supplemental "
                "Reports; '1' or '2' plus optional 'a'/'b'/'c' on "
                "Apportionment Recovery; '1' through '33+' on Federal "
                "Indirect Cost Data. Positional and stable across "
                "years for a given (report_kind, section) group."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Description as printed (multi-line joined, "
                "whitespace normalized). Truncated to ~250 chars for "
                "readability. Consumers wanting the full text should "
                "read the source PDF."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": (
                "Raw printed value. May be numeric ('154,902.18', "
                "'0.1489') or textual ('Yes' / 'No' on the "
                "Inflationary Adjustment Index certification)."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Numeric value parsed from value_text. NULL when the "
                "printed value is textual (e.g. 'Yes'/'No') or "
                "blank."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "report_kind", "section", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_F196_DATA_REQUIREMENTS]
