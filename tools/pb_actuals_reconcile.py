"""Reconcile the F-196 building-code comp split with the Purple Book concept of
"school-allocated staff", using the S-275 to restrict to Purple-Book-type duties.

    venv/bin/python3 tools/pb_actuals_reconcile.py     # from repo root

Companion: tools/bb_summary_from_db.py (the Budget Book chain). Full write-up:
docs/guides/COMP_SPLIT_RECONSTRUCTION.md. Query results are cached under
./out_summary/ (gitignored); delete a CSV there to force a re-pull.

The problem: F-196 actuals coded to school buildings include custodians, food
service, etc., while the Purple Book only allocates certain roles (teachers,
librarians, principals/VPs, counselors, social workers, aides, office staff).
So the naive building split overstates "school allocated" relative to the
Purple Book / Budget Book definition.

Method (per year):
  1. From S-275, compute salary at school buildings for Purple-Book-type duties
     vs all duties, split certificated (duty < 90 -> object 2) and classified
     (duty >= 90 -> object 3).
  2. Apply those salary shares to the F-196 comp actuals coded to school
     buildings: object 2 x cert share, object 3 x classified share, and
     benefits (object 4) x the combined covered-salary share.
  3. Separately show the district-office comp the pipeline already flags as
     school-staff money parked centrally (c_in_school_allocated_staff), which
     is Purple-Book-type by construction (activities 27/23/24/84).

Substitute teachers (duty 52) are excluded from the covered set by default --
the Purple Book does not allocate subs to schools -- and shown as a sensitivity.
"""
import os
import subprocess
import pandas as pd

OUT = 'out_summary/'
CCDDD = 17001
YEARS = {2024: '2023-2024', 2025: '2024-2025'}

# Purple-Book-type duty roots (the pie graphic's SCHOOL-ALLOCATED STAFFING list).
TEACHERS = [31, 32, 33, 34]
PB_DUTIES = TEACHERS + [
    91,                  # Aide
    94,                  # Office or Clerical
    42,                  # Counselor
    44,                  # Social Worker
    21, 22, 23, 24, 25,  # Principals / Vice Principals / Other School Admin
    41,                  # Library Media Specialist
]
SUBSTITUTE = 52

# Purple-Book activities on the F-196/S-275 activity axis.
PB_ACTIVITIES = [22, 23, 24, 27]


def _bq_csv(name, sql):
    path = OUT + name
    if not os.path.exists(path):
        r = subprocess.run(
            ['bq', 'query', '--nouse_legacy_sql', '--format=csv', '--max_rows=100000', sql],
            capture_output=True, text=True, check=True)
        os.makedirs(OUT, exist_ok=True)
        with open(path, 'w') as f:
            f.write(r.stdout)
    return pd.read_csv(path)


def load_s275():
    """S-275 salary+FTE by year x building type x duty. Salary is the
    per-assignment apportioned estimate (private_assignment); final reports only."""
    return _bq_csv('s275_school_duty_salary.csv', f'''
        SELECT r.school_year,
               COALESCE(ds.is_district_office, FALSE) AS is_district_office,
               a.duty_root_code,
               ROUND(SUM(a.fte_in_assignment), 1) AS fte,
               ROUND(SUM(pa.c_est_total_final_salary), 0) AS salary
        FROM `sps-btn-data.safs_s275.assignment` a
        JOIN `sps-btn-data.safs_s275.report` r USING (report_id)
        JOIN `sps-btn-data.safs_s275.private_assignment` pa USING (assignment_id)
        LEFT JOIN `sps-btn-data.safs_domains.d_school` ds
             ON ds.school_code = a.school_code
        WHERE r.ccddd = {CCDDD}
              AND r.school_year IN ("{YEARS[2024]}", "{YEARS[2025]}")
        GROUP BY 1, 2, 3''')


def load_s275_cross():
    """S-275 salary+FTE by year x building type x activity x duty -- the
    duty-by-activity cross needed to split the method A vs B wedge."""
    return _bq_csv('s275_school_duty_activity_salary.csv', f'''
        SELECT r.school_year,
               COALESCE(ds.is_district_office, FALSE) AS is_district_office,
               a.activity_code,
               a.duty_root_code,
               ROUND(SUM(a.fte_in_assignment), 1) AS fte,
               ROUND(SUM(pa.c_est_total_final_salary), 0) AS salary
        FROM `sps-btn-data.safs_s275.assignment` a
        JOIN `sps-btn-data.safs_s275.report` r USING (report_id)
        JOIN `sps-btn-data.safs_s275.private_assignment` pa USING (assignment_id)
        LEFT JOIN `sps-btn-data.safs_domains.d_school` ds
             ON ds.school_code = a.school_code
        WHERE r.ccddd = {CCDDD}
              AND r.school_year IN ("{YEARS[2024]}", "{YEARS[2025]}")
        GROUP BY 1, 2, 3, 4''')


