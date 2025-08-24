import logging

from sqlalchemy import text

from .common import EXTRACT_CLASS_OF

logger = logging.getLogger(__name__)


def _find_all_p223_enrollment_tables(session):
    logger.info("Finding p223_enrollment_summary_.* tables")

    result = session.execute(text(
        """
        SELECT
          table_name
        FROM
          information_schema.tables
        WHERE
          table_schema='public'
          AND table_type='BASE TABLE'
          AND table_name LIKE 'p223_enrollment_summary_%';
        """
    ))

    return [row[0] for row in result]


def _insert_from(session, source_table_name):
    session.execute(text(
        f"""
        INSERT INTO enrollment (
            school_year,
            class_of,

            ccddd,
            county,
            district,

            report_type,
            enrollment_domain,
            grade_category,
            amount,

            _source,
            _source_table
        )
        SELECT
            t.school_year,
            {EXTRACT_CLASS_OF},

            t.ccddd,
            co.county,
            c.district,

            t.report_type,
            t.enrollment_domain,
            t.grade_category,
            t.amount,

            t._source,
            t._source_table
        FROM
            "{source_table_name}" t
        LEFT JOIN d_ccddd c ON (t.ccddd = c.ccddd)
        LEFT JOIN d_county co ON (c.county_code = co.county_code)
        """
    ))


def generate_enrollment(session):
    logger.info("Processing enrollment tables")
    all_tables = _find_all_p223_enrollment_tables(session)
    logger.info(f"found {len(all_tables)} tables")
    for t in all_tables:
        _insert_from(session, t)
