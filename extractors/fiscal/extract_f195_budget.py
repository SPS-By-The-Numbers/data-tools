#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget (and Overview) PDF.

A single F-195 Budget PDF holds ~30 sub-reports; the Phase-1 parser
captures the SUMMARY OF X FUND BUDGET tables (all 5 funds). The same
parser runs against F-195 Budget Overview, which embeds the same
sub-reports across its pages 5-39.

Usage:
    python3 -m extractors.fiscal.extract_f195_budget data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_f195_budget.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "sub_report", "fund", "section", "item_code",
    "data_year_offset", "data_school_year", "data_class_of",
    "column_kind", "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    seen = set()
    for pattern in ("F-195 Budget.pdf", "F-195 Budget Overview.pdf"):
        for p in sorted(root.rglob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_budget",
        parse_fn_name="parse_f195_budget_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
