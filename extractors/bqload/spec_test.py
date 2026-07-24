from .spec import (
    Canonical, Family, TableSpec, auto_pk_field, schema_fieldnames,
    staging_schema,
)


SCHEMA = {
    "name": "t",
    "doc": "d",
    "fields": [
        {"name": "t_id", "field_type": "auto_primary_key", "doc": ""},
        {"name": "school_year", "field_type": "string",
         "is_logical_key": True, "doc": ""},
        {"name": "amount", "field_type": "decimal", "doc": ""},
        {"name": "_source_id", "field_type": "int", "doc": ""},
        {"name": "_source_table", "field_type": "string", "doc": ""},
    ],
    "unique": [["school_year", "amount"]],
}


def test_schema_fieldnames_drops_auto_pk():
    names = schema_fieldnames(SCHEMA)
    assert "t_id" not in names
    assert names == ["school_year", "amount", "_source_id", "_source_table"]


def test_auto_pk_field():
    assert auto_pk_field(SCHEMA) == "t_id"


def test_staging_schema_permissive():
    ss = staging_schema(SCHEMA)
    # auto-PK kept (Postgres serial), logical-key flag stripped, uniques dropped
    assert auto_pk_field(ss) == "t_id"
    assert "unique" not in ss
    for f in ss["fields"]:
        assert "is_logical_key" not in f
    # original schema untouched
    assert SCHEMA["unique"] == [["school_year", "amount"]]
    assert any(f.get("is_logical_key") for f in SCHEMA["fields"])


def test_tablespec_csv_basename():
    ts = TableSpec(table="foo", schema=SCHEMA)
    assert ts.csv_basename() == "foo.csv"
    assert TableSpec(table="foo", schema=SCHEMA,
                     csv_name="bar.csv").csv_basename() == "bar.csv"


def test_family_by_name():
    fam = Family("fiscal", "ospi_fiscal", "out_fiscal", "d_fiscal_source",
                 [TableSpec("a", SCHEMA), TableSpec("b", SCHEMA)])
    assert fam.by_name("b").table == "b"
    assert fam.by_name("nope") is None


def test_canonical_defaults():
    c = Canonical("unique")
    assert c.status == "unique" and c.prefer is None
