#!python3
"""Walk data/fiscal/apportionment/, parse each 1191FG Grants
Administration PDF.

ESD-level files live under apportionment/<year>/esd/<esd_dir>/<member>/
and are *replicated* across every member-district subdir of a given
ESD (same OSPI source materialized under each member). The walker
dedupes by (year, esd_dir) so each unique ESD file is yielded once.

Usage:
    python3 -m extractors.fiscal.extract_grants_1191fg \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_1191fg_grants.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "org_type", "report_date_text",
    "section", "grant_seq",
    "project_id", "project_code", "project_description",
    "grant_period", "grant_status",
    "revenue_account", "prior_expend",
    "proj", "pom", "obj_sub",
    "funding", "paid_adj", "curr_paymt", "balance",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    # Pass 1: District / college / state_agency files.
    for p in sorted(root.rglob("1191FG Grants Administration.pdf")):
        if p.is_file() and "/esd/" not in str(p):
            yield p
    # Pass 2: ESD-level files, deduped by (year, esd_dir).
    seen_esd = set()
    for p in sorted(root.rglob("1191FG Grants Administration.pdf")):
        if not p.is_file() or "/esd/" not in str(p):
            continue
        parts = p.parts
        try:
            i = parts.index("esd")
        except ValueError:
            continue
        if i < 1 or i + 1 >= len(parts):
            continue
        year = parts[i - 1]
        esd_dir = parts[i + 1]
        key = (year, esd_dir)
        if key in seen_esd:
            continue
        seen_esd.add(key)
        yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.grants_1191fg",
        parse_fn_name="parse_grants_1191fg_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