def load_duty_names():
    return _bq_csv('d_duty_root.csv', '''
        SELECT duty_root, duty_name
        FROM `sps-btn-data.safs_domains.d_duty_root` ORDER BY duty_root''')


def load_activity_names():
    return _bq_csv('d_activity.csv', '''
        SELECT activity_code, activity
        FROM `sps-btn-data.safs_domains.d_activity` ORDER BY activity_code''')


def load_f196_comp_by_object():
    """F-196 comp actuals by year x object, split by building coding, with a
    Purple-Book-activity slice of the school-coded portion.

    PB-type activities: 27 Teaching (teachers + aides), 22 Learning Resources
    (librarians), 23 Principal's Office (principals/VPs/office staff), 24
    Guidance and Counseling (counselors + social workers). This is the F-196
    side of the duty filter: it naturally excludes custodians (63), food
    service (44), health staff (26), etc., which the F-196 codes to school
    buildings but the Purple Book does not allocate.
    """
    return _bq_csv('f19x_actuals_object_school_split.csv', f'''
        SELECT class_of, object_code,
               SUM(IF(NOT is_district_office, amount, 0)) AS school,
               SUM(IF(NOT is_district_office AND activity_code IN (22, 23, 24, 27),
                      amount, 0)) AS school_pb_activity,
               SUM(IF(is_district_office AND c_in_school_allocated_staff, amount, 0))
                   AS do_parked,
               SUM(IF(is_district_office AND NOT c_in_school_allocated_staff, amount, 0))
                   AS district_office
        FROM `sps-btn-data.safs_f19x.general_fund_expenditures`
        WHERE ccddd = {CCDDD} AND class_of IN (2024, 2025)
              AND data_type = 'actuals' AND object_code IN (2, 3, 4)
        GROUP BY 1, 2 ORDER BY 1, 2''')


def m(x):
    return f'{x/1e6:,.1f}'


