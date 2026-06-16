#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget Overview PDF (page 1).

Usage:
    python3 -m extractors.fiscal.extract_f195_overview data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_f195_overview.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "item_code", "fund",
    "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-195 Budget Overview.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_overview",
        parse_fn_name="parse_f195_overview_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
