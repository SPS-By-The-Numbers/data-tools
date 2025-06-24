#!python3

"""
This script turns a s275 access database into an avro file with fields
stripped.

Convert the accdb to csv first by running mdb-export from mdbtools with a
command like

$ mdb-export 2022-2023_Final_S-275_Personnel_Database.accdb \
    2022-2023S-275FinalForPublic

Do NOT attempt to use python only tools for this. They are slow and not
complete. The mdbtools binaries are the best way to convert to a csv.
"""

import argparse
import csv
import fastavro

from extractors.safs import access_db, avro_schema


def s275_col_to_avro_field_and_extractor(field_name):
    match field_name:
        case ("cou" | "dis" | "codist" | "parea" |
              "darea" | "droot" | "dsufx" | "bldgn"):
            return (avro_schema.to_avro_field(field_name, "int"),
                    access_db.int_or_null)

        case ("prog" | "act"):
            return (avro_schema.to_avro_field(field_name, "int"),
                    access_db.program_activity_or_null)

        case ("asssal" | "cins" | "cman" | "certbase" | "clasbase" |
              "othersal" | "tfinsal" |
              "ftehrs" | "ftedays" | "certfte" | "clasfte" | "exp" |
              "camix1" | "asspct" | "assfte" | "asshpy" |
              "acred" | "icred" | "bcred" | "vcred"):
            return (avro_schema.to_avro_field(field_name, "decimal"),
                    access_db.decimal_or_null)

        case "SchoolYear":
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_db.clean_string)

        case ("FirstName" | "MiddleName" | "LastName"):
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_db.title_case)

        case _:
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_db.clean_string)


def make_schema(header):
    return {
        "type": "record",
        "namespace": "spsbythenumbers",
        "name": "S275Data",
        "fields": [s275_col_to_avro_field_and_extractor(h)[0] for h in header]
    }


def convert(field_name, value):
    try:
        return s275_col_to_avro_field_and_extractor(field_name)[1](value)
    except Exception as e:
        print(f"Failed on '{field_name}' for '{value}'", e)


def main():
    parser = argparse.ArgumentParser(
        prog='s275_access',
        description='Converts and access database to avro format')

    parser.add_argument('--infile', required=True, help='csv inputfile')
    parser.add_argument('--outfile', required=True, help='output file avro')

    args = parser.parse_args()

    rows = []
    with open(args.infile, newline='') as infile:
        reader = csv.reader(infile)
        schema = None
        headers = None

        for row in reader:
            if schema is None:
                headers = row
                schema = make_schema(row)
            else:
                fields = zip(headers, row)
                rows.append(dict([(h, convert(h, v)) for h, v in fields]))

    with open(args.outfile, "wb") as outfile:
        fastavro.writer(outfile,
                        fastavro.parse_schema(schema),
                        rows,
                        codec="zstandard")


if __name__ == '__main__':
    main()
