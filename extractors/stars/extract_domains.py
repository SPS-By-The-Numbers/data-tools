#!python3
"""Write the STARS domain (lookup) tables out as CSV files.

Usage:
    python3 -m extractors.stars.extract_domains out_stars/

Each schema in schemas/domains.py becomes one CSV: `<table_name>.csv`.
The column order matches the schema's `fields` order (excluding the
auto_primary_key surrogate and the _source / _source_table audit
fields, which aren't meaningful for hand-curated lookup data).
"""

import argparse
import csv
import sys
from pathlib import Path

from .schemas.domains import ALL_SCHEMAS, ROWS_BY_TABLE


def _row_fields(schema):
    """Return the data column names from a schema, skipping audit + PK noise."""
    skip = {"_source", "_source_table"}
    out = []
    for f in schema["fields"]:
        if f["name"] in skip:
            continue
        if f.get("field_type") == "auto_primary_key":
            continue
        out.append(f["name"])
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("outdir", help="output directory (will be created if missing)")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    total = 0
    for schema in ALL_SCHEMAS:
        name = schema["name"]
        rows = ROWS_BY_TABLE.get(name, [])
        fields = _row_fields(schema)
        path = outdir / f"{name}.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in fields})
        print(f"{name}: {len(rows)} rows -> {path}", file=sys.stderr)
        total += len(rows)
    print(f"\n[done] {len(ALL_SCHEMAS)} tables, {total} total rows.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
