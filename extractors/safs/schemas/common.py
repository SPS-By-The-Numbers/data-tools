#!python3

from decimal import getcontext, Decimal

"""Precision used on the sql DECIMAL type"""
DECIMAL_PRECISION = 38
getcontext().prec = DECIMAL_PRECISION


"""Scale used on the sql DECIMAL type."""
DECIMAL_SCALE = 9


"""quant() parameter for Decimals after math. ALWAYS QUANT TO AVOID ERRORS."""
DECIMAL_QUANT_AMOUNT = Decimal(10**(-DECIMAL_SCALE))


def make_field(name, field_type, doc=None, default=None, primary_key=False):
    """Given a name and field_type, produces the right AVRO field definition"""
    if field_type == 'decimal':
        schema_type = [
            "null",
            {
                "logicalType": "decimal",
                "precision": 38,
                "scale": 9,
                "type": "bytes"
            }
        ]
    elif field_type == 'timestamp':
        schema_type = [
            "null",
            {
                "logicalType": "timestamp-millis",
                "type": "long"
            }
        ]
    else:
        schema_type = [
            "null",
            field_type,
        ]

    return {
        "default": None,
        "name": name,
        "type": schema_type,
        "doc": doc,
        "_orig_type": field_type
    }
