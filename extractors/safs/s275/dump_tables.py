#!python3

import argparse
import fastavro
import logging

from pathlib import Path

from sqlalchemy.orm import Session

from extractors.common import common_logging_setup, get_args
from extractors.safs.avro_schema import (to_avro_value, to_avro_schema)
from . import schemas
from . import orm

logger = logging.getLogger(__name__)


class NormalizedS275Dumper(orm.DbConnection):
    def _to_avro_row(self, session, table, schema):
        for row in session.query(table).yield_per(1000):
            yield {f['name']: to_avro_value(f, getattr(row, f['name']))
                   for f in schema['fields']}

    def write_table(self, session, table, schema, outdir, outprefix):
        logger.info(f"Writing {schema['name']} to {outdir}")
        with open(outdir /
                  f"{outprefix}{schema['name']}.avro", "wb") as outfile:
            fastavro.writer(outfile,
                            fastavro.parse_schema(to_avro_schema(schema)),
                            self._to_avro_row(session, table, schema),
                            codec='zstandard')

    def write_all_tables(self, outprefix, outdir_str):
        with Session(self._engine) as session:
            outdir = Path(outdir_str)

            for tablename, schema in schemas.TABLENAME_SCHEMA_MAP.items():
                orm_class = orm.TABLENAME_ORM_CLASS_MAP[tablename]
                self.write_table(session, orm_class, schema, outdir, outprefix)


def main():
    parser = argparse.ArgumentParser(
        description='Combines raw s275 avro files into normalized tables')
    parser.add_argument('--outprefix', default="s275-",
                        help='Prefix for avro filenamess')
    parser.add_argument('--outdir', required=True,
                        help='directory for set of normalized avro tables"')
    orm.add_orm_arguments(parser)
    common_logging_setup(parser)

    args = get_args(parser)

    normalized_s275 = NormalizedS275Dumper(args)

    normalized_s275.write_all_tables(args.outprefix, args.outdir)


if __name__ == '__main__':
    main()
