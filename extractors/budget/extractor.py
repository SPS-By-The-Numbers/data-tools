import logging
import re

from enum import Enum
from decimal import Decimal

from budget.school_allocations_validate import (validate_funding,
                                                validate_staffing)

logger = logging.getLogger(__name__)


Mode = Enum('Mode', ['SchoolName',
                     'EnrollmentAndDemographics',
                     'BudgetByFundingType',
                     'SchoolFundedStaff',
                     'OtherData',
                     'Done'])

RE_DOLLAR_COMMA = re.compile(r"\$|,")


def remove_comma_dollar_str(line):
    return re.sub(RE_DOLLAR_COMMA, "", line)


def remove_comma_dollar(line):
    x = remove_comma_dollar_str(line)
    if x == "-":
        return Decimal(0)
    return Decimal(x)


def get_school_funded_staff_fields(output, value_headers,
                                   value_fields):
    """Each column is the Funding type for staff allocated.,

    Examples are General Education, Bilingual Education, Seattle Ed Levy,
    State LAP, Special Ecuation, Federl Title I and a Total column.
    """
    for h, v in zip(value_headers, [normalize_num(x) for x in value_fields]):
        if h not in output:
            output[h] = []
        output[h] = v


def parse_school_funded_staff_fields(headers, fields, staffing_config):
    staff_type = fields[0]
    if staff_type in staffing_config["all_types"]:
        staffing_info = {}
        get_school_funded_staff_fields(staffing_info, headers[1:],
                                       fields[1:])
        return staff_type, staffing_info
    else:
        return None, None


def parse_school_funded_staff(rows, school_info, staffing_config):
    last_header_row = 0
    for r in rows:
        last_header_row += 1
        if re.match(r'^\s*Staff Type.*', r):
            break

    headers, all_fields = staffing_config["get_fields"](
        rows[0:last_header_row], rows[last_header_row:], staffing_config)

    staffing = school_info['staffing'] = {}
    for fields in all_fields:
        staff_type, staffing_info = parse_school_funded_staff_fields(
            headers, fields)
        if staff_type is not None:
            staffing[staff_type] = staffing_info


