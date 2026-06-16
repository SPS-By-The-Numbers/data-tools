#!python3
"""Walk data/fiscal/state_institutions/, parse each 1191SI PDF, emit rows.

Usage:
    python3 -m extractors.fiscal.extract_state_institutions data/fiscal/state_institutions/
        --format csv > out_fiscal/fiscal_state_institutions.csv

By default writes CSV to stdout. Pass --format summary for per-file row counts,
--format json for newline-delimited JSON.
"""

import argparse
import csv
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

from .filename import parse as parse_filename
from .parsers.state_institutions import parse_state_institutions_pdf


logger = logging.getLogger(__name__)


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "institution_name", "revenue_account", "allocation_status",
    "section_code", "section_seq", "section_title",
    "item_path", "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(repr(o))


def _iter_pdfs(root: Path):
    """Yield 1191SI PDF paths under root, recursing into year subdirs.

    The state_institutions/ tree occasionally includes companion documents
    that aren't Form 1191SI (e.g. `State Summary Spreadsheet.pdf` in 2024-25).
    Filter to files whose stem ends with `1191SI` so the parser only ever
    sees the form it knows how to handle.
    """
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*.pdf")):
        if p.is_file() and p.stem.endswith("1191SI"):
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="state_institutions directory or single 1191SI PDF")
    ap.add_argument("--format", choices=("csv", "json", "summary"), default="csv")
    ap.add_argument("--limit", type=int, default=None, help="stop after N files")
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level)

    root = Path(args.input)
    files = list(_iter_pdfs(root))
    if args.limit:
        files = files[: args.limit]

    writer = None
    total_rows = 0
    parsed_files = 0
    errors = 0

    for path in files:
        try:
            info = parse_filename(path)
        except ValueError as e:
            logger.error("filename parse failed for %s: %s", path, e)
            errors += 1
            continue

        try:
            rows = list(parse_state_institutions_pdf(info))
        except Exception as e:  # noqa: BLE001 -- want to keep walking the corpus
            logger.error("parse failed for %s: %s", path.name, e)
            errors += 1
            continue

        if args.format == "summary":
            print(f"{len(rows):3d}  {path.name}")
        elif args.format == "json":
            for r in rows:
                print(json.dumps(r, default=_json_default))
        else:
            if writer is None:
                writer = csv.DictWriter(sys.stdout, fieldnames=FIELDNAMES)
                writer.writeheader()
            for r in rows:
                writer.writerow({
                    k: (str(v) if isinstance(v, Decimal) else v)
                    for k, v in r.items()
                })
        total_rows += len(rows)
        parsed_files += 1

    print(
        f"[done] files parsed: {parsed_files}, errors: {errors}, total rows: {total_rows}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
