import argparse
import csv
import datetime
import dateutil
import fastavro
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

logging.basicConfig(level='INFO')


def to_bq_name(name):
    return name.replace(' ', '_').lower()


def to_type(name):
    match name:
        case ("Activity Code" |
              "County District Code" |
              "Fund Code" |
              "NCES Code" |
              "Object Code" |
              "Program Code" |
              "Revenue Code" |
              "County District Code" |
              "School Code"):
            return ['null', 'int']

        case ("Amount"):
            return [
                'null',
                {
                    "type": "bytes",
                    "logicalType": "decimal",
                    "precision": 38,
                    "scale": 9,
                }]

        case ("Last Updated"):
            return ['null', {
                'type': 'int',
                'logicalType': 'timestamp-millis'
            }]

        case _:
            return ['null', 'string']


def infer_schema(val):
    name = val.replace('\ufeff', '').strip()
    return {
        'name': to_bq_name(name),
        'type': to_type(name)
    }


def header_to_schema(row):
    return {
        'name': 'sfas',
        'type': 'record',
        'fields': [infer_schema(val) for val in row]
    }


def parse_value(name, value):
    match name:
        case ("Activity Code" |
              "County District Code" |
              "Fund Code" |
              "NCES Code" |
              "Object Code" |
              "Program Code" |
              "Revenue Code" |
              "County District Code" |
              "School Code"):
            if value == '':
                return None
            return int(value)

        case ("Amount"):
            if value == '':
                return None
            return Decimal(value)

        case ("Last Updated"):
            if value == '':
                return None
            dt = dateutil.parser.parse(value).astimezone(
                tz=datetime.timezone.utc)
            return int(dt.timestamp())

        case _:
            return value


def process(reader, outfile):
    header = None
    rows = []
    is_codes = False
    for row in reader:
        # If a codes file is found, drop the first 2 values. That's the row
        # number and an empty column.

        if is_codes:
            row = row[2:]

        if header is None:
            # Skip weird first row excel artifact in export of codes sheet.
            if len(row) > 2 and row[0] == '' and row[1] == 'Unnamed: 0':
                is_codes = True
                continue

            header = row
        else:
            vals = [(to_bq_name(name), parse_value(name, val))
                    for name, val in zip(header, row)]
            rows.append(dict(vals))
    fastavro.writer(outfile,
                    schema=fastavro.parse_schema(
                        header_to_schema(header)),
                    records=rows,
                    codec='zstandard')


def main():
    parser = argparse.ArgumentParser(
        prog='f196_load',
        description='Converts and access database to avro format')

    parser.add_argument('--infile', required=True, help='csv inputfile')
    parser.add_argument('--outfile', required=True, help='output file avro')

    args = parser.parse_args()

    with open(args.infile, "r", encoding="utf-8", newline='') as infile:
        reader = csv.reader(infile)
        with open(args.outfile, "wb") as outfile:
            process(reader, outfile)


if __name__ == '__main__':
    main()
