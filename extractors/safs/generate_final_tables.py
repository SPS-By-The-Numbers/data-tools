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
            AND school_year is not NULL
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


def _make_upsert(source_table, target_table, column_map, unique_columns):
    select_sql = _get_most_recent_domain(
        ', '.join(column_map.keys()),
        source_table,
        unique_columns
    )

    return text(_make_insert(
        target_table,
        column_map.values(),
        ', '.join(unique_columns),
        f'{target_table}.school_year <= EXCLUDED.school_year',
        select_sql))


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
        self._populate_domain_program(session)
        self._populate_domain_activity(session)
        self._populate_domain_object(session)
        self._populate_domain_nces(session)
        self._populate_domain_ccddd(session)
        self._populate_domain_county(session)
        self._populate_domain_school(session)
        self._populate_domain_fund(session)
        self._populate_domain_subfund(session)
        self._populate_domain_duty_root(session)
        self._populate_domain_duty_suffix(session)

    def _populate_domain_program(self, session):
        logger.info("Populating d_program")
        session.execute(
            _make_upsert(source_table='f196_program',
                         target_table='d_program',
                         column_map={
                             'program_code': 'program_code',
                             'description': 'program',
                             'short_description': 'short_description',
                             'notes': 'notes',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['program_code']
                         ))
        session.execute(
            _make_upsert(source_table='f195_program',
                         target_table='d_program',
                         column_map={
                             'program_code': 'program_code',
                             'title': 'program',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['program_code']
                         ))

    def _populate_domain_activity(self, session):
        logger.info("Populating d_activity")
        session.execute(
            _make_upsert(source_table='f196_activity',
                         target_table='d_activity',
                         column_map={
                             'activity_code': 'activity_code',
                             'description': 'activity',
                             'short_description': 'short_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['activity_code']
                         ))
        session.execute(
            _make_upsert(source_table='f195_activity',
                         target_table='d_activity',
                         column_map={
                             'activity_code': 'activity_code',
                             'description': 'activity',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['activity_code']
                         ))

    def _populate_domain_object(self, session):
        session.execute(
            _make_upsert(source_table='f196_object',
                         target_table='d_object',
                         column_map={
                             'object_code': 'object_code',
                             'description': 'object',
                             'short_description': 'short_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['object_code']
                         ))

    def _populate_domain_nces(self, session):
        logger.info("skipping d_nces")
        return

    def _populate_domain_ccddd(self, session):
        logger.info("Populating d_ccddd")
        session.execute(
            _make_upsert(source_table='f195_ccddd',
                         target_table='d_ccddd',
                         column_map={
                             'ccddd': 'ccddd',
                             'name': 'district',
                             'county_code': 'county_code',
                             'district_code': 'district_code',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['ccddd']
                         ))

    def _populate_domain_county(self, session):
        logger.info("Populating d_county")
        session.execute(
            _make_upsert(source_table='f195_county',
                         target_table='d_county',
                         column_map={
                             'county_code': 'county_code',
                             'name': 'county',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['county_code']
                         ))

    def _populate_domain_school(self, session):
        logger.info("Skipping d_school")
        return
        session.execute(
            _make_upsert(source_table='f195_county',
                         target_table='d_county',
                         column_map={
                             'county_code': 'county_code',
                             'name': 'county',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['county_code']
                         ))

    def _populate_domain_fund(self, session):
        logger.info("Populating d_fund")
        session.execute(
            _make_upsert(source_table='f195_fund',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'fund_name': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))

    def _populate_domain_subfund(self, session):
        logger.info("Skipping d_subfund")
        return
        session.execute(
            _make_upsert(source_table='f195_fund',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'fund_name': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))

    def _populate_domain_duty_root(self, session):
        logger.info("Skipping d_duty_root")
        return
        session.execute(
            _make_upsert(source_table='f195_fund',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'fund_name': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))

    def _populate_domain_duty_suffix(self, session):
        logger.info("Skipping d_duty_suffix")
        return
        session.execute(
            _make_upsert(source_table='f195_fund',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'fund_name': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))

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
