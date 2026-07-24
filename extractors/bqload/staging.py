"""PostgreSQL staging for the bqload pipeline (seed-first).

Each table is materialized in Postgres from its schema dict (via the SAFS
`orm.make_table`, so decimals are exact `DECIMAL(38,9)` -- no float anywhere).
Staging is populated from the already-parsed `out_<family>/<table>.csv` files
one table at a time (TRUNCATE + batched INSERT). A `_bqload_manifest` table
records each table's source CSV size/mtime/row-count so an unchanged CSV is
skipped on re-run.

The per-source-file incremental parse path (delete-then-insert keyed on
`_source`) is intentionally not built here yet; the seed path assumes the PDF
parse already ran and produced the CSVs.
"""

import csv as csvmod
import hashlib
import logging
import os
from pathlib import Path

from sqlalchemy import (
    BigInteger, Column, Integer, MetaData, String, Table, create_engine,
    select, text,
)

from ..safs import orm
from .spec import schema_fieldnames, staging_schema


logger = logging.getLogger(__name__)

_MANIFEST = "_bqload_manifest"
_BATCH = 20_000
# Audit columns are absent from the static dimension CSVs (extract_domains
# omits them); tolerate that and leave them NULL in staging.
_OPTIONAL_COLS = {"_source_id", "_source_table"}
# Allow large text CSV cells (some free-text labels are long).
csvmod.field_size_limit(1 << 24)


class _MetaHolder:
    """Minimal stand-in for a declarative Base: orm.make_table needs .metadata."""
    def __init__(self, metadata):
        self.metadata = metadata


class StagingDb:
    def __init__(self, db_name, db_user=None, db_password="", host="localhost"):
        db_user = db_user or os.getlogin()
        self.engine = create_engine(
            f"postgresql+psycopg2://{db_user}:{db_password}@{host}/{db_name}")
        self._md = MetaData()
        self._holder = _MetaHolder(self._md)
        self._tables = {}          # name -> sqlalchemy Table (staging variant)
        self._manifest = Table(
            _MANIFEST, self._md,
            Column("table_name", String, primary_key=True),
            Column("csv_path", String),
            Column("csv_size", BigInteger),
            Column("csv_mtime_ns", BigInteger),
            Column("row_count", Integer),
        )

    # -- table management ---------------------------------------------------
    def table(self, schema) -> Table:
        name = schema["name"]
        if name not in self._tables:
            self._tables[name] = orm.make_table(staging_schema(schema),
                                                self._holder)
        return self._tables[name]

    def ensure_tables(self, schemas):
        for s in schemas:
            self.table(s)
        self._md.create_all(self.engine)

    # -- seeding ------------------------------------------------------------
    def _manifest_row(self, conn, table_name):
        return conn.execute(
            select(self._manifest).where(
                self._manifest.c.table_name == table_name)).mappings().first()

    def is_fresh(self, schema, csv_path: Path) -> bool:
        """True if the table was already seeded from this exact CSV."""
        st = csv_path.stat()
        with self.engine.connect() as conn:
            row = self._manifest_row(conn, schema["name"])
        return bool(row
                    and row["csv_size"] == st.st_size
                    and row["csv_mtime_ns"] == st.st_mtime_ns)

    def load_csv(self, schema, csv_path: Path, force=False,
                 source_map=None) -> dict:
        """TRUNCATE the table and load every row of csv_path. Idempotent.

        `source_map` {raw _source string -> source_id}: when the CSV still has
        the raw `_source` path column instead of `_source_id` (a CSV that
        predates build_sources), translate it so provenance survives.
        """
        name = schema["name"]
        csv_path = Path(csv_path)
        if not force and self.is_fresh(schema, csv_path):
            logger.info("%s: unchanged CSV, skipping", name)
            return {"table": name, "skipped": True}

        tbl = self.table(schema)
        fields = [f for f in schema["fields"]
                  if f["field_type"] != "auto_primary_key"]
        colnames = set(schema_fieldnames(schema))
        has_source_id_field = "_source_id" in colnames
        from .values import row_to_py

        st = csv_path.stat()
        total = 0
        unmapped = 0
        with self.engine.begin() as conn:
            conn.execute(text(f'TRUNCATE TABLE "{name}"'))
            with csv_path.open(newline="") as fh:
                reader = csvmod.DictReader(fh)
                csv_cols = set(reader.fieldnames or [])
                missing = (colnames - csv_cols) - _OPTIONAL_COLS
                extra = csv_cols - colnames
                if missing:
                    raise ValueError(
                        f"{csv_path.name} missing columns {sorted(missing)}")
                # Translate raw `_source` -> `_source_id` when the CSV predates
                # build_sources (has `_source`, not `_source_id`).
                translate = (has_source_id_field
                             and "_source_id" not in csv_cols
                             and "_source" in csv_cols)
                if translate and source_map is None:
                    logger.warning("%s: CSV has raw _source but no source_map; "
                                   "_source_id will be NULL", name)
                if extra - ({"_source"} if translate else set()):
                    logger.warning("%s: ignoring extra CSV columns %s", name,
                                   sorted(extra - ({"_source"} if translate
                                                   else set())))
                batch = []
                for row in reader:
                    py = row_to_py(fields, row)
                    if translate and source_map is not None:
                        sid = source_map.get(row.get("_source"))
                        if sid is None:
                            unmapped += 1
                        py["_source_id"] = sid
                    batch.append(py)
                    if len(batch) >= _BATCH:
                        conn.execute(tbl.insert(), batch)
                        total += len(batch)
                        batch = []
                if batch:
                    conn.execute(tbl.insert(), batch)
                    total += len(batch)
            if unmapped:
                logger.warning("%s: %d rows had an _source with no id in the "
                               "source dim", name, unmapped)
            # upsert manifest
            conn.execute(text(f'DELETE FROM "{_MANIFEST}" '
                              f"WHERE table_name = :n"), {"n": name})
            conn.execute(self._manifest.insert(), {
                "table_name": name,
                "csv_path": str(csv_path),
                "csv_size": st.st_size,
                "csv_mtime_ns": st.st_mtime_ns,
                "row_count": total,
            })
        logger.info("%s: loaded %d rows from %s", name, total, csv_path.name)
        return {"table": name, "rows": total, "skipped": False}

    # -- reading ------------------------------------------------------------
    def iter_rows(self, schema):
        """Stream all staging rows (incl. the assigned auto-PK) as dicts."""
        tbl = self.table(schema)
        with self.engine.connect().execution_options(
                stream_results=True) as conn:
            for row in conn.execute(select(tbl)).mappings():
                yield dict(row)

    def row_count(self, schema) -> int:
        with self.engine.connect() as conn:
            return conn.execute(
                text(f'SELECT count(*) FROM "{schema["name"]}"')).scalar_one()

    def fingerprint(self, schema) -> str:
        with self.engine.connect() as conn:
            row = self._manifest_row(conn, schema["name"])
        if not row:
            return ""
        key = f'{row["csv_size"]}:{row["csv_mtime_ns"]}:{row["row_count"]}'
        return hashlib.sha256(key.encode()).hexdigest()[:16]