def parse_page(page, page_config, funding_config, enrollment_config,
               staffing_config):
    school_info = {}
    mode = Mode.SchoolName

    row_cache = None

    logger.debug("Parsing page")
    for raw_line in page.split('\n'):
        line = remove_comma_dollar_str(raw_line.strip())
        if not line:
            continue

        match mode:
            case Mode.SchoolName:
                # First line should be school name.
                if 'name' not in school_info:
                    # Example:
                    #  Adams Elementary      A.
                    x = re.sub(r"\s\s+", "\t", line)
                    school_info['name'] = x.split('\t')[0]
                else:
                    if line == 'Enrollment and Demographics':
                        logger.debug("Parsing Enrollment")
                        mode = Mode.EnrollmentAndDemographics

            case Mode.EnrollmentAndDemographics:
                # Example:
                #  Enrollment Type 22-23 23-24 24-25 Enrollment
                #  Total AAFTE* Enrollment 307 278 267
                #  ...
                #
                # Or sometimes
                #                         22-23 23-24 24-25
                #  Total AAFTE* Enrollment 307 278 267
                #
                if line.startswith(page_config["funding_section_start"]):
                    logger.debug("Funding")
                    mode = Mode.BudgetByFundingType
                elif x := re.match(
                        r".*(\d\d-\d\d)\s+(\d\d-\d\d*)\s+(\d\d-\d\d).*",
                        line):
                    school_info['enrollment'] = {}
                    school_info['enrollment']['School Year'] = [x[1], x[2],
                                                                x[3]]
                else:
                    for extract_config in enrollment_config["rows"]:
                        name = extract_config['name']
                        if line.startswith(name):
                            extractor = extract_config['extractor']

                            school_info['enrollment'][name] = extractor(
                                line,
                                extract_config['start'],
                                extract_config['num'],
                                extract_config['breaks'])
                            # Found a match. No need to keep going.
                            break

            case Mode.BudgetByFundingType:
                # Example:
                #  Funding Type 22-23 23-24 24-25 School Budget
                #  General Education 274834 234343 299144
                #  ...
                if re.match(r'.*School Funded Staff', line):
                    logger.debug("Staffing")
                    mode = Mode.SchoolFundedStaff
                    row_cache = []
                else:
                    for extract_config in funding_config["rows"]:
                        name = extract_config['name']
                        if line.startswith(name):
                            if 'funding' not in school_info:
                                school_info['funding'] = {}
                            extractor = extract_config['extractor']

                            school_info['funding'][name] = extractor(
                                line,
                                extract_config['start'],
                                extract_config['num'],
                                extract_config['breaks'])
                            # Found a match. No need to keep going.
                            break

            case Mode.SchoolFundedStaff:
                # The entire section is hard to parse.  Try to collate
                # all the rows into an array with some hack overlapping if
                # logic and then strip out the data.
                if line.startswith(page_config["staff_section_end"]):
                    row_cache.append(raw_line)
                    parse_school_funded_staff(
                        row_cache, school_info,
                        staffing_config)
                    logger.debug("Parsing Other Data")
                    mode = Mode.OtherData
                elif (line.startswith('General') or
                      line.startswith('Staff Type')):
                    # Collate the header rows.
                    row_cache.append(raw_line)
                else:
                    # Collate all the staff type rows. Note that the
                    # Terminal line of 'Total School Funded Staff' is
                    # caught by the if tatement.
                    for staff_type in staffing_config["rows"]:
                        if line.startswith(staff_type):
                            row_cache.append(raw_line)

            case Mode.OtherData:
                if 'other' not in school_info:
                    school_info['other'] = {}
                    school_info['other']['headers'] = [
                        'value'
                    ]

                if line.startswith('Classroom & Specialist Teachers'):
                    school_info['other']['teachers'] = get_nums(
                        line, 1, 1, page_config["other_info_break"])
                elif line.startswith('Student FTE'):
                    school_info['other']['student_fte'] = get_nums(
                        line, 1, 1, page_config["other_info_break"])
                elif line.startswith('Student Teacher Ratio'):
                    school_info['other']['ratio'] = get_nums(
                        line, 1, 1, page_config["other_info_break"])
                elif line.startswith('Budget Per Student'):
                    school_info['other']['budget_per_student'] = get_nums(
                        line, 1, 1, page_config["other_info_break"])

                elif line.startswith('Seattle Public School'):
                    logger.debug("Parsing Done")
                    mode = Mode.Done

            case Mode.Done:
                break

    return school_info


def parse_file_into_schools(infile, page_config, funding_config,
                            enrollment_config, staffing_config):
    """Takes a file of "pdf2txt -layout" and parses it into an array version.

    Returns: List of schools where each entry contains normalized strings
             extracted from infile.
    """
    all_text = infile.read()
    pages = all_text.split("\f")

    # Skip pages with less than 15 lines. These are likely blanks or images
    # between sections. The Images comes out to around 10 lines.
    return [parse_page(page,
                       page_config, funding_config, enrollment_config,
                       staffing_config)
            for page in pages if page.count('\n') > 15]


def make_yyyy(year):
    if len(year) == 2:
        return f"20{year}"
    return year


def merge_year_info(info, raw_year, info_type, year_info):
    # Convert to the standard year code used in OSPI date which uses
    # 4 digit years.
    year = '-'.join([make_yyyy(y) for y in raw_year.split('-')])
    year_data = info["year_data"]
    if year not in year_data:
        year_data[year] = {}

    if info_type in year_data[year]:
        year_data[year][info_type] = year_data[year][info_type] | year_info
    else:
        year_data[year][info_type] = year_info


def extract_funding(info, raw_info, funding_config):
    """Extract the structed funding data strings in raw_info into info"""
    funding_info = raw_info["funding"]
    year_columns = funding_info["Funding Type"]

    for i in range(0, len(year_columns)):
        year_info = {}
        expected_total = None
        for extract_config in funding_config["rows"]:
            name = extract_config['name']
            if name == 'Funding Type':
                # TODO: Do this more generically.
                continue
            elif name == funding_config["total_budget_row"]:
                # TODO: Do this more generically.
                expected_total = funding_info[name][i]
                continue
            elif name in funding_info:
                year_info[name] = funding_info[name][i]

        # Sanity check the info.
        recalculated_total = 0
        for _, funding_amount in year_info.items():
            recalculated_total = recalculated_total + funding_amount

        if recalculated_total != expected_total:
            logger.error(
                f"{info['metadata']['name']}: "
                f"expected {expected_total} got {recalculated_total}")

        merge_year_info(info, year_columns[i], 'funding', year_info)


