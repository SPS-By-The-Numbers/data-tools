#!python3
"""Walk data/fiscal/fiscal/, parse the Federal Restricted / Unrestricted
Indirect Cost Rate Schedule sub-reports of each F-196 All Pages PDF.

Populates `fiscal_f196_indirect_rate` -- 14-line rate calculation per
district per year, both Restricted and Unrestricted flavors. The
calculated rate (line 14) is the primary analytical output.

Usage:
    python3 -m extractors.fiscal.extract_f196_indirect_rate \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_indirect_rate.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "rate_kind", "line_number", "line_label", "value",
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
        parse_fn_module="extractors.fiscal.parsers.f196_indirect_rate",
        parse_fn_name="parse_f196_indirect_rate_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
