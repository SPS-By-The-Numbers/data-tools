#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget PDF's `PROGRAM
SUMMARY BY OBJECT OF EXPENDITURE` sub-report (GF9).

Usage:
    python3 -m extractors.fiscal.extract_f195_program_summary_by_object \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_program_summary_by_object.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "program_code", "is_total", "item_label",
    "object_total",
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
    for p in sorted(root.rglob("F-195 Budget.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_program_summary_by_object",
        parse_fn_name="parse_f195_program_summary_by_object_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
