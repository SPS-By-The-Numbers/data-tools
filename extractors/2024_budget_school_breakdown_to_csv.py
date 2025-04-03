import argparse
import csv
import logging
import math
import re

from enum import Enum

logger = logging.getLogger(__name__)

Mode = Enum('Mode', ['SchoolName',
                     'EnrollmentAndDemographics',
                     'BudgetByFundingType',
                     'SchoolFundedStaff',
                     'OtherData',
                     'Done'])


ENROLLMENT_COL_BREAK = [0, 35, 54, 70, 87]
FUNDING_COL_BREAK = [0, 22, 63, 85]
FUNDING_TOTAL_BUDGET_BREAK = [0, 22, 60, 79]
OTHER_INFO_BREAK = [0, 60]
MAX_LINE_LENGTH = 2048

# Name of the column that holds the total staffing number for each staff type.
STAFFING_TOTAL_COLUMN = "Total Staff FTE"

# Name of the column that holds the total staffing number for each funding
# type.
STAFFING_TOTAL_ROW = "Total Staff FTE"


def get_header_ranges(line):
    # Any two whitespaces is a field separator. Make it a tab and then break
    # it.
    headers = [x.strip() for x in re.sub(r'\s\s+', '\t', line).split('\t')]

    # Go back and turn the headers into a regex to find locations.
    header_regex = r'\s+'.join([f'({h})' for h in headers])
    matches = re.match(header_regex, line)
    return headers, [
        (matches.start(i), matches.end(i)) for i in range(1, len(headers) + 1)]


def flatten_school_info(page):
    rows = []
    school_name = None
    for category, category_info in page.items():
        # Funding Type, General Education, 22-23, Amt
        # Category, Entry, Column, Amt
        if category == 'name':
            school_name = category_info
            continue
        headers = category_info['headers']
        for entry, values in category_info.items():
            if entry == 'headers':
                continue
            for h, v in zip(headers, values):
                rows.append([school_name, category, entry, h, v])
    return rows


def normalize_line(line):
    x = re.sub(r"\$|,", "", line)
    return x


def normalize_num(n):
    if n == '-' or n == '':
        return 0
    return float(n)


def get_cols(line, start, num, breaks):
    vals = []
    last_break = breaks[0]
    for b in breaks[1:]:
        vals.append(line[last_break:b].strip())
        last_break = b
    vals.append(line[breaks[-1]:].strip())

    return vals[start:start + num]


def get_cols_dashed(line, start, num, _):
    splits = re.sub(r'\s\s+', ';', line).split(';')
    return splits[start:start + num]


def get_nums(line, start, num, breaks):
    x = [normalize_num(n) for n in get_cols(line, start, num, breaks)]
    return x


def get_nums_dashed(line, start, num, _):
    return [normalize_num(n) for n in get_cols_dashed(line, start, num, None)]


def find_fields(rows):
    filled = [False] * max(len(r) for r in rows)
    # Overlap all the rows to find non-spaces.
    for row in rows:
        for i in range(0, len(row)):
            filled[i] |= row[i] != ' '

    mask_string = ''.join(['c' if x else ' ' for x in filled])
    char_patterns = [x.strip()
                     for x in re.sub(r'\s\s+', '\t', mask_string).split('\t')]
    pattern_regex = r'\s+'.join([f'({pattern})' for pattern in char_patterns])
    matches = re.search(pattern_regex, mask_string)
    header_splits = [(matches.start(i), matches.end(i))
                     for i in range(1, len(char_patterns) + 1)]

    first_header = [rows[0][s[0]:s[1]].strip() for s in header_splits]
    second_header = [rows[1][s[0]:s[1]].strip() for s in header_splits]
    headers = [' '.join([a, b]).strip()
               for a, b in zip(first_header, second_header)]

    splits = []
    last_end = 0
    for i in range(0, len(header_splits)):
        if i + 1 < len(header_splits):
            # Normally choose the 2/3 point between start and end
            next_start = header_splits[i + 1][0]
            cur_end = header_splits[i][1]
            delta = next_start - cur_end
            end = header_splits[i][1] + int(delta * 0.666)
        else:
            end = None  # Go the end of line.
        splits.append((last_end, end))
        last_end = end

    return headers, splits


def parse_school_funded_staff(rows, school_info):
    headers = [
        "Staff Type",
        "General Education",
        "Special Education",
        "Bilingual Education",
        "State LAP",
        "Federal Title I",
        "Other Grants",
        "Seattle Ed. Levy",
        STAFFING_TOTAL_COLUMN,
    ]

    all_fields = []
    for row in rows[2:]:
        all_fields.append(get_cols_dashed(row, 0, 9, None))
    logger.debug(all_fields)

    staffing = school_info['staffing'] = {}
    for fields in all_fields:
        staff_type, staffing_info = parse_school_funded_staff_fields(
            headers, fields)
        if staff_type is not None:
            staffing[staff_type] = staffing_info


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


