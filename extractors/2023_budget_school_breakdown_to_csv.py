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
    print(all_fields)

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

                elif line.startswith('Total Budget'):
                    school_info['funding']['total'] = get_nums(
                        line, 1, 3, FUNDING_TOTAL_BUDGET_BREAK)

                elif line.startswith('School Funded Staff'):
                    mode = Mode.SchoolFundedStaff
                    row_cache = []

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


def main(text_infile, csv_outfile):
    with open(text_infile, "r", encoding="utf-8") as infile:
        all_text = infile.read()
        pages = all_text.split("\f")
        parsed_pages = [parse_page(page) for page in pages if len(page) > 10]

    rows = flatten_pages(parsed_pages)
    with open(csv_outfile, 'w', newline='') as outfile:
        writer = csv.writer(outfile)
        writer.writerow(['School Name', 'Category', 'Entry', 'Column',
                         'Value'])
        for row in rows:
            writer.writerow(row)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
