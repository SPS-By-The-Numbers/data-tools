import logging

from sqlalchemy import text
from ..avro_schema import get_null_sentinel

from .common import EXTRACT_STARTING_YEAR

logger = logging.getLogger(__name__)


def _get_most_recent_domain(columns, table, primary_keys,
                            order_by="school_year", other_where=[]):
    partition_by = ', '.join(primary_keys)

    # Raw source tables will have no error checking for nullness of pks. Remove
    # those and add other conditions.
    where_clause = ' AND '.join([f'{pk} IS NOT NULL'
                                 for pk in primary_keys] +
                                other_where)
    return f"""
        SELECT
            {columns}
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER(partition by {partition_by}
                                  ORDER BY {order_by} DESC) AS rn
            FROM {table}
            WHERE {where_clause}
            AND school_year IS NOT NULL
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


def _make_upsert(source_table, target_table, column_map, unique_columns,
                 conflict_sort_cols=['school_year'], other_where=[]):
    """Merges the source table into the target table.

    column_map is a dictionary of column names. Key is source. Value is
    destination.
    """
    select_sql = _get_most_recent_domain(
        ', '.join(column_map.keys()),
        source_table,
        unique_columns,
        other_where=other_where)
    conflict_sort = ' AND '.join([f'{target_table}.{col} <= EXCLUDED.{col}'
                                  for col in conflict_sort_cols])

    return text(_make_insert_impl(
        target_table,
        column_map.values(),
        ', '.join(unique_columns),
        conflict_sort,
        select_sql))


def _populate_revenue_table(session, data_type, fund_name):
    table_name = f"{fund_name}_revenues"
    logger.info(f"Populating {table_name} with child actuals")

    extra_columns = ""
    extra_values = ""

    if data_type == 'actuals':
        source_table_prefix = "f196"
        extra_columns = f"""
            accounting_item_id,
            actuals_{fund_name}_revenues_id,
        """
        extra_values = f"""
            t.accounting_item_id,
            t.actuals_{fund_name}_revenues_id,
        """
    else:
        source_table_prefix = "f195"

    session.execute(text(
        f"""
        INSERT INTO {table_name} (
            data_type,

            ccddd,
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
            '{data_type}',

            t.ccddd,
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
            {EXTRACT_STARTING_YEAR},
            t._source,
            t._source_table
        FROM {source_table_prefix}_{fund_name}_revenues t
        LEFT JOIN d_fund f ON (t.fund_code = f.fund_code)
        LEFT JOIN d_revenue r ON (t.revenue_code = r.revenue_code)
        LEFT JOIN d_program p ON (r.program_code = p.program_code)
        WHERE amount != 0
        AND t.revenue_code % 1000 != 0  -- ignore roll-ups for funding source.
        """
    ))


def _populate_domain_tables(session):
    _populate_domain_program(session)
    _populate_domain_activity(session)
    _populate_domain_object(session)
    _populate_domain_nces(session)
    _populate_domain_ccddd(session)
    _populate_domain_county(session)
    _populate_domain_revenue(session)
    _populate_domain_school(session)
    _populate_domain_fund(session)
    _populate_domain_subfund(session)
    _populate_domain_duty_root(session)
    _populate_domain_duty_suffix(session)
    _populate_domain_budget_item(session)
    _populate_domain_actuals_item(session)
    session.commit()


def _populate_domain_program(session):
    logger.info("Populating d_program")
    session.execute(
        _make_upsert(source_table='spsbtn_programs',
                     target_table='d_program',
                     column_map={
                         'program_code': 'program_code',
                         'program_f196': 'program',
                         'sps_program_grouping_augmented':
                             'sps_program_grouping',
                         'sps_program_grouping': 'raw_sps_program_grouping',
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

    # Fix-up special program 0 used in revenues.
    session.execute(
        text("""
             UPDATE d_program
             SET
             program = '[special] Unrestricted',
             sps_program_grouping = '[special] Unrestricted',
             school_year = '9998-9999',
             _source = 'generate_final_tables.py',
             _source_table = 'generate_final_tables.py'
             WHERE program_code = 0
             """
             ))

    # Ensure sps_program_grouping always has a value
    session.execute(
        text("""
             UPDATE d_program
             SET
             sps_program_grouping = CONCAT('[infered] ', program)
             WHERE sps_program_grouping IS NULL
             """
             ))


def _populate_domain_activity(session):
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


def _populate_domain_object(session):
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


def _populate_domain_nces(session):
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


def _populate_domain_ccddd(session):
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


def _populate_domain_county(session):
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


def _populate_domain_revenue(session):
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
             category_code = FLOOR(revenue_code/1000) * 1000
             """))

    # Add in the category codes
    session.execute(
        text("""
             INSERT INTO d_revenue (revenue_code, category_code,
             school_year, _source, _source_table)
             VALUES
             (1000, 1000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (2000, 2000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (3000, 3000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (4000, 4000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (5000, 5000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (6000, 6000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (7000, 7000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (8000, 8000, '9998-9999', 'generate_final_tables.py',
                 'manual'),
             (9000, 9000, '9998-9999', 'generate_final_tables.py',
                 'manual')
             """
             ))

    # Fill in category column.
    session.execute(
        text("""
             UPDATE d_revenue
             SET
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
                     THEN
                         'Revenues from Other Agencies and Associations'
                 WHEN FLOOR(category_code / 1000) = 9
                     THEN 'Other Financing Sources'
             END
             """
             ))

    # Fix-up roll-up names.
    session.execute(
        text("""
             UPDATE d_revenue
             SET revenue = CONCAT('[Roll-Up] ', category)
             WHERE revenue_code = category_code
             """
             ))