def extract_staffing(info, raw_info, current_year):
    """Extract the structed funding data strings in raw_info into info"""
    staffing_info = raw_info["staffing"]
    errors = []

    year_info = {}
    for staff_type, funding_fte_info in staffing_info.items():
        for funding_type, fte in funding_fte_info.items():
            if funding_type not in year_info:
                year_info[funding_type] = {}

            year_info[funding_type][staff_type] = fte

    # Validation
    name = info['metadata']['name']
    funding_type_totals, staff_type_totals = validate_staffing(name, year_info,
                                                               errors)
    validate_funding(name, year_info, funding_type_totals, staff_type_totals,
                     errors)

    merge_year_info(info, current_year, 'staffing', year_info)
    if "staffing" not in info["metadata"]["errors"]:
        info["metadata"]["errors"]["staffing"] = {}
    info["metadata"]["errors"]["staffing"][current_year] = errors


def extract_enrollment(info, raw_info, enrollment_config):
    """Extract the structed funding data strings in raw_info into info"""

    # This happens with Skills Center.
    if "enrollment" not in raw_info:
        return

    enrollment_info = raw_info["enrollment"]
    year_columns = enrollment_info["School Year"]

    for i in range(0, len(year_columns)):
        year_info = {}
        for extract_config in enrollment_config["rows"]:
            name = extract_config['name']
            if name in enrollment_info:
                year_info[name] = enrollment_info[name][i]

        merge_year_info(info, year_columns[i], 'enrollment', year_info)


def normalize_school(raw_info, school_map, funding_config, enrollment_config):
    """Takes result of parsing a school and turns it into structred data.

    The input data is raw strings.  This will do self-checks and then return
    a object with the following structure.
    {
       name: "Name of School",
       "General Education": {
          "aafte": 124.8,
          "Classroom Teachers": 65.4,
          "Special Eduation Teachers": 65.4,
          "Funding": 11063993
       },
       ....,
       "Other Grants": {
          # Not all funding types map to a demographic, so no aafte here.
          "Classroom Teachers": 65.4,
          "Funding": 106045,
       }
    }

    """
    raw_name = raw_info["name"]
    if raw_name not in school_map:
        logger.error(f"Missing {raw_name}")
        school_map_info = {'name': "unknown"}
    else:
        school_map_info = school_map[raw_info["name"]]
    info = {
        "metadata": school_map_info | {
            "scraped_name": raw_info["name"],
            "errors": {}
        },
        "year_data": {
        }
    }
    name = info["metadata"]["name"]

    logger.info(f"Extracting funding for {name}")
    extract_funding(info, raw_info, funding_config)

    logger.info(f"Extracting funding for {name}")
    extract_enrollment(info, raw_info, enrollment_config)

    # Use the most recent year as the "current" year.
    years = list(info["year_data"].keys())
    years.sort()
    current_year = years[-1]
    logger.info(f"Extracting staffing for {name}")
    extract_staffing(info, raw_info, current_year)

    return info


def normalize_num(n):
    if n == '-' or n == '':
        return 0
    return float(n)


def get_nums_dashed(line, start, num, _):
    return [normalize_num(n) for n in get_cols_dashed(line, start, num, None)]


def get_cols_dashed(line, start, num, _):
    splits = re.sub(r'\s\s+', ';', line).split(';')
    return splits[start:start + num]


def get_cols(line, start, num, breaks):
    vals = []
    last_break = breaks[0]
    for b in breaks[1:]:
        vals.append(line[last_break:b].strip())
        last_break = b
    vals.append(line[breaks[-1]:].strip())

    return vals[start:start + num]


def get_nums(line, start, num, breaks):
    x = [normalize_num(n) for n in get_cols(line, start, num, breaks)]
    return x
