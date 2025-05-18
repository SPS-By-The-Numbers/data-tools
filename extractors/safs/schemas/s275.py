from .common import make_field

ASSIGNMENT_SCHEMA = {
    "type": "record",
    "name": "s275_assignemnt",
    "doc": "Represents one assignment. Closest thing to a row in the s275",
    "fields": [
        make_field(
            name="assignment_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="contract_id",
            field_type="int",
            doc=("contract this assignment belongs to")),
        make_field(
            name="s275_report_id",
            field_type="int",
            doc=("which s275 report this belongs to")),
        make_field(
            name="employee_id",
            field_type="int",
            doc=("(logical primary key part) employee this assignment "
                 "belongs to")),
        make_field(
            name="school_code",
            field_type="int",
            doc=("(logical primary key part) school this assignment "
                 "belongs to")),
        make_field(
            name="program_code",
            field_type="int",
            doc=("(logical primary key part) s275 has non-numeric codes. We "
                 "map them to negative numbers")),
        make_field(
            name="activity_code",
            field_type="int",
            doc=("(logical primary key part) s275 has non-numeric codes. We "
                 "map them to negative numbers")),
        make_field(
            name="duty_root_code",
            field_type="int",
            doc=("(logical primary key part) OSPI duty title code root "
                 "(first 2 digits)")),
        make_field(
            name="duty_suffix_code",
            field_type="int",
            doc=("(logical primary key part) OSPI duty title code suffix "
                 "(last digit). It's just 0 or 1 which determines "
                 "Certificated or Classified.")),
        make_field(
            name="grade",
            field_type="string",
            doc=("(logical primary key part) Grade. There are different "
                 "rules for each duty code for what they need to be "
                 "assigned to")),
        make_field(
            name="pct_of_certificated_contract",
            field_type="decimal",
            doc=("Percent of Certificated Contracted Time")),
        make_field(
            name="fte_in_assignment",
            field_type="decimal",
            doc=("How much FTE is this assignment worth.  Note that agrees "
                 "with fte_in_assignment, but not total_final_salary or "
                 "assignment_salary. All three of these can independently be "
                 "non-zero.")),
        make_field(
            name="percent_fte_in_assignment",
            field_type="decimal",
            doc=("What percent of the employees total FTE are in this "
                 "assignment. Note that agrees with fte_in_assignment, but "
                 "not total_final_salary or assignment_salary. All three of "
                 "these can independently be non-zero.")),
        make_field(
            name="hours_per_year_in_assignment",
            field_type="decimal",
            doc=("Assignment Hours Per Year. This seems largely informational "
                 "It does not necessarily agree with any of "
                 "assignment_salary, fte_in_assignment, "
                 "percent_fte_in_assignment, or total_final_salary")),
        make_field(
            name="is_major",
            field_type="boolean",
            doc=("Does s275 consider this to be the \"major\" assignment")),
        make_field(
            name="s275_recno",
            field_type="int",
            doc=("Record number in 275. Needed to deduplicate. This is just "
                 "an audit log. The duplicate entries will not be included."))
    ]
}

S275_REPORT_SCHEMA = {
    "type": "record",
    "name": "s275_report",
    "doc": "Represents one s275 report for one year from a district or esd",
    "fields": [
        make_field(
            name="s275_report_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="school_year_code",
            field_type="string",
            doc=("(logical key part) school year this report is for. "
                 "Ex 2023-2024")),
        make_field(
            name="ccddd",
            field_type="int",
            doc=("(logical key part) OSPI County Disrict Code")),
        make_field(
            name="county_code",
            field_type="int",
            doc=("county code for convenience. cc part of ccddd")),
        make_field(
            name="district_code",
            field_type="int",
            doc=("district_code for convenience. ddd part of ccddd")),
        make_field(
            name="is_esd",
            field_type="boolean",
            doc=("True if this is a ESD and not a District.")),
        make_field(
            name="s275_crasdate",
            field_type="timestamp",
            doc=("cras timestamp in S275. With ceridate seems to creation or "
                 "update timestamp?")),
        make_field(
            name="s275_ceridate",
            field_type="timestamp",
            doc=("ceri timestamp in S275. With crasdate seems to creation or "
                 "update timestamp?"))
    ]
}

