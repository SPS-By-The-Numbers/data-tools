"""Schema for the `fiscal_f195_salary_exhibits` fact table.

Source: `SALARY EXHIBITS -- CERTIFICATED / CLASSIFIED EMPLOYEES`
sub-reports of OSPI Form F-195 Budget:

  - `GF9-201-XX` (certificated, per General Fund program)
  - `GF9-301-XX` (classified,   per General Fund program)
  - `CP-7`       (certificated, Capital Projects Fund)
  - `CP-8`       (classified,   Capital Projects Fund)

Per-district budgeted salary detail decomposed by
`(fund, program, activity, duty_code)`. Each detail row is one OSPI
duty code within one (program, activity) -- e.g.
`01-23-210 ELEMENTARY PRINCIPAL 73.000 196,312 192,628 193,132.66
14,098,684 8,012,282 6,086,402` for General Fund, Basic Education
(prog 01), Unit Administration (act 23), Elementary Principal (duty
210).

The sub-report emits three row kinds:
  - `detail` rows -- one per printed duty-code line
  - `activity_total` rows -- `ACTIVITY CODE XX TOTAL <fte> <salary> ...`
    per activity within a program
  - `program_total` rows -- `PROGRAM TOTAL <fte> <salary> ...` at the
    end of each program's page span

**Form vintage drift -- STATE / LOCAL split:**
  - 2013-14 through 2018-19: one salary column, `TOTAL ANNUAL SALARY`.
    `state_annual_salary` and `local_annual_salary` are NULL for these
    years.
  - 2019-20 onward (McCleary "prototypical school" funding rewrite):
    the form adds `ANNUAL STATE SALARY` and `ANNUAL LOCAL SALARY`
    columns, decomposing the total by funding source.

**Row shape drift -- rate units:**
  - Certificated rows have `HIGH / LOW / AVERAGE ANNUAL RATE`
    (`$/year` scale, e.g. `275,882.00`). `number_of_hours` is NULL.
  - Classified rows have `NUMBER OF HOURS` and `HIGH / LOW / AVERAGE
    HOURLY RATE` (`$/hour` scale, e.g. `42.94`). Same column names
    (`high_rate`, `low_rate`, `avg_rate`) hold either unit --
    disambiguate on `exhibit_kind`.

Programs with no reported salary data print
`**** NO CERTIFICATED SALARY DATA FOR THIS PROGRAM ****` (or the
`CLASSIFIED` equivalent) and yield 0 rows -- both CP-7 and CP-8
frequently have no data for districts without capital-projects staff.

Identity checks:
  - Per-activity: sum of `detail.total_annual_salary` for a given
    `(program_code, activity_code)` == `activity_total.total_annual_
    salary` for the same key.
  - Per-program: sum of `activity_total.total_annual_salary` for a
    given `program_code` == `program_total.total_annual_salary`.
  - 2019-20+: `total_annual_salary == state_annual_salary +
    local_annual_salary` on every row (both details and totals).
  - Cross-check against `fiscal_f195_program_summary_by_object`
    (GF9) grand-total: sum of `program_total.total_annual_salary`
    (cert) across all GF programs should reconcile to
    `sum(object_2_cert_salaries)` for the grand-total row; likewise
    classified totals to `sum(object_3_class_salaries)`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_F195_SALARY_EXHIBITS = {
    "name": "fiscal_f195_salary_exhibits",
    "doc": (
        "Per-district per-(fund, program, activity, duty) budgeted "
        "salary detail from OSPI Form F-195 Budget sub-reports "
        "GF9-201-XX (General Fund certificated), GF9-301-XX (General "
        "Fund classified), CP-7 (Capital Projects certificated), and "
        "CP-8 (Capital Projects classified). Each detail row is one "
        "OSPI duty code; per-activity and per-program subtotals are "
        "also captured. Rate columns hold annual $ for certificated "
        "rows and hourly $ for classified rows; NUMBER OF HOURS is "
        "populated only for classified rows. The STATE / LOCAL "
        "decomposition is present only from 2019-20 onward (post-"
        "McCleary form vintage)."
    ),
    "fields": [
        {
            "name": "fiscal_f195_salary_exhibits_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "exhibit_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "`certificated` (GF9-201-XX or CP-7 sub-report) or "
                "`classified` (GF9-301-XX or CP-8 sub-report)."
            ),
        },
        {
            "name": "fund",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "`general` (GF9-201-XX / GF9-301-XX) or "
                "`capital_projects` (CP-7 / CP-8)."
            ),
        },
        {
            "name": "program_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit program code as printed for General "
                "Fund rows (`01`, `21`, `79`, `97`, ...) or the "
                "literal `CP` for Capital Projects rows. Matches the "
                "program_code space used elsewhere in the F-195 "
                "family (fiscal_f195_program_summary_by_object, "
                "fiscal_f195_budget[expenditure_by_program])."
            ),
        },
        {
            "name": "activity_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 2-digit activity code (`21`, `22`, `23`, ..., "
                "`27`, `28`, `31`, `33`) parsed from the middle field "
                "of the printed 3-part `PP-AA-DDD` activity code. "
                "Empty string on `program_total` rows. For Capital "
                "Projects the printed activity code is `CP`, which "
                "is preserved verbatim."
            ),
        },
        {
            "name": "duty_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI 3-digit duty code (`005`, `120`, `210`, `310`, "
                "`910`, `940`, ...) parsed from the last field of "
                "the printed `PP-AA-DDD` activity code. Empty string "
                "on `activity_total` and `program_total` rows."
            ),
        },
        {
            "name": "row_kind",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "`detail` (per-duty-code line), `activity_total` "
                "(`ACTIVITY CODE XX TOTAL` subtotal per activity "
                "within a program), or `program_total` (`PROGRAM "
                "TOTAL` at the end of a program's page span)."
            ),
        },
        {
            "name": "program_label",
            "field_type": "string",
            "doc": (
                "Program label as printed on the PROGRAM banner "
                "(e.g. `Basic Education`, `Special Education, "
                "Supplemental, State`, `Capital Projects`). "
                "Whitespace normalized. Labels drift across "
                "vintages -- use `program_code` for cross-year joins."
            ),
        },
        {
            "name": "title_of_position",
            "field_type": "string",
            "doc": (
                "Position title as printed on a detail row "
                "(`ELEMENTARY PRINCIPAL`, `OFFICE/CLERICAL`, ...). "
                "Empty string on subtotal / total rows. Titles "
                "are OSPI-standard names for each duty code."
            ),
        },
        {
            "name": "fte",
            "field_type": "decimal",
            "doc": (
                "Full-time equivalent staff count. Certificated FTE "
                "is based on contract days (min 180); classified "
                "FTE is `hours / 2080`. Both are printed to 3 "
                "decimal places."
            ),
        },
        {
            "name": "number_of_hours",
            "field_type": "decimal",
            "doc": (
                "Annualized hours (classified rows only; NULL for "
                "certificated rows). Equals `2080 * fte` on detail "
                "rows. NULL on subtotal rows (form leaves the "
                "hours column blank there)."
            ),
        },
        {
            "name": "high_rate",
            "field_type": "decimal",
            "doc": (
                "Highest pay rate observed in this "
                "(program, activity, duty). Unit: `$/year` for "
                "certificated rows, `$/hour` for classified rows. "
                "NULL on subtotal rows (rates are aggregated across "
                "activities and duties, not summed)."
            ),
        },
        {
            "name": "low_rate",
            "field_type": "decimal",
            "doc": (
                "Lowest pay rate observed. Unit follows `high_rate`. "
                "NULL on subtotal rows."
            ),
        },
        {
            "name": "avg_rate",
            "field_type": "decimal",
            "doc": (
                "Average pay rate. Unit follows `high_rate`. NULL on "
                "subtotal rows. Per OSPI footnote 2: on detail rows "
                "`total_annual_salary == fte * avg_rate` for "
                "certificated, `== number_of_hours * avg_rate` for "
                "classified."
            ),
        },
        {
            "name": "total_annual_salary",
            "field_type": "decimal",
            "doc": (
                "Total annualized salary for this line. Per-form "
                "identity: sum of `detail.total_annual_salary` in a "
                "given (program, activity) equals the corresponding "
                "`activity_total.total_annual_salary`; sum of "
                "activity totals in a program equals the "
                "`program_total.total_annual_salary`."
            ),
        },
        {
            "name": "state_annual_salary",
            "field_type": "decimal",
            "doc": (
                "State-funded portion of `total_annual_salary`. "
                "Present only in 2019-20+ files (post-McCleary form "
                "vintage). NULL in 2013-14 through 2018-19."
            ),
        },
        {
            "name": "local_annual_salary",
            "field_type": "decimal",
            "doc": (
                "Local (non-state) portion of `total_annual_salary`. "
                "Present only in 2019-20+ files. NULL in 2013-14 "
                "through 2018-19. Identity: "
                "`total_annual_salary == state_annual_salary + "
                "local_annual_salary` on every row from 2019-20 on."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [[
        "school_year", "ccddd", "exhibit_kind", "fund",
        "program_code", "activity_code", "duty_code", "row_kind",
    ]],
}


ALL_SCHEMAS = [FISCAL_F195_SALARY_EXHIBITS]
