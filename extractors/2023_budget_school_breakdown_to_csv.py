import csv
import re
import sys

from enum import Enum


ENROLLMENT_COLS = [7, 11, 17]

FUNDING_TYPE_COLS = [4, 14, 19]

Mode = Enum('Mode', ['SchoolName',
                     'EnrollmentAndDemographics',
                     'BudgetByFundingType',
                     'SchoolFundedStaff',
                     'OtherData',
                     'Done'])


def flatten_school_info(page):
    rows = []
    school_name = None
    for category, category_info in page.items():
        # Funding Type, General Education, 22-23, Amt
        # Category, Entry, Column, Amt
        if category == 'name':
            school_name = category_info
            continue
        print(category, category_info)
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


def get_cols(row, indicies):
    return [row[idx] for idx in indicies]


def get_nums(row, indicies):
    result = []
    for x in get_cols(row, indicies):
        if type(x) is int or type(x) is float:
                result.append(x)

        elif type(x) is str:
            if len(x) == 0:
                result.append(0)
            else:
                result.append(float(x.replace(",","")))

        else:
            raise ValueError(x)
    return result


def parse_page(page_rows):
    school_info = {}
    mode = Mode.SchoolName
    for row in page_rows:
        first = row[0]
        match mode:
            case Mode.SchoolName:
                # First line should be school name.
                if first and 'name' not in school_info:
                    school_info['name'] = first
                else:
                    if first == 'Enrollment and Demographics':
                        mode = Mode.EnrollmentAndDemographics

            case Mode.EnrollmentAndDemographics:
                # ,,,,,,,21-22,,,,"School Year
                # 22-23",,,,,,23-24,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
                # Total AAFTE* Enrollment,,,,,,,402.0,,,,354.0,,,,,,279.0,
                if row[ENROLLMENT_COLS[1]].startswith('School Year'):
                    school_info['enrollment'] = {}
                    school_info['enrollment']['headers'] = [
                        row[7],
                        row[11].split('\n')[1],
                        row[17]]
                elif first == 'Total AAFTE* Enrollment':
                    school_info['enrollment']['aafte'] = [
                        row[idx] for idx in ENROLLMENT_COLS]
                elif first == 'Special Education':
                    school_info['enrollment']['speced'] = [
                        row[idx] for idx in ENROLLMENT_COLS]
                elif first == 'Bilingual Education':
                    school_info['enrollment']['speced'] = [
                        row[idx] for idx in ENROLLMENT_COLS]
                elif first == 'Free and Reduced Lunch':
                    school_info['enrollment']['frl'] = [
                        row[idx] for idx in ENROLLMENT_COLS]

                elif first == 'Total Budget':
                    mode = Mode.BudgetByFundingType

            case Mode.BudgetByFundingType:
                if first == 'Funding Type':
                    school_info['funding'] = {}
                    school_info['funding']['headers'] = get_cols(
                        row, FUNDING_TYPE_COLS)
                elif first == 'General Education':
                    school_info['funding']['gen_ed'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Special Education':
                    school_info['funding']['spec_ed'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Bilingual Education':
                    school_info['funding']['bi_ling'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'State LAP':
                    school_info['funding']['lap'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Federal Title I':
                    school_info['funding']['title_i'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Other Grants':
                    school_info['funding']['other_grants'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Seattle Ed. Levy':
                    school_info['funding']['ed_levy'] = get_nums(
                        row, FUNDING_TYPE_COLS)
                elif first == 'Total School Budget':
                    school_info['funding']['total'] = get_nums(
                        row, FUNDING_TYPE_COLS)

                elif first == 'School Funded Staff':
                    mode = Mode.SchoolFundedStaff

            case Mode.SchoolFundedStaff:
                # The header is hard to parse. Just hard coding it.
                if line.startswith('Staff Type'):
                    school_info['staff'] = {}
                    school_info['staff']['headers'] = [
                        'General Education',
                        'Special Education',
                        'Bilingual Education',
                        'State LAP',
                        'Federal Title I',
                        'Other Grants',
                        'Seattle Ed Levy',
                        'Total Staff FTE',
                    ]
                elif line.startswith('Bilingual Teachers'):
                    school_info['funding']['bi_ling'] = get_nums(line, 2, 8)
                elif line.startswith('Classroom Teachers'):
                    school_info['funding']['classroom'] = get_nums(line, 2, 8)
                elif line.startswith('Counselors & Social Workers'):
                    school_info['funding']['counselors'] = get_nums(line, 4, 8)
                elif line.startswith('Instructional Assistants'):
                    school_info['funding']['ia'] = get_nums(line, 2, 8)
                elif line.startswith('Librarians'):
                    school_info['funding']['libraries'] = get_nums(line, 1, 8)
                elif line.startswith('Office & Clerical'):
                    school_info['funding']['office'] = get_nums(line, 3, 8)
                elif line.startswith('Other Support'):
                    school_info['funding']['other'] = get_nums(line, 2, 8)
                elif line.startswith('Preschool Teachers'):
                    school_info['funding']['preschool'] = get_nums(line, 2, 8)
                elif line.startswith('School Administrators'):
                    school_info['funding']['admins'] = get_nums(line, 2, 8)
                elif line.startswith('Special Education Teachers'):
                    school_info['funding']['spec_ed'] = get_nums(line, 3, 8)
                elif line.startswith('Specialists & Interv Teachers'):
                    school_info['funding']['specialists'] = get_nums(line,
                                                                     4, 8)
                elif line.startswith('Total Staff FTE'):
                    school_info['funding']['total'] = get_nums(line, 3, 8)

                elif line.startswith('Other Data'):
                    mode = Mode.OtherData

            case Mode.OtherData:
                if 'other' not in school_info:
                    school_info['other'] = {}
                    school_info['other']['headers'] = [
                        'value'
                    ]

                if line.startswith('Centrally Assistants Nurse FTE'):
                    school_info['other']['nurse'] = get_nums(line, 4, 1)
                elif line.startswith('Classroom & Specialist Teachers'):
                    school_info['other']['teachers'] = get_nums(line, 4, 1)
                elif line.startswith('Student FTE'):
                    school_info['other']['student_fte'] = get_nums(line, 2, 1)
                elif line.startswith('Student Teacher Ratio'):
                    school_info['other']['ratio'] = get_nums(line, 3, 1)
                elif line.startswith('Budget Per Student'):
                    school_info['other']['budget_per_student'] = get_nums(line,
                                                                          3, 1)

                elif line.startswith('Seattle Public School'):
                    mode = Mode.Done

            case Mode.Done:
                break

    return school_info


def main(text_infile, csv_outfile):
    with open(text_infile, newline='') as csvfile:
        spamreader = csv.reader(csvfile)
        pages = []
        current_page = []
        for row in spamreader:
            if all(not v for v in row):
                continue
            current_page.append(row)
            if row[0] == 'Budget Per Student':
                pages.append(current_page)
                current_page = []

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
