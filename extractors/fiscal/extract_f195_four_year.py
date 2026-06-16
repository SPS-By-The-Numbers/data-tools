#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Four-year Budget Summary Plan PDF.

Usage:
    python3 -m extractors.fiscal.extract_f195_four_year data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_f195_four_year.csv

Use --workers N to set parallelism (default: ncpu-1).
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "section", "item_code",
    "data_year_offset", "data_school_year", "data_class_of",
    "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-195 Four-year Budget Summary Plan.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_four_year",
        parse_fn_name="parse_f195_four_year_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