def parse_school_funded_staff_fields(headers, fields):
    staff_type = fields[0]
    if staff_type in STAFFING_TYPES_CONFIG:
        staffing_info = {}
        get_school_funded_staff_fields(staffing_info, headers[1:],
                                       fields[1:])
        return staff_type, staffing_info
    else:
        return None, None


FUNDING_CONFIG = [
    {
        'name': 'General Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Special Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Bilingual Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'State LAP',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Federal Title I',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Other Grants',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Seattle Ed. Levy',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Funding Type',
        'start': 1,
        'num': 3,
        'extractor': get_cols_dashed,
        'breaks': None,
    },
    {
        'name': 'Total School Budget',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
]


ENROLLMENT_CONFIG = [
    {
        'name': 'Total AAFTE* Enrollment',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Special Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Bilingual Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
    {
        'name': 'Free and Reduced Lunch',
        'start': 1,
        'num': 3,
        'extractor': get_nums_dashed,
        'breaks': None,
    },
]


STAFFING_TYPES_CONFIG = [
    "Bilingual Teachers",
    "Classroom Teachers",
    "Clerical Support",
    "Counselors & Social Workers",
    "Instructional Assistants",
    "Librarians",
    "Office & Clerical",
    "Other Certificated Staff",
    "Other Support",
    "Preschool Teachers",
    "School Administrators",
    "Special Education Teachers",
    "Specialists & Interv Teachers",
    STAFFING_TOTAL_ROW,
]


def parse_page(page):
    school_info = {}
    mode = Mode.SchoolName

    row_cache = None

    logger.debug("Parsing page")
    for raw_line in page.split('\n'):
        line = normalize_line(raw_line.strip())
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
                if line.startswith('Budget by Funding Type'):
                    logger.debug("Funding")
                    mode = Mode.BudgetByFundingType
                elif x := re.match(
                        r".*(\d\d-\d\d)\s+(\d\d-\d\d*)\s+(\d\d-\d\d).*",
                        line):
                    school_info['enrollment'] = {}
                    school_info['enrollment']['School Year'] = [x[1], x[2],
                                                                x[3]]
                else:
                    for extract_config in ENROLLMENT_CONFIG:
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
                    for extract_config in FUNDING_CONFIG:
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
                if line.startswith('Total Staff FTE'):
                    row_cache.append(raw_line)
                    parse_school_funded_staff(row_cache, school_info)
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
                    for staff_type in STAFFING_TYPES_CONFIG:
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
                        line, 1, 1, OTHER_INFO_BREAK)
                elif line.startswith('Student FTE'):
                    school_info['other']['student_fte'] = get_nums(
                        line, 1, 1, OTHER_INFO_BREAK)
                elif line.startswith('Student Teacher Ratio'):
                    school_info['other']['ratio'] = get_nums(
                        line, 1, 1, OTHER_INFO_BREAK)
                elif line.startswith('Budget Per Student'):
                    school_info['other']['budget_per_student'] = get_nums(
                        line, 1, 1, OTHER_INFO_BREAK)

                elif line.startswith('Seattle Public School'):
                    logger.debug("Parsing Done")
                    mode = Mode.Done

            case Mode.Done:
                break

    return school_info


def parse_file_into_schools(infile):
    """Takes a file of "pdf2txt -layout" and parses it into an array version.

    Returns: List of schools where each entry contains normalized strings
             extracted from infile.
    """
    all_text = infile.read()
    pages = all_text.split("\f")

    # Skip pages with less than 15 lines. These are likely blanks or images
    # between sections. The Images comes out to around 10 lines.
    return [parse_page(page) for page in pages if page.count('\n') > 15]


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


def extract_funding(info, raw_info):
    """Extract the structed funding data strings in raw_info into info"""
    funding_info = raw_info["funding"]
    year_columns = funding_info["Funding Type"]

    for i in range(0, len(year_columns)):
        year_info = {}
        expected_total = None
        for extract_config in FUNDING_CONFIG:
            name = extract_config['name']
            if name == 'Funding Type':
                # TODO: Do this more generically.
                continue
            elif name == 'Total School Budget':
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

    # Validation loop.
    staff_type_totals = {}
    funding_type_totals = {}
    total_column_fte_sum = 0
    total_row_fte_sum = 0
    total_row_and_column_fte = 0
    for funding_type, staff_type_fte in year_info.items():
        # Total column is accidentally a funding type. skip.
        if funding_type == STAFFING_TOTAL_COLUMN:
            for st, fte in staff_type_fte.items():
                if st == STAFFING_TOTAL_ROW:
                    total_row_and_column_fte = fte
                else:
                    total_column_fte_sum += fte
            continue

        for staff_type, fte in staff_type_fte.items():
            # Account for Staff type
            if staff_type in staff_type_totals:
                staff_type_totals[staff_type] += fte
            else:
                staff_type_totals[staff_type] = fte

            # Account for Funding Total. Skip the Total line for the funding
            # summation
            if staff_type == STAFFING_TOTAL_ROW:
                total_row_fte_sum += fte
                continue

            if funding_type in funding_type_totals:
                funding_type_totals[funding_type] += fte
            else:
                funding_type_totals[funding_type] = fte

    # Validate
    if not math.isclose(total_column_fte_sum, total_row_and_column_fte):
        errors.append(['total_column',
                       total_row_and_column_fte - total_column_fte_sum])
        logger.error(f"{info['metadata']['name']}: "
                     f"{STAFFING_TOTAL_COLUMN} in staffing is "
                     f"{total_row_and_column_fte:.2f} but got "
                     f"{total_column_fte_sum:.2f}")

    if not math.isclose(total_row_fte_sum, total_row_and_column_fte):
        errors.append(['total_row',
                       total_row_and_column_fte - total_row_fte_sum])
        logger.warning(f"{info['metadata']['name']}: "
                       f"{STAFFING_TOTAL_ROW} in staffing is "
                       f"{total_row_and_column_fte:.2f} but got "
                       f"{total_row_fte_sum:.2f}")

    # Check same number of funding types. Subtract one for total.
    fund_type_diff = (
        (len(year_info.keys()) - 1) - len(funding_type_totals.keys()))
    if fund_type_diff != 0:
        errors.append(['funding_type', fund_type_diff])
        logger.warning(f"{info['metadata']['name']}: "
                       f"Differing number of funding types in {year_info} "
                       f"{len(year_info.keys()) - 1} and "
                       f"{len(funding_type_totals.keys())}")

    # Loop over all staffing collating data in 2 dimensions.
    # TODO: Should this be a data frame?
    for funding_type, staff_type_fte in year_info.items():
        # Check number of staff types match
        staff_type_diff = (len(staff_type_fte.keys()) -
                           len(staff_type_totals.keys()))
        if staff_type_diff != 0:
            errors.append(['staff_type', staff_type_diff])
            logger.warning(f"{info['metadata']['name']}: "
                           "Differing number of staff types in {funding_type} "
                           f"{year_info} {staff_type_fte.keys()} and "
                           f"{staff_type_totals.keys()}")

        # Verify the match of staff type FTE sums.
        for staff_type, fte in staff_type_fte.items():
            if funding_type == STAFFING_TOTAL_COLUMN:
                logger.debug(
                    f"{info['metadata']['name']}: "
                    f"Validating {fte:.1f} {staff_type} "
                    f"{staff_type_totals[staff_type]:.1f}")
                if not math.isclose(fte, staff_type_totals[staff_type]):
                    # Skip "Total School Funded Staff" as it will double-count
                    # errors from other staff error issues. This does mean
                    # there can be a summation problem on the row, but it's
                    # probably okay. Emit the error message though.
                    if staff_type != 'Total School Funded Staff':
                        errors.append(['staff_type_fte',
                                       fte - staff_type_totals[staff_type]])

                    logger.warning(f"{info['metadata']['name']}: "
                                   "Mismatched Staff type total for "
                                   f"{staff_type}. Got "
                                   f"{staff_type_totals[staff_type]:.1f} "
                                   f"but expecting {fte:.1f}")
                continue

            # Verify the match of funding category FTE sums.
            if staff_type == "Total School Funded Staff":
                if not math.isclose(fte, funding_type_totals[funding_type]):
                    errors.append(['fund_type_fte',
                                   fte - funding_type_totals[funding_type]])
                    logger.warning(f"{info['metadata']['name']}: "
                                   "Mismatched Funding type total for "
                                   f"{funding_type}. Got "
                                   f"{funding_type_totals[funding_type]} "
                                   f"but expecting {fte}")

    merge_year_info(info, current_year, 'staffing', year_info)
    if "staffing" not in info["metadata"]["errors"]:
        info["metadata"]["errors"]["staffing"] = {}
    info["metadata"]["errors"]["staffing"][current_year] = errors


def extract_enrollment(info, raw_info):
    """Extract the structed funding data strings in raw_info into info"""

    # This happens with Skills Center.
    if "enrollment" not in raw_info:
        return

    enrollment_info = raw_info["enrollment"]
    year_columns = enrollment_info["School Year"]

    for i in range(0, len(year_columns)):
        year_info = {}
        for extract_config in ENROLLMENT_CONFIG:
            name = extract_config['name']
            if name in enrollment_info:
                year_info[name] = enrollment_info[name][i]

        merge_year_info(info, year_columns[i], 'enrollment', year_info)


def normalize_school(raw_info, school_map):
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
    name = raw_info["name"]
    school_map_info = school_map[raw_info["name"]]
    info = {
        "metadata": school_map_info | {
            "scraped_name": raw_info["name"],
            "errors": {}
        },
        "year_data": {
        }
    }

    logger.info(f"Extracting funding for {name}")
    extract_funding(info, raw_info)

    logger.info(f"Extracting funding for {name}")
    extract_enrollment(info, raw_info)

    # Use the most recent year as the "current" year.
    years = list(info["year_data"].keys())
    years.sort()
    current_year = years[-1]
    logger.info(f"Extracting staffing for {name}")
    extract_staffing(info, raw_info, current_year)

    return info


def value_for_csv(category, value):
    match category:
        case "staffing":
            return "fte", value, None
        case "funding":
            return "dollars", value, None
        case "enrollment":
            return "aafte", value, None


def merge_staffing_error_for_year(counters, errors):
    for error in errors:
        match error[0]:
            case "fund_type_fte":
                counters["funding_error_total_fte"] += error[1]
                counters["funding_fte_error_count"] += 1
            case "staff_type_fte":
                counters["staff_error_total_fte"] += error[1]
                counters["staff_fte_error_count"] += 1


def calculate_staffing_errors(parsed_schools):
    all_errors = {}
    for school in parsed_schools:
        for year, errors in school["metadata"]["errors"]["staffing"].items():
            if year not in all_errors:
                all_errors[year] = {
                    "funding_fte_error_count": 0,
                    "funding_error_total_fte": 0,
                    "staff_fte_error_count": 0,
                    "staff_error_total_fte": 0,
                }
            merge_staffing_error_for_year(all_errors[year], errors)
    return all_errors


def write_denormalized_csv(outfile, parsed_schools):
    writer = csv.writer(outfile)
    writer.writerow([
        'school',
        'school_code',
        'school_year_code',
        'category',  # enrollment, staffing, funding
        'subcategory',
        'item_name',
        'value_type',
        'amount',
        'other_value',
    ])
    for school in parsed_schools:
        name = school['metadata']['name']
        school_code = school['metadata']['school_code']

        # Output all the year data.
        for year, year_entries in school['year_data'].items():
            for category, category_entries in year_entries.items():
                for item_name, item_entries in category_entries.items():
                    if category == 'staffing':
                        subcategoires = item_entries
                    else:
                        # For 1 dimension categories, subcategory is the
                        # same as category
                        subcategoires = {category: item_entries}

                    for subcategory, item_value in subcategoires.items():
                        value_type, amount, other_value = value_for_csv(
                            category, item_value)
                        writer.writerow([
                            name,
                            school_code,
                            year,
                            category,
                            subcategory,
                            item_name,
                            value_type,
                            amount,
                            other_value
                        ])

    budget_errors = calculate_staffing_errors(parsed_schools)
    for year, error_counts in budget_errors.items():
        for item_name, value in error_counts.items():
            if item_name.endswith("_count"):
                value_type = "count"
            elif item_name.endswith("total_fte"):
                value_type = "fte"
            else:
                raise ValueError(item_name)
            writer.writerow([
                "error_counts",
                "-1",
                year,
                "errors",
                item_name,
                value_type,
                value,
                None
            ])


def main():
    parser = argparse.ArgumentParser(
        description='Parses the school breakdowns out of a budget file')

    parser.add_argument('--log-level', default='INFO',
                        help='set log level {DEBUG, INFO, WARNING, ERROR}')
    parser.add_argument('--infile',
                        type=argparse.FileType('r', encoding='UTF-8'),
                        required=True,
                        help='output of "pdf2txt -layout -f start -l end"')
    parser.add_argument('--schoolmap',
                        type=argparse.FileType('r', encoding='UTF-8'),
                        required=True,
                        help='csv with school_code, normalized name, match"')
    parser.add_argument('--outfile',
                        type=argparse.FileType('w', encoding='UTF-8'),
                        required=True,
                        help='output csv')

    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)

    raw_parsed_schools = parse_file_into_schools(args.infile)
    school_map = {row[2]: {"school_code": row[0], "name": row[1]} for row in
                  csv.reader(args.schoolmap) if row[2]}

    parsed_schools = [normalize_school(raw_info, school_map)
                      for raw_info in raw_parsed_schools]

    write_denormalized_csv(args.outfile, parsed_schools)


if __name__ == '__main__':
    main()
