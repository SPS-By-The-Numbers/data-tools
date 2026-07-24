"""Export staged Postgres tables to zstandard-compressed AVRO.

Generalizes `extractors/safs/dump_tables.py:AvroDumper`: streams a staging
table's rows through `to_avro_value` into `fastavro.writer(codec='zstandard')`
using `to_avro_schema(schema)`. Writes `<out_dir>/tables/<table>.avro` plus a
`<table>.meta.json` fingerprint so an unchanged table is not re-exported.
"""

import hashlib
import json
import logging
from pathlib import Path

import fastavro

from ..safs.avro_schema import to_avro_schema, to_avro_value


logger = logging.getLogger(__name__)


def _schema_hash(schema) -> str:
    blob = json.dumps(to_avro_schema(schema), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _avro_rows(staging, schema):
    fields = schema["fields"]
    for row in staging.iter_rows(schema):
        yield {f["name"]: to_avro_value(f, row.get(f["name"]))
               for f in fields}


def export_table(staging, schema, out_dir, write_csv=False,
                 force=False) -> dict:
    name = schema["name"]
    tables_dir = Path(out_dir) / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    avro_path = tables_dir / f"{name}.avro"
    meta_path = tables_dir / f"{name}.meta.json"

    fp = staging.fingerprint(schema)
    shash = _schema_hash(schema)
    if not force and avro_path.exists() and meta_path.exists():
        try:
            prev = json.loads(meta_path.read_text())
            if prev.get("fingerprint") == fp and prev.get("schema_hash") == shash:
                logger.info("%s: unchanged, skipping export", name)
                return {"table": name, "skipped": True,
                        "rows": prev.get("row_count")}
        except (json.JSONDecodeError, OSError):
            pass

    n = 0

    def _counting_rows():
        nonlocal n
        for r in _avro_rows(staging, schema):
            n += 1
            yield r

    with avro_path.open("wb") as fh:
        fastavro.writer(fh,
                        fastavro.parse_schema(to_avro_schema(schema)),
                        _counting_rows(),
                        codec="zstandard")

    if write_csv:
        _write_csv(staging, schema, tables_dir / f"{name}.csv")

    meta_path.write_text(json.dumps(
        {"table": name, "fingerprint": fp, "schema_hash": shash,
         "row_count": n}, indent=2))
    logger.info("%s: exported %d rows -> %s", name, n, avro_path)
    return {"table": name, "rows": n, "path": str(avro_path), "skipped": False}


def _write_csv(staging, schema, csv_path):
    import csv as csvmod
    names = [f["name"] for f in schema["fields"]]
    with csv_path.open("w", newline="") as fh:
        w = csvmod.DictWriter(fh, fieldnames=names)
        w.writeheader()
        for row in staging.iter_rows(schema):
            w.writerow({k: ("" if row.get(k) is None else row.get(k))
                        for k in names})
