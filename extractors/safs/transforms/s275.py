import logging
import os

from sqlalchemy import text
from .common import EXTRACT_STARTING_YEAR

# Used in the SQL CREATE [x] TABLE for intermediate tables. Set to 'TEMPORARY'
# so they are temporary tables.  Set to '' to persist them for debugging.
#T_IS_TEMPORARY = 'TEMPORARY'
T_IS_TEMPORARY = ''


logger = logging.getLogger(__name__)


SALT = f"'{os.environ.get('S275_SALT', '')}'"


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

    # Create a temporary table mapping all (first_name, middle_name, last_name,
    # cert) logical identifiers for an employee and mapping it to a single
    # obfuscated_id.
    #
    # This table handles if one cert has multiple names.
    session.execute(text(
        f"""
        DROP TABLE IF EXISTS t_employee_id;
        CREATE {T_IS_TEMPORARY} TABLE t_employee_id (
            cert TEXT,
            first_name TEXT,
            middle_name TEXT,
            last_name TEXT,
            obfuscated_id TEXT,

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
                    ELSE first_name || ',' || middle_name || ',' || last_name
                END raw_id,
                cert,
                first_name,
                middle_name,
                last_name
            FROM s275_final
        )
        """))

    # Create the real s275_employee table.
    session.execute(text(
        """
        INSERT INTO s275_employee (
          obfuscated_id
        )
        SELECT distinct obfuscated_id
            FROM t_employee_id
        """
    ))


def _generate_private_employee(session):
    logging.info("Populating private employee table")
    session.execute(text(
        """
        WITH raw_private_employee_data AS (
            SELECT
                e.employee_id, -- Foreign key.

                CONCAT_WS(
                    ' ',
                    NULLIF(t.first_name, ''),
                    NULLIF(t.middle_name, ''),
                    NULLIF(t.last_name, '')
                ) AS full_name,

                t.sex,
                t.hispanic = 'Y' is_hispanic,
                t.race,
                t.cert certificate_id,
                ROW_NUMBER() OVER(PARTITION BY e.employee_id
                                  ORDER BY
                                    t.school_year DESC,
                                    t.codist DESC,
                                    CAST(t.recno as int) DESC) AS rn
            FROM s275_final t
            LEFT JOIN t_employee_id tei ON(
                t.cert = tei.cert AND
                t.first_name = tei.first_name AND
                t.middle_name = tei.middle_name AND
                t.last_name = tei.last_name)
            LEFT JOIN s275_employee e ON(tei.obfuscated_id = e.obfuscated_id)
        )
        INSERT INTO s275_private_employee (
            employee_id, -- Foreign key.

            full_name,
            sex,
            is_hispanic,
            race,
            certificate_id
        )
        SELECT
            t.employee_id,
            t.full_name,
            t.sex,
            t.is_hispanic,
            t.race,
            t.certificate_id
        FROM raw_private_employee_data t where rn = 1
        """))


# Populate the employee info for a single s275 report.
def _generate_report_employee(session):
    logging.info("Populating report employee table")
    session.execute(text(
        f"""
        DROP TABLE IF EXISTS t_report_employee_canonical;
        CREATE {T_IS_TEMPORARY} TABLE t_report_employee_canonical (
            report_id INT NOT NULL,
            employee_id INT NOT NULL,

            canoncial_s275_final_id INT NOT NULL,

            CONSTRAINT t_report_employee_canonical_lk
                UNIQUE (report_id, employee_id)
        )
        """))

    session.execute(text(
        """
        WITH raw_report_employee_id AS (
            SELECT
                r.report_id,
                e.employee_id,
                t.s275_final_id,

                -- report_id and employee_id already come to one person.
                -- Pick the last record.
                ROW_NUMBER() OVER(PARTITION BY e.employee_id, r.report_id
                                  ORDER BY CAST(t.recno as int) DESC) AS rn
            FROM s275_final t
            LEFT JOIN s275_report r ON(
                r.report_type = 'final' AND
                t.codist = r.ccddd AND
                t.school_year = r.school_year
            )
            LEFT JOIN t_employee_id tei ON(
                t.cert = tei.cert AND
                t.first_name = tei.first_name AND
                t.middle_name = tei.middle_name AND
                t.last_name = tei.last_name)
            LEFT JOIN s275_employee e ON(e.obfuscated_id = tei.obfuscated_id)
        )
        INSERT INTO t_report_employee_canonical (
            report_id,
            employee_id,
            canoncial_s275_final_id
        )
        SELECT
            report_id,
            employee_id,
            s275_final_id
        FROM raw_report_employee_id t
        WHERE rn = 1
        """))

    session.execute(text(
        """
        WITH raw_report_employee_data AS (
            SELECT
                rec.report_id report_id,
                rec.employee_id employee_id,

                t.hdeg highest_degree,
                t.hyear highest_degree_year,
                t.exp experience_years,
--                t.NBcertexpdate nbpts_certificate_expiration,
                CASE
                    WHEN cbrtn = 'C' THEN 'Continuing'
                    WHEN cbrtn = 'B' THEN 'Beginning'
                    WHEN cbrtn = 'R' THEN 'Returning'
                    WHEN cbrtn = 'T' THEN 'Transfering'
                    WHEN cbrtn = 'N' THEN 'New Classified-Only'
                    ELSE 'Unknown'
                END hire_state,
                CAST(t.recno as INT) s275_recno

            FROM t_report_employee_canonical rec
            LEFT JOIN s275_final t ON(
                rec.canoncial_s275_final_id = t.s275_final_id)
        )
        INSERT INTO s275_report_employee (
            report_id, -- Foreign key.
            employee_id, -- Foreign key.

            highest_degree,
            highest_degree_year,
            experience_years,
--            nbpts_certificate_expiration,
            hire_state,
            s275_recno
        )
        SELECT
            report_id,
            employee_id,

            highest_degree,
            highest_degree_year,
            experience_years,
--            nbpts_certificate_expiration,
            hire_state,
            s275_recno
        FROM raw_report_employee_data t
        """))


