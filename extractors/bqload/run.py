"""Orchestrate the seed-first fiscal/stars -> BigQuery pipeline.

Stages:
  seed    -- load out_<family>/<table>.csv into Postgres staging (idempotent)
  export  -- stream staging -> out_<family>/tables/<table>.avro (zstd)
  upload  -- push AVRO to GCS
  load    -- load GCS AVRO into BigQuery (WRITE_TRUNCATE) + set descriptions

Default stages are seed,export (no production side effects). Run
  python3 -m extractors.bqload.run --family fiscal --stages seed,export
from the repo root.
"""

import argparse
import importlib
import logging
from pathlib import Path

from .staging import StagingDb
from .export import export_table


logger = logging.getLogger(__name__)

DEFAULT_STAGES = "seed,export"


def load_family(name):
    try:
        mod = importlib.import_module(f"extractors.{name}.registry")
    except ModuleNotFoundError as e:
        raise SystemExit(f"no registry for family {name!r}: {e}")
    return mod.FAMILY


def _load_source_map(out_dir, family):
    """{source_path|source_filename -> source_id} from out_<family>/d_*_source.csv.

    Used to translate fact CSVs that still carry the raw `_source` string
    (predating build_sources) into `_source_id`. Returns None if absent.
    """
    import csv as csvmod
    path = out_dir / f"{family.source_dim_table}.csv"
    if not path.exists():
        return None
    csvmod.field_size_limit(1 << 24)
    with path.open(newline="") as fh:
        reader = csvmod.DictReader(fh)
        cols = reader.fieldnames or []
        key = next((c for c in ("source_path", "source_filename")
                    if c in cols), None)
        if key is None or "source_id" not in cols:
            return None
        return {row[key]: int(row["source_id"]) for row in reader}


def _selected(family, tables_arg):
    if not tables_arg:
        return family.tables
    want = set(tables_arg.split(","))
    picked = [t for t in family.tables if t.table in want]
    missing = want - {t.table for t in picked}
    if missing:
        raise SystemExit(f"unknown tables: {sorted(missing)}")
    return picked


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--family", required=True, choices=["fiscal", "stars"])
    p.add_argument("--stages", default=DEFAULT_STAGES,
                   help=f"comma list of seed,export,upload,load (default {DEFAULT_STAGES})")
    p.add_argument("--tables", help="comma list; default all")
    p.add_argument("--out-dir", help="default out_<family>")
    p.add_argument("--db-name", help="Postgres db (default <family>_prod)")
    p.add_argument("--db-user", default=None)
    p.add_argument("--db-password", default="")
    p.add_argument("--force", action="store_true",
                   help="ignore freshness fingerprints; re-seed/re-export")
    p.add_argument("--csv", action="store_true",
                   help="also write a CSV next to each exported AVRO")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s: %(message)s")

    family = load_family(args.family)
    out_dir = Path(args.out_dir or family.out_dir)
    db_name = args.db_name or f"{args.family}_prod"
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    specs = _selected(family, args.tables)

    staging = None
    if {"seed", "export"} & set(stages):
        staging = StagingDb(db_name, args.db_user, args.db_password)
        staging.ensure_tables([s.schema for s in specs])

    if "seed" in stages:
        source_map = _load_source_map(out_dir, family)
        # Seed the source-dim table first so it lands in staging/BQ too.
        specs_ordered = sorted(specs, key=lambda t: t.kind != "source_dim")
        for spec in specs_ordered:
            csv_path = out_dir / spec.csv_basename()
            if not csv_path.exists():
                logger.warning("%s: no CSV at %s, skipping seed",
                               spec.table, csv_path)
                continue
            staging.load_csv(spec.schema, csv_path, force=args.force,
                             source_map=source_map)

    if "export" in stages:
        for spec in specs:
            export_table(staging, spec.schema, out_dir,
                         write_csv=args.csv, force=args.force)

    if "upload" in stages or "load" in stages:
        from .gcs_bq import upload_and_load
        upload_and_load(out_dir, family.name, family.bq_dataset, specs,
                        upload="upload" in stages, load="load" in stages,
                        describe="load" in stages)

    logger.info("done: family=%s stages=%s tables=%d",
                args.family, ",".join(stages), len(specs))


if __name__ == "__main__":
    main()
