"""Schema for the `fiscal_1220_sped_transfer` fact table.

Source: OSPI Report 1220TR SPECIAL EDUCATION TRANSFER OF ALLOCATION,
the ESD-level companion to Report 1220 (`fiscal_1220_sped`). Published
2013-14 through 2016-17 only.

Each 1-page report shows the ESD's member districts and how their three
special-education-related state allocations (Accounts 3121, 4121, 4122)
were transferred through the ESD. One report per (ESD, school_year).
In the raw corpus, the same PDF is replicated under every member
district subdir (~30 dups per ESD-year); consumers should dedup on
(school_year, esd_code).

Row kinds captured:

  - `detail` (~30 rows per ESD-year): per member district transfer
    amounts. member_ccddd + district_name populated.
  - `total_transferred` (1 row): sum of detail amounts, per account.
  - `safety_net` (1 row): the printed SAFETY NET amount (only Account
    4121 is populated; the other two are NULL).
  - `grand_total` (1 row): the printed GRAND TOTAL. Some vintages
    (2013-14) print 3 grand totals (one per account); most vintages
    print a single grand total in the Account 4121 column.

**The unique analytical contribution** is the ESD's role as a
pass-through: the ESD receives the state's per-district allocation and
transfers it to the member district. `fiscal_1220_sped_transfer` +
`fiscal_1220_sped` together let you audit that flow for the years the
report existed.
"""

from .common import AUDIT_FIELDS


FISCAL_1220_SPED_TRANSFER = {
    "name": "fiscal_1220_sped_transfer",
    "doc": (
        "Per-ESD per-member-district transfer of Special Education "
        "allocations (Accounts 3121 / 4121 / 4122) from OSPI Report "
        "1220TR. Coverage: 2013-14 through 2016-17 (~30 unique ESD-year "
        "reports; each replicated under all member district subdirs "
        "in the raw corpus)."
    ),
    "fields": [
        {
            "name": "fiscal_1220_sped_transfer_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
        {
            "name": "school_year",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "OSPI-format school year, e.g. '2015-2016'.",
        },
        {
            "name": "class_of",
            "field_type": "int",
            "doc": "End-year of the school year (int), e.g. 2016.",
        },
        {
            "name": "esd_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "5-digit CCDDD-style code for the ESD, e.g. '06801' "
                "for ESD 112. Parsed from the banner line."
            ),
        },
        {
            "name": "esd_number",
            "field_type": "string",
            "doc": "ESD number label as printed, e.g. '112'.",
        },
        {
            "name": "row_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'detail' (per member district), 'total_transferred', "
                "'safety_net', or 'grand_total'."
            ),
        },
        {
            "name": "member_ccddd",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "For row_kind='detail': 5-digit CCDDD of the receiving "
                "member district. For summary rows: sentinel '00000'."
            ),
        },
        {
            "name": "member_name",
            "field_type": "string",
            "doc": (
                "Member district name as printed. Empty on summary "
                "rows. Labels drift across years -- join on "
                "member_ccddd for cross-year queries."
            ),
        },
        {
            "name": "acct_3121_special_ed_general_app",
            "field_type": "decimal",
            "doc": (
                "Account 3121 Special Education General "
                "Apportionment Allocation transferred (dollars)."
            ),
        },
        {
            "name": "acct_4121_special_education",
            "field_type": "decimal",
            "doc": (
                "Account 4121 Special Education Allocation "
                "transferred (dollars)."
            ),
        },
        {
            "name": "acct_4122_special_ed_infants",
            "field_type": "decimal",
            "doc": (
                "Account 4122 Special Education Infants Allocation "
                "transferred (dollars). Also known as 'Special Ed "
                "Infants & Toddlers' in some vintages."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "esd_code", "row_kind", "member_ccddd"]],
}


ALL_SCHEMAS = [FISCAL_1220_SPED_TRANSFER]