def _generate_private_report_employee(session):
    logging.info("Populating private report employee table")
    session.execute(text(
        """
        WITH raw_private_report_employee_data AS (
            SELECT
                rec.report_id report_id,
                rec.employee_id employee_id,

                t.tfinsal total_final_salary,
                t.cins insurance,
                t.cman benefits,
                t.othersal other_salary,
                CAST(t.recno as INT) s275_recno

            FROM t_report_employee_canonical rec
            LEFT JOIN s275_final t ON(
                rec.canoncial_s275_final_id = t.s275_final_id)
        )
        INSERT INTO s275_private_report_employee (
            s275_report_employee_id, -- Foreign key.

            total_final_salary,
            insurance,
            benefits,
            other_salary,
            s275_recno
        )
        SELECT
            re.s275_report_employee_id,
            t.total_final_salary,
            t.insurance,
            t.benefits,
            t.other_salary,
            t.s275_recno
        FROM raw_private_report_employee_data t
        JOIN s275_report_employee re ON (t.report_id = re.report_id AND
                                         t.employee_id = re.employee_id)
        """))


def _generate_assignment_fte(session):
    logging.info("Populating assignment_fte table")
    session.execute(text(
        """
        INSERT INTO s275_assignment_fte (
            fte_hours,
            fte_days,
            certificated_fte,
            classified_fte,
            is_classified,
            is_certificated
        )
        SELECT DISTINCT
            t.ftehrs fte_hours,
            t.ftedays fte_days,
            t.certfte certificated_fte,
            t.clasfte classified_fte,
            (t.clasflag = 'Y') is_classified,
            (t.certflag = 'Y') is_certificated
        FROM s275_final t
        """))


def _generate_temp_canonical_assignment_table(session):
    logging.info("Populating t_assignment_canonical table")
    session.execute(text(
        f"""
        DROP TABLE IF EXISTS t_assignment_canonical;
        CREATE {T_IS_TEMPORARY} TABLE t_assignment_canonical (
            -- Logical key
            s275_report_employee_id INT NOT NULL,
            assignment_fte_id INT NOT NULL,

            school_code INT NOT NULL,
            program_code INT NOT NULL,
            activity_code INT NOT NULL,
            duty_root_code INT NOT NULL,
            duty_suffix_code INT NOT NULL,

            grade TEXT NOT NULL,

            fte_in_assignment DECIMAL NOT NULL,
            pct100_fte_in_assignment DECIMAL NOT NULL,
            hours_per_year_in_assignment DECIMAL NOT NULL,

            is_major BOOLEAN NOT NULL,

            -- The row to use.
            canoncial_s275_final_id INT NOT NULL,
            s275_recno INT NOT NULL,

            -- Extra info for making the foreign key fill in easy.
            report_id INT NOT NULL,
            employee_id INT NOT NULL,

            CONSTRAINT t_assignment_canonical_lk
                UNIQUE (s275_report_employee_id,
                        assignment_fte_id,
                        school_code,
                        program_code,
                        activity_code,
                        duty_root_code,
                        duty_suffix_code,
                        grade,
                        fte_in_assignment,
                        pct100_fte_in_assignment,
                        hours_per_year_in_assignment,
                        is_major)
        )
        """))

    session.execute(text(
        """
        WITH raw_assignment_row AS (
            SELECT
                re.s275_report_employee_id,
                af.assignment_fte_id,

                t.bldgn school_code,
                t.prog program_code,
                t.act activity_code,
                t.droot duty_root_code,
                t.dsufx duty_suffix_code,
                t.grade grade,
                t.assfte fte_in_assignment,
                t.asspct pct100_fte_in_assignment,
                t.asshpy hours_per_year_in_assignment,
                (t.major = '1') is_major,

                r.report_id report_id,
                e.employee_id employee_id,

                t.s275_final_id,
                CAST(t.recno as INT) s275_recno,

                -- Pick the last record.
                ROW_NUMBER() OVER(
                    PARTITION BY
                        re.s275_report_employee_id,
                        af.assignment_fte_id,

                        t.bldgn,
                        t.prog,
                        t.act,
                        t.droot,
                        t.dsufx,
                        t.grade,
                        t.assfte,
                        t.asspct,
                        t.asshpy,
                        (t.major = '1')

                    ORDER BY CAST(t.recno as int) DESC) AS rn
            FROM s275_final t
            LEFT JOIN s275_report r ON(
                r.report_type = 'final' AND
                t.codist = r.ccddd AND
                t.school_year = r.school_year
            )
            LEFT JOIN t_employee_id tei ON(
                t.cert = tei.cert AND
                t.first_name = tei.first_name AND
                t.middle_name = tei.middle_name AND
                t.last_name = tei.last_name)
            LEFT JOIN s275_employee e ON(e.obfuscated_id = tei.obfuscated_id)
            LEFT JOIN s275_report_employee re ON(
                e.employee_id = re.employee_id AND
                r.report_id = re.report_id)
            LEFT JOIN s275_assignment_fte af ON(
                t.ftehrs = af.fte_hours AND
                t.ftedays = af.fte_days AND
                t.certfte = af.certificated_fte AND
                t.clasfte = af.classified_fte AND
                (t.clasflag = 'Y') = af.is_classified AND
                (t.certflag = 'Y') = af.is_certificated)
        )
        INSERT INTO t_assignment_canonical (
            s275_report_employee_id,
            assignment_fte_id,

            school_code,
            program_code,
            activity_code,
            duty_root_code,
            duty_suffix_code,
            grade,
            fte_in_assignment,
            pct100_fte_in_assignment,
            hours_per_year_in_assignment,
            is_major,

            report_id,
            employee_id,

            canoncial_s275_final_id,

            s275_recno
        )
        SELECT
            s275_report_employee_id,
            assignment_fte_id,

            school_code,
            program_code,
            activity_code,
            duty_root_code,
            duty_suffix_code,
            grade,
            fte_in_assignment,
            pct100_fte_in_assignment,
            hours_per_year_in_assignment,
            is_major,

            report_id,
            employee_id,

            s275_final_id,

            s275_recno
        FROM raw_assignment_row t
        WHERE rn = 1
        """))


