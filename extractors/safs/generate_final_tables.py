#!python3

import argparse
import inflection
import logging

from extractors.common import common_logging_setup, get_args
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

from .db_connection import DbConnection, add_db_arguments
from .orm import make_table
from .schemas import f19x
from .schemas import domains


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _get_most_recent_domain(columns, table, partition_by,
                            order_by="school_year"):
    return f"""
        SELECT
            {columns}
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER(partition by {partition_by}
                                  ORDER BY {order_by} DESC) AS rn
            FROM {table}
            )
        WHERE rn=1
    """


def _make_insert(target_table, columns, select_sql):
    return f"""
    INSERT INTO
        {target_table}
        ({columns})
    {select_sql}
    """


class FinalTableGenerator(DbConnection):
    def generate_final_tables(self, drop_first):
        orm_classes = {}
        orm_classes.update(self._create_orm_classes(domains.ALL_SCHEMAS))
        orm_classes.update(self._create_orm_classes(f19x.ALL_SCHEMAS))

        if drop_first:
            logger.info("Dropping all tables")
            Base.metadata.drop_all(self.engine)

        logger.info("Creating tables")
        Base.metadata.create_all(self.engine)

        logger.info("Populating tables")
        with Session(self.engine) as session:
            self._populate_domain_tables(session)
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

    def _populate_domain_tables(self, session):
        logger.info("Populating domain")
        for schema in domains.ALL_SCHEMAS:
            target_tablename = schema['name']
            source_tablename = target_tablename[2:]  # strip leading d_
            source_tablename = f"f195_{source_tablename}"
            field_list = [(f['name'], f['source']) for f in schema['fields']
                          if f.get('source', None) is not None]
            primary_keys = [f['source'] for f in schema['fields']
                            if f.get('is_primary_key', False)]

            select_sql = _get_most_recent_domain(
                ', '.join([f[1] for f in field_list]),
                source_tablename,
                ', '.join(primary_keys)
            )

            insert_sql = _make_insert(target_tablename,
                                      ', '.join([f[0] for f in field_list]),
                                      select_sql)


            session.execute(text(insert_sql))
            break


    def _populate_general_fund_expenditures(self):
        pass

    def _populate_debt_service_fund_revenues(self):
        pass

    def _populate_capital_projects_revenues(self):
        pass

    def _populate_trans_vehicle_revenues(self):
        pass

    def _populate_ospi_items(self):
        pass


def _parse_args():
    parser = argparse.ArgumentParser(
        prog='generate_final_tables',
        description=(
            'Generates final tables using raw data loaded in from_access.py'))

    parser.add_argument('--db-drop-first', action="store_true",
                        help='Should drop the table before loading')

    common_logging_setup(parser)
    add_db_arguments(parser)

    return get_args(parser)


def main():
    args = _parse_args()

    generator = FinalTableGenerator(args)
    generator.generate_final_tables(args.db_drop_first)


if __name__ == '__main__':
    main()
