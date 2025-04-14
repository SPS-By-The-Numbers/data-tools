import argparse
import logging

from budget import line_tools
from budget import school_info_tools as si_tools
from common import common_pdftext_setup
from enum import Enum

logger = logging.getLogger(__name__)


Section = Enum('Section', ['SchoolAttributes',
                           'StaffingAllocations',
                           'NonStaffAllocations',
                           'TitleIAndLAP',
                           'TotalAllocations',
                           'WssAndSpecEd',
                           'AboveWss',
                           'Done'])


def default_line_parser(school_name, school_info, current_section,
                        line, raw_line, errors):
    errors.append("Default Parser hit. oops")
    return Section.Done


def school_attributes_line_parser(school_name, school_info, current_section,
                                  line, raw_line, errors):
    """Parses one school attribute line into the school_info struct.

    Attributes are free-form strings tags. They are parseable by splitting
    on two consectuive spaces and trimming.
    """
    if line.startswith("Fund  "):
        return Section.StaffingAllocations

    si_tools.append_text_values(school_info,
                                "attributes",
                                line_tools.tokenize_by_two_space(line))
    return current_section


LineParsers = {
    Section.SchoolAttributes: school_attributes_line_parser,
    Section.StaffingAllocations: default_line_parser,
    Section.NonStaffAllocations: default_line_parser,
    Section.TitleIAndLAP: default_line_parser,
    Section.TotalAllocations: default_line_parser,
    Section.WssAndSpecEd: default_line_parser,
    Section.AboveWss: default_line_parser,
}


def _break_lines_by_school(infile):
    """Separate a file into all the raw-lines for each school."""
    raw_lines_by_school = {}

    cur_school = None
    raw_lines = []
    for raw_line in infile.readlines():
        if raw_line.endswith("Budget Allocation\n"):
            if cur_school is not None:
                logging.info(f"Write {cur_school} with {len(raw_lines)} lines")
                raw_lines_by_school[cur_school] = raw_lines

            # Reset raw_lines once Budget Allocation is found.
            raw_lines = []

            # First entry is the school. It's a left-justified header like
            #
            #  Alan T Sugiyama HS      -      2025-26 Budget Allocation
            #
            # Sometimes there is a dash. Sometimes not. Spacing is not exact
            # but there is always more than 1 space between fields so split
            # by double-space and grab the first entry
            cur_school = line_tools.tokenize_by_two_space(raw_line.strip())[0]
        else:
            raw_lines.append(raw_line)

    # Catch straggler.
    if cur_school is not None:
        logging.info(f"Write {cur_school} with {len(raw_lines)} lines")
        raw_lines_by_school[cur_school] = raw_lines

    return raw_lines_by_school


def extract_data_from_school(school_name, raw_lines, errors):
    # 1. Read attribute (HiPov, Intl, Option, Tier X, etc) until
    #  "Staffing Allocations" is found.
    #
    # 2. parse the rows based on Pattern of
    #   [Fund]* [Fund Center]* [Fund Center Code] [Budget Item] \
    #   [Budget Item Id]* [FTE]* [$allocation]
    #
    # The problem is that Fund, Fund Centert and Fund Center Code are not
    # repeated if its the same as the previous row. Similarly FTE is blank if
    # $allocation is 0.
    #
    # Read until "Total Staffing (FTE) Allocation"
    #
    # 3. Parse the Non-Staff Allocations
    #   [Fund] [Fund Center] [Fund Center Code] [Budget Item] \
    #   [Budget Item Id] [$allocation]
    #
    # Read until "Total Non-Staff Allocations"
    #
    # 4. parse the Title I & Learning Assistant Program
    #
    #   [Fund] [Fund Center] [Fund Center Code] [Budget Item] [$allocation]
    #
    # Read until "Total Title I & LAP"
    #
    # 4. Parse Allocated - Budgeted Centrally
    #
    # Read until "Total Allocated/Budgeted Centrally"
    #
    # 5. Read "Total Allocations" as a FTE sanitcheck.
    #
    # 6. Read WSS Enrollment rules as well as Projected Special Ed Staffing.
    #   Note, it's slightly differnet for HS.
    #
    #  TODO: This will be the hardest to parse.
    #
    # 7. "Read Allocation Above Weighted Staffing Standards"
    #  Stop at end of file.

    current_section = Section.SchoolAttributes
    school_info = {}
    for raw_line in raw_lines:
        if current_section == Section.Done:
            break

        # Skip empty lines.
        line = raw_line.strip()
        if not line:
            continue

        # Consume the line.
        print("hi, ", line)
        current_section = LineParsers[current_section](
            school_name, school_info, current_section, line, raw_line,
            errors)

    return school_info


def main():
    parser = argparse.ArgumentParser(description='Parses a purplebook')

    args = common_pdftext_setup(parser)
    lines_by_schools = _break_lines_by_school(args.infile)

    schools = {}
    errors = []
    for name, lines in lines_by_schools.items():
        schools[name] = extract_data_from_school(name, lines, errors)

    print(schools)


if __name__ == '__main__':
    main()
