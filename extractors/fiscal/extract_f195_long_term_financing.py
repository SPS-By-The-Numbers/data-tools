#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget PDF's
`<FUND> - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS AND
NOTES` sub-report (GF14 / CP9 / TVF4).

F-195 Budget Overview does NOT contain these sub-reports (verified
across vintages), so this walker parses Budget only.

Usage:
    python3 -m extractors.fiscal.extract_f195_long_term_financing \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_long_term_financing.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "section", "item_seq", "is_total", "item_label",
    "contract_length_months",
    "amount_beginning", "principal_fy", "interest_fy", "amount_ending",
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
        parse_fn_module="extractors.fiscal.parsers.f195_long_term_financing",
        parse_fn_name="parse_f195_long_term_financing_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
