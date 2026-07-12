"""Schema for the `fiscal_f195_program_summary_by_object` fact table.

Source: `PROGRAM SUMMARY BY OBJECT OF EXPENDITURE` sub-report (GF9)
of OSPI Form F-195 Budget. General-Fund per-program per-OSPI-object
budgeted expenditure cross-tab. Complements
`fiscal_f195_budget[expenditure_by_program]` (which shows the
per-program total) by breaking each program's General-Fund total
into 9 object-code buckets plus a per-row Total column.

Layout per page (2-4 pages per file):

  Column headers (3 lines):
      Total (0) (1) (2) (3) (4) (5) (7) (8) (9)
      Object Debit Credit Cert. Class. Employee Supplies/ Purchased Travel Capital
      Program Transfer Transfer Salaries Salaries Benefits Materials Services Outlay

  Per-program rows: `<code> | <label> <total> <val0> <val1> ... <val9>`
  Per-group TOTAL rows: `TOTAL <group> <total> <val0> ... <val9>`

Section groups match `fiscal_f195_budget[expenditure_by_program]`
(GF8): regular_instruction / federal_special_purpose / special_
education_instruction / vocational_instruction / skill_center_
instruction / compensatory_education / other_instructional_programs /
community_services / support_services, plus `summary` for per-group
TOTAL rows and the grand TOTAL PROGRAM EXPENDITURES row.

Note that object code 6 is deliberately skipped in the form -- the 9
object columns are (0, 1, 2, 3, 4, 5, 7, 8, 9).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_PROGRAM_SUMMARY_BY_OBJECT = {
    "name": "fiscal_f195_program_summary_by_object",
    "doc": (
        "Per-district per-program budgeted General-Fund expenditures "
        "broken out by OSPI object code (0-9, skipping 6) plus a row "
        "total, from OSPI Form F-195 Budget sub-report GF9. The "
        "current-year budget slice of the cross-tab; consumers "
        "wanting the actuals should join to "
        "fiscal_f196_program_activity_object[breakdown_kind='program'] "
        "for the totals and fiscal_f196_program_activity_object"
        "[breakdown_kind='object'] for the object-code totals."
    ),
    "fields": [
        {
            "name": "fiscal_f195_program_summary_by_object_id",
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
                "`fiscal_f195_budget[expenditure_by_program]`): "
                "`regular_instruction`, `federal_special_purpose`, "
                "`federal_stimulus` (2013-14 through ~2019-20 form "
                "vintage), `special_education_instruction`, "
                "`vocational_instruction`, `skill_center_instruction`, "
                "`compensatory_education`, `other_instructional_"
                "programs`, `community_services`, `support_services`, "
                "or `summary` (per-group TOTAL rows and the grand "
                "`TOTAL PROGRAM EXPENDITURES` row)."
            ),
        },
        {
            "name": "program_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit program code as printed (`01`, `21`, "
                "`79`, `97`, ...). Per-group TOTAL rows carry the "
                "group's total code (`00`, `10`, `20`, `30`, `40`, "
                "`50 and 60`, `70`, `80`, `90`). The grand-total row "
                "uses the slug `total_program_expenditures`."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the per-group TOTAL rows and the grand "
                "TOTAL PROGRAM EXPENDITURES row."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Program label as printed (whitespace normalized). "
                "Multi-line labels are joined."
            ),
        },
        {
            "name": "object_total",
            "field_type": "decimal",
            "doc": (
                "`Total Object Program` -- sum of the 9 object "
                "columns. Should equal the same program's row in "
                "`fiscal_f195_budget[expenditure_by_program]` for the "
                "current year."
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
        "school_year", "ccddd", "section", "program_code",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_PROGRAM_SUMMARY_BY_OBJECT]
