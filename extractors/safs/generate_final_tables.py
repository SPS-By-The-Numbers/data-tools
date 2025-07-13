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


def _get_most_recent_domain(columns, table, primary_keys,
                            order_by="school_year"):
    partition_by = ', '.join(primary_keys)

    # Raw source tables will have no error checking for nullness of pks.
    null_remove = ' AND '.join([f'{pk} IS NOT NULL' for pk in primary_keys])
    return f"""
        SELECT
            {columns}
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER(partition by {partition_by}
                                  ORDER BY {order_by} DESC) AS rn
            FROM {table}
            WHERE {null_remove}
            )
        WHERE rn=1
    """


def _make_insert(target_table, columns, conflict_clause, conflict_where,
                 select_sql):
    set_clause = ', '.join([f"{c}=EXCLUDED.{c}" for c in columns])
    return f"""
    INSERT INTO
        {target_table}
        ({', '.join(columns)})
        {select_sql}
    ON CONFLICT({conflict_clause})
    DO UPDATE SET {set_clause}
    WHERE {conflict_where}
    """


def _make_upsert(source_table, target_table, column_map, primary_keys):
    select_sql = _get_most_recent_domain(
        ', '.join(column_map.keys()),
        source_table,
        primary_keys
    )

    return text(_make_insert(
        target_table,
        column_map.values(),
        ', '.join(primary_keys),
        f'{target_table}.school_year < EXCLUDED.school_year',
        select_sql))


def _prefixes_for_domain(domain):
    match domain:
        case 'program' | 'activity' | 'object':
            return ['f195', 'f196']

        case 'nces' | 'subfund':
            # return ['f196']
            return []

        case 'duty_root' | 'duty_suffix':
            # return ['s275']
            return []

        case 'ccddd' | 'county':
            return ['f195']

        case 'fund':
            return ['f195']


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
        session.execute(
            _make_upsert('f195_program',
                         'd_program',
                         {
                             'program_code': 'program_code',
                             'title': 'program',
                         },
                         ['program_code']
                         ))
        session.execute(
            _make_upsert('f196_program',
                         'd_program',
                         {
                             'program_code': 'program_code',
                             'description': 'program',
                         },
                         ['program_code']
                         ))
        return

        for schema in domains.ALL_SCHEMAS:
            target_tablename = schema['name']
            field_list = [(f['name'], f['source']) for f in schema['fields']
                          if f.get('source', None) is not None]
            primary_keys = [f['source'] for f in schema['fields']
                            if f.get('is_primary_key', False)]

            domain = target_tablename[2:]  # strip leading d_
            for prefix in _prefixes_for_domain(domain):
                source_tablename = f"{prefix}_{domain}"

                select_sql = _get_most_recent_domain(
                    ', '.join([f[1] for f in field_list]),
                    source_tablename,
                    primary_keys
                )

                insert_sql = _make_insert(
                    target_tablename,
                    [f[0] for f in field_list],
                    ', '.join(primary_keys),
                    f'{target_tablename}.school_year < EXCLUDED.school_year',
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
