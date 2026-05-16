#!python3
"""Walk a directory of KPI PDFs, parse each, emit records.

Usage:
    python3 -m extractors.stars.extract_kpi data/stars/kpi/

By default writes CSV to stdout. Pass --json for newline-delimited JSON, or
--summary for just per-file row counts.
"""

import argparse
import csv
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

from .filename import parse as parse_filename
from .parsers.kpi import parse_kpi_pdf


logger = logging.getLogger(__name__)


def _json_default(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(repr(o))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="directory of KPI PDFs (or a single file)")
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
        files = sorted(p for p in root.iterdir()
                       if p.is_file() and p.suffix.lower() == ".pdf")
    else:
        files = [root]
    if args.limit:
        files = files[: args.limit]

    writer = None
    fieldnames = None
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
        if info.extension != "pdf":
            logger.info("skipping non-PDF: %s", path.name)
            continue

        rows = list(parse_kpi_pdf(info))
        if args.format == "summary":
            print(f"{len(rows):3d}  {path.name}")
        elif args.format == "json":
            for r in rows:
                print(json.dumps(r, default=_json_default))
        else:  # csv
            if writer is None:
                fieldnames = list(rows[0].keys()) if rows else [
                    "school_year", "class_of", "ccddd", "county", "district",
                    "metric_code", "data_class_of", "data_school_year",
                    "value", "_source", "_source_table",
                ]
                writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
                writer.writeheader()
            for r in rows:
                writer.writerow({k: (str(v) if isinstance(v, Decimal) else v)
                                 for k, v in r.items()})
        total_rows += len(rows)
        parsed += 1

    print(
        f"\n[done] files parsed: {parsed}, errors: {errors}, total rows: {total_rows}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
