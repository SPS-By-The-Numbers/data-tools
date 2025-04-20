import re
from decimal import Decimal

SPACE_SPAN_TO_TOKEN = re.compile(r"\s\s+")

DOLLAR_REALIGN = re.compile(r"\s\$\s*([0-9][0-9,]*|-)(?:\s|$)")


def tokenize_by_two_space(line):
    """For fields separated by a many spaces, break by spans of 2+ spaces"""
    return [field.strip() for field in
            re.sub(SPACE_SPAN_TO_TOKEN, "\t", line).split("\t")]


def realign_dollar_sign(line):
    """Make sure dollarsigns connect to their number and have spaces in front.

    Sometimes the $ gets placed in weird spots in the field.  If there is a
    free-floating one, make sure it connects to the number to the right of it
    and that there are at least 2 spaces to the left so it can broken into a
    field easily.
    """
    return re.sub(DOLLAR_REALIGN, r"  $\1  ", line).strip()


def identity(x):
    return x


def to_number(x):
    x = x.replace(',', '')
    return Decimal(x)


def to_number_dash_zero(x):
    if x == '-':
        return Decimal(0)
    return to_number(x)


def pop_read(fields, validation_re, convert=identity, raise_invalid=True):
    if len(fields) == 0:
        if raise_invalid:
            raise ValueError("Ran out of fields")
        return None

    token = fields[-1]
    if validation_re is not None and not re.fullmatch(validation_re, token):
        if raise_invalid:
            raise ValueError(f"Failed validation: {token}")
        return None

    # Pop here so that if raise_invalid=False, the fields are undisturbed.
    fields.pop()
    return convert(token)


# Regular expression for fields.
"""A Dollar amount with leading dollarsign and commas"""
RE_DOLLAR_COMMA = re.compile(r'\$[0-9,]+')

"""A Dollar amount with leading dollarsign and commas, dash is zero"""
RE_DOLLAR_COMMA_DASH = re.compile(r'\$(?:[0-9,]+|-)')

"""Decimal number"""
RE_DECIMAL = re.compile(r'[0-9]+\.[0-9]+')

"""Decimal number with commas"""
RE_DECIMAL_COMMA = re.compile(r'[0-9,]+\.[0-9]+')

"""Decimal number with commas, dash is zero"""
RE_DECIMAL_COMMA_DASH = re.compile(r'[0-9,]+\.[0-9]+|-')

"""Decimal number, dash is zero"""
RE_DECIMAL_DASH = re.compile(r'[0-9]+\.[0-9]+|-')

"""Integer"""
RE_INT = re.compile(r'[0-9]+')

"""Integer with commas"""
RE_INT_COMMA = re.compile(r'[0-9,]+')

"""Integer with ccommans, dash is zero"""
RE_INT_COMMA_DASH = re.compile(r'[0-9,]+|-')

"""Integer with ccommans, dash is zero"""
RE_NUMBER_COMMA_DASH = re.compile(r'[0-9,]+(?:\.[0-9]+)?|-')

"""Integer, dash is zero"""
RE_INT_DASH = re.compile(r'[0-9]+|-')

"""Alphanumeric, no spaces"""
RE_ALPHANUM_NO_SPACES = re.compile(r'[A-Za-z0-9]+')

"""Alphanumeric with spaces"""
RE_ALPHANUM_SPACES = re.compile(r'[A-Za-z0-9 ]+')

"""Alphanumeric with spaces and dashes"""
RE_ALPHANUM_SPACES_DASH = re.compile(r'[A-Za-z0-9 \-+/]+')

"""Alphanumeric with spaces and dashes"""
RE_ALPHANUM_SPACES_DASH_PERIOD = re.compile(r'[A-Za-z0-9 \.\-+/]+')

"""Alphanumeric, no spaces, dashes-okay, lowercase only"""
RE_ALPHANUM_LOWER_DASH = re.compile(r'[0-9a-z-]+')

"""Alphanumeric, no spaces, uppercase only"""
RE_ALPHANUM_UPPER = re.compile(r'[0-9A-Z]+')

"""Any non-empty string"""
RE_NON_EMPTY = re.compile(r'.+')

"""Any non-space string"""
RE_NON_SPACE = re.compile(r'\S+')
