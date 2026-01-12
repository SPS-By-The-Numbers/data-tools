#!python3

import argparse
import fastavro
import logging

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from extractors.common import common_logging_setup, get_args
from extractors.safs.avro_schema import to_avro_value, to_avro_schema
from .schemas import f19x, s275, assessment, domains, enrollment, sqss
from .db_connection import DbConnection, add_db_arguments


logger = logging.getLogger(__name__)


class AvroDumper(DbConnection):
    def __init__(self, args):
        super().__init__(args)
        self._yield_per = args.yield_per

    def _to_avro_rows(self, session, schema):
        for row in (session.execute(text(f"select * from {schema['name']}"))
                    .yield_per(self._yield_per)):
            yield {f['name']: to_avro_value(f, getattr(row, f['name']))
                   for f in schema['fields']}

    def write_table(self, session, outdir, schema):
        tablename = schema['name']
        logger.info(f"Writing {tablename} to {outdir}")
        with open(outdir / f"{tablename}.avro", "wb") as outfile:
            fastavro.writer(outfile,
                            fastavro.parse_schema(to_avro_schema(schema)),
                            self._to_avro_rows(session, schema),
                            codec='zstandard')

    def write_all_tables(self, session, outdir, dataset):
        match dataset:
            case 'f19x':
                all_schemas = f19x.ALL_SCHEMAS

            case 's275':
                all_schemas = s275.ALL_SCHEMAS

            case 'domains':
                all_schemas = domains.ALL_SCHEMAS

            case 'enrollment':
                all_schemas = enrollment.ALL_SCHEMAS

            case 'assessment':
                all_schemas = assessment.ALL_SCHEMAS

            case 'sqss':
                all_schemas = sqss.ALL_SCHEMAS

            case _:
                raise ValueError(dataset)

        for schema in all_schemas:
            self.write_table(session, outdir, schema)

    def write_all_datasets(self, outdir_str, datasets):
        with Session(self._engine) as session:
            for d in datasets:
                outdir = Path(outdir_str) / d

                logging.info(f"Ensuring {outdir} exists")
                outdir.mkdir(parents=True, exist_ok=True)

                self.write_all_tables(session, outdir, d)


def main():
    parser = argparse.ArgumentParser(
        description='Dumps finalized tables out into avro')
    parser.add_argument('--outdir', required=True,
                        help='directory for set finalized avro tables')
    parser.add_argument('--yield-per', default=1000,
                        help='How many rows to select before writing')
    parser.add_argument('datasets', nargs="+",
                        choices=['f19x', 's275', 'assessment', 'domains',
                                 'enrollment', 'sqss'],
                        help=('Datasets to dump. f19x, s275, enrollment, '
                              'assessment, sqss, or domains'))
    add_db_arguments(parser)
    common_logging_setup(parser)

    args = get_args(parser)

    AvroDumper(args).write_all_datasets(args.outdir, args.datasets)


if __name__ == '__main__':
    main()
