"""Schema for the STARS Operations Allocation Detail fact table.

The OSPI Operations Allocation Detail Report (form 1026A) is a single-page
per-district summary of how that district's transportation operations
allocation was computed for one school year. Each district publishes the
same fixed 30-item structure organized into four sections:

  A. Calculation of Expected Allocation -- seven formula inputs
     (Land Area, Average Distance, Destinations, Basic Program, Special
     Program, Non-High Yes, Non-High No) followed by six summary rows
     (A.1 through A.6 ending in the calculated expected allocation).

  B. Alternate Funding System Adjustments -- five line items plus a
     subtotal (B.6) that may pull the allocation off the formula value.

  C. Other Adjustments -- alt-calendar modifier (C.1), car-mileage
     reimbursement (C.2), and a subtotal (C.3).

  D. Determination of Final STARS Allocation -- the adjusted allocation,
     prior-year expenditures, legislative add-ons, and the bottom-line
     ACTUAL ALLOCATION AMOUNT (D.8).

Schema is long-form with one row per (school_year, ccddd, item_code).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


OPS_ALLOCATION_ITEMS = (
    # Section A detail rows: input value × coefficient -> calculated value.
    "land_area",
    "average_distance",
    "destinations",
    "basic_program",
    "special_program",
    "non_high_yes",
    "non_high_no",
    # Section A summary.
    "a1_sum_calculated_values",
    "a2_expected_allocation_constant",
    "a3_expected_allocation_value",
    "a4_initial_allocation",
    "a5_local_characteristics_factor",
    "a6_calculated_expected_allocation",
    # Section B detail + subtotal.
    "b1_non_high",
    "b2_low_ridership",
    "b3_transportation_coop",
    "b4_esd",
    "b5_other",
    "b6_alternate_system_total",
    # Section C detail + subtotal.
    "c1_alt_calendar_modifier",
    "c2_car_mileage_reimbursement",
    "c3_other_adjustments_total",
    # Section D detail + final.
    "d1_adjusted_allocation",
    "d2_prior_year_expenditures",
    "d3_federal_restricted_rate_indirects",
    "d4_adjusted_prior_year_expenditures",
    "d5_lesser_of_adjusted_or_prior_year",
    "d6_legislative_salary",
    "d7_legislative_benefit",
    "d8_actual_allocation_amount",
)


STARS_OPERATIONS_ALLOCATION = {
    "name": "stars_operations_allocation",
    "doc": ("STARS Operations Allocation Detail (form 1026A) per district "
            "per school year. Long-form: one row per line item."),
    "fields": [
        {
            "name": "stars_operations_allocation_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "section_code",
            "field_type": "string",
            "doc": "Section letter (A/B/C/D) the item belongs to.",
        },
        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Canonical snake_case item identifier. One of: "
                    + ", ".join(OPS_ALLOCATION_ITEMS) + "."),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": "Raw item label as printed in the PDF/DOCX.",
        },
        {
            "name": "item_value",
            "field_type": "decimal",
            "doc": ("Input value for Section A detail rows (e.g. Land Area "
                    "in square miles, Basic Program ride-equivalents). NULL "
                    "on summary rows."),
        },
        {
            "name": "coefficient",
            "field_type": "decimal",
            "doc": ("Per-item coefficient/rate. Populated for Section A "
                    "detail rows and the C.1 Alt Calendar Modifier; NULL "
                    "elsewhere."),
        },
        {
            "name": "calculated_value",
            "field_type": "decimal",
            "doc": ("Unitless calculated value (typically value x coefficient, "
                    "or a derived sum). Populated for Section A detail and "
                    "summary rows A.1-A.3 / A.5. NULL on dollar-amount rows."),
        },
        {
            "name": "amount",
            "field_type": "decimal",
            "doc": ("Dollar amount for the line item. Populated on Section "
                    "A.4 / A.6 and on every Section B / C / D row."),
        },
        {
            "name": "running_total",
            "field_type": "decimal",
            "doc": ("Cumulative dollar running total carried by certain "
                    "summary rows that print both an adjustment and its "
                    "resulting subtotal (B.6, C.1, C.3). NULL otherwise."),
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_OPERATIONS_ALLOCATION]
