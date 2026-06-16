#!python3
"""Build d_fiscal_source and rewrite fact CSVs to use the integer FK.

Walks data/fiscal/ recursively, parses each file path via
extractors.fiscal.filename.parse(), sorts by relative path, assigns a
sequential source_id, and writes the dimension table to
out_fiscal/d_fiscal_source.csv. Then rewrites each existing
out_fiscal/fiscal_*.csv to replace its `_source` path column with an
integer `_source_id`.

Idempotent: rerunning regenerates the same IDs (sorted by path) and
overwrites the fact CSVs in place.

Usage:
    python3 -m extractors.fiscal.build_sources \\
        --data-dir data/fiscal/ --out-dir out_fiscal/
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from .filename import parse as parse_filename


logger = logging.getLogger(__name__)


_SOURCE_FIELDS = [
    "source_id", "source_path", "report_type", "school_year",
    "class_of", "org_type", "ccddd", "org_code", "org_slug",
    "esd_code", "esd_slug", "leaf", "extension",
]


def _enumerate_sources(data_dir: Path):
    """Walk data_dir recursively; yield dicts ready for the dimension table."""
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            info = parse_filename(p)
        except ValueError as e:
            logger.warning("skipping unparseable path: %s (%s)", p, e)
            continue
        rel = "/".join(p.relative_to(data_dir).parts)
        yield {
            "source_path": rel,
            "report_type": info.report_type,
            "school_year": info.school_year,
            "class_of": info.class_of,
            "org_type": info.org_type or "",
            "ccddd": info.ccddd if info.ccddd is not None else "",
            "org_code": info.org_code or "",
            "org_slug": info.org_slug or "",
            "esd_code": info.esd_code or "",
            "esd_slug": info.esd_slug or "",
            "leaf": info.leaf,
            "extension": info.extension or "",
        }


def _write_sources_csv(rows, path: Path):
    rows = sorted(rows, key=lambda r: r["source_path"])
    id_by_path = {}
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_SOURCE_FIELDS)
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            r2 = {**r, "source_id": i}
            w.writerow({k: r2.get(k, "") for k in _SOURCE_FIELDS})
            id_by_path[r["source_path"]] = i
    return id_by_path


def _rewrite_fact_csv(path: Path, id_by_path: dict):
    """Replace _source string column with integer _source_id column."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    swapped = 0
    skipped = 0
    with path.open(newline="") as fin, tmp.open("w", newline="") as fout:
        reader = csv.DictReader(fin)
        if "_source" not in reader.fieldnames:
            tmp.unlink(missing_ok=True)
            return None
        out_fields = ["_source_id" if fn == "_source" else fn
                      for fn in reader.fieldnames]
        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()
        for row in reader:
            src = row.pop("_source", "")
            sid = id_by_path.get(src)
            if sid is None:
                skipped += 1
                continue
            row["_source_id"] = sid
            writer.writerow(row)
            swapped += 1
    tmp.replace(path)
    return swapped, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data/fiscal", type=Path)
    ap.add_argument("--out-dir", default="out_fiscal", type=Path)
    ap.add_argument("--no-rewrite", action="store_true",
                    help="Only write d_fiscal_source.csv; don't rewrite fact CSVs")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")

    data_dir = args.data_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = list(_enumerate_sources(data_dir))
    sources_path = out_dir / "d_fiscal_source.csv"
    id_by_path = _write_sources_csv(rows, sources_path)
    print(f"d_fiscal_source: {len(rows):,} rows -> {sources_path}", file=sys.stderr)

    if args.no_rewrite:
        return

    for csv_path in sorted(out_dir.glob("fiscal_*.csv")):
        if csv_path.name.startswith("d_"):
            continue
        result = _rewrite_fact_csv(csv_path, id_by_path)
        if result is None:
            print(f"  {csv_path.name}: no _source column; left as-is", file=sys.stderr)
            continue
        swapped, skipped = result
        msg = f"  {csv_path.name}: rewrote {swapped:,} rows"
        if skipped:
            msg += f" ({skipped} skipped: no matching source path)"
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    main()
