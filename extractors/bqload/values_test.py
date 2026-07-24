from decimal import Decimal

from .values import csv_str_to_py_value, row_to_py


def _f(name, ftype):
    return {"name": name, "field_type": ftype, "doc": ""}


def test_empty_and_null_become_none():
    for ftype in ("string", "int", "decimal", "boolean", "timestamp"):
        assert csv_str_to_py_value(_f("x", ftype), "") is None
        assert csv_str_to_py_value(_f("x", ftype), "NULL") is None
        assert csv_str_to_py_value(_f("x", ftype), None) is None


def test_int_and_decimal():
    assert csv_str_to_py_value(_f("n", "int"), "42") == 42
    d = csv_str_to_py_value(_f("d", "decimal"), "1234.5")
    assert d == Decimal("1234.5")
    # quantized to scale 9
    assert d == Decimal("1234.500000000")


def test_decimal_bad_value_is_none():
    assert csv_str_to_py_value(_f("d", "decimal"), "n/a") is None


def test_boolean():
    tf = _f("b", "boolean")
    assert csv_str_to_py_value(tf, "True") is True
    assert csv_str_to_py_value(tf, "false") is False
    assert csv_str_to_py_value(tf, "1") is True
    assert csv_str_to_py_value(tf, "0") is False


def test_string_passthrough_and_empty_none():
    assert csv_str_to_py_value(_f("s", "string"), "hi") == "hi"


def test_row_to_py_only_present_and_typed():
    fields = [_f("school_year", "string"), _f("ccddd", "int"),
              _f("amount", "decimal"), _f("_source_id", "int")]
    row = {"school_year": "2020-2021", "ccddd": "17001", "amount": "3.5"}
    out = row_to_py(fields, row)
    assert out == {"school_year": "2020-2021", "ccddd": 17001,
                   "amount": Decimal("3.500000000")}
    # _source_id absent from row -> absent from output (Postgres/NULL fills it)
    assert "_source_id" not in out
