import dateutil
import hashlib

from ..avro_schema import (to_int, parse_first_schoolyear, y_n_to_boolean,
                           one_to_boolean)


def decode_cbrtn(record, source):
    """Just pass through the data value unchanged"""
    src_val = record[source].upper()
    match src_val:
        case 'C':
            return 'Continuing'
        case 'B':
            return 'Beginning'
        case 'R':
            return 'Returning'
        case 'T':
            return 'Transfering'
        case 'N':
            return 'New Classified-Only'
        case '' | '0' | None:
            return 'Unknown'
        case _:
            raise ValueError(src_val)


def area_to_is_esd(record, source):
    """area is "L" if district."""
    src_val = record[source]
    return src_val != 'L'


def parse_datetime(record, source):
    """Takes formats like 08/20/14 11:37:28 and turns into a timestamp"""
    date_str = record.get(source, None)
    if date_str:
        return dateutil.parser.parse(date_str)
    return None


def name_typo_correction(name):
    # TODO: Move this to its own file.
    return name


def make_obfuscated_id(record, _):
    """Attempts to create an id for an individual in the s275.

    The s275 does not have a real concept of an employee id so this attempts to
    infer it from the fields.

    First, if there is a teaching certificate, the certificate number is used
    as an employee identifier.

    If there is not one, then the FirstName, MiddleName, LastName are used.

    There will be collisions. Even for the same person two different reporting
    entities will often have mismatches in meta information such as the years
    of experience, highest degree, etc. There is not enough data to do better
    so this is so far a best guess.
    """
    identifier = None
    if 'cert' in record:
        identifier = record['cert']

    if not identifier:
        identifier = name_typo_correction(extract_full_name(record, _))

    m = hashlib.sha256()
    m.update(identifier.encode("utf-8"))
    return m.hexdigest()


def extract_full_name(record, source):
    """Constructs a single joined full-name"""
    raw_full_name = ' '.join([record['FirstName'], record['MiddleName'],
                              record['LastName']])
    return name_typo_correction(raw_full_name)


"""Fields for deduping on upsert and tracking changes"""
UPSERT_AUDIT_FIELDS = [
    {
        "name": "s275_recno",
        "source": "recno",
        "field_type": "int",
        "extractor": to_int,
        "doc": ("Record number in 275. Needed to deduplicate. This is "
                "just an audit log. The duplicate entries will not be "
                "included.")
    }
]

REPORT_SCHEMA = {
    "name": "s275_report",
    "doc": "Represents one s275 report for one year from a district or esd",
    "fields": [
        {
            "name": "report_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },
        {
            "name": "school_year_code",
            "field_type": "string",
            "source": "SchoolYear",
            "is_logical_key": True,
            "doc": ("(logical key part) school year this report is for. "
                    "Ex 2023-2024")
        },
        {
            "name": "ccddd",
            "source": "codist",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical key part) OSPI County Disrict Code")
        },
        {
            "name": "county_code",
            "source": "cou",
            "field_type": "int",
            "doc": ("[convenience] county code is cc part of ccddd")
        },
        {
            "name": "district_code",
            "source": "dis",
            "field_type": "int",
            "doc": ("[convenience] district_code is ddd part of ccddd")
        },
        {
            "name": "is_esd",
            "source": "area",
            "field_type": "boolean",
            "extractor": area_to_is_esd,
            "doc": ("True if this is a ESD and not a District.")
        },
        {
            "name": "s275_crasdate",
            "source": "crasdate",
            "field_type": "timestamp",
            "extractor": parse_datetime,
            "doc": ("cras timestamp in S275. With ceridate seems to creation "
                    "or update timestamp?")
        },
        {
            "name": "s275_ceridate",
            "source": "ceridate",
            "field_type": "timestamp",
            "extractor": parse_datetime,
            "doc": ("ceri timestamp in S275. With crasdate seems to "
                    "creation or update timestamp?")
        },
        {
            "name": "school_starting_year",
            "field_type": "string",
            "source": "SchoolYear",
            "extractor": parse_first_schoolyear,
            "doc": ("[convenience] The starting school year as an integer. "
                    "Makes sorting and comparisons easier.")
        },
    ]
}

