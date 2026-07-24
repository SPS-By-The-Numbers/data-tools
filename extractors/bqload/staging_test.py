"""Staging tests against a throwaway local Postgres DB.

Skips cleanly when no local Postgres is reachable (CI without a server).
"""

import getpass
import os

import pytest

from .staging import StagingDb


SCHEMA = {
    "name": "bqload_toy",
    "doc": "toy",
    "fields": [
        {"name": "toy_id", "field_type": "auto_primary_key", "doc": ""},
        {"name": "school_year", "field_type": "string",
         "is_logical_key": True, "doc": ""},
        {"name": "amount", "field_type": "decimal", "doc": ""},
        {"name": "_source_id", "field_type": "int", "doc": ""},
        {"name": "_source_table", "field_type": "string", "doc": ""},
    ],
    "unique": [["school_year"]],
}


@pytest.fixture
def db():
    user = getpass.getuser()
    name = f"bqload_test_{os.getpid()}"
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        admin = psycopg2.connect(host="localhost", dbname="postgres", user=user)
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"no local Postgres: {e}")
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = admin.cursor()
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    cur.execute(f'CREATE DATABASE "{name}"')
    staging = StagingDb(name, db_user=user)
    try:
        yield staging
    finally:
        staging.engine.dispose()   # release the connection before dropping
        cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.close()


def _write_csv(path, header, rows):
    lines = [",".join(header)] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_seed_and_idempotence(db, tmp_path):
    db.ensure_tables([SCHEMA])
    csv = _write_csv(
        tmp_path / "bqload_toy.csv",
        ["school_year", "amount", "_source_id", "_source_table"],
        [["2020-2021", "3.5", "7", "t"], ["2021-2022", "", "8", "t"]])

    r = db.load_csv(SCHEMA, csv)
    assert r["rows"] == 2
    assert db.row_count(SCHEMA) == 2
    assert db.is_fresh(SCHEMA, csv)

    # Re-load without force: skipped.
    assert db.load_csv(SCHEMA, csv)["skipped"] is True
    # Rows are typed: decimal + NULL preserved.
    rows = sorted(db.iter_rows(SCHEMA), key=lambda x: x["school_year"])
    assert rows[0]["amount"] is not None
    assert rows[1]["amount"] is None
    assert rows[0]["_source_id"] == 7
    assert rows[0]["toy_id"] is not None      # Postgres assigned the surrogate


def test_changed_csv_is_not_fresh(db, tmp_path):
    db.ensure_tables([SCHEMA])
    csv = _write_csv(tmp_path / "bqload_toy.csv",
                     ["school_year", "amount", "_source_id", "_source_table"],
                     [["2020-2021", "1", "1", "t"]])
    db.load_csv(SCHEMA, csv)
    assert db.is_fresh(SCHEMA, csv)
    _write_csv(csv, ["school_year", "amount", "_source_id", "_source_table"],
               [["2020-2021", "1", "1", "t"], ["2021-2022", "2", "1", "t"]])
    assert not db.is_fresh(SCHEMA, csv)
    r = db.load_csv(SCHEMA, csv)
    assert r["rows"] == 2 and db.row_count(SCHEMA) == 2


def test_source_translation(db, tmp_path):
    """A CSV with raw `_source` (not `_source_id`) is translated via map."""
    db.ensure_tables([SCHEMA])
    csv = _write_csv(
        tmp_path / "bqload_toy.csv",
        ["school_year", "amount", "_source", "_source_table"],
        [["2020-2021", "1", "a/b.pdf", "t"],
         ["2021-2022", "2", "c/d.pdf", "t"]])
    smap = {"a/b.pdf": 11, "c/d.pdf": 22}
    db.load_csv(SCHEMA, csv, source_map=smap)
    ids = sorted(r["_source_id"] for r in db.iter_rows(SCHEMA))
    assert ids == [11, 22]
