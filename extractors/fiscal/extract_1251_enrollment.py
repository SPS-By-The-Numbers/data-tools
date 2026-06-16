#!python3
"""Walk data/fiscal/apportionment/, parse 1251 FTE + 1251H Headcount PDFs.

Both reports share one fact table (`fiscal_1251_enrollment`) with a
`report_kind` discriminator: 'fte' for Report 1251 and 'headcount' for
Report 1251H.

Usage:
    python3 -m extractors.fiscal.extract_1251_enrollment \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_1251_enrollment.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "report_kind", "section", "grade", "month", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    # 1251 FTE.pdf and 1251H Headcount.pdf -- two patterns.
    # ESD-branch files are skipped: they are 1,800-line ESD-aggregate
    # reports (one per ESD, replicated under every member-district subdir),
    # not per-district reports. ESD-level enrollment would need a
    # separate dedup'd parser and arguably belongs in a different fact
    # table; deferred.
    for p in sorted(root.rglob("1251 FTE.pdf")):
        if p.is_file() and "/esd/" not in str(p):
            yield p
    for p in sorted(root.rglob("1251H Headcount.pdf")):
        if p.is_file() and "/esd/" not in str(p):
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.enrollment_1251",
        parse_fn_name="parse_1251_enrollment_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
