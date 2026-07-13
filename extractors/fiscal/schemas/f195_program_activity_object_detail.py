"""Schema for the `fiscal_f195_program_activity_object_detail` fact table.

Source: `OBJECTS OF EXPENDITURE` per-program sub-report (GF9-XX) of
OSPI Form F-195 Budget. One page per General Fund program (rows 25
onward on 2024-25 vintage, rows 23 onward on 2013-14 vintage), each
page presenting the same 10-column Activity x Object cross-tab:

  Column headers (3 lines):
      Activity Total (0) (1) (2) (3) (4) (5) (7) (8) (9)
                     Debit Credit Cert. Class. Employee Supplies/ Purchased Travel Capital
                     Transfer Transfer Salaries Salaries Benefits Materials Services Outlay

  Per-activity rows: `NN <activity-name> <total> <val0> ... <val9>`
  Program subtotal:  `Total <total> <val0> ... <val9>`
  Program FTE row:   `FTE Program Staff <cert-fte> <class-fte>`

This is the BUDGET side of the (program, activity, object) grid --
pairs with `fiscal_f196_program_activity_object_detail` (actuals). The
column definitions match `fiscal_f195_program_summary_by_object` (GF9
summary; per-program totals only, no activity breakout).

Object code 6 is deliberately skipped in the OSPI object list; the 9
object columns are (0, 1, 2, 3, 4, 5, 7, 8, 9). Column values are
integer dollars in F-195 Budget (not decimal cents).

Identity checks:
  - Per-program: sum of `row_kind='detail'` for a given `program_code`
    on each numeric column equals the corresponding `program_total`
    row value.
  - Cross-check against `fiscal_f195_program_summary_by_object`:
    the `program_total` row's per-object values here equal that
    program's row in `fiscal_f195_program_summary_by_object`.
  - Cross-check against `fiscal_f195_staff_by_activity` (GF15):
    `fte_cert` on `row_kind='fte_program_staff'` equals the sum of
    the (program, cert) FTE breakdown in fiscal_f195_staff_by_activity
    for the same program.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_PROGRAM_ACTIVITY_OBJECT_DETAIL = {
    "name": "fiscal_f195_program_activity_object_detail",
    "doc": (
        "Per-district per-(program, activity, object) budgeted "
        "General-Fund expenditure detail from OSPI Form F-195 Budget "
        "sub-report GF9-XX (one page per program, Activity x Object "
        "cross-tab). Pairs with fiscal_f196_program_activity_object_"
        "detail (actuals) to enable budget-vs-actuals analysis at the "
        "deepest breakdown available in the corpus. The paired "
        "fiscal_f195_program_summary_by_object provides the same "
        "per-program per-object slice without the activity dimension."
    ),
    "fields": [
        {
            "name": "fiscal_f195_program_activity_object_detail_id",
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
                "`fiscal_f195_program_summary_by_object`): "
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
                "<name>` banner at the top of each GF9-XX page."
            ),
        },
        {
            "name": "activity_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit activity code (`21` Supv Inst, `22` Lrn "
                "Resrc, `27` Teaching, `28` Extracur, ...). Empty "
                "string on `row_kind='program_total'` and "
                "`row_kind='fte_program_staff'` rows."
            ),
        },
        {
            "name": "row_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "`detail` (per-activity money row), `program_total` "
                "(the `Total` subtotal at the bottom of the program "
                "page), or `fte_program_staff` (the `FTE Program "
                "Staff` row carrying certificated and classified FTE "
                "totals for the program)."
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
                "subtotal / total rows."
            ),
        },
        {
            "name": "activity_total",
            "field_type": "decimal",
            "doc": (
                "`Activity Total` -- sum of the 9 object columns for "
                "this activity within this program. Budgeted dollars "
                "(integer)."
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
        {
            "name": "fte_cert",
            "field_type": "decimal",
            "doc": (
                "Certificated FTE. Populated only on "
                "`row_kind='fte_program_staff'` (from the `FTE Program "
                "Staff` row); NULL on detail and program_total rows."
            ),
        },
        {
            "name": "fte_class",
            "field_type": "decimal",
            "doc": (
                "Classified FTE. Populated only on "
                "`row_kind='fte_program_staff'`; NULL elsewhere."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "program_code", "row_kind", "activity_code",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_PROGRAM_ACTIVITY_OBJECT_DETAIL]
