import argparse
import csv

from decimal import Decimal
import fastavro

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


class AccessCsvConverter:
    def __init__(self, name, args, get_column_config):
        self._rows = []
        self._schema = None
        self._name = name
        self._infile = args.infile
        self._outfile = args.outfile
        self._get_column_config = get_column_config

    def parse(self):
        reader = csv.reader(self._infile)
        header = None

        for row in reader:
            if self._schema is None:
                header = row
                self._schema = self._make_schema_from_header(header)
            else:
                fields = zip(header, row)
                self._rows.append(
                    dict([(h, self._convert(h, v)) for h, v in fields]))

    def write(self):
        fastavro.writer(self._outfile,
                        fastavro.parse_schema(self._schema),
                        self._rows,
                        codec="zstandard")

    def _convert(self, field_name, value):
        try:
            return self._get_column_config(field_name)[1](value)
        except Exception as e:
            print(f"Failed on '{field_name}' for '{value}'", e)

    def _make_schema_from_header(self, header):
        return {
            "type": "record",
            "namespace": "spsbythenumbers",
            "name": self._name,
            "fields": [self._get_column_config(h)[0] for h in header]
        }


def add_access_csv_arguments(parser):
    parser.add_argument('--infile', required=True,
                        type=argparse.FileType('r'),
                        help='csv inputfile')
    parser.add_argument('--outfile', required=True,
                        type=argparse.FileType('wb'),
                        help='output file avro')
