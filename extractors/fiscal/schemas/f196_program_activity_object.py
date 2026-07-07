"""Schema for the `fiscal_f196_program_activity_object` fact table.

Source: the Program/Activity/Object Report sub-report (pp 30-31 typical)
of each F-196 All Pages PDF. This is the roll-up view: three
side-by-side summary tables that decompose the district's total
expenditures three different ways:

  - PROGRAM EXPENDITURE SUMMARY -- per-program (01 Basic Education,
    02 ALE, 21 Sp Ed Sup St, ..., 99 Pupil Transportation)
  - ACTIVITY EXPENDITURE SUMMARY -- per-activity (11 Bd of Dir,
    12 Supt Off, 21 Supv Inst, 27 Teaching, 62 Grnd Mnt, ...)
  - OBJECT EXPENDITURE SUMMARY -- per-object (0 Debit Transfer,
    1 Credit Transfer, 2 Cert Salaries, 3 Class Salaries,
    4 Employee Benefits, 5 Supplies/Materials, 7 Purchased Services,
    8 Travel, 9 Capital Outlay)

**The sub-report is General Fund only.** The three breakdowns sum to
the General Fund's total_expenditures (not the all-funds total):
  sum(program) = sum(activity) = sum(object)
  = fiscal_f196_summary.value where fund='general' and
                                   item_code='total_expenditures'
Program/Activity/Object accounting is defined for the General Fund
(the district's main operating fund with program-based classification);
other funds (ASB / Debt Service / Capital Projects / Transportation
Vehicle / Permanent) use their own simpler activity/object breakdowns
captured by the Budgetary Comparison Schedule.

Long-form: one row per (school_year, ccddd, breakdown_kind, code). The
per-Object breakdown is the unique analytical add -- it's the only
place in the corpus where district-level totals are split by expenditure
object (Cert Salaries vs Class Salaries vs Employee Benefits vs
Purchased Services vs ...). The per-Program and per-Activity views are
also useful for headline breakdowns that would otherwise require
aggregating from the per-PROGRAM cross-tab detail (deferred to a later
phase).
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F196_PROGRAM_ACTIVITY_OBJECT = {
    "name": "fiscal_f196_program_activity_object",
    "doc": (
        "Roll-up view of district expenditures decomposed by Program, "
        "Activity, and Object from the Program/Activity/Object Report "
        "sub-report of OSPI Form F-196 All Pages. Each district's "
        "total expenditures are three-way partitioned (per program, "
        "per activity, per object); the three sums reconcile. "
        "2013-14 through 2024-25 (3,724 files)."
    ),
    "fields": [
        {
            "name": "fiscal_f196_program_activity_object_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "breakdown_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Which of the three breakdowns this row belongs to: "
                "'program', 'activity', or 'object'."
            ),
        },
        {
            "name": "code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI code within the breakdown. **The code space is "
                "specific to each breakdown_kind** -- e.g. '21' means "
                "Sp Ed Sup St in breakdown_kind='program' and Supv Inst "
                "in breakdown_kind='activity'. The all-breakdowns "
                "grand-total row uses the sentinel 'TOTAL'. See "
                "OSPI Accounting Manual for the full code list."
            ),
        },
        {
            "name": "is_total",
            "field_type": "boolean",
            "doc": (
                "True for the three grand-total rows: 'TOTAL ALL "
                "PROGRAMS', 'TOTAL ALL ACTIVITIES', 'TOTAL ALL "
                "OBJECTS'. All three carry the same value on any given "
                "file (they all sum to district total expenditures)."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Multi-line "
                "labels are joined (e.g. 'Sp Ed, Infants and Toddlers, "
                "State'). **Labels drift across years** -- new programs "
                "have been added (SLRF, ESSER II/III, Transition to "
                "Kindergarten), some renamed (Skills Center -> Skill "
                "Center). Consumers cross-year should join on `code`, "
                "which is positional and stable."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": (
                "Expenditure amount. The form omits leading zeros on "
                "very small values (`.00` renders as `.00` -- parsed as "
                "0.00 by parse_decimal). Object 1 (Credit Transfer) is "
                "consistently negative -- it offsets the positive "
                "Object 0 (Debit Transfer) so the two net to zero when "
                "summed."
            ),
        },
        {
            "name": "value_text",
            "field_type": "string",
            "doc": "Raw value text before numeric parsing.",
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "breakdown_kind", "code"]],
}


ALL_SCHEMAS = [FISCAL_F196_PROGRAM_ACTIVITY_OBJECT]
