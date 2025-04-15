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
                'TitleIAndLAP',
                'TotalAllocations',
                'WssAndSpecEd',
                'AboveWss',
                'Done'])


def identity(x):
    return x


def to_number(x):
    return Decimal(x)


def pop_read(fields, validation_re, convert=identity, raise_invalid=True):
    if len(fields) == 0:
        if raise_invalid:
            raise ValueError("Ran out of fields")
        return None

    token = fields[-1]
    if validation_re is not None and not re.fullmatch(validation_re, token):
        if raise_invalid:
            raise ValueError(f"Failed validation: {token}")
        return None

    # Pop here so that if raise_invalid=False, the fields are undisturbed.
    fields.pop()
    return convert(token)


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
    RE_AMOUNT = re.compile(r'\$[0-9,]+')
    RE_FTE = re.compile(r'[0-9]+\.[0-9]+')
    RE_BUDGET_ITEM_ID = re.compile(r'[0-9a-z-]+')
    RE_FUND_CENTER_ID = re.compile(r'[A-Za-z0-9]+')
    RE_FUND_ID = re.compile(r'[A-Z0-9]+')

    def __init__(self):
        self._last_fund_id = None
        self._last_fund_center_id = None
        self._last_fund_center = None
        self._allocations = []

    def get_allocations(self):
        return self._allocations

    def add(self, fields):
        """Takes a tokenized set of fields and adds a row of this"""

        # Read the amount
        amount = pop_read(fields, AllocationRowAccumulator.RE_AMOUNT,
                          remove_comma_dollar)

        # Read the FTE field.
        fte = Decimal(0)
        if not amount.is_zero():
            fte = pop_read(fields, AllocationRowAccumulator.RE_FTE,
                           to_number)

        # Read the budget item id field.
        budget_item_id = pop_read(fields,
                                  AllocationRowAccumulator.RE_BUDGET_ITEM_ID,
                                  raise_invalid=False)

        # Read Budget Item.
        budget_item = pop_read(fields, None)

        # Read the fund center id
        fund_center_id = pop_read(fields,
                                  AllocationRowAccumulator.RE_FUND_CENTER_ID,
                                  raise_invalid=False)
        if fund_center_id is None:
            fund_center_id = self._last_fund_center_id
        else:
            self._last_fund_center_id = fund_center_id

        # Read the fund center id
        fund_center = pop_read(fields, None, raise_invalid=False)
        if fund_center is None:
            fund_center = self._last_fund_center
        else:
            self._last_fund_center = fund_center

        # Read the fund center id
        fund_id = pop_read(fields,
                           AllocationRowAccumulator.RE_FUND_ID,
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
            # TODO: Parse the value out of this row.
            return Section.NonStaffAllocations

        fields = line_tools.tokenize_by_two_space(line)

        num_fields = len(fields)
        if num_fields == 1:
            # There is a small summation column on the right for K-5 numbers.
            # This is useful only as a sanity check for elementary schools.
            val = pop_read(fields, AllocationRowAccumulator.RE_FTE,
                           to_number, raise_invalid=False)
            if val is not None:
                self._elementary_fte_check = val
        elif num_fields > 2:
            self._allocations.add(fields)

        return None


SectionParsers = {
    Section.Start: NullParser,
    Section.SchoolAttributes: SchoolAttributesParser,
    Section.StaffingAllocations: StaffingAllocationsParser,
    Section.NonStaffAllocations: NullParser,
    Section.TitleIAndLAP: NullParser,
    Section.TotalAllocations: NullParser,
    Section.WssAndSpecEd: NullParser,
    Section.AboveWss: NullParser,
}
