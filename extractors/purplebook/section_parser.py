import logging
import re

from budget import line_tools
from budget.extractor import remove_comma_dollar
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


Section = Enum('Section',
               ['Start',
                'SchoolAttributes',
                'StaffingAllocations',
                'NonStaffAllocations',
                'TitleIAndLap',
                'BudgetedCentrally',
                'TotalAllocations',
                'WssAndSpecEd',
                'AboveWss',
                'Done'])

WssType = Enum('WssType', ['HeadCount', 'AafteOnly'])

TotalMode = Enum('TotalMode', ['NotYet', 'GetAafte', 'Done'])


def is_spec_ed_staff_type(s):
    return (re.match(line_tools.RE_ALPHANUM_SPACES_DASH, s) and
            not (re.match(line_tools.RE_DECIMAL_DASH, s) or
                 re.match(line_tools.RE_INT_COMMA_DASH, s)))


def read_total_line(line):
    fields = line_tools.tokenize_by_two_space(line)
    amount = line_tools.pop_read(fields, line_tools.RE_DOLLAR_COMMA,
                                 remove_comma_dollar)
    fte = line_tools.pop_read(fields, line_tools.RE_DECIMAL,
                              line_tools.to_number,
                              raise_invalid=False)
    return fte, amount


class BaseParser:
    def __init__(self, school_name, school_info, errors):
        self._context = {}
        self._school_name = school_name
        self._school_info = school_info
        self._errors = errors
        self.init_context()

    def init_context(self):
        # Override to add to init without passing through.
        pass

    def accumulate(self, line, raw_line):
        raise NotImplementedError()

    def commit(self, school_info):
        pass


class NullParser(BaseParser):
    """Used just to ignore a section"""
    def accumulate(self, line, raw_line):
        pass


class SchoolAttributesParser(BaseParser):
    def commit(self, school_info):
        school_info["attributes"] = set(self._context.keys())

    def accumulate(self, line, raw_line):
        """Parses one school attribute line into the school_info struct.

        Attributes are free-form strings tags. They are parseable by splitting
        on two consectuive spaces and trimming.
        """
        if line.startswith("Fund  "):
            return Section.StaffingAllocations

        for token in line_tools.tokenize_by_two_space(line):
            # Single - is empty value.
            if token != '-':
                self._context[token] = None

        return None


class AllocationRowAccumulator(object):
    def __init__(self):
        self._last_fund_id = None
        self._last_fund_center_id = None
        self._last_fund_center = None
        self._allocations = []

    def get_allocations(self):
        return self._allocations

    def add(self, fields, skip_fte=False, optional_fte=False):
        """Takes a tokenized set of fields and adds a row of this"""

        # Read the amount
        amount = line_tools.pop_read(fields, line_tools.RE_DOLLAR_COMMA,
                                     remove_comma_dollar,
                                     raise_invalid=False)

        # Read the FTE field.
        if skip_fte:
            fte = None
        else:
            fte = Decimal(0)
            if amount and not amount.is_zero():
                fte = line_tools.pop_read(fields, line_tools.RE_DECIMAL,
                                          line_tools.to_number,
                                          raise_invalid=(not optional_fte))

        # Read the budget item id field.
        budget_item_id = line_tools.pop_read(fields,
                                             line_tools.RE_ALPHANUM_LOWER_DASH,
                                             raise_invalid=False)

        # Read Budget Item.
        budget_item = line_tools.pop_read(fields, None)

        # Read the fund center id
        fund_center_id = line_tools.pop_read(fields,
                                             line_tools.RE_ALPHANUM_NO_SPACES,
                                             raise_invalid=False)
        if fund_center_id is None:
            fund_center_id = self._last_fund_center_id
        else:
            self._last_fund_center_id = fund_center_id

        # Read the fund center id
        fund_center = line_tools.pop_read(fields, None, raise_invalid=False)
        if fund_center is None:
            fund_center = self._last_fund_center
        else:
            self._last_fund_center = fund_center

        # Read the fund center id
        fund_id = line_tools.pop_read(fields,
                                      line_tools.RE_ALPHANUM_UPPER,
                                      raise_invalid=False)
        if fund_id is None:
            fund_id = self._last_fund_id
        else:
            self._last_fund_id = fund_id

        self._allocations.append({
            "fund_id": fund_id,
            "fund_center": fund_center,
            "fund_center_id": fund_center_id,
            "budget_item": budget_item,
            "budget_item_id": budget_item_id,
            "fte": fte,
            "amount": amount,
        })


