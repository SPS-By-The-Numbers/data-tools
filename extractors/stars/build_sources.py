#!python3
"""Build the d_stars_source dimension table and rewrite fact CSVs to use FK.

Walks `data/stars/<report_dir>/` for every scraped file, parses the
filename via extractors.stars.filename.parse(), assigns a sequential
source_id, and writes the lookup to `out_stars/d_stars_source.csv`.

Then rewrites each existing fact CSV under `out_stars/` to replace its
`_source` filename column with an integer `_source_id` column. This
deduplicates filename text that repeats 12-35x per row across the fact
tables.

Usage:
    python3 -m extractors.stars.build_sources \\
        --data-dir data/stars/ \\
        --out-dir  out_stars/

Idempotent: rerunning regenerates the same IDs (sorted by filename) and
overwrites the fact CSVs in place.
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from .filename import parse as parse_filename


logger = logging.getLogger(__name__)


_REPORT_LABEL_TO_DIR = {
    "Key Performance Indicators":       "kpi",
    "Operations Allocation Detail":     "operations_allocation",
    "Quarterly District Detail":        "quarterly_district",
    "Efficiency Detail":                "efficiency",
    "Efficiency Review":                "efficiency_review",
}


# Field order for the d_stars_source CSV. Must match the schema in
# schemas/domains.py:D_STARS_SOURCE.
_SOURCE_FIELDS = [
    "source_id", "source_filename", "report_dir", "school_year",
    "class_of", "ccddd", "district", "subcategory", "original_name",
    "extension",
]


def _enumerate_sources(data_dir: Path):
    """Walk data_dir/<report_dir>/* and yield parsed filename records."""
    for sub in sorted(data_dir.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.iterdir()):
            if p.suffix.lower() not in (".pdf", ".docx"):
                continue
            try:
                info = parse_filename(p)
            except ValueError as e:
                logger.warning("skipping unparseable filename: %s (%s)",
                               p.name, e)
                continue
            report_dir = _REPORT_LABEL_TO_DIR.get(info.report_type, sub.name)
            yield {
                "source_filename": p.name,
                "report_dir": report_dir,
                "school_year": info.school_year,
                "class_of": info.class_of,
                "ccddd": info.ccddd,
                "district": info.district_name,
                "subcategory": info.org_type,  # None for 4-segment names
                "original_name": info.original_name,
                "extension": info.extension,
            }


def _write_sources_csv(rows, path: Path):
    """Sort by filename, assign sequential source_id, write CSV."""
    rows = sorted(rows, key=lambda r: r["source_filename"])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_SOURCE_FIELDS)
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            r = {**r, "source_id": i}
            w.writerow({k: ("" if r.get(k) is None else r.get(k))
                        for k in _SOURCE_FIELDS})
    return {r["source_filename"]: i for i, r in enumerate(rows, start=1)}


def _rewrite_fact_csv(path: Path, id_by_filename: dict):
    """Replace _source string column with integer _source_id column."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    swapped = 0
    skipped = 0
    with path.open(newline="") as fin, tmp.open("w", newline="") as fout:
        reader = csv.DictReader(fin)
        if "_source" not in reader.fieldnames:
            tmp.unlink(missing_ok=True)
            return None  # nothing to do
        out_fields = []
        for fn in reader.fieldnames:
            if fn == "_source":
                out_fields.append("_source_id")
            else:
                out_fields.append(fn)
        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()
        for row in reader:
            fname = row.pop("_source", "")
            sid = id_by_filename.get(fname)
            if sid is None:
                skipped += 1
                continue
            row["_source_id"] = sid
            writer.writerow(row)
            swapped += 1
    tmp.replace(path)
    return swapped, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True,
                        help="data/stars/ root containing per-report subdirs")
    parser.add_argument("--out-dir", required=True,
                        help="out_stars/ where the source table + fact CSVs live")
    parser.add_argument("--no-rewrite", action="store_true",
                        help="only write d_stars_source.csv; don't rewrite fact CSVs")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build the sources table.
    rows = list(_enumerate_sources(data_dir))
    sources_path = out_dir / "d_stars_source.csv"
    id_by_filename = _write_sources_csv(rows, sources_path)
    print(f"d_stars_source: {len(rows)} rows -> {sources_path}",
          file=sys.stderr)

    if args.no_rewrite:
        return

    # Rewrite each fact CSV to use _source_id instead of _source.
    for csv_path in sorted(out_dir.glob("stars_*.csv")):
        if csv_path.name.startswith("d_"):
            continue
        result = _rewrite_fact_csv(csv_path, id_by_filename)
        if result is None:
            print(f"  {csv_path.name}: no _source column; left as-is",
                  file=sys.stderr)
            continue
        swapped, skipped = result
        msg = f"  {csv_path.name}: rewrote {swapped:,} rows"
        if skipped:
            msg += f" ({skipped} rows skipped: no matching source filename)"
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    main()
