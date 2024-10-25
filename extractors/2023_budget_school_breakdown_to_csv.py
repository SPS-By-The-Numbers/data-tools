import csv
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


def parse_page(page):
    school_info = {}
    mode = Mode.SchoolName

    # Used to put together 2 line headers.
    first_header_line = None
    row_bitmap = [False] * MAX_LINE_LENGTH
    num_fields = 0

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
                    x = re.sub(r"\s\s*", "\t", line)
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
                if line.startswith('Funding Type'):
                    school_info['funding'] = {}
                    school_info['funding']['headers'] = get_cols(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('General Education'):
                    school_info['funding']['gen_ed'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Special Education'):
                    school_info['funding']['spec_ed'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Bilingual Education'):
                    school_info['funding']['bi_ling'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('State LAP'):
                    school_info['funding']['lap'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Federal Title I'):
                    school_info['funding']['title_i'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Other Grants'):
                    school_info['funding']['other_grants'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Seattle Ed. Levy'):
                    school_info['funding']['ed_levy'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)
                elif line.startswith('Total School Budget'):
                    school_info['funding']['total'] = get_nums(
                        line, 1, 3, FUNDING_COL_BREAK)

                elif line.startswith('School Funded Staff'):
                    mode = Mode.SchoolFundedStaff
                    first_header_line = None

            case Mode.SchoolFundedStaff:
                FIELD_SIZE = 16
                # The header is hard to parse. Just hard coding it.
                if line.startswith('General'):
                    # Every 15 chars is a column
                    if first_header_line is not None:
                        raise ValueError(first_header_line)
                    first_header_line = line

                if line.startswith('Staff Type'):
                    headers, header_matches = get_header_ranges(line)
                    first_headers, first_header_matches = get_header_ranges(
                        first_header_line)
                    print(line, headers, header_matches)

                    for i in range(len(headers)):
                        if i < len(first_header_line) and first_header_line[i]:
                            headers[i] = (first_header_line[i] + " " +
                                          headers[i])
                    school_info['staff'] = {}
                    school_info['staff']['headers'] = headers
                    num_fields = len(headers)
                    header_breaks = [0]
                    header_breaks.extend(
                        [x + 48 for x in range(0, num_fields * FIELD_SIZE,
                                               FIELD_SIZE)])
                elif line.startswith('Bilingual Education Teachers'):
                    school_info['funding']['bi_ling'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Classroom Teachers'):
                    school_info['funding']['classroom'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Instructional Assistants'):
                    school_info['funding']['ia'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Clerical Support'):
                    school_info['funding']['office'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Other Certificated Staff'):
                    school_info['funding']['other_cert'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Preschool Teachers'):
                    school_info['funding']['preschool'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('School Administrator'):
                    school_info['funding']['admins'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Special Education Teachers'):
                    print(line, header_breaks)
                    school_info['funding']['spec_ed'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Specialists & Intv. Teachers'):
                    school_info['funding']['specialists'] = get_nums(
                        line, 1, num_fields, header_breaks)
                elif line.startswith('Total School Funded Staff'):
                    school_info['funding']['total_fte'] = get_nums(
                        line, 1, num_fields, header_breaks)
                    mode = Mode.OtherData

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


def main(text_infile, csv_outfile):
    with open(text_infile, "r", encoding="utf-8") as infile:
        all_text = infile.read()
        pages = all_text.split("\f")
        parsed_pages = [parse_page(page) for page in pages if len(page) > 10]

    return
    rows = flatten_pages(parsed_pages)
    with open(csv_outfile, 'w', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow(['School Name', 'Category', 'Entry', 'Column',
                         'Value'])
        for row in rows:
            writer.writerow(row)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
