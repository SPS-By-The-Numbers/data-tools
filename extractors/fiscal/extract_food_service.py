#!python3
"""Walk data/fiscal/fiscal/, parse each Food Service Program Summary PDF, emit rows.

Usage:
    python3 -m extractors.fiscal.extract_food_service data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_food_service.csv
"""

import argparse
import csv
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

from .filename import parse as parse_filename
from .parsers.food_service import parse_food_service_pdf


logger = logging.getLogger(__name__)


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "item_code", "subkey", "item_label",
    "value", "value_text", "is_indirect_calc",
    "_source", "_source_table",
]


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(repr(o))


def _iter_pdfs(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("Food Service Program Summary.pdf")):
        if p.is_file():
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="fiscal/ root dir or a single PDF")
    ap.add_argument("--format", choices=("csv", "json", "summary"), default="csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level)

    files = list(_iter_pdfs(Path(args.input)))
    if args.limit:
        files = files[: args.limit]

    writer = None
    total_rows = 0
    parsed = 0
    errors = 0

    for path in files:
        try:
            info = parse_filename(path)
        except ValueError as e:
            logger.error("filename parse failed for %s: %s", path, e)
            errors += 1
            continue
        try:
            rows = list(parse_food_service_pdf(info))
        except Exception as e:  # noqa: BLE001
            logger.error("parse failed for %s: %s", path, e)
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
        parsed += 1

    print(
        f"[done] files parsed: {parsed}, errors: {errors}, total rows: {total_rows}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
