import argparse
# import csv
import re
import sys

from enum import Enum

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


def flatten_pages(pages):
    rows = []
    for page in pages:
        rows.extend(flatten_school_info(page))
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


def get_nums(line, start, num, breaks):
    x = [normalize_num(n) for n in get_cols(line, start, num, breaks)]
    return x


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
    headers, field_splits = find_fields(rows[0:2])

    all_fields = []
    for row in rows[2:]:
        fields = []
        all_fields.append(fields)
        for split in field_splits:
            fields.append(row[split[0]:split[1]].strip())

    for fields in all_fields:
        parse_school_funded_staff_fields(headers, fields, school_info)


def get_school_funded_staff_fields(output, value_headers,
                                   value_fields):
    """Each column is the Funding type for staff allocated.,

    Examples are General Education, Bilingual Education, Seattle Ed Levy,
    State LAP, Special Ecuation, Federl Title I and a Total column.
    """
    for h, v in zip(value_headers, [normalize_num(x) for x in value_fields]):
        if h not in output:
            output[h] = []
        output[h].append(v)


def parse_school_funded_staff_fields(headers, fields, school_info):
    match fields[0]:
        case ('Bilingual Education Teachers'
              'Total School Funded Staff' |
              'Specialists & Intv. Teachers' |
              'Special Education Teachers' |
              'School Administrator' |
              'Classroom Teachers' |
              'Instructional Assistants' |
              'Clerical Support' |
              'Other Certificated Staff' |
              'Preschool Teachers'):
            label = f'staff_type - {fields[0]}'
            school_info[label] = {'headers': headers}

            get_school_funded_staff_fields(school_info[label], headers[1:],
                                           fields[1:])


STAFFING_CONFIG = [
    {
        'name': 'General Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Special Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Bilingual Education',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'State LAP',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Federal Title I',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Other Grants',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Seattle Ed. Levy',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Funding Type',
        'start': 1,
        'num': 3,
        'extractor': get_cols,
        'breaks': FUNDING_COL_BREAK,
    },
    {
        'name': 'Total Budget',
        'start': 1,
        'num': 3,
        'extractor': get_nums,
        'breaks': FUNDING_TOTAL_BUDGET_BREAK,
    },
]


def parse_page(page):
    school_info = {}
    mode = Mode.SchoolName

    row_cache = None

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
                if x := re.match(
                        r".*(\d\d-\d\d)\s+(\d\d-\d\d*)\s+(\d\d-\d\d).*",
                        line):
                    school_info['enrollment'] = {}
                    school_info['enrollment']['headers'] = [x[1], x[2], x[3]]
                elif line.startswith('Total AAFTE* Enrollment'):
                    school_info['enrollment']['aafte'] = get_nums(
                        line, 1, 3, ENROLLMENT_COL_BREAK)
                elif line.startswith('Special Education'):
                    school_info['enrollment']['speced'] = get_nums(
                        line, 1, 3, ENROLLMENT_COL_BREAK)
                elif line.startswith('Bilingual Education'):
                    school_info['enrollment']['speced'] = get_nums(
                        line, 1, 3, ENROLLMENT_COL_BREAK)
                elif line.startswith('Free and Reduced Lunch'):
                    school_info['enrollment']['frl'] = get_nums(
                        line, 1, 3, ENROLLMENT_COL_BREAK)

                elif line.startswith('Total Budget'):
                    mode = Mode.BudgetByFundingType

            case Mode.BudgetByFundingType:
                # Example:
                #  Funding Type 22-23 23-24 24-25 School Budget
                #  General Education 274834 234343 299144
                #  ...
                if line.startswith('School Funded Staff'):
                    mode = Mode.SchoolFundedStaff
                    row_cache = []
                else:
                    for extract_config in STAFFING_CONFIG:
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
                # The header is hard to parse. Just hard coding it.
                if line.startswith('Total School Funded Staff'):
                    row_cache.append(raw_line)
                    parse_school_funded_staff(row_cache, school_info)
                    mode = Mode.OtherData
                elif (line.startswith('General') or
                      line.startswith('Staff Type') or
                      line.startswith('Bilingual Education Teachers') or
                      line.startswith('Classroom Teachers') or
                      line.startswith('Instructional Assistants') or
                      line.startswith('Clerical Support') or
                      line.startswith('Other Certificated Staff') or
                      line.startswith('Preschool Teachers') or
                      line.startswith('School Administrator') or
                      line.startswith('Special Education Teachers') or
                      line.startswith('Specialists & Intv. Teachers')):
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

    # Skip pages with less than 10 lines. These are likely blanks or images
    # between sections.
    return [parse_page(page) for page in pages if len(page) > 10]


def normalize_name(name):
    return name


def extract_funding(info, raw_info):
    """Extract the structed funding data strings in raw_info into info"""
    funding_info = raw_info["funding"]
    year_columns = funding_info["Funding Type"]

    for i in range(0, len(year_columns)):
        year_info = {}
        expected_total = None
        for extract_config in STAFFING_CONFIG:
            name = extract_config['name']
            if name == 'Funding Type':
                # TODO: Do this more generically.
                continue
            elif name == 'Total Budget':
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
            raise RuntimeError(
                f"expected {expected_total} got {recalculated_total}")

        info[year_columns[i]] = year_info


def extract_staffing(info, raw_info):
    """Extract the structed funding data strings in raw_info into info"""


def extract_enrollment(info, raw_info):
    """Extract the structed funding data strings in raw_info into info"""


def normalize_school(raw_info):
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
    info = {}
    info["name"] = normalize_name(raw_info["name"])
    extract_funding(info, raw_info)
    extract_staffing(info, raw_info)
    extract_enrollment(info, raw_info)
    return info


def main(text_infile, csv_outfile):
    parser = argparse.ArgumentParser(
        description='Parses the school breakdowns out of a budget file')

    parser.add_argument('--log-level', default='INFO',
                        help='set log level {DEBUG, INFO, WARNING, ERROR}')
    parser.add_argument('--infile',
                        type=argparse.FileType('r', encoding='UTF-8'),
                        required=True,
                        help='output of "pdf2txt -layout -f start -l end"')
    parser.add_argument('--outfile',
                        type=argparse.FileType('w', encoding='UTF-8'),
                        required=True,
                        help='output csv')

    args = parser.parse_args()

    raw_parsed_schools = parse_file_into_schools(args.infile)

    parsed_schools = [normalize_school(raw_info)
                      for raw_info in raw_parsed_schools]

    print(parsed_schools)

    # rows = flatten_pages(parsed_schools)
    # writer = csv.writer(args.outfile)
    # writer.writerow(['School Name', 'Category', 'Entry', 'Column', 'Value'])
    # for row in rows:
    #     writer.writerow(row)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
