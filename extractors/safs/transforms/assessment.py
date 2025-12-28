import logging

from sqlalchemy import text

from .common import EXTRACT_CLASS_OF

logger = logging.getLogger(__name__)


def generate_assessment(session):
    logger.info("Processing assessment table")
    session.execute(text(
        f"""
        INSERT INTO rc_assessment (
            school_year,
            class_of,

            ccddd,
            county,
            district,

            school_code,
            test_subject,
            test_administration_group,
            test_administration,
            student_group_type,
            student_group,

            grade_level,
            dataasof,

            dat,
            num_expected_no_prior,
            num_expected_incl_prior,
            pct_participation,
            pct_noscore,
            pct_alternative,

            num_met_standard,
            pct_met_standard,

            num_met_foundational,
            pct_met_foundational,

            pct_level_1,
            pct_level_2,
            pct_level_3,
            pct_level_4,

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
            t.test_subject,
            t.test_administration_group,
            t.test_administration,
            t.student_group_type,
            t.student_group,

            t.grade_level,
            t.dataasof,

            t.dat,

            t.count_of_students_expected_excl_prior,
            t.count_of_students_expected_incl_prior,
            t.percent_participation,
            t.percent_no_score,
            t.percent_taking_alternative,

            t.count_consistent_grade,
            t.percent_consistent_grade,

            t.count_foundational_grade,
            t.percent_foundational_grade,

            t.percent_level_1,
            t.percent_level_2,
            t.percent_level_3,
            t.percent_level_4,

            t._source,
            t._source_table
        FROM
            assessment_odata t
        LEFT JOIN d_ccddd c ON (t.district_code = c.ccddd)
        LEFT JOIN d_county co ON (c.county_code = co.county_code)
        WHERE
            organization_level = 'School'
        """
    ))

    # Fix up some data labeling inconsistency
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Two Or More Races"
        WHERE student_group = "TwoorMoreRaces"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Native Hawaiian/ Other Pacific Islander"
        WHERE student_group = "Native Hawaiian/Pacific Islander"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Non-Migrant"
        WHERE student_group = "Non Migrant"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Non-Military Parent"
        WHERE student_group = "Non Military Parent"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Non-Section 504"
        WHERE student_group = "Non Section 504"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Non-Low-Income"
        WHERE student_group = "Non-Low Income"
        """
    ))
    session.execute(text(
        """
        UPDATE rc_assessment
        SET student_group = "Non-Students with Disabilities"
        WHERE student_group = "Students without Disabilities"
        """
    ))
