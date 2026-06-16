"""Schema for the `fiscal_1191fg_grants` fact table.

Source: OSPI Report 1191FG "Grants Administration". A periodic
statement (run monthly during the school year) of every grant a
recipient (typically a school district, occasionally an ESD as a
recipient in its own right) has under active administration, with
per-grant funding/paid-to-date/current-payment/balance and per-funding-
line detail.

The form's structure:
  - Header banner + report date + recipient identification.
  - Repeated per grant:
      GRANT <project_id> <project_code> <description> [<period>] <status>
      REV <revenue_account> EXPEND <prior_expend>
      <proj> <pom> <obj_sub> <funding> <paid_adj> <curr_paymt> <balance>
      ... more detail rows ...
      GRANT TOTAL <funding> <paid_adj> <curr_paymt> <balance>
  - Closing roll-up:
      DISTRICT TOTALS <funding> <paid_adj> <curr_paymt> <balance>

Long-form output: one row per printed line carrying the four financial
columns (funding / paid_adj / curr_paymt / balance). The row's
`section` says which kind of line it is.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_1191FG_GRANTS = {
    "name": "fiscal_1191fg_grants",
    "doc": (
        "Per-grant per-funding-line capture of OSPI Report 1191FG "
        "Grants Administration. One row per detail line (a single "
        "funding-source / POM / object-sub allocation within a grant), "
        "plus a `grant_total` row per grant and a `district_total` row "
        "per recipient per report. Districts, ESDs (recipients in their "
        "own right), and a small set of state agencies / colleges are "
        "all addressed by the same form -- in practice only districts "
        "and ESDs produce data; the agency / college files have been "
        "header-only placeholders throughout the corpus."
    ),
    "fields": [
        {
            "name": "fiscal_1191fg_grants_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "org_type",
            "field_type": "string",
            "doc": (
                "'district' | 'esd' | 'college' | 'state_agency'. ESD "
                "files are deduplicated at the walker; CCDDD on those "
                "rows is the ESD's own (e.g. 34801 for ESD 113), not "
                "the path-derived inner member-district code."
            ),
        },
        {
            "name": "report_date_text",
            "field_type": "string",
            "doc": (
                "As-of date printed at the top of the report (e.g. "
                "'08-30-19'). Free text; multiple snapshots of the same "
                "(school_year, ccddd) pair share one PDF -- only the "
                "latest snapshot per year is published to the scraper."
            ),
        },
        {
            "name": "section",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "'grant_detail' | 'grant_total' | 'district_total'. "
                "Detail rows carry `proj` / `pom` / `obj_sub` plus the "
                "four amount columns; grant_total rows carry only the "
                "amounts and the grant header context; district_total "
                "rows carry only the amounts."
            ),
        },
        {
            "name": "grant_seq",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Ordinal of the grant block within the document, "
                "starting at 1. 0 on `district_total` rows."
            ),
        },
        {
            "name": "project_id",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Grant project identifier as printed (typically a "
                "7-digit code padded with leading zeros, e.g. '0173935'). "
                "Empty on `district_total` rows."
            ),
        },
        {
            "name": "project_code",
            "field_type": "string",
            "doc": (
                "Grant program short code (e.g. 'PERKINS', 'TITLE1', "
                "'ARPHMLESS'). First token after the project_id on the "
                "GRANT header line. Empty on `district_total` rows."
            ),
        },
        {
            "name": "project_description",
            "field_type": "string",
            "doc": (
                "Grant description as printed (e.g. 'Perkins Skill "
                "Ctrs', 'Title 1 PtA Basic'). Whatever the form prints "
                "between the project_code and the trailing "
                "[period] status tokens."
            ),
        },
        {
            "name": "grant_period",
            "field_type": "string",
            "doc": (
                "Grant fiscal-period code as printed (e.g. '1819' for "
                "the 2018-19 school year, '2124' for a multi-year ARP / "
                "ESSER grant). Empty when the form embeds the period in "
                "`project_description` (common in 2013-14)."
            ),
        },
        {
            "name": "grant_status",
            "field_type": "string",
            "doc": (
                "'OPEN' (active, may still receive payments) or "
                "'CLOSED' (final). Always the last token of the GRANT "
                "header line."
            ),
        },
        {
            "name": "revenue_account",
            "field_type": "string",
            "doc": (
                "OSPI revenue account code (e.g. '6146', '6151', "
                "'4158') from the REV/EXPEND line that follows the "
                "GRANT header. Empty on `district_total` rows."
            ),
        },
        {
            "name": "prior_expend",
            "field_type": "decimal",
            "doc": (
                "EXPEND value from the REV/EXPEND line -- expenditures "
                "the recipient has booked against this grant in prior "
                "periods, as of the report's as-of date. Replicated on "
                "every detail/grant_total row for the same grant."
            ),
        },
        {
            "name": "proj",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Per-detail funding-line code (the form's 'PROJ' "
                "column). Encodes the funding source + budget year + "
                "carryforward flag, e.g. 'ZV19', 'TB18*' (asterisk = "
                "carryforward), 'ZV18#' (hash = adjustment). Empty on "
                "grant_total / district_total rows."
            ),
        },
        {
            "name": "pom",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Per-detail POM code (the form's 'POM' column -- "
                "Program/Object Management identifier, e.g. '15014', "
                "'BASIC', 'TARG3'). Empty on grant_total / "
                "district_total rows."
            ),
        },
        {
            "name": "obj_sub",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Per-detail object/sub code (the form's 'OBJ/SUB' "
                "column, e.g. 'NZ001'). Empty on grant_total / "
                "district_total rows."
            ),
        },
        {
            "name": "funding",
            "field_type": "decimal",
            "doc": (
                "Authorized funding amount for this line. On grant_total "
                "rows: sum across detail rows of the same grant. On "
                "district_total rows: sum across all grants."
            ),
        },
        {
            "name": "paid_adj",
            "field_type": "decimal",
            "doc": "Paid-to-date plus prior-period adjustments.",
        },
        {
            "name": "curr_paymt",
            "field_type": "decimal",
            "doc": (
                "Current period payment -- the dollars actually paid "
                "out in the period this report covers."
            ),
        },
        {
            "name": "balance",
            "field_type": "decimal",
            "doc": (
                "Remaining balance = funding - paid_adj - curr_paymt."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "section", "grant_seq",
                "project_id", "proj", "pom", "obj_sub"]],
}


ALL_SCHEMAS = [FISCAL_1191FG_GRANTS]
