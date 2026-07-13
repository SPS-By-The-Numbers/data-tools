#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget PDF's Salary
Exhibit sub-reports (GF9-201-XX, GF9-301-XX, CP-7, CP-8).

Usage:
    python3 -m extractors.fiscal.extract_f195_salary_exhibits \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_salary_exhibits.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "exhibit_kind", "fund", "program_code", "activity_code", "duty_code",
    "row_kind", "program_label", "title_of_position",
    "fte", "number_of_hours",
    "high_rate", "low_rate", "avg_rate",
    "total_annual_salary", "state_annual_salary", "local_annual_salary",
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
        parse_fn_module="extractors.fiscal.parsers.f195_salary_exhibits",
        parse_fn_name="parse_f195_salary_exhibits_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
