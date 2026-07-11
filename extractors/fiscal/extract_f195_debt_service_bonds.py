#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget PDF's
`DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS` sub-report
(DS4).

F-195 Budget Overview does NOT contain DS4, so this walker parses
the Budget PDF only.

Usage:
    python3 -m extractors.fiscal.extract_f195_debt_service_bonds \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_debt_service_bonds.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "item_seq", "is_total",
    "date_of_issue", "amount_original", "amount_outstanding",
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
        parse_fn_module="extractors.fiscal.parsers.f195_debt_service_bonds",
        parse_fn_name="parse_f195_debt_service_bonds_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
