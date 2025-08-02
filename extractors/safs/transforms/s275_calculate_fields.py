#!python3

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _fill_employee_rollup_info(session):
    """Fill in latest employee data in Employee table.

    Pick the largest record number for the most recent school year.
    """
    logger.info("Starting Employee rollup update")
    employee_rollup_sql = """
        UPDATE
            s275_employee e
        SET
            c_highest_degree = t.highest_degree,
            c_highest_degree_year = t.highest_degree_year,
            c_experience_years = t.experience_years,
            c_nbpts_certificate_expiration =
                t.nbpts_certificate_expiration,
            c_hire_state = t.hire_state,
            c_record_ccddd = t.ccddd,
            c_record_county_code = t.county_code,
            c_record_s275_recno = t.s275_recno
        FROM (
            SELECT
                re.employee_id,
                re.highest_degree,
                re.highest_degree_year,
                re.experience_years,
                re.nbpts_certificate_expiration,
                re.hire_state,
                r.ccddd,
                r.county_code,
                re.s275_recno,
                ROW_NUMBER() OVER (
                    PARTITION BY re.employee_id
                    ORDER BY r.school_starting_year DESC,
                                re.s275_recno DESC
                ) as rn
            FROM s275_report_employee re
            LEFT JOIN s275_report r ON (re.report_id = r.report_id)
        ) t
        WHERE e.employee_id = t.employee_id
        AND t.rn = 1
        """
    session.execute(text(employee_rollup_sql))


def _fill_private_assignments_values(session):
    """ Calculate the assignment total_final_salary and benefits in the
        PrivateAssignment table.

        This is very confusing. There are 3 kinds of values that are
        updated at different times. They are as follows:

        == Actual Gross Salary ==
        This is one column: total_final_salary.
        The value here comes from _payroll_ at end of the fiscal year and
        is supposed to be the gross compensation for the fiscal year.
        This is will reflect things like mid-year terminations, leaves, and
        supplemental contracts. It is a per-employee, not a per-assignment
        attribute.

        This is supposed to be an entry for every employee on the payroll
        at the end of year.

        == Assignment Salary ==
        These are the numbers for all employees on Oct 1st. These numbers
        do not get updated on terminations, leaves, hires, and fires and
        represent what the employee would have earned had they finished
        their terms.

        assignemnt_salary -- is a per-assigment attribute that determines
        the money allocated to the position. Seems to be 0 at times which
        probably indicates a reassignment after Oct 1st.

        other_salary -- is a per-employee attribute that includes extra
        time-driven (eg extra hours) or not time-driven (extra
        responsibilities) salaries. These are not broken down into
        assignments and do not get updated.

        == Insurance and benefits ==
        These are updated due to contract negotiations for everyone.
        The are updated to represent the amount paid fo the employee
        UNLESS the employee is terminated early. In the case of early
        termination, these numbers, confusingly, are not prorated down
        and similar to assignemnt_salary represent what they would have
        been paid had they finished their term.

        insurance, benefits -- both of these are per-employee values that
        specify the insurance and benefits for the employee for the whole
        year. These are not broken down into assignments and do not change
        if a person is terminated early. They are updated as a result of
        contract neogiations though.

        == Interpretation ==
        The s275 is a strange beast. First, it is just a snapshot of
        staffing on October 1st. All hires/fires after are ignored keeping
        the entry-set static.

        Next, other than total_final_salary, there is no concept of
        what is actually paid to an employee. It is not possible to
        calculate the actual benefits and insurance.

        Similarly, asside from the assignment_salary, there is no solid
        indication on how an employee's time is allocated between different
        positions. There is the fte_in_assignment and
        pct100_fte_in_assignment but these numbers do not seem to be self
        consistent (sometimes one is zero and the other isn't).

        This makes it only possible to know informionat for employees that
        were in the district on Oct 1st. Folks hired afterwards do not
        show up.

        For the folks listed, the following is knowable:

            * the actual total gross salary
            * the oct 1st assignments and expected salaries

        Weird things that can be calculated:
            * A guess at total insurance and benfits of oct 1st employees.
                but the number is odd since it reflects mid-year contract
                negotiations without proration.
            * A guess at the FTE assignment per position.

        Thing that can be inferred
            * If total_final_salary is way lower than sum of all
                assignment_salary, there was an early termination.

        Thing that can be estimated
            * amount of budgeted insurance/benefits/other_sal per assignment
            * amount of total_final_salary per assignment

        These estimated amounts will have error because new assignments
        can be added for a person with a total_final_salary which will
        be given assignment_salary of 0 so that assignment will be
        missed. Also, the insurance/benefit/other_sal numbers will be
        updated to reflect contract negotiations.

        TODO: Do we have folks with only a asssal=0 assignment and
        non-zero total_final_salary?
    """
    logger.info("Private Assignment Calculation start ")
    pct_of_assignments = """(COALESCE(pa.assignment_salary /
                            NULLIF(t.all_assignment_salary, 0), 0))"""

    update_private_assignment_sql = f"""
        UPDATE
            s275_private_assignment pa
        SET
            c_pct_of_assignments = {pct_of_assignments},

            c_est_other_salary = {pct_of_assignments}
                * pre.other_salary,

            c_est_insurance = {pct_of_assignments}
                * pre.insurance,

            c_est_benefits = {pct_of_assignments}
                * pre.benefits,

            c_est_total_final_salary = {pct_of_assignments}
                * pre.total_final_salary,

            c_est_total_compensation =
                pa.assignment_salary +
                {pct_of_assignments} * pre.other_salary +
                {pct_of_assignments} * pre.insurance +
                {pct_of_assignments} * pre.benefits
        FROM (
            SELECT
                pa.s275_report_employee_id,
                sum(pa.assignment_salary) all_assignment_salary
            FROM s275_private_assignment pa
            GROUP BY
                pa.s275_report_employee_id
            ) t
        LEFT JOIN s275_private_report_employee pre on (
            pre.s275_report_employee_id = t.s275_report_employee_id)

        WHERE pa.s275_report_employee_id = t.s275_report_employee_id
        """
    session.execute(text(update_private_assignment_sql))


def fill_fields(session):
    _fill_employee_rollup_info(session)
    _fill_private_assignments_values(session)
    session.commit()