class StaffingAllocationsParser(BaseParser):
    def init_context(self):
        self._allocations = AllocationRowAccumulator()
        self._elementary_fte_check = None

    def commit(self, school_info):
        school_info["staffing"] = self._allocations.get_allocations()
        school_info["totals"]["staffing"] = self._totals
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one Staffing Allocations line.

        Attributes have multiple sections split by spaces, mostly:

        [Fund]* [Fund Center]* [Fund Center Code] [Budget Item] \
            [Budget Item Id]* [FTE]* [$allocation]

        The problem is that Fund, Fund Centert and Fund Center Code are not
        repeated if its the same as the previous row. Similarly FTE is blank if
        $allocation is 0.  Also if things get squished up, you may only have
        one space.

        This line parsing instead is done by popping off a field from the
        _right_ and then examining the field format to see what value it might
        be.

        "Total Staffing (FTE) Allocation" is the start of the next section.
        """
        if line.startswith("Total Staffing (FTE) Allocation"):
            fte, amount = read_total_line(line)
            self._totals = {
                "fte": fte,
                "amount": amount
            }
            return Section.NonStaffAllocations

        fields = line_tools.tokenize_by_two_space(line)

        num_fields = len(fields)
        if num_fields == 1:
            # There is a small summation column on the right for K-5 numbers.
            # This is useful only as a sanity check for elementary schools.
            val = line_tools.pop_read(fields, line_tools.RE_DECIMAL,
                                      line_tools.to_number,
                                      raise_invalid=False)
            if val is not None:
                self._elementary_fte_check = val
            elif num_fields > 2:
                self._allocations.add(fields)

        return None


class NonStaffAllocationsParser(BaseParser):
    def init_context(self):
        self._allocations = AllocationRowAccumulator()

    def commit(self, school_info):
        school_info["nonstaff"] = self._allocations.get_allocations()
        school_info["totals"]["nonstaff"] = self._totals
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one Non Staff Allocations line.


        Attributes have multiple sections split by spaces, mostly:

            [Fund]* [Fund Center]* [Fund Center Code] [Budget Item]
            [Budget Item Id]* [$allocation]

        The problem is that Fund, Fund Centert and Fund Center Code are not
        repeated if its the same as the previous row. Similarly Budget Item Id
        is blank if $allocation is 0.

        This line parsing instead is done by popping off a field from the
        _right_ and then examining the field format to see what value it might
        be.

        "Total Non-Staff Allocation" is the start of the next section.
        """
        if line.startswith("Total Non-Staff Allocation"):
            _, amount = read_total_line(line)
            self._totals = {
                "fte": 0,
                "amount": amount
            }
            return Section.TitleIAndLap

        fields = line_tools.tokenize_by_two_space(line)

        num_fields = len(fields)
        if num_fields > 1:
            self._allocations.add(fields, skip_fte=True)

        return None


class TitleIAndLapParser(BaseParser):
    def init_context(self):
        self._allocations = AllocationRowAccumulator()

    def commit(self, school_info):
        school_info["title1_and_lap"] = self._allocations.get_allocations()
        school_info["totals"]["title1_and_lap"] = self._totals
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one Title I and LAP allocation line.


        Attributes have multiple sections split by spaces, mostly:

            [Fund]* [Fund Center]* [Fund Center Code] [Budget Item] \
                [fte]* [$allocation]

        Fund, Fund Center and Fund Center Code are not repeated if its the
        same as the previous row. FTE is blank if $allocation is 0.

        This line parsing instead is done by popping off a field from the
        _right_ and then examining the field format to see what value it might
        be.
        """
        if line.startswith("Total Title I & LAP"):
            fte, amount = read_total_line(line)
            self._totals = {
                "fte": fte,
                "amount": amount
            }
            return Section.BudgetedCentrally

        fields = line_tools.tokenize_by_two_space(line)

        num_fields = len(fields)
        if num_fields > 1:
            self._allocations.add(fields, optional_fte=True)

        return None


class BudgetedCentrallyParser(BaseParser):
    def init_context(self):
        self._allocations = AllocationRowAccumulator()

    def commit(self, school_info):
        school_info["budgeted_centrally"] = self._allocations.get_allocations()
        school_info["totals"]["budgeted_centrally"] = self._totals
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one centrally budgted items.


        Attributes have multiple sections split by spaces, mostly:

            [Fund]* [Fund Center]* [Fund Center Code] [Budget Item] \
                [fte]* [$allocation]

        Fund, Fund Center and Fund Center Code are not repeated if its the
        same as the previous row. FTE is blank if $allocation is 0.

        This line parsing instead is done by popping off a field from the
        _right_ and then examining the field format to see what value it might
        be.
        """
        if line.startswith("Total Allocated/Budgeted Centrally"):
            fte, amount = read_total_line(line)
            self._totals = {
                "fte": fte,
                "amount": amount
            }
            return Section.TotalAllocations

        fields = line_tools.tokenize_by_two_space(line)

        num_fields = len(fields)
        if num_fields > 1:
            self._allocations.add(fields)

        return None