EMPLOYEE_SCHEMA = {
    "name": "s275_employee",
    "doc": ("Represents one employee in the s275 logically identified by a "
            "unique First, Middle, and Last name. So far there have been no "
            "collisions. Note that This table is a obfucation proxy and does "
            "not contain the actual full name or demographic info. Details on "
            "the employee that would allow for harvesting prejoined "
            "information on demographics, full name, compensation, etc are "
            "store in the PrivateEmployee and PrivateContract tables."),
    "fields": [
        {
            "name": "employee_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "obfuscated_id",
            "field_type": "string",
            "is_logical_key": True,
            "extractor": make_obfuscated_id,
            "doc": (
                "(logical key) obfuscated_id that attempts to represent one "
                "employee across all districts and over years. It is based "
                "first on the certificate number. If that is empty, it tries "
                "to reverts to using FirstName, MiddleName, LastName. The ID "
                "generation is a salted content hash and guaranteed "
                "stable. No real attempt to made to avoid reversing the ID "
                "to the original as this is public data. This structure is "
                "concpetually closer to a \"knock before entering\" sign.")
        },
        {
            "name": "c_highest_degree",
            "field_type": "string",
            "doc": ("Inferred most recent value of the Highest degree "
                    "received by this employee")
        },
        {
            "name": "c_highest_degree_year",
            "field_type": "string",
            "doc": ("Inferred most recent value year the highest degree is "
                    "received")
        },
        {
            "name": "c_experience_years",
            "field_type": "decimal",
            "doc": ("Inferred most recent value of number of years of "
                    "experience")
        },
        {
            "name": "c_nbpts_certificate_expiration",
            "field_type": "timestamp",
            "doc": ("Inferred most recent value of For teachers and other "
                    "certificated instructional staff "
                    "(CIS) who hold, or held, current certification by the "
                    "NBPTS, report the expiration date of the national board "
                    "certification in year-month-day")
        },
        {
            "name": "c_hire_state",
            "field_type": "string",
            "doc": ("Inferred most recent value of hire_state of employee")
        },
        {
            "name": "c_record_ccddd",
            "field_type": "int",
            "doc": ("OSPI County Disrict Code of record these fields are from")
        },
        {
            "name": "c_record_county_code",
            "field_type": "int",
            "doc": ("county and district code that the c_ fields came from")
        },
        {
            "name": "c_record_s275_recno",
            "source": "recno",
            "field_type": "int",
            "extractor": to_int,
            "doc": ("Record number in 275 that the c_ fields came from.")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

PRIVATE_EMPLOYEE_SCHEMA = {
    "name": "s275_private_employee",
    "doc": "Contains full name and demographics of the associated Employee",
    "fields": [
        {
            "name": "private_employee_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "full_name",
            "field_type": "string",
            "extractor": extract_full_name,
            "doc": ("(logical key) Join of First, Middle, Last through the "
                    "Spelling Correction Table.")
        },
        {
            "name": "employee_id",
            "field_type": "int",
            "is_logical_key": True,
            "foreign_key": "s275_employee.employee_id",
            "doc": ("employee this belongs to. 1:1 relationship")
        },
        {
            "name": "sex",
            "source": "sex",
            "field_type": "string",
            "doc": ("OSPI Demographics: Gender")
        },
        {
            "name": "is_hispanic",
            "source": "hispanic",
            "field_type": "boolean",
            "extractor": y_n_to_boolean,
            "doc": ("OSPI Demographics: Hispanic")
        },
        {
            "name": "race",
            "source": "race",
            "field_type": "string",
            "doc": ("OSPI Demographics: Race")
        },
        {
            "name": "certificate_id",
            "source": "cert",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Certificate number for certificated employees")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

REPORT_EMPLOYEE_SCHEMA = {
    "name": "s275_report_employee",
    "doc": ("Represents information about an employee that is unique to one "
            "s275 report such as if they are a continuing, beginning, "
            "returning, transfering, new classified-employee."),
    "fields": [
        {
            "name": "s275_report_employee_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "report_id",
            "field_type": "int",
            "foreign_key": "s275_report.report_id",
            "is_logical_key": True,
            "doc": ("s275_report this belongs to")
        },
        {
            "name": "employee_id",
            "field_type": "int",
            "foreign_key": "s275_employee.employee_id",
            "is_logical_key": True,
            "doc": ("employee this belongs to")
        },
        {
            "name": "highest_degree",
            "source": "hdeg",
            "field_type": "string",
            "doc": ("Highest degree received by this employee")
        },
        {
            "name": "highest_degree_year",
            "source": "hyear",
            "field_type": "string",
            "doc": ("year the highest degree is received")
        },
        {
            "name": "experience_years",
            "source": "exp",
            "field_type": "decimal",
            "doc": ("number of years of experience")
        },
        {
            "name": "nbpts_certificate_expiration",
            "source": "NBcertexpdate",
            "field_type": "timestamp",
            "extractor": parse_datetime,
            "doc": ("For teachers and other certificated instructional staff "
                    "(CIS) who hold, or held, current certification by the "
                    "NBPTS, report the expiration date of the national board "
                    "certification in year-month-day")
        },
        {
            "name": "hire_state",
            "source": "cbrtn",
            "field_type": "string",
            "extractor": decode_cbrtn,
            "doc": (
                "Continuing = An individual who was reported by the district"
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
                "previous school year.")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

PRIVATE_REPORT_EMPLOYEE_SCHEMA = {
    "name": "s275_private_report_employee",
    "doc": ("Contains compensation related info for the report employee"),
    "fields": [
        {
            "name": "s275_private_report_employee_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "s275_report_employee_id",
            "field_type": "int",
            "foreign_key": "s275_report_employee.s275_report_employee_id",
            "is_logical_key": True,
            "doc": ("s275_report this belongs to")
        },
        {
            "name": "total_final_salary",
            "source": "tfinsal",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("Final Salary for year. Compare to D.6. \n\n"
                    "If the person’s assignment has changed or the person has "
                    "terminated employment or gone on leave, updates to the "
                    "assignment salaries and benefits are determined by what "
                    "the individual would have earned had that individual "
                    "remained in the same position and assignment as reported "
                    "on October 1. However, total final salary is determined "
                    "by payroll, not the snapshot. See example 2F on page 40 "
                    "of 2024-2025 s275 personnel reporting handbook")
        },
        {
            "name": "insurance",
            "source": "cins",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("Annual Insurance Benefits for year")
        },
        {
            "name": "benefits",
            "source": "cman",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("Annual Manditory Benefits for year")
        },
        {
            "name": "other_salary",
            "source": "othersal",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": (
                "Other salaries from supplemental contract "
                "(RCW 28A.400.200). For reporting purposes, such contracts "
                "include formal and informal contracts known in the district "
                "by various terms such as TRI, supplemental, stipends, and "
                "time sheets.")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

ASSIGNMENT_SCHEMA = {
    "name": "s275_assignment",
    "doc": "Represents one assignment. Closest thing to a row in the s275",
    "fields": [
        {
            "name": "assignment_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },
        {
            "name": "s275_report_employee_id",
            "field_type": "int",
            "foreign_key": "s275_report_employee.s275_report_employee_id",
            "is_logical_key": True,
            "doc": ("which s275 report and employee this assignment is for")
        },
        {
            "name": "report_id",
            "field_type": "int",
            "foreign_key": "s275_report.report_id",
            "doc": ("[convenience] which s275 report this belongs to. Can be "
                    "joined through s275_report_employee_id")
        },
        {
            "name": "employee_id",
            "field_type": "int",
            "foreign_key": "s275_employee.employee_id",
            "doc": ("[convenience] employee this assignment belongs to. Can be"
                    "joined through s275_report_employee_id")
        },
        {
            "name": "assignment_fte_id",
            "field_type": "int",
            "foreign_key": "s275_assignment_fte.assignment_fte_id",
            "is_logical_key": True,
            "doc": ("FTE info associated with this assignment"),
        },
        {
            "name": "school_code",
            "source": "bldgn",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical primary key part) school this assignment "
                    "belongs to")
        },
        {
            "name": "program_code",
            "source": "prog",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical primary key part) s275 has non-numeric codes. "
                    "We map them to negative numbers")
        },
        {
            "name": "activity_code",
            "source": "act",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical primary key part) s275 has non-numeric codes. "
                    "We map them to negative numbers")
        },
        {
            "name": "duty_root_code",
            "source": "droot",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical primary key part) OSPI duty title code root "
                    "(first 2 digits)")
        },
        {
            "name": "duty_suffix_code",
            "source": "dsufx",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("(logical primary key part) OSPI duty title code suffix "
                    "(last digit). It's just 0 or 1 which determines "
                    "Certificated or Classified.")
        },
        {
            "name": "grade",
            "source": "grade",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("(logical primary key part) Grade. There are different "
                    "rules for each duty code for what they need to be "
                    "assigned to")
        },
        {
            "name": "fte_in_assignment",
            "source": "assfte",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("How much FTE is this assignment worth.  Note that agrees "
                    "with pct100_fte_in_assignment, but not "
                    "total_final_salary or assignment_salary. All three of "
                    "these can independently be non-zero.")
        },
        {
            "name": "pct100_fte_in_assignment",
            "source": "asspct",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("Percentage of the employees total FTE are in this "
                    "assignment. Note that agrees with fte_in_assignment, but "
                    "not total_final_salary or assignment_salary. DO NOT USE "
                    "TO PRORATE THE SALARY AMOUNTS. It is very possible to "
                    "have positive total_final_salary and/or "
                    "assignment_salary with 0 FTE assigned, possibly(?) as a "
                    "result of some roll-over bookkeeping.  Note also that "
                    "the value here is in percernt so 100 is 100%. This is "
                    "the original format. Dividing by 100 to normalize causes "
                    "some precision loss from the original data.")
        },
        {
            "name": "hours_per_year_in_assignment",
            "source": "asshpy",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("Assignment Hours Per Year. This seems largely "
                    "informational It does not necessarily agree with any of "
                    "assignment_salary, fte_in_assignment, "
                    "percent_fte_in_assignment, or total_final_salary")
        },
        {
            "name": "is_major",
            "source": "major",
            "field_type": "boolean",
            "is_logical_key": True,
            "extractor": one_to_boolean,
            "doc": ("Does s275 consider this to be the \"major\" assignment")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

ASSIGNMENT_FTE_SCHEMA = {
    "name": "s275_assignment_fte",
    "doc": ("Fte related info for an assignment. This is very frequently "
            "the same across many assignements and not frequently useful "
            "separating it out allows for lower data sizes."),
    "fields": [
        {
            "name": "assignment_fte_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "fte_hours",
            "source": "ftehrs",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Usually same for all certificated "
                    "employees in the district. Only for duties 110 to 640.")
        },
        {
            "name": "fte_days",
            "source": "ftedays",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Usually same for all certificated "
                    "employees in the district. Only for duties 110 to 640.")
        },
        {
            "name": "certificated_fte",
            "source": "certfte",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Full-time equivalent (FTE) certificated "
                    "employment is determined as defined in WAC 392-121-212.  "
                    "Only for duties 110 to 640.")
        },
        {
            "name": "classified_fte",
            "source": "clasfte",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Not in the S275 manual, but probably "
                    "similar to certfte just suing clasbase instead")
        },
        {
            "name": "is_classified",
            "source": "clasflag",
            "field_type": "boolean",
            "is_logical_key": True,
            "extractor": y_n_to_boolean,
            "doc": ("(logical key) Is Classified")
        },
        {
            "name": "is_certificated",
            "source": "certflag",
            "field_type": "boolean",
            "is_logical_key": True,
            "extractor": y_n_to_boolean,
            "doc": ("(logical key) Is Certificated")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

PRIVATE_ASSIGNMENT_COMP_BASE_SCHEMA = {
    "name": "s275_assignment_comp_base",
    "doc": ("Represents compensation base numbers for an assignemnt. These "
            "are very frequently the same across assignments and are not "
            "super useful. Normalizing them lowers data size."),
    "fields": [
        {
            "name": "private_assignment_comp_base_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "certificated_base",
            "source": "certbase",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Base Salary for certificated compensation")
        },
        {
            "name": "classified_base",
            "source": "clasbase",
            "field_type": "decimal",
            "is_logical_key": True,
            "doc": ("(logical key) Base Salary for classified compensation")
        },
    ] + UPSERT_AUDIT_FIELDS,
}

PRIVATE_ASSIGNMENT_SCHEMA = {
    "name": "s275_private_assignment",
    "doc": ("Contains compensation info related to the assignment. Separated "
            "out since it is invasive feeling"),
    "fields": [
        {
            "name": "private_assignment_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key")
        },
        {
            "name": "assignment_id",
            "field_type": "int",
            "foreign_key": "s275_assignment.assignment_id",
            "is_logical_key": True,
            "doc": ("(logical key) assignment this belongs to")
        },
        {
            "name": "private_assignment_comp_base_id",
            "field_type": "int",
            "foreign_key": ("s275_assignment_comp_base."
                            "private_assignment_comp_base_id"),
            "is_logical_key": True,
            "doc": ("(logical key) contract base compensation info")
        },
        {
            "name": "s275_report_employee_id",
            "field_type": "int",
            "foreign_key": "s275_report_employee.s275_report_employee_id",
            "doc": ("[convenience] report employee this belongs to.")
        },

        {
            "name": "assignment_salary",
            "source": "asssal",
            "field_type": "decimal",
            "doc": ("salary for this assignment")
        },

        # The following are calculated fields.
        {
            "name": "c_pct_of_assignments",
            "field_type": "decimal",
            "doc": ("Conceptually what percentage of the fte assignment is "
                    "in this assignment.  Calculated as "
                    "assignment_salary/sum(all assignment_salary in report).")
        },
        {
            "name": "c_est_other_salary",
            "field_type": "decimal",
            "doc": (
                "Conceptually how much of the other_salary is taken by this "
                "assignment. This is just an estimate as the original data "
                "duplicates the same othersal into multiple assignment rows "
                "frequently.\n\n"

                "Calculated as assignment_salary_percentage * other_salary")
        },
        {
            "name": "c_est_insurance",
            "field_type": "decimal",
            "doc": (
                "Conceptually how much of the insurance is taken by this "
                "assignment. This is just an estimate as insurance follows "
                "the person, not the assignment. However, splitting it up "
                "this way yields a more sensible "
                "assignment_total_compensation estimate.\n\n"

                "Calcualted as assignment_salary_percentage * insruance")
        },
        {
            "name": "c_est_benefits",
            "field_type": "decimal",
            "doc": (
                "Conceptually how much of the benefits is taken by this "
                "assignment. This is just an estimate as insurance follows "
                "the person, not the assignment. However, splitting it up "
                "assignment_total_compensation estimate.\n\n"

                "Calculated as assignment_salary_percentage * benefits")
        },
        {
            "name": "c_est_total_final_salary",
            "field_type": "decimal",
            "doc": (
                "Conceptually, how much of the total final salary is taken "
                "up by this assignment."
            )
        },
        {
            "name": "c_est_total_compensation",
            "field_type": "decimal",
            "doc": (
                "Conceptually, how much of the total compensation is taken "
                "up by this assignment.\n\n"

                "Calculated as assignment_salary + assignment_other_salary "
                "+ assignment_insurance + assignment_benefits\n\n"

                "The s275 manual examples make it look like "
                "assignment_other_salary should be included inside "
                "assignment_salary but this does not seem to quite match "
                "the f196 values.  The current calculation is a best guess.")
        },
    ] + UPSERT_AUDIT_FIELDS,
}


ALL_SCHEMAS = [
    REPORT_SCHEMA,

    EMPLOYEE_SCHEMA,
    PRIVATE_EMPLOYEE_SCHEMA,

    REPORT_EMPLOYEE_SCHEMA,
    PRIVATE_REPORT_EMPLOYEE_SCHEMA,

    ASSIGNMENT_SCHEMA,
    ASSIGNMENT_FTE_SCHEMA,
    PRIVATE_ASSIGNMENT_COMP_BASE_SCHEMA,
    PRIVATE_ASSIGNMENT_SCHEMA
]

TABLENAME_SCHEMA_MAP = {s['name']: s for s in ALL_SCHEMAS}
