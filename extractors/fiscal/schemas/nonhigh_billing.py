"""Schema for the `fiscal_nonhigh_billing` fact table.

Source: OSPI Report F-483 "Nonhigh Billing Summary". One short PDF per
(school year, district), filed in two flavors:

  - **F-483N** -- "Nonhigh District" point of view. The focal district
    is a nonhigh (K-8 / K-6) district that sends students to one or
    more serving high districts. The report enumerates each serving
    high district as a counterparty and computes the amount the focal
    nonhigh district owes each one.
  - **F-483H** -- "Serving High District" point of view. The focal
    district receives students from one or more nonhigh districts. The
    report enumerates each sending nonhigh district as a counterparty
    and computes the amount each one owes the focal.

Form layout drifted at the 2019-20 statutory rewrite (RCW 28A.545.030
added the "lesser of either rate" clause). Both layouts are captured in
the same long-form schema:

  - section = `levy_per_aafte` -- the per-district levy / AAFTE
    calculation (form columns A-E). In the post-2019 form this is
    emitted twice per file: once for the focal district, once per
    counterparty. In the pre-2019 F-483H form, only the focal high
    district has levy items (the counterparty nonhigh districts
    don't). In the pre-2019 F-483N form, each serving high
    counterparty has its own levy items (the focal nonhigh district
    has none).
  - section = `payable` -- the per-edge payable / billing calculation
    (form columns F-I in the pre-2019 form, F-J in the post-2019 form).
    One row per (counterparty_district, item_code) for each item the
    form prints. INITIAL reports (2025-26) omit column J because the
    November payment hasn't happened yet.
  - section = `payable_total` -- the Total row printed at the bottom of
    the payable section. Counterparty fields are blank; `item_code` is
    the column letter being totaled.

Logical key: (school_year, ccddd, status, section, subject_role,
subject_ccddd, item_code).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_NONHIGH_BILLING = {
    "name": "fiscal_nonhigh_billing",
    "doc": (
        "Long-form per-line-item capture of OSPI Form F-483 Nonhigh "
        "Billing Summary. Captures the levy-per-AAFTE calculation block "
        "and the per-counterparty payable block from both the F-483N "
        "(nonhigh district POV) and F-483H (serving high district POV) "
        "variants. Pre-2019 and post-2019 form layouts share the same "
        "long-form shape; see CSV_GUIDE.md for the section / item_code "
        "semantics that differ between them."
    ),
    "fields": [
        {
            "name": "fiscal_nonhigh_billing_id",
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
                "'f483n' (focal district is the nonhigh district -- the "
                "sender) or 'f483h' (focal district is the serving high "
                "district -- the receiver). Determined from the printed "
                "report number (REPORT F-483N vs REPORT F-483H), which "
                "also matches the header line ('NON HIGH DISTRICT:' vs "
                "'SERVING HIGH DISTRICT:')."
            ),
        },
        {
            "name": "status",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'Initial' (published in spring of the school year, before "
                "the November payment lands) or 'Final' (published in fall "
                "after the school year ends, with November payment "
                "settled). Most years publish only Final; 2025-26 in this "
                "corpus is entirely Initial. INITIAL files omit column J."
            ),
        },
        {
            "name": "form_variant",
            "field_type": "string",
            "doc": (
                "'pre_2019' (2013-14 through 2018-19 source years) or "
                "'post_2019' (2019-20 onwards). OSPI restructured the "
                "form when RCW 28A.545.030 added the 'lesser of either "
                "rate' provision: column letters got reassigned (e.g. "
                "the levy in dollars moved from column A to column D), "
                "and a per-counterparty levy sub-table was added. "
                "`item_code` carries the semantic name so cross-variant "
                "joins don't need this column; it's here for traceability."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'levy_per_aafte' | 'payable' | 'payable_total'. See "
                "CSV_GUIDE.md for how each section maps onto the pre- vs "
                "post-2019 form layouts."
            ),
        },
        {
            "name": "subject_role",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'nonhigh' or 'high' -- which side of the equation the "
                "`subject_ccddd` district represents. Empty for "
                "'payable_total' rows (which aggregate across "
                "counterparties)."
            ),
        },
        {
            "name": "subject_ccddd",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "CCDDD of the district whose data this row carries. For "
                "section='levy_per_aafte' this is either the focal "
                "district (= the file's `ccddd`) or one of the "
                "counterparty districts. For section='payable' this is "
                "always the counterparty (the focal is implicit, = the "
                "file's `ccddd`). 0 for 'payable_total' rows."
            ),
        },
        {
            "name": "subject_name",
            "field_type": "string",
            "doc": (
                "District name as printed on the form (e.g. 'WALLA WALLA', "
                "'EVERGREEN (CLARK)'). Free text -- not a canonical FK."
            ),
        },
        {
            "name": "is_focal",
            "field_type": "boolean",
            "doc": (
                "True if `subject_ccddd` equals the file's focal `ccddd`. "
                "Lets consumers separate the focal district's own row "
                "from counterparty rows without a self-join."
            ),
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Column letter as printed on the form: 'A' through 'E' "
                "for levy_per_aafte items, 'F' through 'J' for payable "
                "/ payable_total items. Letter semantics differ between "
                "pre-2019 and post-2019 form layouts -- see "
                "CSV_GUIDE.md."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Short canonical label for the column (e.g. "
                "'reported_resident_aafte', 'payable_levy', "
                "'levy_per_resident_aafte', 'sending_nonhigh_aafte', "
                "'total_school_year_payable_amount')."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Parsed numeric value. Dollar amounts, AAFTE counts, and "
                "rates all share this column. Parenthesized negatives "
                "(common on column C 'Nonhigh AAFTE' rows from a serving "
                "high district's POV) parse to negative decimals."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "status", "section",
                "subject_role", "subject_ccddd", "item_code"]],
}


ALL_SCHEMAS = [FISCAL_NONHIGH_BILLING]