EMPLOYEE_SCHEMA = {
    "type": "record",
    "name": "s275_employee",
    "doc": ("Represents one employee in the s275 logically identified by a "
            "unique First, Middle, and Last name. So far there have been no "
            "collisions. Note that This table is a obfucation proxy and does "
            "not contain the actual full name or demographic info. Details on "
            "the employee that would allow for harvesting prejoined "
            "information on demographics, full name, compensation, etc are "
            "store in the PrivateEmployee and PrivateContract tables."),
    "fields": [
        make_field(
            name="employee_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="obfuscated_id",
            field_type="string",
            doc=("(logical key) obfuscated_id that attempts to represent one "
                 "employee across all districts and over years. It is based "
                 "first on the certificate number. If that is empty, it tries "
                 "to reverts to using FirstName, MiddleName, LastName. The ID "
                 "generation is a salted content hash and guaranteed "
                 "stable. No real attempt to made to avoid reversing the ID "
                 "to the original as this is public data. This structure is "
                 "concpetually closer to a \"knock before entering\" sign.")),
        make_field(
            name="c_highest_degree",
            field_type="string",
            doc=("Inferred most recent value of the Highest degree received "
                 "by this employee")),
        make_field(
            name="c_highest_degree_year",
            field_type="string",
            doc=("Inferred most recent value year the highest degree is "
                 "received")),
        make_field(
            name="c_experience_years",
            field_type="decimal",
            doc=("Inferred most recent value of number of years of "
                 "experience")),
        make_field(
            name="c_nbpts_certificate_expiration",
            field_type="timestamp",
            doc=("Inferred most recent value of For teachers and other "
                 "certificated instructional staff "
                 "(CIS) who hold, or held, current certification by the "
                 "NBPTS, report the expiration date of the national board "
                 "certification in year-month-day"))
    ]
}

CONTRACT_SCHEMA = {
    "type": "record",
    "name": "s275_contract",
    "doc": ("Represents one contract in the s275. This is not a true concept "
            "in the s275 accounting manual. Rather it is an inferred set of "
            "values taken from the fields used to calculate tfinsal. In the "
            "s275, this is denoramlized and exceptionally repetitive. "
            "Normalizing the data is a space-saving and sanity-preserving "
            "measure"),
    "fields": [
        make_field(
            name="contract_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="fte_hours",
            field_type="decimal",
            doc=("(logical key) Usually same for all certificated employees "
                 "in the district. Only for duties 110 to 640.")),
        make_field(
            name="fte_days",
            field_type="decimal",
            doc=("(logical key) Usually same for all certificated employees "
                 "in the district. Only for duties 110 to 640.")),
        make_field(
            name="certificated_fte",
            field_type="decimal",
            doc=("(logical key) Full-time equivalent (FTE) certificated "
                 "employment is determined as defined in WAC 392-121-212.  "
                 "Only for duties 110 to 640.")),
        make_field(
            name="classified_fte",
            field_type="decimal",
            doc=("(logical key) Not in the S275 manual, but probably siilar "
                 "to certfte just suing clasbase instead")),
        make_field(
            name="certificated_base_hours",
            field_type="decimal",
            doc=("(logical key) Used to calculate certificated_fte")),
        make_field(
            name="classified_base_hours",
            field_type="decimal",
            doc=("(logical key) Used to calculate clas_fte")),
        make_field(
            name="is_classified",
            field_type="boolean",
            doc=("(logical key) Is Classified")),
        make_field(
            name="is_certificated",
            field_type="boolean",
            doc=("(logical key) Is Certificated"))
    ]
}

S275_REPORT_EMPLOYEE_SCHEMA = {
    "type": "record",
    "name": "s275_report_employee",
    "doc": ("Represents information about an employee that is unique to one "
            "s275 report such as if they are a continuing, beginning, "
            "returning, transfering, new classified-employee."),
    "fields": [
        make_field(
            name="s275_report_employee_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="s275_report_id",
            field_type="int",
            doc=("s275_report this belongs to")),
        make_field(
            name="employee_id",
            field_type="int",
            doc=("employee this belongs to")),
        make_field(
            name="hire_state",
            field_type="string",
            doc=("Continuing = An individual who was reported by the district"
                 " in the previous year, unless Individual the person is a "
                 "certificated employee with less than 0.5 certificated "
                 "years of experience as of August 31. In that case report "
                 "such a person as a beginning individual.\n\n"

                 "Beginning = An individual with a certificated assignment "
                 "who is reported with less than 0.5 certificated years of "
                 "experience.\n\n"

                 "Returning = An individual with a certificated assignment "
                 "who was not reported in a Individual certificated capacity "
                 "anywhere during the previous school year and has at least "
                 "0.5 certificated years of experience as of August 31. "
                 "Report in this category an individual returning from "
                 "leave\n\n"

                 "Transfering = An individual with a certificated assignment "
                 "who was employed in a to District certificated capacity in "
                 "another Washington district (in a public or a private "
                 "school), another state, or foreign country during the "
                 "previous school year and has at least 0.5 certificated "
                 "years of experience as of August 31 and was not reported "
                 "by the current school year’s employing district last "
                 "year.\n\n"

                 "New = An employee with only classified assignments that "
                 "was not reported by the reporting district for the "
                 "previous school year.")),
        make_field(
            name="highest_degree",
            field_type="string",
            doc=("Highest degree received by this employee")),
        make_field(
            name="highest_degree_year",
            field_type="string",
            doc=("year the highest degree is received")),
        make_field(
            name="experience_years",
            field_type="decimal",
            doc=("number of years of experience")),
        make_field(
            name="nbpts_certificate_expiration",
            field_type="timestamp",
            doc=("For teachers and other certificated instructional staff "
                 "(CIS) who hold, or held, current certification by the "
                 "NBPTS, report the expiration date of the national board "
                 "certification in year-month-day"))
    ]
}

