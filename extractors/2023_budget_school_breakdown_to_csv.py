import argparse
import csv
import logging
import re

from common import common_pdftext_setup
from budget.csv_utils import write_denormalized_csv
from budget.extractor import (parse_file_into_schools, normalize_school,
                              get_cols, get_nums)

logger = logging.getLogger(__name__)

ENROLLMENT_COL_BREAK = [0, 35, 54, 70, 87]
FUNDING_COL_BREAK = [0, 22, 63, 85]
FUNDING_TOTAL_BUDGET_BREAK = [0, 22, 60, 79]
OTHER_INFO_BREAK = [0, 60]


FUNDING_CONFIG = {
    # Name of row with Total budget for funding used to check scrape.
    "total_budget_row": 'Total Budget',

    "rows": [
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
    ],
}


PAGE_CONFIG = {
    "total_budget_row": 'Total Budget',

    # Line that matches start of the staffing section.
    "staff_section_end": "Total School Funded Staff",

    # Start marker for funding section.
    "funding_section_start": 'Total Budget',

    # For parsing the "Other Info" section.
    # TODO: This is in the wrong config.
    "other_info_break": [0, 60]
}


ENROLLMENT_CONFIG = {
    "rows": [
        {
            'name': 'Total AAFTE* Enrollment',
            'start': 1,
            'num': 3,
            'extractor': get_nums,
            'breaks': ENROLLMENT_COL_BREAK,
        },
        {
            'name': 'Special Education',
            'start': 1,
            'num': 3,
            'extractor': get_nums,
            'breaks': ENROLLMENT_COL_BREAK,
        },
        {
            'name': 'Bilingual Education',
            'start': 1,
            'num': 3,
            'extractor': get_nums,
            'breaks': ENROLLMENT_COL_BREAK,
        },
        {
            'name': 'Free and Reduced Lunch',
            'start': 1,
            'num': 3,
            'extractor': get_nums,
            'breaks': ENROLLMENT_COL_BREAK,
        },
    ],
}


STAFFING_CONFIG = {
    "get_fields": get_school_funding_staff_fields,
    "all_types": [
        'Total School Funded Staff',
        'Bilingual Education Teachers',
        'Classroom Teachers',
        'Clerical Support',
        'Instructional Assistants',
        'Other Certificated Staff',
        'Preschool Teachers',
        'School Administrator',
        'Special Education Teachers',
        'Specialists & Intv. Teachers'
    ],
}



def find_fields(rows):
    filled = [False] * max(len(r) for r in rows)
    # Overlap all the rows to find non-spaces.
    for row in rows:
        for i in range(0, len(row)):
            filled[i] |= row[i] != ' '

    # Consider all blank spaces until the first filled to be part of the first
    # field. This ignores leading whitespace which causes issues if the page
    # if off-aligned as the alternative programs often are.
    for i in range(0, len(row)):
        if filled[i]:
            break
        filled[i] = True

    mask_string = ''.join(['c' if x else ' ' for x in filled])
    char_patterns = [x.strip()
                     for x in re.sub(r'\s\s+', '\t', mask_string).split('\t')]
    pattern_regex = r'\s+'.join([f'({pattern})' for pattern in char_patterns])
    matches = re.search(pattern_regex, mask_string)
    header_splits = [(matches.start(i), matches.end(i))
                     for i in range(1, len(char_patterns) + 1)]

    first_header = [rows[0][s[0]:s[1]].strip() for s in header_splits]
    if len(rows) > 1:
        second_header = [rows[1][s[0]:s[1]].strip() for s in header_splits]
        headers = [' '.join([a, b]).strip()
                   for a, b in zip(first_header, second_header)]
    else:
        headers = first_header

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


def get_school_funding_staff_fields(header_rows, data_rows, staffing_config):
    headers, field_splits = find_fields(header_rows)

    all_fields = []
    for row in data_rows:
        fields = []
        all_fields.append(fields)
        for split in field_splits:
            fields.append(row[split[0]:split[1]].strip())

    return headers, all_fields


def main():
    parser = argparse.ArgumentParser(
        description='Parses the school breakdowns out of a budget file')

    parser.add_argument('--schoolmap',
                        type=argparse.FileType('r', encoding='UTF-8'),
                        required=True,
                        help='csv with school_code, normalized name, match"')

    args = common_pdftext_setup(parser)
    logging.basicConfig(level=args.log_level)

    raw_parsed_schools = parse_file_into_schools(args.infile,
                                                 PAGE_CONFIG, FUNDING_CONFIG,
                                                 ENROLLMENT_CONFIG,
                                                 STAFFING_CONFIG)
    school_map = {row[2]: {"school_code": row[0], "name": row[1]} for row in
                  csv.reader(args.schoolmap) if row[2]}

    parsed_schools = [normalize_school(raw_info, school_map)
                      for raw_info in raw_parsed_schools]

    write_denormalized_csv(args.outfile, parsed_schools)


if __name__ == '__main__':
    main()
