from decimal import Decimal

import fastavro

from .export import export_table


SCHEMA = {
    "name": "toy",
    "doc": "toy table",
    "fields": [
        {"name": "toy_id", "field_type": "auto_primary_key", "doc": "pk"},
        {"name": "label", "field_type": "string", "doc": "a label"},
        {"name": "amount", "field_type": "decimal", "doc": "money"},
        {"name": "_source_id", "field_type": "int", "doc": "fk"},
    ],
}


class FakeStaging:
    """Duck-typed stand-in for StagingDb (no Postgres needed)."""
    def __init__(self, rows, fp="fp1"):
        self._rows = rows
        self._fp = fp

    def iter_rows(self, schema):
        return iter(self._rows)

    def fingerprint(self, schema):
        return self._fp


def _rows():
    return [
        {"toy_id": 1, "label": "a", "amount": Decimal("3.500000000"),
         "_source_id": 7},
        {"toy_id": 2, "label": None, "amount": None, "_source_id": 8},
    ]


def test_export_roundtrip(tmp_path):
    staging = FakeStaging(_rows())
    res = export_table(staging, SCHEMA, tmp_path)
    assert res["rows"] == 2
    with (tmp_path / "tables" / "toy.avro").open("rb") as f:
        got = list(fastavro.reader(f))
    assert got[0]["label"] == "a"
    assert got[0]["amount"] == Decimal("3.500000000")
    assert got[0]["_source_id"] == 7
    assert got[1]["label"] is None and got[1]["amount"] is None


def test_export_skips_when_unchanged(tmp_path):
    staging = FakeStaging(_rows())
    export_table(staging, SCHEMA, tmp_path)
    second = export_table(staging, SCHEMA, tmp_path)
    assert second["skipped"] is True


def test_export_reruns_when_fingerprint_changes(tmp_path):
    export_table(FakeStaging(_rows(), fp="A"), SCHEMA, tmp_path)
    res = export_table(FakeStaging(_rows(), fp="B"), SCHEMA, tmp_path)
    assert res.get("skipped") is False
