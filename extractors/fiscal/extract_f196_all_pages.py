#!python3
"""Walk data/fiscal/fiscal/, parse the SUMMARY block (page 2) of each
F-196 All Pages PDF.

Populates `fiscal_f196_summary` -- same logical schema as the standalone
F-196 Summary doc used to. The All Pages corpus covers 2013-14 through
2024-25 (3,724 files), so this driver replaces the standalone F-196
Summary parser and extends backward coverage to 2013-14.

Usage:
    python3 -m extractors.fiscal.extract_f196_all_pages data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_f196_summary.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "item_code", "fund",
    "item_label", "value", "value_text",
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
        parse_fn_module="extractors.fiscal.parsers.f196_all_pages",
        parse_fn_name="parse_f196_all_pages_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