def _generate_assignment(session):
    logging.info("Populating assignment table")
    session.execute(text(
        """
        INSERT INTO s275_assignment (
            s275_report_employee_id,
            assignment_fte_id,

            school_code,
            program_code,
            activity_code,
            duty_root_code,
            duty_suffix_code,
            grade,
            fte_in_assignment,
            pct100_fte_in_assignment,
            hours_per_year_in_assignment,
            is_major,

            report_id,
            employee_id,
            s275_recno
        )
        SELECT
            s275_report_employee_id,
            assignment_fte_id,

            school_code,
            program_code,
            activity_code,
            duty_root_code,
            duty_suffix_code,
            grade,
            fte_in_assignment,
            pct100_fte_in_assignment,
            hours_per_year_in_assignment,
            is_major,

            report_id,
            employee_id,
            s275_recno
        FROM t_assignment_canonical t
        """))


def _generate_private_assignment_comp_base(session):
    logging.info("Populating assignment comp base table")
    session.execute(text(
        """
        INSERT INTO s275_private_assignment_comp_base (
            certificated_base,
            classified_base
        )
        SELECT DISTINCT
            certbase,
            clasbase
        FROM s275_final
        """
    ))


def _generate_private_assignment(session):
    logging.info("Populating private assignment table")
    session.execute(text(
        """
        INSERT INTO s275_private_assignment (
            assignment_id,
            private_assignment_comp_base_id,

            assignment_salary,

            s275_report_employee_id
        )
        SELECT
           a.assignment_id,
           pacb.private_assignment_comp_base_id,
           t.asssal,
           a.s275_report_employee_id

        FROM s275_final t
        JOIN t_assignment_canonical c ON (
                t.s275_final_id = c.canoncial_s275_final_id
           )
        JOIN s275_private_assignment_comp_base pacb ON (
            t.certbase = pacb.certificated_base AND
            t.clasbase = pacb.classified_base
        )
        JOIN s275_assignment a ON (
           a.s275_report_employee_id = c.s275_report_employee_id AND
           a.assignment_fte_id = c.assignment_fte_id AND

           a.school_code = c.school_code AND
           a.program_code = c.program_code AND
           a.activity_code = c.activity_code AND
           a.duty_root_code = c.duty_root_code AND
           a.duty_suffix_code = c.duty_suffix_code AND
           a.grade = c.grade AND
           a.fte_in_assignment = c.fte_in_assignment AND
           a.pct100_fte_in_assignment = c.pct100_fte_in_assignment AND
           a.hours_per_year_in_assignment = c.hours_per_year_in_assignment AND
           a.is_major = c.is_major
           )
        """))


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
    _generate_assignment_fte(session)

    _generate_temp_canonical_assignment_table(session)
    _generate_assignment(session)
    session.commit()

    _generate_private_assignment_comp_base(session)
    _generate_private_assignment(session)
    session.commit()
