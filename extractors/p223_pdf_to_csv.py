"""
Hacky ps223 pdf to csv converter.
$ curl \
    https://www.seattleschools.org/wp-content/uploads/2024/09/P223_Sep24.pdf \
    -o p223_sep24.pdf
$ pdftotext -layout p223_sep24.pdf -f 2 - | tr -s ' ' > squished.txt
$ python3 p223_pdf_to_csv.py squished.txt out.csv
"""

import re
import csv
import sys

SCHOOL_PREFIX = 'School: '
HEADERS = [
    "Regular Program",
    "Bilingual Served",
    "Spec. Ed. Served",
    "Male",
    "Female",
    "Non-Binary",
    "Total Student Count",
    "P223 Total Count",
    "P223 Total FTE",
]

PRESCHOOL_LINE = 'Gr: Preschool'
STATE_FDK_LINE = ' State FDK'
STATE_FDK_EQUALS_LINE = ' State FDK ='
K_12_LINE_REGEX = re.compile('^ ([1-9K][0-2]?)')


def get_grade(line):
    if line.startswith(PRESCHOOL_LINE):
        return 'Preschool', line[len(PRESCHOOL_LINE):].strip()

    grade = None
    if line.startswith(STATE_FDK_LINE) and not line.startswith(STATE_FDK_EQUALS_LINE):
        return 'K', line[len(STATE_FDK_LINE):].strip()

    m = K_12_LINE_REGEX.match(line)
    if m:
        grade = m.group(1)
        return grade, line[len(grade) + 1:].strip()
    else:
        return None, None


def parse_line(line, school):
    grade, remaining = get_grade(line)
    if grade and remaining:
        school[grade] = [float(x) for x in remaining.split(' ')]


def main(filename, csvname, month=None):
    p233_data = {}
    school = None
    with open(filename, "r", encoding="utf-8") as infile:
        for line in infile:
            if line.startswith(SCHOOL_PREFIX):
                school = {}
                p233_data[line[len(SCHOOL_PREFIX):].strip()] = school
            else:
                parse_line(line, school)

    with open(csvname, 'w', newline='') as outfile:
        writer = csv.writer(outfile)

        header_row = []
        if month is not None:
            header_row.append('Month')

        header_row.extend(['School', 'Grade'] + HEADERS)
        writer.writerow(header_row)

        for school, gradeinfo in p233_data.items():
            for grade, data in gradeinfo.items():
                data_row = []
                if month is not None:
                    data_row.append(month)

                data_row.extend([school, grade] + data)
                writer.writerow(data_row)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