def main():
    s275 = load_s275()
    f196 = load_f196_comp_by_object()
    cross = load_s275_cross()
    dnames_db = load_duty_names().set_index('duty_root').duty_name.to_dict()
    anames = load_activity_names().set_index('activity_code').activity.to_dict()

    for class_of, sy in YEARS.items():
        s = s275[(s275.school_year == sy) & (~s275.is_district_office)]
        cert = s[s.duty_root_code < 90]
        clas = s[s.duty_root_code >= 90]

        def covered(df, extra=()):
            return df[df.duty_root_code.isin(PB_DUTIES + list(extra))].salary.sum()

        cert_tot, clas_tot = cert.salary.sum(), clas.salary.sum()
        p2 = covered(cert) / cert_tot
        p3 = covered(clas) / clas_tot
        p4 = (covered(cert) + covered(clas)) / (cert_tot + clas_tot)
        p2_sub = covered(cert, (SUBSTITUTE,)) / cert_tot   # sensitivity

        f = f196[f196.class_of == class_of].set_index('object_code')
        F2, F3, F4 = f.school[2], f.school[3], f.school[4]
        parked = f.do_parked.sum()
        pb_act = f.school_pb_activity.sum()

        est = p2 * F2 + p3 * F3 + p4 * F4
        est_sub = p2_sub * F2 + p3 * F3 + \
            ((covered(cert, (SUBSTITUTE,)) + covered(clas)) / (cert_tot + clas_tot)) * F4

        print('=' * 78)
        print(f'class_of {class_of} ({sy})')
        print()
        print('  S-275 salary at school buildings ($M) and Purple-Book-type share:')
        print(f'    certificated (obj 2): {m(covered(cert)):>8s} of {m(cert_tot):>8s}  -> {p2:6.1%}')
        print(f'    classified   (obj 3): {m(covered(clas)):>8s} of {m(clas_tot):>8s}  -> {p3:6.1%}')
        print(f'    combined     (obj 4): {"":>8s}    {"":>8s}     -> {p4:6.1%}')
        print()
        print('  Not covered at schools (the wedge the naive split wrongly includes),')
        print('  top duties by salary:')
        notcov = s[~s.duty_root_code.isin(PB_DUTIES)].nlargest(6, 'salary')
        dnames = {21: 'Elem Principal', 22: 'Elem VP', 23: 'Sec Principal',
                  24: 'Sec VP', 25: 'Other School Admin', 41: 'Librarian',
                  42: 'Counselor', 43: 'OT', 44: 'Social Worker', 45: 'SLP',
                  46: 'Psychologist', 47: 'Nurse', 48: 'PT', 40: 'Other Support',
                  52: 'Substitute Teacher', 96: 'Professional',
                  97: 'Service Worker', 99: 'Director/Supervisor'}
        for _, r in notcov.iterrows():
            nm = dnames.get(r.duty_root_code, f'duty {r.duty_root_code}')
            print(f'    {nm:22s} {m(r.salary):>8s}  ({r.fte:,.0f} FTE)')
        print()
        print('  F-196 comp actuals coded to school buildings ($M):')
        print(f'    obj 2 / 3 / 4: {m(F2)} / {m(F3)} / {m(F4)}   (total {m(F2 + F3 + F4)})')
        print()
        print('  Purple-Book-comparable school-allocated comp, actuals:')
        print(f'    A. S-275 duty shares x school F-196    {m(est):>8s}  (+ subs: {m(est_sub)})')
        print(f'    B. F-196 PB activities (22/23/24/27)   {m(pb_act):>8s}')
        print(f'    + DO-parked school staff comp (flag)   {m(parked):>8s}')
        print(f'    = reconciled estimate (A / B)          {m(est + parked):>8s} / {m(pb_act + parked)}')
        print()
        # ------------------------------------------ duty x activity cross-filter
        x = cross[(cross.school_year == sy) & (~cross.is_district_office)].copy()
        x['pb_duty'] = x.duty_root_code.isin(PB_DUTIES)
        x['pb_act'] = x.activity_code.isin(PB_ACTIVITIES)

        q = x.groupby(['pb_duty', 'pb_act']).salary.sum()
        print()
        print('  S-275 duty x activity cross at schools ($M salary):')
        print(f'    {"":24s} {"PB activity":>12s} {"other activity":>14s}')
        print(f'    {"PB duty":24s} {m(q.get((True, True), 0)):>12s} {m(q.get((True, False), 0)):>14s}')
        print(f'    {"other duty":24s} {m(q.get((False, True), 0)):>12s} {m(q.get((False, False), 0)):>14s}')

        print()
        print('  PB-type duties charged OUTSIDE PB activities (A counts, B drops):')
        w = (x[x.pb_duty & ~x.pb_act].groupby('activity_code')
             .agg({'salary': 'sum', 'fte': 'sum'}).nlargest(5, 'salary'))
        for code, r in w.iterrows():
            print(f'    {anames.get(code, f"activity {code}"):38s} {m(r.salary):>7s}  ({r.fte:,.0f} FTE)')
        print('  Non-PB duties charged INSIDE PB activities (B counts, A drops):')
        w = (x[~x.pb_duty & x.pb_act].groupby('duty_root_code')
             .agg({'salary': 'sum', 'fte': 'sum'}).nlargest(5, 'salary'))
        for code, r in w.iterrows():
            print(f'    {dnames_db.get(code, f"duty {code}"):38s} {m(r.salary):>7s}  ({r.fte:,.0f} FTE)')

        # Method C: duty shares computed WITHIN PB activities, applied to the
        # activity-filtered F-196 comp -- strips subs/support staff that ride
        # inside activity 22/23/24/27.
        xa = x[x.pb_act]
        c_cert = xa[xa.duty_root_code < 90]
        c_clas = xa[xa.duty_root_code >= 90]
        c2 = c_cert[c_cert.pb_duty].salary.sum() / c_cert.salary.sum()
        c3 = c_clas[c_clas.pb_duty].salary.sum() / c_clas.salary.sum()
        c4 = xa[xa.pb_duty].salary.sum() / xa.salary.sum()
        B2, B3, B4 = (f.school_pb_activity[i] for i in (2, 3, 4))
        est_c = c2 * B2 + c3 * B3 + c4 * B4
        print()
        print(f'  C. cross-filtered: within-PB-activity duty shares '
              f'(cert {c2:.1%} / class {c3:.1%})')
        print(f'     x F-196 PB-activity school comp       {m(est_c):>8s}')
        print(f'     + DO-parked school staff comp (flag)  {m(parked):>8s}')
        print(f'     = reconciled estimate (C)             {m(est_c + parked):>8s}')

        print()
        print('  For comparison:')
        print(f'    naive F-196 building split             {m(f.school.sum() + parked):>8s}')
        print(f'    Budget Book school-allocated (budget)  '
              f'{m({2024: 634_579_723, 2025: 660_376_817}[class_of]):>8s}')
        print(f'    Purple Book total (budget)             '
              f'{m({2024: 598_012_933, 2025: 600_498_786}[class_of]):>8s}')


if __name__ == '__main__':
    main()
