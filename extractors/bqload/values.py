"""Convert parser/CSV string cells into typed Python values for staging.

The seed path reads `out_<family>/<table>.csv` where every cell is a string
(empty string means NULL). These helpers turn a cell into the Python type the
Postgres column and, later, the AVRO decimal/int/bool encoding expect. No
SAFS null-sentinel machinery is involved -- empty strings map straight to None.
"""

import logging
from decimal import Decimal, InvalidOperation

import dateutil.parser

from ..safs.avro_schema import DECIMAL_QUANT_AMOUNT


logger = logging.getLogger(__name__)

_TRUE = {"true", "1", "t", "yes", "y"}
_FALSE = {"false", "0", "f", "no", "n"}


def csv_str_to_py_value(field: dict, s):
    """Convert one CSV cell (string) to a typed value per field["field_type"]."""
    if s is None:
        return None
    if isinstance(s, str):
        if s == "" or s == "NULL":
            return None
    ftype = field["field_type"]

    if ftype == "string":
        return s

    if ftype == "int" or ftype == "auto_primary_key":
        return int(s)

    if ftype == "decimal":
        try:
            return Decimal(str(s)).quantize(DECIMAL_QUANT_AMOUNT)
        except InvalidOperation:
            logger.warning("un-parseable decimal %r in %s", s, field["name"])
            return None

    if ftype == "boolean":
        low = str(s).strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        return None

    if ftype == "timestamp":
        return dateutil.parser.parse(s)

    raise ValueError(f"unknown field_type {ftype!r} for {field['name']}")


def row_to_py(fields: list, row: dict) -> dict:
    """Map a CSV row dict (str values) to typed values, keyed by field name.

    `fields` is a list of schema field dicts. Only fields present in `row` are
    emitted (the auto-PK, absent from the CSV, is left for Postgres to fill).
    Extra keys in `row` are ignored.
    """
    out = {}
    for f in fields:
        name = f["name"]
        if name in row:
            out[name] = csv_str_to_py_value(f, row[name])
    return out
