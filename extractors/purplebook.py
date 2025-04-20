import argparse
import csv
import logging

from budget import line_tools
from budget import school_info_tools as si_tools
from common import common_logging_setup, common_pdftext_setup, get_args
from purplebook.section_parser import Section, SectionParsers

logger = logging.getLogger(__name__)


def staffing_allocations_line_accumulate(school_name, school_info,
                                         current_section, line, raw_line,
                                         errors):
    """Parses one Staffing Allocations line.

    Attributes have multiple sections split by spaces, mostly:

       [Fund]* [Fund Center]* [Fund Center Code] [Budget Item] \
       [Budget Item Id]* [FTE]* [$allocation]

    The problem is that Fund, Fund Centert and Fund Center Code are not
    repeated if its the same as the previous row. Similarly FTE is blank if
    $allocation is 0.  Also if things get squished up, you may only have
    one space.

    This line parsing instead is done by popping off a field from the _right_
    and then examining the field format to see what value it might be.

    "Total Staffing (FTE) Allocation" is the start of the next section.
    """
    if line.startswith("Total Staffing (FTE) Allocation"):
        # TODO: Parse the value out of this row.
        return Section.NonStaffAllocations

    fields = line_tools.tokenize_by_two_space(line)
    si_tools.append_text_values(school_info, "staffing", fields)
    return current_section


def _break_lines_by_school(infile):
    """Separate a file into all the raw-lines for each school."""
    raw_lines_by_school = {}

    cur_school = None
    raw_lines = []
    for raw_line in infile.readlines():
        if raw_line.endswith("Budget Allocation\n"):
            if cur_school is not None:
                logging.info(
                    f"Finding {cur_school} with {len(raw_lines)} lines")
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

    school_info = {"totals": {}}

    current_section = Section.Start
    next_section = Section.SchoolAttributes
    section_parser = SectionParsers[current_section](school_name, errors)

    for raw_line in raw_lines:
        if next_section is not None and next_section != current_section:
            section_parser.commit(school_info)
            current_section = next_section
            if current_section == Section.Done:
                break
            section_parser = SectionParsers[current_section](school_name,
                                                             errors)

        # Skip empty lines.
        line = line_tools.realign_dollar_sign(raw_line.strip())
        if not line:
            continue

        # Consume the line.
        next_section = section_parser.accumulate(line, raw_line)

    # Catch straggler
    if current_section != Section.Done:
        section_parser.commit(school_info)

    return school_info


def write_denormalized_csv(outfile, schools):
    writer = csv.writer(outfile)
    FUNDING_COLS = [
        "fund_id",
        "fund_center",
        "fund_center_id",
        "budget_item",
        "budget_item_id",
        "fte",
        "amount",
    ]
    writer.writerow(
        [
            'school',
            'section',
            "otherval",
        ] + FUNDING_COLS
    )

    for school_name, school_info in schools.items():
        for section, items in school_info.items():
            match section:
                case "attributes":
                    for attr in items:
                        writer.writerow([
                            school_name,
                            section,
                            attr])

                case "totals":
                    for total_name, values in items.items():
                        if total_name == 'wss':
                            for k, v in values.items():
                                writer.writerow([
                                    school_name,
                                    section,
                                    "",  # otherval
                                    "",  # fund_id
                                    "",  # fund_center
                                    "",  # fund_center_id
                                    k,   # budget_item
                                    "",  # budget_item_id
                                    v,
                                    "",
                                ])
                        else:
                            writer.writerow([
                                school_name,
                                section,
                                "",  # otherval
                                "",  # fund_id
                                "",  # fund_center
                                "",  # fund_center_id
                                total_name,  # budget_item
                                "",  # budget_item_id
                                values["fte"],
                                values["amount"],
                            ])

                case "above_wss":
                    for row in items:
                        writer.writerow([
                            school_name,
                            section,
                            row['date'],  # otherval
                            "",  # fund_id
                            row["funding_source"],  # fund_center
                            "",  # fund_center_id
                            row["budget_item"],  # budget_item
                            "",  # budget_item_id
                            row["fte"],
                            "",  # Amount
                            row["reason"],
                            row["reason2"],
                        ])

                case "wss_spec_ed":
                    for table_type, table_entries in items.items():
                        if table_type == 'wss':
                            for row in table_entries:
                                grade = row['grade']
                                for k, v in row.items():
                                    if k == 'grade':
                                        continue
                                    writer.writerow([
                                        school_name,
                                        'wss_enrollment',
                                        "",  # otherval
                                        grade,  # fund_id
                                        "",  # fund_center
                                        "",  # fund_center_id
                                        k,  # budget_item
                                        "",  # budget_item_id
                                        v,
                                        ""
                                    ])
                        elif table_type == 'spec_ed':
                            for row in table_entries:
                                staff_type = row['staff_type']
                                for k, v in row.items():
                                    if k == 'staff_type':
                                        continue
                                    writer.writerow([
                                        school_name,
                                        'spec_ed_staffing',
                                        "",  # otherval
                                        staff_type,  # fund_id
                                        "",  # fund_center
                                        "",  # fund_center_id
                                        k,   # budget_item
                                        "",  # budget_item_id
                                        v,
                                        ""
                                    ])

                case _:
                    for row in items:
                        writer.writerow([
                            school_name,
                            section,
                            ""] + [row[k] for k in FUNDING_COLS]
                        )


def main():
    parser = argparse.ArgumentParser(description='Parses a purplebook')

    common_pdftext_setup(parser)
    common_logging_setup(parser)

    args = get_args()

    lines_by_schools = _break_lines_by_school(args.infile)

    schools = {}
    errors = []
    for name, raw_lines in lines_by_schools.items():
        logging.info(f"Parsing {name} with {len(raw_lines)} lines")
        schools[name] = extract_data_from_school(name, raw_lines, errors)

    write_denormalized_csv(args.outfile, schools)


if __name__ == '__main__':
    main()
