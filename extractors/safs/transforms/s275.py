import logging
import os

from sqlalchemy import text
from .common import EXTRACT_STARTING_YEAR


logger = logging.getLogger(__name__)


SALT = f"'{os.environ.get('S275_SALT', '')}'"

def recno_partition_by(logical_keys):
    return f"""ROW_NUMBER() OVER(partition by school_year, codist {logic_keys}
               ORDER BY recno DESC) AS rn"""


def _generate_report(session):
    logging.info("Populating report table")
    session.execute(text(
        f"""
        INSERT INTO s275_report (
          report_type,

          school_year,
          school_starting_year,

          ccddd,

          county_code,

          district_code,

          is_esd,

          s275_crasdate,
          s275_ceridate,
          _source,
          _source_table
        )
        SELECT
          'final',

          school_year,
          {EXTRACT_STARTING_YEAR},

          codist,

          cou,
          dis,
          area != 'L',
          TO_TIMESTAMP(crasdate, 'MM/DD/YY HH24:MI:SS'),
          TO_TIMESTAMP(ceridate, 'MM/DD/YY HH24:MI:SS'),
          _source,
          _source_table
        FROM (
          SELECT
            *,
            ROW_NUMBER() OVER(partition by school_year, codist
                              ORDER BY crasdate DESC) AS rn
          FROM s275_final
        ) t
        WHERE rn = 1
        """
    ))


def _generate_employee(session):
    logging.info("Populating employee table")
    session.execute(text(
        """
        CREATE TEMPORARY TABLE t_employee_id (
            obfuscated_id TEXT,
            cert TEXT,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT,
            CONSTRAINT t_employee_id_lk
                UNIQUE (cert, first_name, middle_name, last_name)
        )
        """
    ))
    session.execute(text(
        """
        INSERT INTO t_employee_id (
            obfuscated_id,
            cert,
            first_name,
            middle_name,
            last_name
        )
        SELECT
            encode(sha256(raw_id::bytea), 'hex') obfuscated_id,
            cert,
            first_name,
            middle_name,
            last_name
        FROM (
            SELECT DISTINCT
                CASE
                    WHEN cert IS NOT NULL AND cert != '' THEN cert
                    ELSE COALESCE(first_name, '') || ',' ||
                        COALESCE(middle_name, '') || ',' ||
                        COALESCE(last_name, '')
                END raw_id,
                COALESCE(cert, '') cert,
                COALESCE(first_name, '') first_name,
                COALESCE(middle_name, '') middle_name,
                COALESCE(last_name, '') last_name
            FROM s275_final
        )
        """))
    session.commit()
    session.execute(text(
        """
        INSERT INTO s275_employee (
          obfuscated_id
        )
        SELECT obfuscated_id
            FROM t_employee_id
        """
    ))


def _generate_private_employee(session):
    logging.info("Populating private employee table")
    session.execute(text(
        f"""
        WITH raw_private_employee_data AS (
            SELECT
                employee_id, -- Foreign key.
                CONCAT_WS(
                    ' ',
                    NULLIF(first_name, ''),
                    NULLIF(middle_name, ''),
                    NULLIF(last_name, '')
                ) AS full_name

                sex,
                is_hispanic,
                race,
                certificate_id,
                ROW_NUMBER()
            FROM s275_final
        )
        INSERT INTO s275_private_employee (
            employee_id, -- Foreign key.

            full_name,
            sex,
            is_hispanic,
            race,
            certificate_id
        )
        SELECT * FROM raw_private_employee_data t where rn = 1
        """))


# Populate the employee info for a single s275 report.
def _generate_report_employee(session):
    pass


def _generate_private_report_employee(session):
    pass


def _generate_assignment(session):
    pass


def _generate_assignment_fte(session):
    pass


def _generate_private_assignment_comp_base(session):
    pass


def _generate_private_assignment(session):
    pass


def generate_s275(session):
    logger.info("Processing s275 tables")

    # Generate the basic concepts of a report and employee across the state.
    _generate_report(session)
    _generate_employee(session)
    _generate_private_employee(session)
    session.commit()

    # Populate the employee info for a single s275 report.
    _generate_report_employee(session)
    _generate_private_report_employee(session)
    session.commit()

    # Populate the assignment info for a single s275 report. This is most of
    # the data.
    _generate_assignment(session)
    _generate_assignment_fte(session)
    _generate_private_assignment_comp_base(session)
    _generate_private_assignment(session)
    session.commit()
