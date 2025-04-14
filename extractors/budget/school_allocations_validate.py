import math
import logging

logger = logging.getLogger(__name__)

# Name of the column that holds the total staffing number for each staff type.
STAFFING_TOTAL_COLUMN = "Total"

# Name of the column that holds the total staffing number for each funding
# type.
STAFFING_TOTAL_ROW = "Total School Funded Staff"


def validate_staffing_totals(name,
                             total_row_fte_sum,
                             total_column_fte_sum,
                             total_row_and_column_fte,
                             errors):
    if not math.isclose(total_column_fte_sum, total_row_and_column_fte):
        errors.append(['total_column',
                       total_row_and_column_fte - total_column_fte_sum])
        logger.error(f"{name}: "
                     f"{STAFFING_TOTAL_COLUMN} in staffing is "
                     f"{total_row_and_column_fte:.2f} but got "
                     f"{total_column_fte_sum:.2f}")

    if not math.isclose(total_row_fte_sum, total_row_and_column_fte):
        errors.append(['total_row',
                       total_row_and_column_fte - total_row_fte_sum])
        logger.warning(f"{name}: "
                       f"{STAFFING_TOTAL_ROW} in staffing is "
                       f"{total_row_and_column_fte:.2f} but got "
                       f"{total_row_fte_sum:.2f}")


def validate_staffing(name, year_info, errors):
    staff_type_totals = {}
    funding_type_totals = {}
    total_column_fte_sum = 0
    total_row_fte_sum = 0
    total_row_and_column_fte = 0
    for funding_type, staff_type_fte in year_info.items():
        # Total column is accidentally a funding type. skip.
        if funding_type == STAFFING_TOTAL_COLUMN:
            for st, fte in staff_type_fte.items():
                if st == STAFFING_TOTAL_ROW:
                    total_row_and_column_fte = fte
                else:
                    total_column_fte_sum += fte
            continue

        for staff_type, fte in staff_type_fte.items():
            # Account for Staff type
            if staff_type in staff_type_totals:
                staff_type_totals[staff_type] += fte
            else:
                staff_type_totals[staff_type] = fte

            # Account for Funding Total. Skip the Total line for the funding
            # summation
            if staff_type == STAFFING_TOTAL_ROW:
                total_row_fte_sum += fte
                continue

            if funding_type in funding_type_totals:
                funding_type_totals[funding_type] += fte
            else:
                funding_type_totals[funding_type] = fte

    # Validate Totals
    validate_staffing_totals(name, total_row_fte_sum, total_column_fte_sum,
                             total_row_and_column_fte, errors)

    return funding_type_totals, staff_type_totals


def validate_num_funding_types(name, year_info, funding_type_totals, errors):
    expected_funding = len(year_info.keys())
    if expected_funding != 0:
        # Subtract one for total column if any were scraped.
        expected_funding -= 1
    fund_type_diff = expected_funding - len(funding_type_totals.keys())
    if fund_type_diff != 0:
        errors.append(['funding_type', fund_type_diff])
        logger.warning(f"{name}: "
                       f"Differing number of funding types in {year_info} "
                       f"{expected_funding} and "
                       f"{len(funding_type_totals.keys())}")


def validate_funding(name, year_info, funding_type_totals, staff_type_totals,
                     errors):
    # Check same number of funding types.
    validate_num_funding_types(name, year_info, funding_type_totals, errors)

    # Loop over all staffing collating data in 2 dimensions.
    # TODO: Should this be a data frame?
    for funding_type, staff_type_fte in year_info.items():
        # Check number of staff types match
        staff_type_diff = (len(staff_type_fte.keys()) -
                           len(staff_type_totals.keys()))
        if staff_type_diff != 0:
            errors.append(['staff_type', staff_type_diff])
            logger.warning(f"{name}: "
                           "Differing number of staff types in {funding_type} "
                           f"{year_info} {staff_type_fte.keys()} and "
                           f"{staff_type_totals.keys()}")

        # Verify the match of staff type FTE sums.
        for staff_type, fte in staff_type_fte.items():
            if funding_type == STAFFING_TOTAL_COLUMN:
                logger.debug(
                    f"{name}: "
                    f"Validating {fte:.1f} {staff_type} "
                    f"{staff_type_totals[staff_type]:.1f}")
                if not math.isclose(fte, staff_type_totals[staff_type]):
                    # Skip "Total School Funded Staff" as it will double-count
                    # errors from other staff error issues. This does mean
                    # there can be a summation problem on the row, but it's
                    # probably okay. Emit the error message though.
                    if staff_type != 'Total School Funded Staff':
                        errors.append(['staff_type_fte',
                                       fte - staff_type_totals[staff_type]])

                    logger.warning(f"{name}: "
                                   "Mismatched Staff type total for "
                                   f"{staff_type}. Got "
                                   f"{staff_type_totals[staff_type]:.1f} "
                                   f"but expecting {fte:.1f}")
                continue

            # Verify the match of funding category FTE sums.
            if staff_type == "Total School Funded Staff":
                if not math.isclose(fte, funding_type_totals[funding_type]):
                    errors.append(['fund_type_fte',
                                   fte - funding_type_totals[funding_type]])
                    logger.warning(f"{name}: "
                                   "Mismatched Funding type total for "
                                   f"{funding_type}. Got "
                                   f"{funding_type_totals[funding_type]:.1f} "
                                   f"but expecting {fte:.1f}")
