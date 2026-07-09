#!python3
"""Walk data/fiscal/fiscal/, parse the three Data Requirements
sub-reports of each F-196 All Pages PDF.

Populates `fiscal_f196_data_requirements` -- OSPI Data Requirements
items per district per year (Supplemental Reports p 66, Apportionment
Recovery p 67, Federal Indirect Cost Data pp 68-71).

Usage:
    python3 -m extractors.fiscal.extract_f196_data_requirements \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_data_requirements.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "report_kind", "section", "item_code",
    "item_label", "value_text", "value",
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
        parse_fn_module="extractors.fiscal.parsers.f196_data_requirements",
        parse_fn_name="parse_f196_data_requirements_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
