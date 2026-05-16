#!python3
"""Walk a directory of Efficiency Detail files, parse each, emit two streams.

Writes per-district subject rows by default. Pass --table cohort to emit
the per-peer cohort table instead.

Usage:
    python3 -m extractors.stars.extract_efficiency data/stars/efficiency/
    python3 -m extractors.stars.extract_efficiency data/stars/efficiency/ --table cohort
"""

import argparse
import csv
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

from .filename import parse as parse_filename
from .parsers.efficiency import parse_efficiency


logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(repr(o))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="directory of PDFs/DOCXs (or a single file)")
    parser.add_argument(
        "--table", choices=("subject", "cohort"), default="subject",
        help="which table to emit (default: subject)")
    parser.add_argument(
        "--format", choices=("csv", "json", "summary"), default="csv",
        help="output format")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N input files")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)

    root = Path(args.input)
    if root.is_dir():
        files = sorted(
            p for p in root.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".docx")
        )
    else:
        files = [root]
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
            logger.error("filename parse failed: %s", e)
            errors += 1
            continue

        try:
            subject, cohorts = parse_efficiency(info)
        except Exception as e:  # pragma: no cover
            logger.error("parse failed for %s: %s", path.name, e)
            errors += 1
            continue

        rows = [subject] if (args.table == "subject" and subject is not None) else (
            cohorts if args.table == "cohort" else []
        )

        if args.format == "summary":
            print(f"{len(rows):3d}  {path.name}")
        elif args.format == "json":
            for r in rows:
                print(json.dumps(r, default=_json_default))
        else:  # csv
            if writer is None and rows:
                writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
                writer.writeheader()
            for r in rows:
                writer.writerow({
                    k: (str(v) if isinstance(v, Decimal) else v)
                    for k, v in r.items()
                })
        total_rows += len(rows)
        parsed += 1

    print(
        f"\n[done] files parsed: {parsed}, errors: {errors}, "
        f"total {args.table} rows: {total_rows}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