def _populate_domain_school(session):
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


def _populate_domain_fund(session):
    logger.info("Populating d_fund")
    session.execute(
        _make_upsert(source_table='spsbtn_funds',
                     target_table='d_fund',
                     column_map={
                         'fund_code': 'fund_code',
                         'fund': 'fund',
                         'fund_des': 'fund_des',
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


def _populate_domain_subfund(session):
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


def _populate_domain_duty_root(session):
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


def _populate_domain_duty_suffix(session):
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


def _populate_domain_budget_item(session):
    logger.info("Populating d_budget_item")
    # item_code seems to be mostly stable from year to year. There are
    # some small shifts in the description (eg capitalization or
    # abbreviation changes). A handful of codes (maybe a dozen?) do seem
    # to shift semantically but that might be errors in the original
    # domain.
    #
    # This attempts to make a best-guess deduping by picking the longest
    # description followed by the last school year.
    session.execute(text(
        """
        WITH f195_item_dict_deduped AS (
            SELECT
                *,
                ROW_NUMBER() OVER(partition by item_code
                                    ORDER BY
                                    LENGTH(description) DESC,
                                    school_year DESC) AS rn
                FROM f195_item_dict
                WHERE item_code != '' AND description != ''
        )
        INSERT INTO d_budget_item (
            item_code,
            description,
            school_year,
            _source,
            _source_table
        )
        SELECT
            t.item_code,
            t.description,
            t.school_year,
            t._source,
            t._source_table
        FROM f195_item_dict_deduped t
        WHERE t.rn = 1
        """
    ))


def _populate_domain_actuals_item(session):
    logger.info("Populating d_actuals_item")
    # The f196 tables, unlike the 195 basically don't collide for
    # item_code. There are 4 collisions, all semantically the same
    session.execute(text(
        """
        WITH f196_item_dict_deduped AS (
            SELECT
                *,
                ROW_NUMBER() OVER(partition by item_code
                                  ORDER BY
                                  LENGTH(description) DESC,
                                  school_year DESC) AS rn
                FROM f196_item_dict
                WHERE item_code != '' AND description != ''
        )
        INSERT INTO d_actuals_item (
            item_code,
            description,
            general_ledger_code_list,
            value_sources,
            value_uses,
            item_data_type,
            mode_of_input,
            retained,
            notes,
            school_year,
            _source,
            _source_table
        )
        SELECT
            t.item_code,
            t.description,
            t.gl_code,
            t.page_where_value_is_entered,
            t.report_where_value_is_displayed,
            t.data_type,
            t.mode_of_input,
            t.retained,
            t.notes,
            t.school_year,
            t._source,
            t._source_table
        FROM f196_item_dict_deduped t
        WHERE t.rn = 1
        """
    ))


def _populate_domain_actuals_item_preseve_fund_code(session):
    """This preserves the fund_code but that's not actually useful."""
    logger.info("Populating d_actuals_item")
    session.execute(text(
        """
        WITH RECURSIVE cleaned_f196_fund_code_list AS (
            SELECT
                f196_item_dict_id,
                CASE
                    WHEN t.fund_code_list = '1,2.9' THEN '1,2,9'
                    ELSE t.fund_code_list
                END as fund_code_list
            FROM f196_item_dict t
        ),
        fund_code_split AS (
            SELECT
                f196_item_dict_id,
                CAST(TRIM(SPLIT_PART(fund_code_list, ',', 1)) AS int)
                    fund_code,
                1 AS position,
                ARRAY_LENGTH(STRING_TO_ARRAY(fund_code_list, ','), 1) AS
                    max_position
            FROM cleaned_f196_fund_code_list
            WHERE
                fund_code_list IS NOT NULL
                AND fund_code_list != ''
                AND fund_code_list != 'N/A'

            UNION ALL

            SELECT
                fcs.f196_item_dict_id,
                CAST(TRIM(SPLIT_PART(fund_code_list, ',', fcs.position + 1))
                    AS int)
                    fund_code,
                fcs.position + 1 AS position,
                fcs.max_position
            FROM fund_code_split fcs
            JOIN cleaned_f196_fund_code_list t ON (
                fcs.f196_item_dict_id = t.f196_item_dict_id)
            WHERE fcs.position < fcs.max_position
        )
        INSERT INTO d_actuals_item (
            item_code,
            description,
            fund_code,
            general_ledger_code_list,
            value_from_list,
            value_use_list,
            item_data_type,
            mode_of_input,
            retained,
            notes,
            school_year,
            _source,
            _source_table
        )

        SELECT
            t.item_code,
            t.description,
            fcs.fund_code,
            t.gl_code,
            t.page_where_value_is_entered,
            t.report_where_value_is_displayed,
            t.data_type,
            t.mode_of_input,
            t.retained,
            t.notes,
            t.school_year,
            t._source,
            t._source_table
        FROM f196_item_dict t
        JOIN fund_code_split fcs ON (
            t.f196_item_dict_id = fcs.f196_item_dict_id)
        """
    ))


def _populate_general_fund_expenditures_from_budget(session):
    logger.info("Populating general_fund_expenditures with budget data")
    session.execute(text(
        f"""
        INSERT INTO general_fund_expenditures (
            -- constant data
            data_type,
            has_school,

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
            'budget',
            FALSE,

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
        WHERE amount != 0
        """
    ))


def _populate_general_fund_expenditures_from_actuals(session):
    logger.info("Populating general_fund_expenditures with actuals data")
    session.execute(text(
        f"""
        INSERT INTO general_fund_expenditures (
            -- constant data
            data_type,
            has_school,

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
            'actuals',
            FALSE,

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
        WHERE amount != 0
        AND
        t.school_year NOT IN (
            SELECT DISTINCT school_year
            FROM f196_child_general_fund_expenditures)
        """
    ))


def _populate_general_fund_expenditures_from_child_actuals(session):
    logger.info("Populating general_fund_expenditures with child actuals")
    session.execute(text(
        """
        INSERT INTO general_fund_expenditures (
            data_type,
            has_school,

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
            'actuals',
            TRUE,

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
        WHERE amount != 0
        """
    ))


def _populate_general_fund_expenditures_calculated_columns(session):
    logger.info("Populating general_fund_expenditures calculated columns")
    # Fill in c_pct_expenditure
    session.execute(text(
        """
        UPDATE general_fund_expenditures as gfe
        SET
            c_pct_expenditure = CASE
                WHEN t.total = 0 THEN 0
                ELSE gfe.amount / t.total
            END

        FROM
            (SELECT
                data_type,
                ccddd,
                school_year,
                sum(amount) as total
            FROM general_fund_expenditures
            GROUP BY
                data_type,
                ccddd,
                school_year
            ) as t
        WHERE
            gfe.data_type = t.data_type
            AND gfe.ccddd = t.ccddd
            AND gfe.school_year = t.school_year
        """
    ))

    # Fill in c_pct_revenue
    session.execute(text(
        """
        UPDATE general_fund_expenditures as gfe
        SET
            c_pct_revenue = CASE
                WHEN t.total = 0 THEN 0
                ELSE gfe.amount / t.total
            END

        FROM
            (SELECT
                data_type,
                ccddd,
                school_year,
                sum(amount) as total
            FROM general_fund_revenues
            GROUP BY
                data_type,
                ccddd,
                school_year
            ) as t
        WHERE
            gfe.data_type = t.data_type
            AND gfe.ccddd = t.ccddd
            AND gfe.school_year = t.school_year
        """
    ))

    # Fill in c_should_be_district_office
    session.execute(text(
        """
        UPDATE general_fund_expenditures as gfe
        SET
            c_in_school_allocated_staff = (is_district_office
            AND object_code in (
                2, -- Salaries - Certificated
                3, -- Salaries - Classified
                4  -- Employee Benefits and Payroll Taxes
            )
            AND activity_code in (
                27, -- Teaching
                23, -- Principal's Office
                24, -- Guidance and Counseling
                84  -- Principal
            )
            )
        """
    ))


def _populate_general_fund_revenues(session):
    _populate_revenue_table(session, "budget", "general_fund")
    _populate_revenue_table(session, "actuals", "general_fund")


def _populate_debt_service_revenues(session):
    _populate_revenue_table(session, "budget", "debt_service")
    _populate_revenue_table(session, "actuals", "debt_service")


def _populate_capital_projects_revenues(session):
    _populate_revenue_table(session, "budget", "capital_project")
    _populate_revenue_table(session, "actuals", "capital_project")


def _populate_trans_vehicle_revenues(session):
    _populate_revenue_table(session, "budget", "trans_vehicle")
    _populate_revenue_table(session, "actuals", "trans_vehicle")


def _populate_budget_items(session):
    logger.info("Populating budget_items")
    session.execute(text(
        f"""
        INSERT INTO budget_items (
            school_year,
            school_starting_year,

            ccddd,
            county,
            district,

            fund_code,
            fund,

            item_code,
            item,

            amount,

            _source,
            _source_table
        )
        SELECT
            t.school_year,
            {EXTRACT_STARTING_YEAR},

            t.ccddd,
            co.county,
            c.district,

            t.fund_code,
            f.fund,

            t.item_code,
            bi.description,

            t.amount,
            t._source,
            t._source_table

        FROM f195_item_numbers t
        JOIN d_fund f ON (t.fund_code = f.fund_code)
        LEFT JOIN d_budget_item bi ON (t.item_code = bi.item_code)
        LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
        LEFT JOIN d_county co ON (c.county_code = co.county_code)
        WHERE t.item_code != ''
        """
    ))


def _populate_actuals_items(session):
    logger.info("Populating actuals_items")
    session.execute(text(
        f"""
        INSERT INTO actuals_items (
            school_year,
            school_starting_year,

            ccddd,
            county,
            district,

            fund_code,
            fund,

            item_code,
            item,

            amount,

            general_ledger_code_list,

            accounting_item_id,
            actuals_item_numbers_id,

            _source,
            _source_table
        )
        SELECT
            t.school_year,
            {EXTRACT_STARTING_YEAR},

            t.ccddd,
            co.county,
            c.district,

            t.fund_code,
            f.fund,

            t.item_code,
            ai.description,

            t.amount,

            ai.general_ledger_code_list,

            t.accounting_item_id,
            t.actuals_item_numbers_id,

            t._source,
            t._source_table

        FROM f196_item_numbers t
        JOIN d_fund f ON (t.fund_code = f.fund_code)
        LEFT JOIN d_actuals_item ai ON (t.item_code = ai.item_code)
        LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
        LEFT JOIN d_county co ON (c.county_code = co.county_code)
        WHERE t.item_code != ''
        """
    ))


def generate_f19x(session):
    logger.info("Processing f19x tables")
    _populate_domain_tables(session)

    _populate_budget_items(session)
    _populate_actuals_items(session)
    session.commit()

    _populate_general_fund_revenues(session)
    _populate_debt_service_revenues(session)
    _populate_capital_projects_revenues(session)
    _populate_trans_vehicle_revenues(session)
    session.commit()

    _populate_general_fund_expenditures_from_budget(session)
    _populate_general_fund_expenditures_from_actuals(session)
    session.commit()

    _populate_general_fund_expenditures_from_child_actuals(
        session)
    _populate_general_fund_expenditures_calculated_columns(
        session)
    session.commit()
