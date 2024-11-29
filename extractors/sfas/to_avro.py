import csv
import datetime
import dateutil
import fastavro
import os
import logging
import sys

logger = logging.getLogger(__name__)

logging.basicConfig(level='INFO')


IN_CSV = "ActualsChildGeneralFundExpenditures (safs3dw).csv"


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
            return ['null', 'double']

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
            return float(value)

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
    inputcsv = sys.argv[1]
    dataset_name = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    with open(inputcsv, "r", encoding="utf-8") as infile:
        reader = csv.reader(infile)
        with open(f'output/{dataset_name}.avro', "wb") as outfile:
            process(reader, outfile)


if __name__ == '__main__':
    main()
