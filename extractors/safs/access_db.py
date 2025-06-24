from decimal import Decimal

from .avro_schema import DECIMAL_QUANT_AMOUNT


def clean_string(x):
    """Basic string cleanup"""
    return x.strip()


def title_case(x):
    """Turns string into title case"""
    return clean_string(x).title()


def int_or_null(x):
    """Parses value as an int or null"""
    x = clean_string(x)
    if x:
        return int(x)

    return None


def decimal_or_null(x):
    """Parses value as a decimal or null"""
    x = clean_string(x)
    if x:
        return Decimal(x).quantize(DECIMAL_QUANT_AMOUNT)

    return None


def program_activity_or_null(x):
    """Normalize Program and Activity codes.

    s275 has SB and CP for ASB and Capital Projects fund. These are not
    standard. Here we use negative codes which is outside the valid range for
    them program and activity codes. This lets use use an int field.
    """
    x = clean_string(x)
    if x == 'SB':
        return -100
    if x == 'CP':
        return -200
    return int(x)
