#!python3

import dateutil
import logging

from decimal import getcontext, Decimal
from datetime import datetime


logger = logging.getLogger(__name__)


"""Precision used on the sql DECIMAL type"""
DECIMAL_PRECISION = 38
getcontext().prec = DECIMAL_PRECISION


"""Scale used on the sql DECIMAL type."""
DECIMAL_SCALE = 9


"""Sentinel number used to represent NULL"""
_NULL_NUMBER = -931415926


"""quant() parameter for Decimals after math. ALWAYS QUANT TO AVOID ERRORS."""
DECIMAL_QUANT_AMOUNT = Decimal(1) / (10**DECIMAL_SCALE)


def get_null_sentinel(field_type, none_instead_of_raise=False):
    """Returns a constant that should mean null for the type.

    RDMBSes have NULL values that do not have reflexive equality. This makes
    unique constraint do unexpected things. Use a sentinel value here to
    designate "null" for different types.

    This is undone in the to_avro_value() method later.
    """
    match field_type:
        case 'decimal':
            # Do not use NaN! Those also don't equal one another. grrr.
            # Do not use INF! This turns into NaN in some DBs!
            return Decimal(_NULL_NUMBER) + DECIMAL_QUANT_AMOUNT

        case 'string':
            return 'sqlh8'

        case 'timestamp':
            # Random early leap day is unlikely to be used anywhere.
            return datetime(month=2, day=29, year=1972)

        case 'int':
            return _NULL_NUMBER

        case _:
            if none_instead_of_raise:
                return None
            raise ValueError(f"No sentinel defined for {field_type}")


def passthru(record, source):
    """Just pass through the data value unchanged"""
    return record[source]


def cleaned_string(record, source):
    value = record.get(source, None)
    if value is None:
        return None
    return value.strip()


def string_with_null(record, source):
    value = record[source].strip()
    if not value or value == "NULL":
        return None
    return value


def just_zero(_, __):
    """return the constant 1"""
    return 0


def to_int(record, source):
    """Reads the value as an int"""
    value = cleaned_string(record, source)
    return int(value)


def to_int_or_null(record, source):
    """Reads the value as an int"""
    value = string_with_null(record, source)
    if value is None:
        return None
    return int(value)


def to_decimal_or_null(record, source):
    value = string_with_null(record, source)
    if value is None:
        return None
    return Decimal(value).quantize(DECIMAL_QUANT_AMOUNT)


def parse_datetime(record, source):
    """Takes formats like 08/20/14 11:37:28 and turns into a timestamp"""
    date_str = cleaned_string(record, source)
    if date_str:
        return dateutil.parser.parse(date_str)
    return None


def parse_first_schoolyear(record, source):
    """Reads the value as an int"""
    return int(record[source].split('-')[0])


def one_to_boolean(record, source):
    """Converts a "1" value ot True. Everything else is False"""
    return record[source] == '1'


def y_n_to_boolean(record, source):
    """Converts a "Y" and "N" value ot True/False"""
    src_val = record[source]
    if src_val == 'Y':
        return True
    elif src_val == 'N':
        return False
    elif src_val == '' or src_val == 'NULL' or src_val is None:
        return None
    else:
        raise ValueError(src_val)


def to_avro_type(field_type):
    """Converts the field_type used in the schema to AVRO friendly defs"""
    match field_type:
        case 'decimal':
            return [
                'null',
                {
                    "type": "bytes",
                    "logicalType": "decimal",
                    "precision": 38,
                    "scale": 9,
                }]

        case 'string':
            return ['null', 'string']

        case 'timestamp':
            return ['null', {
                'type': 'long',
                'logicalType': 'timestamp-millis'
            }]

        case 'int':
            return ['null', 'int']

        case 'auto_primary_key':
            return ['null', 'int']

        case 'boolean':
            return ['null', 'boolean']

        case _:
            raise ValueError(f"Unknown Field type {field_type}")


def to_avro_field(field_name, field_type, doc=None, default=None):
    return {"name": field_name,
            "type": to_avro_type(field_type),
            "default": default,
            "doc": doc,
            }


def to_avro_schema(schema):
    """Given a schema definition, return an AVRO compatible schema dict"""
    return {
        "name": schema["name"],
        "doc": schema["doc"],
        "type": "record",
        "fields": [
            {
                "name": f["name"],
                "doc": f["doc"],
                "type": to_avro_type(f["field_type"])
            }
            for f in schema["fields"]
        ]
    }


def to_avro_value(field, value):
    """Convert python/orm friendly representation to AVRO value for output"""
    if value is None:
        return None

    # Convert hacked up null values cause SQL NULL sucks uniqueness constraints
    # back to None.
    sentinel = get_null_sentinel(field["field_type"],
                                 none_instead_of_raise=True)
    if value == sentinel:
        return None

    # Do any field conversions needed here.
    match field["field_type"]:
        case 'timestamp':
            return int(value.timestamp() * 1000)

        case 'decimal':
            if value.is_nan():
                logger.warning(f"Unexpected NaN in {field['name']}")
                return None

    return value
