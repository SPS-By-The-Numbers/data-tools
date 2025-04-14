import argparse
import csv
import logging

from common import common_pdftext_setup
from budget.school_allocations_validate import (STAFFING_TOTAL_COLUMN,
                                                STAFFING_TOTAL_ROW)
from budget.extractor import (parse_file_into_schools, normalize_school,
                              get_cols_dashed, get_nums_dashed)
from budget.csv_utils import write_denormalized_csv

logger = logging.getLogger(__name__)


def get_school_funding_staff_fields(header_rows, data_rows, staffing_config):
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
    for row in data_rows:
        all_fields.append(get_cols_dashed(row, 0, 9, None))

    return headers, all_fields


FUNDING_TOTAL_BUDGET_BREAK = [0, 22, 60, 79]

PAGE_CONFIG = {
    "total_budget_row": 'Total School Budget',

    # Line that matches start of the staffing section.
    "staff_section_end": "Total Staff FTE",

    # Start marker for funding section.
    "funding_section_start": "Budget by Funding Type",

    # For parsing the "Other Info" section.
    # TODO: This is in the wrong config.
    "other_info_break": [0, 60]
}

FUNDING_CONFIG = {
    # Name of row with Total budget for funding used to check scrape.
    "total_budget_row": 'Total School Budget',

    "rows": [
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
    ],
}


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


STAFFING_CONFIG = {
    "get_fields": get_school_funding_staff_fields,
    "all_types": [
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
    ],
}


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
