import logging

from sqlalchemy import text

from .common import EXTRACT_CLASS_OF

logger = logging.getLogger(__name__)


def generate_sqss(session):
    logger.info("Processing sqss table")
    session.execute(text(
        f"""
        INSERT INTO rc_sqss (
            school_year,
            class_of,

            ccddd,
            county,
            district,

            school_code,
            grade_level,
            student_group_type,
            student_group,
            dataasof,
            dat,

            measure,

            percent,
            numerator,
            denominator,

            num_taking_ap,
            pct_taking_ap,

            num_taking_ib,
            pct_taking_ib,

            num_taking_cihs,
            pct_taking_cihs,

            num_taking_cambridge,
            pct_taking_cambridge,

            num_taking_cte,
            pct_taking_cte,

            num_taking_runningstart,
            pct_taking_runningstart,

            _source,
            _source_table
        )
        SELECT
            t.school_year,
            {EXTRACT_CLASS_OF},

            t.district_code,
            co.county,
            c.district,

            t.school_code,
            t.grade_level,
            t.student_group_type,
            t.student_group,
            t.dataasof,
            t.dat,

            t.measure,

            (t.numerator / NULLIF(t.denominator, 0)) percent,
            t.numerator,
            t.denominator,

            t.num_taking_ap,
            t.pct_taking_ap,

            t.num_taking_ib,
            t.pct_taking_ib,

            t.num_taking_cihs,
            t.pct_taking_cihs,

            t.num_taking_cambridge,
            t.pct_taking_cambridge,

            t.num_taking_cte,
            t.pct_taking_cte,

            t.num_taking_runningstart,
            t.pct_taking_runningstart,

            t._source,
            t._source_table
        FROM
            sqss_odata t
        LEFT JOIN d_ccddd c ON (t.district_code = c.ccddd)
        LEFT JOIN d_county co ON (c.county_code = co.county_code)
        WHERE
            organization_level = 'School'
        """
    ))
