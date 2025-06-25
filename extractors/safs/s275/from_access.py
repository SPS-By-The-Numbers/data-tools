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

from extractors.safs import access_csv, avro_schema


def get_s275_column_config(field_name):
    match field_name:
        case ("cou" | "dis" | "codist" | "parea" |
              "darea" | "droot" | "dsufx" | "bldgn"):
            return (avro_schema.to_avro_field(field_name, "int"),
                    access_csv.int_or_null)

        case ("prog" | "act"):
            return (avro_schema.to_avro_field(field_name, "int"),
                    access_csv.program_activity_or_null)

        case ("asssal" | "cins" | "cman" | "certbase" | "clasbase" |
              "othersal" | "tfinsal" |
              "ftehrs" | "ftedays" | "certfte" | "clasfte" | "exp" |
              "camix1" | "asspct" | "assfte" | "asshpy" |
              "acred" | "icred" | "bcred" | "vcred"):
            return (avro_schema.to_avro_field(field_name, "decimal"),
                    access_csv.decimal_or_null)

        case "SchoolYear":
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_csv.clean_string)

        case ("FirstName" | "MiddleName" | "LastName"):
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_csv.title_case)

        case _:
            return (avro_schema.to_avro_field(field_name, "string"),
                    access_csv.clean_string)


def main():
    parser = argparse.ArgumentParser(
        prog='s275_access',
        description='Converts and access database to avro format')

    access_csv.add_access_csv_arguments(parser)
    args = parser.parse_args()

    converter = access_csv.AccessCsvConverter("s275_data", args,
                                              get_s275_column_config)
    converter.parse()
    converter.write()


if __name__ == '__main__':
    main()
