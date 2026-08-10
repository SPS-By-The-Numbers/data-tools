"""Rebuild the "Summary" sheet of `Medium #3 = Cracking thd Budget Part 1.xlsx`
from BigQuery instead of hardcoded values.

    venv/bin/python3 tools/bb_summary_from_db.py     # from repo root

Companion: tools/pb_actuals_reconcile.py (the school-side S-275 cross-check).
Full write-up: docs/guides/COMP_SPLIT_RECONSTRUCTION.md. Query results are
cached under ./out_summary/ (gitignored); delete a CSV there to force a re-pull.

Everything marked [DB] comes from `sps-btn-data.safs_f19x.general_fund_expenditures`
(OSPI F-195 budget / F-196 actuals). Everything marked [PRIMARY] cannot come from
the database and must be sourced from primary materials:

  * Budget Book school-allocation totals (spreadsheet Summary!C5:D6) -- the
    per-school allocation section of the SPS Budget Book. Not in OSPI data.
  * Purple Book staffing allocations (Summary!C38:D40) -- the SPS "purple book"
    school staffing reports. Parsed by extractors/budget + extractors/purplebook
    but not loaded into BigQuery.

The 2024 chronic-underspend constants in Summary!C131:C146 are NOT treated as
primary: they are rounded copies of budget-minus-actuals variances that the DB
reproduces to the dollar, so they are recomputed here (and diffed against the
spreadsheet's rounded values).
"""
import os
import subprocess
import pandas as pd

OUT = 'out_summary/'
TBL = 'sps-btn-data.safs_f19x.general_fund_expenditures'
CCDDD = 17001
YEARS = (2024, 2025)   # class_of; 2024 = school year 2023-24

# ---------------------------------------------------------------- buckets
# The Summary sheet's comp-activity groups (rows 11-35), as OSPI activity codes.
TEACHING = [27, 28, 34]              # Teaching, Extracurricular, Prof Learning-State
STUDENT = [84, 23, 24, 25, 26, 35]   # Principal(debt, comp is 0), Principal's Office,
                                     # Guidance, Pupil Mgmt, Health, Pupil Safety
BUILDING = [62, 63, 64, 65, 74, 44, 67]  # Grounds, Ops of Bldgs, Maintenance,
                                         # Utilities, Warehousing, Food Svc Ops, Security
# Other = every remaining activity (computed as residual, like Summary!C35).

# The "Chronic Underspend 2024" groups (Summary rows 129-146). Same activities
# the spreadsheet lists, but the dollar values are recomputed from the DB.
# Teaching / Prof Learn are combined exactly as the workbook's
# "2024 Compnon-comp 8 underspend" sheet combines them.
UNDERSPEND_GROUPS = {
    'Teaching Related': [27, 34],            # "Teaching / Prof Learn"
    'Student Support': [23],                 # "Principal's Office"
    'Building Support': [63, 44],            # Ops of Buildings, Food Svc Ops
    'Other comp': [21, 72, 12, 51],          # Supervision-Instr, Info Systems,
                                             # Superintendent's Office, Supervision-Transp
}

# What the spreadsheet hardcoded for the same groups (Summary!C131:C146), for diffing.
XLSX_UNDERSPEND = {
    'Teaching Related': 37_000_000,
    'Student Support': 3_700_000,
    'Building Support': 2_700_000 + -1_000_000,
    'Other comp': 3_700_000 + 4_600_000 + 900_000 + 800_000,
}

# Spreadsheet Summary!C150:C167 median(2016-2024) underspend constants, for diffing
# against the recomputed medians (rows 187-193 use these).
XLSX_MEDIAN_UNDERSPEND = {
    'Teaching Related': 50_000_000,
    'Student Support': 1_400_000,
    'Building Support': 800_000 + 540_000,
    'Other comp': 1_900_000 + 1_300_000 + 800_000 + 700_000,
}

# ---------------------------------------------------------------- [PRIMARY] constants
# Budget Book, school-allocation section (Summary!C6:D6, C5:D5).
BB_SCHOOL_ALLOC_COMP = {2024: 634_579_723, 2025: 660_376_817}
BB_NONGRANT_SCHOOL_ALLOC_COMP = {2024: 585_466_859, 2025: 607_948_098}  # reported only

# Purple Book school staffing allocations (Summary!C38:D40).
PB_TEACHING_LIB_OTHER = {2024: 510_496_137, 2025: 496_041_712 + 10_787_737 + 4_794_364}
PB_PRINCIPAL_OFFICE = {2024: 66_478_371, 2025: 68_213_544}
PB_GUIDANCE = {2024: 21_038_425, 2025: 20_660_973}


def _bq_csv(name, sql):
    """Run a BigQuery query, cached to a CSV under out_summary/."""
    path = OUT + name
    if not os.path.exists(path):
        r = subprocess.run(
            ['bq', 'query', '--nouse_legacy_sql', '--format=csv', '--max_rows=100000', sql],
            capture_output=True, text=True, check=True)
        os.makedirs(OUT, exist_ok=True)
        with open(path, 'w') as f:
            f.write(r.stdout)
    return pd.read_csv(path)


