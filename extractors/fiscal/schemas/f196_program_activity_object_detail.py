"""Schema for the `fiscal_f196_program_activity_object_detail` fact table.

Source: F-196 All Pages per-PROGRAM Activity x Object cross-tab
sub-report (pp ~33-65 typical, ~33 pages per file). One page per
General Fund program, each page presenting the same 10-column
Activity x Object cross-tab:

  Column headers (3 lines):
      Activity Total (0) (1) (2) (3) (4) (5) (7) (8) (9)
                     Debit Credit Cert. Class. Employee Supplies/ Purchased Travel Capital
                     Transfer Transfer Salaries Salaries Benefits Materials Services Outlay

  Per-activity rows: `NN <activity-name> <total> <val0> ... <val9>`
  Program subtotal:  `NN Total <total> <val0> ... <val9>` (NN = program code)

This is the ACTUALS side of the (program, activity, object) grid --
pairs with `fiscal_f195_program_activity_object_detail` (budget). The
column definitions match `fiscal_f196_program_activity_object` (the
per-program / per-activity / per-object roll-up summary; no
per-program-per-activity cross-tab there).

Object code 6 is deliberately skipped in the OSPI object list; the 9
object columns are (0, 1, 2, 3, 4, 5, 7, 8, 9). Column values are
decimal dollars-and-cents in F-196 (not integer as in F-195 Budget).

Identity checks:
  - Per-program: sum of `row_kind='detail'` for a given `program_code`
    on each numeric column equals the corresponding `program_total`
    row value.
  - Cross-check against `fiscal_f196_program_activity_object[
    breakdown_kind='program']`: the `program_total.activity_total`
    equals that program's `value` in the program-breakdown roll-up.
  - Cross-check against `fiscal_f196_program_activity_object[
    breakdown_kind='object']`: sum of the per-object columns across
    all program_total rows equals the object-breakdown roll-up.

Wrap-tail handling: Seattle-scale programs (~$500M General Fund) have
10-figure values (e.g. `489,664,037.00`) that overflow the column
width and wrap the trailing 1-2 digits to the next visual line. The
parser merges wrap-tails using the same pattern as
`fiscal_f195_salary_exhibits` and `fiscal_f196_all_pages` parsers.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_PROGRAM_ACTIVITY_OBJECT_DETAIL = {
    "name": "fiscal_f196_program_activity_object_detail",
    "doc": (
        "Per-district per-(program, activity, object) actual General-"
        "Fund expenditure detail from OSPI Form F-196 All Pages "
        "per-PROGRAM cross-tab sub-report. Pairs with fiscal_f195_"
        "program_activity_object_detail (budget) to enable budget-vs-"
        "actuals analysis at the deepest breakdown available in the "
        "corpus. The pre-existing fiscal_f196_program_activity_object "
        "provides the same per-program / per-activity / per-object "
        "roll-up totals without the (program x activity) cross-tab."
    ),
    "fields": [
        {
            "name": "fiscal_f196_program_activity_object_detail_id",
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
                "OSPI program group slug (matches "
                "`fiscal_f195_program_summary_by_object` and "
                "`fiscal_f195_program_activity_object_detail`): "
                "`regular_instruction`, `federal_special_purpose`, "
                "`special_education_instruction`, "
                "`vocational_instruction`, `skill_center_instruction`, "
                "`compensatory_education`, `other_instructional_"
                "programs`, `community_services`, `support_services`, "
                "or `unknown` for program codes not in the mapping."
            ),
        },
        {
            "name": "program_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit program code as printed (`01`, `21`, "
                "`79`, `97`, ...). Parsed from the `PROGRAM XX - "
                "<name>` banner at the top of each per-PROGRAM page."
            ),
        },
        {
            "name": "activity_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit activity code (`21` Supv Inst, `22` Lrn "
                "Resrc, `27` Teaching, `28` Extracur, ...). Empty "
                "string on `row_kind='program_total'` rows."
            ),
        },
        {
            "name": "row_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "`detail` (per-activity money row) or `program_total` "
                "(the `NN Total` subtotal at the bottom of the "
                "program page, where NN is the program code)."
            ),
        },
        {
            "name": "program_label",
            "field_type": "string",
            "doc": (
                "Program label as printed on the PROGRAM banner "
                "(e.g. `Basic Education`, `Special Education, "
                "Supplemental, State`). Whitespace normalized. "
                "Labels drift across vintages -- use `program_code` "
                "for cross-year joins."
            ),
        },
        {
            "name": "activity_label",
            "field_type": "string",
            "doc": (
                "Activity name as printed on the detail row "
                "(`Supv Inst`, `Lrn Resrc`, `Teaching`, `Extracur`, "
                "...). Whitespace normalized. Empty string on "
                "program_total rows."
            ),
        },
        {
            "name": "activity_total",
            "field_type": "decimal",
            "doc": (
                "`Activity Total` -- sum of the 9 object columns for "
                "this activity within this program. Actual dollars-"
                "and-cents (decimal)."
            ),
        },
        {
            "name": "object_0_debit_transfer",
            "field_type": "decimal",
            "doc": "Object 0 -- Debit Transfer (inter-program cost transfer, positive).",
        },
        {
            "name": "object_1_credit_transfer",
            "field_type": "decimal",
            "doc": "Object 1 -- Credit Transfer (inter-program cost transfer, negative offset).",
        },
        {
            "name": "object_2_cert_salaries",
            "field_type": "decimal",
            "doc": "Object 2 -- Certificated Salaries.",
        },
        {
            "name": "object_3_class_salaries",
            "field_type": "decimal",
            "doc": "Object 3 -- Classified Salaries.",
        },
        {
            "name": "object_4_employee_benefits",
            "field_type": "decimal",
            "doc": "Object 4 -- Employee Benefits (and Payroll Taxes).",
        },
        {
            "name": "object_5_supplies_materials",
            "field_type": "decimal",
            "doc": "Object 5 -- Supplies / Materials (Non-Capital).",
        },
        {
            "name": "object_7_purchased_services",
            "field_type": "decimal",
            "doc": "Object 7 -- Purchased Services. (Object 6 is unused in the OSPI object list.)",
        },
        {
            "name": "object_8_travel",
            "field_type": "decimal",
            "doc": "Object 8 -- Travel.",
        },
        {
            "name": "object_9_capital_outlay",
            "field_type": "decimal",
            "doc": "Object 9 -- Capital Outlay.",
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "program_code", "row_kind", "activity_code",
    ]],
}


ALL_SCHEMAS = [FISCAL_F196_PROGRAM_ACTIVITY_OBJECT_DETAIL]