PRIVATE_EMPLOYEE_SCHEMA = {
    "type": "record",
    "name": "s275_private_employee_data",
    "doc": "Contains full name and demographics of the associated Employee",
    "fields": [
        make_field(
            name="private_employee_data_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="full_name",
            field_type="string",
            doc=("(logical key) Join of First, Middle, Last through the "
                 "Spelling Correction Table.")),
        make_field(
            name="employee_id",
            field_type="int",
            doc=("employee this belongs to. 1:1 relationship")),
        make_field(
            name="sex",
            field_type="string",
            doc=("OSPI Demographics")),
        make_field(
            name="is_hispanic",
            field_type="boolean",
            doc=("OSPI Demographics")),
        make_field(
            name="race",
            field_type="string",
            doc=("OSPI Demographics")),
        make_field(
            name="certificate_id",
            field_type="string",
            doc=("Certificate number for certificated employees"))
    ]
}

PRIVATE_CONTRACT_SCHEMA = {
    "type": "record",
    "name": "s275_private_contract",
    "doc": ("Contains compensation info from the contract. Separated out "
            "since it is invasive feeling"),
    "fields": [
        make_field(
            name="private_contract_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="contract_id",
            field_type="int",
            doc=("Contract this belongs to")),
        make_field(
            name="total_final_salary",
            field_type="decimal",
            doc=("Final Salary for year for 1 FTE. Compare to D.6. \n\n"
                 "If the person’s assignment has changed or the person has "
                 "terminated employment or gone on leave, updates to the "
                 "assignment salaries and benefits are determined by what "
                 "the individual would have earned had that individual "
                 "remained in the same position and assignment as reported "
                 "on October 1. However, total final salary is determined "
                 "by payroll, not the snapshot. See example 2F on page 40 of "
                 "2024-2025 s275 personnel reporting handbook")),
        make_field(
            name="insurance",
            field_type="decimal",
            doc=("Annual Insurance Benefits for year")),
        make_field(
            name="benefits",
            field_type="decimal",
            doc=("Annual Manditory Benefits for year")),
        make_field(
            name="other_salary",
            field_type="decimal",
            doc=("Other salaries from supplemental contract "
                 "(RCW 28A.400.200). For reporting purposes, such contracts "
                 "include formal and informal contracts known in the district "
                 "by various terms such as TRI, supplemental, stipends, and "
                 "time sheets."))
    ]
}

PRIVATE_ASSIGNMENT_SCHEMA = {
    "type": "record",
    "name": "s275_private_assignment",
    "doc": ("Contains compensation info related to the assignment. Separated "
            "out since it is invasive feeling"),
    "fields": [
        make_field(
            name="private_assignment_id",
            field_type="int",
            doc=("primary key")),
        make_field(
            name="assignment_id",
            field_type="int",
            doc=("(logical key) assignment this belongs to")),
        make_field(
            name="private_contract_id",
            field_type="int",
            doc=("(logical key) contract this assignment beyongs to")),
        make_field(
            name="assignment_salary",
            field_type="decimal",
            doc=("salary for this assignment")),

        # The following are calculated fields.
        make_field(
            name="inferred_assignment_salary_percentage",
            field_type="decimal",
            doc=("Conceptually what percentage of the fte assignment is "
                 "in this assignment.  Calculated as "
                 "assignment_salary/sum(all assignment_salary in report).")),
        make_field(
            name="inferred_assignment_other_salary",
            field_type="decimal",
            doc=("Conceptually how much of the other_salary is taken by this "
                 "assignment. This is just an estimate as the original data "
                 "duplicates the same othersal into multiple assignment rows "
                 "frequently.\n\n"

                 "Calculated as assignment_salary_percentage * other_salary")),
        make_field(
            name="inferred_assignment_insurance",
            field_type="decimal",
            doc=("Conceptually how much of the insurance is taken by this "
                 "assignment. This is just an estimate as insurance follows "
                 "the person, not the assignment. However, splitting it up "
                 "this way yields a more sensible "
                 "assignment_total_compensation estimate.\n\n"

                 "Calcualted as assignment_salary_percentage * insruance")),
        make_field(
            name="inferred_assignment_benefits",
            field_type="decimal",
            doc=("Conceptually how much of the benefits is taken by this "
                 "assignment. This is just an estimate as insurance follows "
                 "the person, not the assignment. However, splitting it up "
                 "assignment_total_compensation estimate.\n\n"

                 "Calculated as assignment_salary_percentage * benefits")),
        make_field(
            name="inferred_assignment_total_compensation",
            field_type="decimal",
            doc=("Conceptually, how much of the total compensation is taken "
                 "up by this assignment.\n\n"

                 "Calculated as assignment_salary + assignment_other_salary "
                 "+ assignment_insurance + assignment_benefits\n\n"

                 "The s275 manual examples make it look like "
                 "assignment_other_salary should be included inside "
                 "assignment_salary but this does not seem to quite match "
                 "the f196 values.  The current calculation is a best guess."))
    ]
}