def load_activity_totals():
    """[DB] budget + actuals by year x activity, comp (obj 2,3,4) and all objects."""
    return _bq_csv('f19x_activity_totals.csv', f'''
        SELECT class_of, data_type, activity_code, activity,
               SUM(IF(object_code IN (2,3,4), amount, 0)) AS comp,
               SUM(amount) AS total
        FROM `{TBL}`
        WHERE ccddd = {CCDDD} AND class_of IN {YEARS}
        GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3''')


def load_underspend_2016_2024():
    """[DB] budget-minus-actuals per year for the chronic-underspend activities,
    used for the median(2016-2024) variant (Summary rows 150-167 / 187-193)."""
    codes = sorted({c for cs in UNDERSPEND_GROUPS.values() for c in cs} | {34})
    return _bq_csv('underspend_2016_2024.csv', f'''
        SELECT class_of, activity_code,
               SUM(IF(data_type="budget", amount, 0)) AS bud,
               SUM(IF(data_type="actuals", amount, 0)) AS act
        FROM `{TBL}`
        WHERE ccddd = {CCDDD} AND class_of BETWEEN 2016 AND 2024
              AND activity_code IN ({", ".join(map(str, codes))})
        GROUP BY 1, 2 ORDER BY 1, 2''')


def median_underspend():
    """{group: sum of per-activity median(2016-2024) budget-minus-actuals},
    matching the workbook's construction (per-activity medians, then summed).
    Teaching pools 27+34 per year first -- one budget line split late in the
    series -- which happens not to change its median."""
    d = load_underspend_2016_2024()
    d['us'] = d.bud - d.act
    p = d.pivot_table(index='class_of', columns='activity_code',
                      values='us', aggfunc='sum').fillna(0)
    out = {'Teaching Related': p[[27, 34]].sum(axis=1).median()}
    for g, codes in UNDERSPEND_GROUPS.items():
        if g != 'Teaching Related':
            out[g] = sum(p[c].median() for c in codes)
    return out


def load_actuals_school_split():
    """[DB] actuals comp by year x activity, split school / district office.

    F-196 actuals carry building codes from 2019-20 on, so the actuals side
    does NOT need the Purple Book residual trick -- the split is directly
    observable. c_in_school_allocated_staff marks district-office comp in
    activities 27/23/24/84 that the pipeline judges to be school-allocated
    staff money parked centrally (see extractors/safs/transforms/f19x.py).
    """
    return _bq_csv('f19x_actuals_school_split.csv', f'''
        SELECT class_of, activity_code, activity,
               SUM(IF(NOT is_district_office, amount, 0)) AS school,
               SUM(IF(is_district_office AND c_in_school_allocated_staff, amount, 0))
                   AS district_office_flagged,
               SUM(IF(is_district_office AND NOT c_in_school_allocated_staff, amount, 0))
                   AS district_office
        FROM `{TBL}`
        WHERE ccddd = {CCDDD} AND class_of IN {YEARS}
              AND data_type = 'actuals' AND object_code IN (2, 3, 4)
        GROUP BY 1, 2, 3 ORDER BY 1, 2''')


def m(x):
    return f'{x/1e6:,.1f}'


def bucket_sums(df, col):
    """{bucket: value} for one year's slice, Other as the residual."""
    tot = df[col].sum()
    t = df[df.activity_code.isin(TEACHING)][col].sum()
    s = df[df.activity_code.isin(STUDENT)][col].sum()
    b = df[df.activity_code.isin(BUILDING)][col].sum()
    return {'Teaching Related': t, 'Student Support': s, 'Building Support': b,
            'Other comp': tot - t - s - b, 'Total': tot}


