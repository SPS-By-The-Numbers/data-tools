#!python3

import argparse
import inflection
import logging

from extractors.common import common_logging_setup, get_args
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

from .db_connection import DbConnection, add_db_arguments
from .orm import make_table
from .schemas import f19x
from .schemas import domains
from .schemas import s275
from .schemas import enrollment
from .transforms.f19x import generate_f19x
from .transforms.s275 import generate_s275
from .transforms.enrollment import generate_enrollment


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class FinalTableGenerator(DbConnection):
    def generate_final_tables(self, drop_first, datasets):
        orm_classes = {}
        for d in datasets:
            if d == 's275':
                orm_classes.update(self._create_orm_classes(s275.ALL_SCHEMAS))

            if d == 'domains' or d == 'f19x':
                orm_classes.update(
                    self._create_orm_classes(domains.ALL_SCHEMAS))
                orm_classes.update(self._create_orm_classes(f19x.ALL_SCHEMAS))

            if d == 'enrollment':
                orm_classes.update(
                    self._create_orm_classes(enrollment.ALL_SCHEMAS))

        if drop_first:
            logger.info("Dropping all tables")
            Base.metadata.drop_all(self.engine)

        logger.info("Creating tables")
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as session:
            for d in datasets:
                if d == 's275':
                    generate_s275(session)

                if d == 'f19x':
                    generate_f19x(session)

                if d == 'enrollment':
                    generate_enrollment(session)
            session.commit()

    def _create_orm_classes(self, schemas):
        orm_classes = {}
        for schema in schemas:
            table_name = schema["name"]
            class_name = inflection.camelize(table_name)
            orm_class = type(class_name,
                             (Base,),
                             {"__table__": make_table(schema, Base)})
            orm_classes[table_name] = orm_class

        return orm_classes


def _parse_args():
    parser = argparse.ArgumentParser(
        prog='generate_final_tables',
        description=(
            'Generates final tables using raw data loaded in from_access.py'))

    parser.add_argument('--db-drop-first', action="store_true",
                        help='Should drop the table before loading')
    parser.add_argument('datasets', nargs="+",
                        choices=['f19x', 's275', 'domains', 'enrollment'],
                        help=('Datasets to dump. f19x, s275, enrollment '
                              'or domains'))

    common_logging_setup(parser)
    add_db_arguments(parser)

    return get_args(parser)


def main():
    args = _parse_args()

    generator = FinalTableGenerator(args)
    generator.generate_final_tables(args.db_drop_first, args.datasets)


if __name__ == '__main__':
    main()
