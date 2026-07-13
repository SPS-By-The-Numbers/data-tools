#!python3
"""Walk data/fiscal/fiscal/, parse each F-196 All Pages PDF's per-PROGRAM
Activity x Object cross-tab sub-report.

Usage:
    python3 -m extractors.fiscal.extract_f196_program_activity_object_detail \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_program_activity_object_detail.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "program_code", "activity_code", "row_kind",
    "program_label", "activity_label",
    "activity_total",
    "object_0_debit_transfer", "object_1_credit_transfer",
    "object_2_cert_salaries", "object_3_class_salaries",
    "object_4_employee_benefits", "object_5_supplies_materials",
    "object_7_purchased_services", "object_8_travel",
    "object_9_capital_outlay",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-196 All Pages.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f196_program_activity_object_detail",
        parse_fn_name="parse_f196_program_activity_object_detail_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