class TotalAllocationsParser(BaseParser):
    def init_context(self):
        self._fte = None
        self._amount = None

    def commit(self, school_info):
        school_info["totals"]["grand_total"] = self._totals
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one centrally budgted items."""
        if line.startswith("Total Allocations"):
            fte, amount = read_total_line(line)
            self._totals = {
                "fte": fte,
                "amount": amount
            }
            return Section.WssAndSpecEd

        return None


class WssAndSpecEdParser(BaseParser):
    def init_context(self):
        self._allocations = {'wss': [], 'spec_ed': []}
        self._spec_ed_allocations = {}
        self._wss_type = None
        self._wss_totals = None
        self._aafte_totals = None
        self._total_mode = TotalMode.NotYet

    def commit(self, school_info):
        school_info["wss_spec_ed"] = self._allocations
        if self._wss_totals is not None:
            school_info["totals"]["wss"] = self._wss_totals

        school_info["spec_ed"] = self._spec_ed_allocations
        # TODO: Validate here.

    def accumulate(self, line, raw_line):
        """Parses one WSS + SpecEd line.

        This one is complicated because there are two tables put side-by-side.
        There are also 2 formats of the WSS table, one for K-8 and then one
        for highschool which have different information. Here are descriptions:

        WSS headers for K-8:

            [Grade] [AAFTE] [ELL] [BOC] [F/R Lunch] [Sped Resource]

        WSS for Highschool

            [Grade] [Headct] [AAFTE] [ELL/BOC] [F/R Lunch] [Sped Resource]

        The Special Education Tables:
            <Resource Name> [Tchrs] [IA's]

        Sometimes the Special Education Tables are longer than the WSS tables,
        and sometimes the WSS tables are longer.

        Grade also sometimes has values like "Sept-June" or "Summer."

        The parsing algorithm is identify WSS type by header and then absorb
        walk rows deciding if it's both items, WSS-only, or SpecEd only.
        """
        if line.startswith("Allocations Above Weighted Staffing Standards"):
            return Section.AboveWss

        # There is an odd pattern here  because the WSS numbers free form text
        # in the Special Ed Staffing table. Example:
        #
        #    3 Resource
        #
        # The "3" is actually the last WSS column entry.  We help out here by
        # adding in another space when there is a leading number to a field
        # with a string. This works cause there is no title that starts with
        # a number.
        expanded_line = re.sub(r'(  [0-9]+) ([A-Za-z])', r'\1  \2', line)
        fields = line_tools.tokenize_by_two_space(expanded_line)

        # Most of the time, this table does not have a final "Total" number.
        # But when it does, we need to switch parsing styles as the table has
        # ended
        if self._consume_total_aafte(raw_line, fields):
            return None

        if self._wss_type is None:
            if len(fields) > 2:
                # Detect WSS Model type.
                if fields[1] == 'AAFTE':
                    self._wss_type = WssType.AafteOnly
                elif fields[1] == 'Headct':
                    self._wss_type = WssType.HeadCount
        else:
            # Table parsing time!
            num_fields = len(fields)

            # Skip lines with too few fields as they are likely noise.
            # TODO: This num_fields length check is a bit wrong.
            if num_fields >= 3:
                if is_spec_ed_staff_type(fields[-2]):
                    # Sometimes the IA column is missing a -. Handle here.
                    self._consume_spec_ed_no_ia(fields)
                elif is_spec_ed_staff_type(fields[-3]):
                    self._consume_spec_ed(fields)

                # Treat the rest as WSS.
                if self._wss_type == WssType.AafteOnly:
                    self._consume_wss_aafte_only(fields)
                elif self._wss_type == WssType.HeadCount:
                    self._consume_wss_headcount(fields)
                else:
                    raise ValueError(self._wss_type)

        return None

    def _consume_spec_ed_no_ia(self, fields):
        # If there is a missing IA field, just pop 2 off.
        teachers_fte = line_tools.pop_read(fields,
                                           line_tools.RE_DECIMAL_DASH,
                                           line_tools.to_number_dash_zero)
        staff_type = line_tools.pop_read(
            fields,
            line_tools.RE_ALPHANUM_SPACES_DASH)
        self._allocations['spec_ed'].append({
            "aides": Decimal(0),
            'staff_type': staff_type,
            "teachers": teachers_fte,
        })


    def _consume_spec_ed(self, fields):
        aides_fte = line_tools.pop_read(fields,
                                        line_tools.RE_DECIMAL_DASH,
                                        line_tools.to_number_dash_zero,
                                        raise_invalid=False)
        if aides_fte is None:
            # This field sometimes has human readable notes. Just eat it.
            line_tools.pop_read(fields, line_tools.RE_NON_EMPTY)
            aides_fte = Decimal(0)

        teachers_fte = line_tools.pop_read(fields,
                                           line_tools.RE_DECIMAL_DASH,
                                           line_tools.to_number_dash_zero)
        staff_type = line_tools.pop_read(
            fields,
            line_tools.RE_ALPHANUM_SPACES_DASH)
        self._allocations['spec_ed'].append({
            'staff_type': staff_type,
            "aides": aides_fte,
            "teachers": teachers_fte,
        })

    def _consume_wss_aafte_only(self, fields):
        if len(fields) < 6:
            return
        sped_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                       line_tools.to_number_dash_zero)
        frl_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                      line_tools.to_number_dash_zero)
        boc_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                      line_tools.to_number_dash_zero)
        ell_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                      line_tools.to_number_dash_zero)
        aafte_fte = line_tools.pop_read(fields,
                                        line_tools.RE_NUMBER_COMMA_DASH,
                                        line_tools.to_number_dash_zero)
        grade = line_tools.pop_read(fields, line_tools.RE_ALPHANUM_SPACES_DASH)

        values = {
            'spec_ed': sped_fte,
            'frl': frl_fte,
            'boc': boc_fte,
            'ell': ell_fte,
            'aafte': aafte_fte,
        }
        if grade == 'Total':
            self._wss_totals = values
        else:
            self._allocations['wss'].append({
                'grade': grade,
            } | values)


    def _consume_wss_headcount(self, fields):
        if len(fields) < 6:
            return
        sped_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                       line_tools.to_number_dash_zero)
        frl_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                      line_tools.to_number_dash_zero)
        ell_boc_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                      line_tools.to_number_dash_zero)
        aafte_fte = line_tools.pop_read(fields,
                                        line_tools.RE_NUMBER_COMMA_DASH,
                                        line_tools.to_number_dash_zero)
        headcount_fte = line_tools.pop_read(fields, line_tools.RE_INT_COMMA_DASH,
                                            line_tools.to_number_dash_zero)
        grade = line_tools.pop_read(fields, line_tools.RE_ALPHANUM_SPACES_DASH)

        values = {
            'spec_ed': sped_fte,
            'frl': frl_fte,
            'ell_boc': ell_boc_fte,
            'aafte': aafte_fte,
            'headcount': headcount_fte,
        }
        if grade == 'Total':
            self._wss_totals = values
        else:
            self._allocations['wss'].append({
                'grade': grade,
            } | values)


    def _consume_total_aafte(self, raw_line, fields):
        """Returns true if we've latched into reading the totals"""
        # Most of the time, this table does not have a final "Total" number.
        # But for Highschool, it has somethign like:
        #
        #  AAFTE Adjusted
        #    for Contact Time         664.4
        #
        # Except for Skills Center which looks like
        #    Total AAFTE
        #                             196.0
        #
        # This is annoying as heck so the accumulate() function needs to switch
        # to a different parsing mode.
        #
        # Use the raw_line to check for the start of these Total fields.
        if self._total_mode == TotalMode.GetAafte:
            if self._wss_totals is None:
                self._wss_totals = {}
            if fields[0].startswith('for Contact Time'):
                self._wss_totals['contact_aafte'] = line_tools.to_number(
                    fields[1])
            else:
                self._wss_totals['total_aafte'] = line_tools.to_number(
                    fields[0])
            self._total_mode = TotalMode.Done
        elif raw_line.startswith('Total AAFTE'):
            self._total_mode = TotalMode.GetAafte
        elif raw_line.startswith('AAFTE Adjusted'):
            self._total_mode = TotalMode.GetAafte

        return self._total_mode != TotalMode.NotYet


SectionParsers = {
    Section.Start: NullParser,
    Section.SchoolAttributes: SchoolAttributesParser,
    Section.StaffingAllocations: StaffingAllocationsParser,
    Section.NonStaffAllocations: NonStaffAllocationsParser,
    Section.TitleIAndLap: TitleIAndLapParser,
    Section.BudgetedCentrally: BudgetedCentrallyParser,
    Section.TotalAllocations: TotalAllocationsParser,
    Section.WssAndSpecEd: WssAndSpecEdParser,
    Section.AboveWss: NullParser,
}
