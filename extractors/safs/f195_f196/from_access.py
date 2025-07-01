#!python3

import argparse
import logging

from extractors.safs.mdb_reader import MdbReader
from extractors.safs.f195_f196 import f195

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        prog='f195_f196_access',
        description='Converts and access database to avro format')

    parser.add_argument('--datatype', default="f196",
                        choices=['f195', 'f196'],
                        help='Which data type to be loading')
    parser.add_argument('--infile', required=True, help='inputfile')

    args = parser.parse_args()

    if args.datatype == "f195":
        reader = MdbReader(args.infile,
                           f195.tablename_normalizer,
                           header_to_schema=f195.header_to_schema)

    for t in reader.tables:
        print(t)

    for r in reader.as_avro_records("object"):
        print(r)


if __name__ == '__main__':
    main()
