#!python3

import argparse
import inflection
import logging

from extractors.common import common_logging_setup, get_args
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

from .avro_schema import get_null_sentinel
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


def _make_insert_impl(target_table, columns, conflict_clause, conflict_where,
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
    """Merges the source table into the target table.

    column_map is a dictionary of column names. Key is source. Value is
    destination.
    """
    select_sql = _get_most_recent_domain(
        ', '.join(column_map.keys()),
        source_table,
        unique_columns
    )

    return text(_make_insert_impl(
        target_table,
        column_map.values(),
        ', '.join(unique_columns),
        f'{target_table}.school_year <= EXCLUDED.school_year',
        select_sql))


def _populate_revenue_table(self, session, data_type, fund_name):
    logger.info("Populating general_fund_expenditures with child actuals")

    extra_columns = ""
    extra_values = ""

    if data_type == 'Actuals':
        extra_columns = f"""
            accounting_item_id,
            actuals_{fund_name}_revenues_id,
        """
        extra_values = f"""
            t.accounting_item_id,
            t.actuals_{fund_name}_revenues_id,
        """

    session.execute(text(
        f"""
        INSERT INTO {fund_name}_revenues (
            data_type,
            fund_code,
            fund,

            revenue_code,
            revenue,

            category_code,
            category,

            program_code,
            program,

            amount,

            {extra_columns}

            school_year,
            school_starting_year,
            _source,
            _source_table
        )
        SELECT
            'Budget',

            t.fund_code,
            f.fund,

            t.revenue_code,
            r.revenue,

            r.category_code,
            r.category,

            r.program_code,
            p.program,

            t.amount,

            {extra_values}

            t.school_year,
            CAST(SPLIT_PART(t.school_year, '-', 1) AS INTEGER)
                AS school_starting_year,
            t._source,
            t._source_table
        FROM f196_{fund_name}_revenues t
        LEFT JOIN d_fund f ON (t.fund_code = f.fund_code)
        LEFT JOIN d_revenue r ON (t.revenue_code = r.revenue_code)
        LEFT JOIN d_program p ON (r.program_code = p.program_code)
        LIMIT 100
        """
    ))


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
            self._populate_general_fund_expenditures_from_budget(session)
            self._populate_general_fund_expenditures_from_actuals(session)
            self._populate_general_fund_expenditures_from_child_actuals(
                session)
            self._populate_debt_service_fund_revenues(session)
            self._populate_capital_projects_revenues(session)
            self._populate_trans_vehicle_revenues(session)
            self._populate_ospi_items(session)
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
        self._populate_domain_revenue(session)
        self._populate_domain_school(session)
        self._populate_domain_fund(session)
        self._populate_domain_subfund(session)
        self._populate_domain_duty_root(session)
        self._populate_domain_duty_suffix(session)

    def _populate_domain_program(self, session):
        logger.info("Populating d_program")
        session.execute(
            _make_upsert(source_table='spsbtn_programs',
                         target_table='d_program',
                         column_map={
                             'program_code': 'program_code',
                             'program_f196': 'program',
                             'sps_program_grouping_augmented':
                                'sps_program_grouping',
                             'sps_program_grouping':
                                'raw_sps_program_grouping',
                             'program_per_pupil': 'per_pupil_program',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['program_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_program',
                         target_table='d_program',
                         column_map={
                             'program_code': 'program_code',
                             'description': 'program',
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
                             'description': 'program',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['program_code']
                         ))

    def _populate_domain_activity(self, session):
        logger.info("Populating d_activity")
        session.execute(
            _make_upsert(source_table='spsbtn_activities',
                         target_table='d_activity',
                         column_map={
                             'activity_code': 'activity_code',
                             'activity': 'activity',
                             'sps_budget_category': 'sps_activity_category',
                             'collapsed': 'simplfied_activity',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['activity_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_activity',
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
            _make_upsert(source_table='spsbtn_object',
                         target_table='d_object',
                         column_map={
                             'object_code': 'object_code',
                             'object_description': 'object',
                             'object_type': 'object_type',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['object_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_object',
                         target_table='d_object',
                         column_map={
                             'object_code': 'object_code',
                             'description': 'object',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['object_code']
                         ))

    def _populate_domain_nces(self, session):
        session.execute(
            _make_upsert(source_table='spsbtn_nces',
                         target_table='d_nces',
                         column_map={
                             'nces_code': 'nces_code',
                             'nces_description': 'nces',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['nces_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_nces',
                         target_table='d_nces',
                         column_map={
                             'nces_code': 'nces_code',
                             'description': 'nces',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['nces_code']
                         ))

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

    def _populate_domain_revenue(self, session):
        logger.info("Populating d_revenue")
        session.execute(
            _make_upsert(source_table='f195_revenue',
                         target_table='d_revenue',
                         column_map={
                             'revenue_code': 'revenue_code',
                             'description': 'revenue',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['revenue_code']
                         ))
        session.execute(
            text("""
                 UPDATE d_revenue
                 SET
                    program_code = revenue_code % 100,
                    category_code = FLOOR(revenue_code/1000) * 1000,
                    category = CASE
                        WHEN FLOOR(category_code / 1000) = 1
                            THEN 'Local Taxes'
                        WHEN FLOOR(category_code / 1000) = 2
                            THEN 'Local Non-tax'
                        WHEN FLOOR(category_code / 1000) = 3
                            THEN 'State-General Purpose'
                        WHEN FLOOR(category_code / 1000) = 4
                            THEN 'State-Special Purpose'
                        WHEN FLOOR(category_code / 1000) = 5
                            THEN 'Federal-General Purpose'
                        WHEN FLOOR(category_code / 1000) = 6
                            THEN 'Federal-Special Purpose'
                        WHEN FLOOR(category_code / 1000) = 7
                            THEN 'Revenues from Other School Districts'
                        WHEN FLOOR(category_code / 1000) = 8
                            THEN 'Revenues from Other Agencies and Associations'
                        WHEN FLOOR(category_code / 1000) = 9
                            THEN 'Other Financing Sources'
                    END
                 """
        ))

    def _populate_domain_school(self, session):
        logger.info("Populating d_school")
        # TODO: Incorportate the sps btn schools override once we get it more
        # normalized.
        session.execute(
            _make_upsert(source_table='f196_school',
                         target_table='d_school',
                         column_map={
                             'school_code': 'school_code',
                             'school_district': 'school_and_district',
                             'school_year': 'school_year',
                             'ccddd': 'ccddd',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['school_code']
                         ))

        # The domain table has school and district with a dash at the end.
        # Extract just the school name.
        session.execute(
            text(
                """
                UPDATE d_school
                SET school = TRIM(SUBSTRING(school_and_district FROM 1 FOR
                    CASE
                        WHEN POSITION('-' IN school_and_district) > 0
                        THEN LENGTH(school_and_district) -
                                POSITION('-' IN REVERSE(school_and_district))
                        ELSE LENGTH(school_and_district)
                    END
                ))
                WHERE school_and_district IS NOT NULL;
                """
            )
        )

        # District office seems to be all school codes < 1500.
        session.execute(
            text(
                """
                UPDATE d_school
                SET is_district_office = (school_code <= 1500)
                """
            )
        )

    def _populate_domain_fund(self, session):
        logger.info("Populating d_fund")
        session.execute(
            _make_upsert(source_table='spsbtn_funds',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'fund': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_fund',
                         target_table='d_fund',
                         column_map={
                             'fund_code': 'fund_code',
                             'description': 'fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['fund_code']
                         ))
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
        logger.info("Populating d_sub_fund")
        session.execute(
            _make_upsert(source_table='spsbtn_sub_funds',
                         target_table='d_sub_fund',
                         column_map={
                             'sub_fund_code': 'sub_fund_code',
                             'sub_fund': 'sub_fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['sub_fund_code']
                         ))
        session.execute(
            _make_upsert(source_table='f196_sub_fund',
                         target_table='d_sub_fund',
                         column_map={
                             'sub_fund_code': 'sub_fund_code',
                             'description': 'sub_fund',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['sub_fund_code']
                         ))

    def _populate_domain_duty_root(self, session):
        logger.info("Populating d_duty_root")
        session.execute(
            _make_upsert(source_table='spsbtn_duty_root',
                         target_table='d_duty_root',
                         column_map={
                             'duty_root': 'duty_root',
                             'duty_name': 'duty_name',
                             'original_duty_pattern':
                                'original_duty_code_pattern',
                             'duty_category': 'duty_name_category',
                             'duty_name_description': 'duty_name_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['duty_root']
                         ))
        session.execute(
            _make_upsert(source_table='f196_duty_root',
                         target_table='d_duty_root',
                         column_map={
                             'duty_root': 'duty_root',
                             'duty_name': 'duty_name',
                             'duty_category': 'duty_name_category',
                             'duty_name_description': 'duty_name_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['duty_root']
                         ))

    def _populate_domain_duty_suffix(self, session):
        logger.info("Populating d_duty_suffix")
        session.execute(
            _make_upsert(source_table='spsbtn_duty_suffix',
                         target_table='d_duty_suffix',
                         column_map={
                             'duty_suffix': 'duty_suffix',
                             'contract_type': 'duty_contract_type',
                             'contract_type_description':
                                'duty_contract_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['duty_suffix']
                         ))
        session.execute(
            _make_upsert(source_table='f196_duty_suffix',
                         target_table='d_duty_suffix',
                         column_map={
                             'duty_suffix': 'duty_suffix',
                             'contract_type': 'duty_contract_type',
                             'contract_type_description':
                                'duty_contract_description',
                             'school_year': 'school_year',
                             '_source': '_source',
                             '_source_table': '_source_table',
                         },
                         unique_columns=['duty_suffix']
                         ))

    def _populate_general_fund_expenditures_from_budget(self, session):
        logger.info("Populating general_fund_expenditures with budget data")
        session.execute(text(
            f"""
            INSERT INTO general_fund_expenditures (
                -- constant data
                data_type,
                fund_code,
                fund,

                -- "nulled" columns for f195
                school_code,
                sub_fund_code,
                nces_code,

                -- Real data
                ccddd,
                district,
                county,
                program_code,
                program,
                activity_code,
                activity,
                object_code,
                object,
                amount,
                school_year,
                school_starting_year,
                _source,
                _source_table
            )
            SELECT
                'Budget',
                1,
                f.fund,

                {get_null_sentinel('int')},
                {get_null_sentinel('int')},
                {get_null_sentinel('int')},

                t.ccddd,
                c.district,
                co.county,
                t.program_code,
                p.program,
                t.activity_code,
                a.activity,
                t.object_code,
                o.object,
                t.amount,
                t.school_year,
                CAST(SPLIT_PART(t.school_year, '-', 1) AS INTEGER)
                    AS school_starting_year,
                t._source,
                t._source_table
            FROM f195_general_fund_expenditures t
            LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
            LEFT JOIN d_county co ON (c.county_code = co.county_code)
            LEFT JOIN d_program p ON (t.program_code = p.program_code)
            LEFT JOIN d_activity a ON (t.activity_code = a.activity_code)
            LEFT JOIN d_object o ON (t.object_code = o.object_code)
            LEFT JOIN d_fund f ON (1 = f.fund_code)
            LIMIT 100
            """
        ))

    def _populate_general_fund_expenditures_from_actuals(self, session):
        logger.info("Populating general_fund_expenditures with actuals data")
        session.execute(text(
            f"""
            INSERT INTO general_fund_expenditures (
                -- constant data
                data_type,
                fund_code,
                fund,

                -- "nulled" columns for f196 top-level table
                school_code,
                sub_fund_code,
                nces_code,

                -- Real data
                accounting_item_id,
                actuals_general_fund_expenditures_id,

                ccddd,
                district,
                county,
                program_code,
                program,
                activity_code,
                activity,
                object_code,
                object,
                amount,
                school_year,
                school_starting_year,
                _source,
                _source_table
            )
            SELECT
                'Actuals',
                1,
                f.fund,

                {get_null_sentinel('int')},
                {get_null_sentinel('int')},
                {get_null_sentinel('int')},

                t.accounting_item_id,
                t.actuals_general_fund_expenditures_id,

                t.ccddd,
                c.district,
                co.county,
                t.program_code,
                p.program,
                t.activity_code,
                a.activity,
                t.object_code,
                o.object,
                t.amount,
                t.school_year,
                CAST(SPLIT_PART(t.school_year, '-', 1) AS INTEGER)
                    AS school_starting_year,
                t._source,
                t._source_table
            FROM f196_general_fund_expenditures t
            LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
            LEFT JOIN d_county co ON (c.county_code = co.county_code)
            LEFT JOIN d_program p ON (t.program_code = p.program_code)
            LEFT JOIN d_activity a ON (t.activity_code = a.activity_code)
            LEFT JOIN d_object o ON (t.object_code = o.object_code)
            LEFT JOIN d_fund f ON (1 = f.fund_code)
            LIMIT 100
            """
        ))

    def _populate_general_fund_expenditures_from_child_actuals(self, session):
        logger.info("Populating general_fund_expenditures with child actuals")
        session.execute(text(
            """
            INSERT INTO general_fund_expenditures (
                data_type,

                fund_code,
                fund,

                accounting_item_id,
                actuals_child_general_fund_expenditures_id,

                ccddd,
                district,
                county,
                school_code,
                school,
                is_district_office,
                program_code,
                program,
                activity_code,
                activity,
                object_code,
                object,
                sub_fund_code,
                sub_fund,
                nces_code,
                nces,
                amount,
                school_year,
                school_starting_year,
                _source,
                _source_table
            )
            SELECT
                'Actuals',
                1,
                f.fund,

                t.accounting_item_id,
                t.actuals_child_general_fund_expenditures_id,

                t.ccddd,
                c.district,
                co.county,
                t.school_code,
                s.school,
                s.is_district_office,
                t.program_code,
                p.program,
                t.activity_code,
                a.activity,
                t.object_code,
                o.object,
                t.sub_fund_code,
                sf.sub_fund,
                t.nces_code,
                n.nces,
                t.amount,
                t.school_year,
                CAST(SPLIT_PART(t.school_year, '-', 1) AS INTEGER)
                    AS school_starting_year,
                t._source,
                t._source_table
            FROM f196_child_general_fund_expenditures t
            LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
            LEFT JOIN d_county co ON (c.county_code = co.county_code)
            LEFT JOIN d_school s ON (t.school_code = s.school_code)
            LEFT JOIN d_program p ON (t.program_code = p.program_code)
            LEFT JOIN d_activity a ON (t.activity_code = a.activity_code)
            LEFT JOIN d_object o ON (t.object_code = o.object_code)
            LEFT JOIN d_fund f ON (1 = f.fund_code)
            LEFT JOIN d_sub_fund sf ON (t.sub_fund_code = sf.sub_fund_code)
            LEFT JOIN d_nces n ON (t.nces_code = n.nces_code)
            LIMIT 100
            """
        ))

    def _populate_debt_service_fund_revenues(self, session):
        pass

    def _populate_capital_projects_revenues(self, session):
        pass

    def _populate_trans_vehicle_revenues(self, session):
        pass

    def _populate_ospi_items(self, session):
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