def main():
    act = load_activity_totals()
    split = load_actuals_school_split()

    bud = {y: act[(act.class_of == y) & (act.data_type == 'budget')] for y in YEARS}
    acts = {y: act[(act.class_of == y) & (act.data_type == 'actuals')] for y in YEARS}

    # ------------------------------------------------ underspend, recomputed [DB]
    us24 = {}
    b24 = bud[2024].set_index('activity_code')
    a24 = acts[2024].set_index('activity_code')
    for grp, codes in UNDERSPEND_GROUPS.items():
        us24[grp] = sum(b24.total.get(c, 0) - a24.total.get(c, 0) for c in codes)

    print('=' * 78)
    print('2024 chronic underspend by group (budget - actuals, all objects)  [DB]')
    print(f'{"":22s} {"recomputed":>12s} {"spreadsheet":>12s} {"diff":>10s}   ($M)')
    for grp in UNDERSPEND_GROUPS:
        d = us24[grp] - XLSX_UNDERSPEND[grp]
        print(f'{grp:22s} {m(us24[grp]):>12s} {m(XLSX_UNDERSPEND[grp]):>12s} {m(d):>10s}')
    print(f'{"Total":22s} {m(sum(us24.values())):>12s} '
          f'{m(sum(XLSX_UNDERSPEND.values())):>12s}')

    med = median_underspend()
    print()
    print('median(2016-2024) underspend by group  [DB]  (Summary rows 150-167)')
    print(f'{"":22s} {"recomputed":>12s} {"spreadsheet":>12s}   ($M)')
    for grp in UNDERSPEND_GROUPS:
        print(f'{grp:22s} {m(med[grp]):>12s} {m(XLSX_MEDIAN_UNDERSPEND[grp]):>12s}')
    print(f'{"Total":22s} {m(sum(med.values())):>12s} '
          f'{m(sum(XLSX_MEDIAN_UNDERSPEND.values())):>12s}')

    # ------------------------------------------------ the Summary chain, per year
    for y in YEARS:
        by = bud[y]
        comp = bucket_sums(by, 'comp')
        total_spend = by.total.sum()

        pb_po, pb_g = PB_PRINCIPAL_OFFICE[y], PB_GUIDANCE[y]
        pb_total = PB_TEACHING_LIB_OTHER[y] + pb_po + pb_g
        bb_alloc = BB_SCHOOL_ALLOC_COMP[y]

        # Reconciled school-allocated estimates (Summary rows 51-53):
        # Teaching absorbs the Budget Book residual over the two PB categories.
        school_teaching = bb_alloc - pb_po - pb_g

        nonschool = {
            'Teaching Related': comp['Teaching Related'] - school_teaching,
            'Student Support': comp['Student Support'] - pb_po - pb_g,
            'Building Support': comp['Building Support'],
            'Other comp': comp['Other comp'],
        }
        adj = {g: nonschool[g] - us24[g] for g in nonschool}  # 2024 underspend, both years
        medadj = {g: nonschool[g] - med[g] for g in nonschool}  # Summary rows 188-193

        print()
        print('=' * 78)
        print(f'class_of {y} ({y-1}-{y} school year), $M unless noted')
        print(f'  Total Spend (budget, all objects)       [DB]      {m(total_spend):>10s}')
        print(f'  Total Comp Spend (objects 2,3,4)        [DB]      {m(by.comp.sum()):>10s}')
        print(f'  School Allocated Comp (Budget Book)     [PRIMARY] {m(bb_alloc):>10s}')
        print(f'  Non-grant School Allocated Comp         [PRIMARY] {m(BB_NONGRANT_SCHOOL_ALLOC_COMP[y]):>10s}  (unused below)')
        print(f'  Purple Book: Teaching+Librarian+Other   [PRIMARY] {m(PB_TEACHING_LIB_OTHER[y]):>10s}')
        print(f'  Purple Book: Principal\'s Office         [PRIMARY] {m(pb_po):>10s}')
        print(f'  Purple Book: Guidance & Counseling      [PRIMARY] {m(pb_g):>10s}')
        print(f'  Purple Book total / delta vs Budget Book          {m(pb_total):>10s} / {m(bb_alloc - pb_total)}')
        print()
        print(f'  {"bucket":20s} {"comp bud":>9s} {"nonschool":>10s} {"-2024 us":>9s} '
              f'{"-median us":>10s} {"med %":>6s}')
        for g in nonschool:
            print(f'  {g:20s} {m(comp[g]):>9s} {m(nonschool[g]):>10s} {m(adj[g]):>9s} '
                  f'{m(medadj[g]):>10s} {medadj[g]/total_spend:>6.1%}')
        print(f'  {"Total non-school":20s} {"":>9s} {m(sum(nonschool.values())):>10s} '
              f'{m(sum(adj.values())):>9s} {m(sum(medadj.values())):>10s} '
              f'{sum(medadj.values())/total_spend:>6.1%}')

        # -------------------------------------------- actuals, split directly [DB]
        # Parked comp (building 1002 in activities 27/23/24/84) counts as
        # CENTRALLY MANAGED -- it is school-serving staff the Budget Book never
        # allocates to a specific school, so it belongs with the DO side.
        sp = split[split.class_of == y]
        school = bucket_sums(sp, 'school')
        do_flag = bucket_sums(sp, 'district_office_flagged')
        do = bucket_sums(sp, 'district_office')
        print()
        print(f'  ACTUALS comp split by building code [DB]; parked pools count as central:')
        print(f'  {"bucket":20s} {"at schools":>10s} {"central":>9s} {"(parked":>9s} {"+ other DO)":>11s} {"vs med est*":>11s}')
        for g in ['Teaching Related', 'Student Support', 'Building Support', 'Other comp']:
            central = do_flag[g] + do[g]
            print(f'  {g:20s} {m(school[g]):>10s} {m(central):>9s} {m(do_flag[g]):>9s} '
                  f'{m(do[g]):>11s} {m(central - medadj[g]):>11s}')
        print(f'  {"Total":20s} {m(school["Total"]):>10s} '
              f'{m(do_flag["Total"] + do["Total"]):>9s} {m(do_flag["Total"]):>9s} '
              f'{m(do["Total"]):>11s}')
        print('  *  central actuals minus the median-adjusted budget-side estimate; the')
        print('     shortfall is centrally-managed program staff delivered AT schools')


if __name__ == '__main__':
    main()
