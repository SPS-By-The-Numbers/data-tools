#!python3

import argparse
import fastavro
import logging

from pathlib import Path

from sqlalchemy.orm import Session

from ..common import common_logging_setup, get_args
from .schemas import s275
from . import s275_orm

logger = logging.getLogger(__name__)


def to_avro_type(field_type):
    match field_type:
        case 'decimal':
            return [
                'null',
                {
                    "type": "bytes",
                    "logicalType": "decimal",
                    "precision": 38,
                    "scale": 9,
                }]

        case 'string':
            return ['null', 'string']

        case 'timestamp':
            return ['null', {
                'type': 'long',
                'logicalType': 'timestamp-millis'
            }]

        case 'int':
            return ['null', 'int']

        case 'auto_primary_key':
            return ['null', 'int']

        case 'boolean':
            return ['null', 'boolean']

        case _:
            raise ValueError(f"Unknown Field type {field_type}")


def to_avro_schema(schema):
    return {
        "name": schema["name"],
        "doc": schema["doc"],
        "type": "record",
        "fields": [
            {
                "name": f["name"],
                "doc": f["doc"],
                "type": to_avro_type(f["field_type"])
            }
            for f in schema["fields"]
        ]
    }


def to_avro_value(field, value):
    if value is None:
        return None

    # Convert hacked up null values cause SQL NULL sucks uniqueness constraints
    # back to None.
    sentinel = s275_orm.get_null_sentinel(field["field_type"],
                                          none_instead_of_raise=True)
    if value == sentinel:
        return None

    # Do any field conversions needed here.
    match field["field_type"]:
        case 'timestamp':
            return int(value.timestamp() * 1000)

    return value


class NormalizedS275Dumper(s275_orm.DbConnection):
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

            for tablename, schema in s275.TABLENAME_SCHEMA_MAP.items():
                orm_class = s275_orm.TABLENAME_ORM_CLASS_MAP[tablename]
                self.write_table(session, orm_class, schema, outdir, outprefix)


def main():
    parser = argparse.ArgumentParser(
        description='Combines raw s275 avro files into normalized tables')
    parser.add_argument('--outprefix', default="s275-",
                        help='Prefix for avro filenamess')
    parser.add_argument('--outdir', required=True,
                        help='directory for set of normalized avro tables"')
    s275_orm.add_orm_arguments(parser)
    common_logging_setup(parser)

    args = get_args(parser)

    normalized_s275 = NormalizedS275Dumper(args.engine)

    normalized_s275.write_all_tables(args.outprefix, args.outdir)


if __name__ == '__main__':
    main()
