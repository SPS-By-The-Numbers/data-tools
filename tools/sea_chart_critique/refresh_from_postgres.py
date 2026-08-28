"""Regenerate the cached S-275 extracts from PostgreSQL instead of BigQuery.

BigQuery still holds the pre-fix `assignment` table, whose FTE is short by
2.8% districtwide and 23% for central administrators (see
extractors/safs/transforms/s275.py -- the dedup used to drop genuinely
distinct assignment rows). `safs_prod` in Postgres has the corrected data, so
until the reload happens the charts read from here.

    $ venv/bin/python3 tools/sea_chart_critique/refresh_from_postgres.py

Writes the same filenames and column headers the BigQuery pulls produced, so
build.py / build_images.py need no changes. Delete the CSVs and re-run the
`bq` commands in the README to go back to BigQuery once it is reloaded.
"""
import csv
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "output", "sea_chart_critique")
DUTY_FUNDING = os.path.join(ROOT, "output", "duty_funding")
PSQL = "/Applications/Postgres.app/Contents/Versions/latest/bin/psql"
DB = "safs_prod"
WHERE = ("r.ccddd = 17001 AND r.school_year = '2024-2025' "
         "AND r.report_type = 'final'")
# F-196 object 4 / (objects 2+3) for SPS 2024-25 -- see docs/guides/DUTY_FUNDING.md
BENEFIT_RATIO = 1.3265


def q(sql):
    # pipe-separated: duty names contain commas, and psql -A does not quote
    out = subprocess.run([PSQL, "-d", DB, "-t", "-A", "-F", "|", "-c", sql],
                         check=True, capture_output=True, text=True).stdout
    return [l.split("|") for l in out.strip().split("\n") if l.strip()]


def write(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print("wrote %s (%d rows)" % (path, len(rows)))


def by_duty():
    rows = q(f"""
        SELECT a.duty_root_code, max(dr.duty_name),
               count(DISTINCT a.report_employee_id),
               round(sum(a.fte_in_assignment), 3),
               round(sum(pa.c_est_total_final_salary), 0)
        FROM assignment a
        JOIN report r USING (report_id)
        LEFT JOIN private_assignment pa USING (assignment_id)
        LEFT JOIN d_duty_root dr ON dr.duty_root = a.duty_root_code
        WHERE {WHERE}
        GROUP BY a.duty_root_code ORDER BY a.duty_root_code""")
    write(os.path.join(OUT, "s275_by_duty_2425.csv"),
          ["duty_root", "duty_title", "employees", "fte", "total_final_salary"],
          rows)


def admin_employees():
    rows = q(f"""
        SELECT a.duty_root_code, a.report_employee_id,
               round(sum(a.fte_in_assignment), 3),
               round(sum(pa.c_est_total_final_salary), 0)
        FROM assignment a
        JOIN report r USING (report_id)
        LEFT JOIN private_assignment pa USING (assignment_id)
        WHERE {WHERE} AND a.duty_root_code IN (11, 12, 13, 99)
        GROUP BY a.duty_root_code, a.report_employee_id
        ORDER BY a.duty_root_code, 4 DESC""")
    write(os.path.join(OUT, "s275_admin_employees_2425.csv"),
          ["duty_root", "emp", "fte", "salary"], rows)


GROUPS = """
  CASE WHEN a.duty_root_code BETWEEN 31 AND 34 THEN 'Teachers'
       WHEN a.duty_root_code = 91 THEN 'Instructional aides (paras)'
       WHEN a.duty_root_code = 96 THEN 'Classified professionals'
       WHEN a.duty_root_code = 99 THEN 'Directors & supervisors'
       WHEN a.duty_root_code BETWEEN 21 AND 25 THEN 'Principals & vice principals'
       WHEN a.duty_root_code = 94 THEN 'Office & clerical'
       WHEN a.duty_root_code IN (12, 13) THEN 'Cabinet & district admin'
       WHEN a.duty_root_code = 11 THEN 'Superintendent' END"""


def headcounts():
    rows = q(f"""
        SELECT {GROUPS} AS grp, count(DISTINCT a.report_employee_id)
        FROM assignment a JOIN report r USING (report_id)
        WHERE {WHERE} AND (a.duty_root_code BETWEEN 31 AND 34
              OR a.duty_root_code BETWEEN 21 AND 25
              OR a.duty_root_code IN (91, 96, 99, 94, 12, 13, 11))
        GROUP BY 1 ORDER BY 2 DESC""")
    write(os.path.join(OUT, "group_headcount.csv"), ["grp", "people"], rows)


def staff():
    """One row per person, duty root of their major assignment -- the same
    shape tools/salary_skyline/query.sql produces."""
    rows = q(f"""
        WITH a AS (
            SELECT a.report_employee_id emp, a.duty_root_code dr,
                   sum(a.fte_in_assignment) fte,
                   count(*) FILTER (WHERE a.is_major) nmaj,
                   sum(coalesce(pa.assignment_salary, 0)) sal
            FROM assignment a
            JOIN report r USING (report_id)
            LEFT JOIN private_assignment pa USING (assignment_id)
            WHERE {WHERE}
            GROUP BY 1, 2),
        pick AS (
            SELECT emp, dr, row_number() OVER (
                     PARTITION BY emp ORDER BY nmaj DESC, fte DESC, sal DESC, dr) rn
            FROM a),
        tot AS (
            SELECT a.report_employee_id emp, sum(a.fte_in_assignment) fte
            FROM assignment a JOIN report r USING (report_id)
            WHERE {WHERE} GROUP BY 1)
        SELECT 0, p.dr, dn.duty_name,
               round(pre.total_final_salary, 2), round(t.fte, 4), 0
        FROM pick p
        JOIN private_report_employee pre ON pre.report_employee_id = p.emp
        JOIN tot t ON t.emp = p.emp
        LEFT JOIN d_duty_root dn ON dn.duty_root = p.dr
        WHERE p.rn = 1
        ORDER BY p.dr, 4 DESC""")
    write(os.path.join(OUT, "staff_2425.csv"),
          ["cat", "duty", "duty_name", "salary", "fte", "pgroup"], rows)


def model_roles():
    """Rewrite actual_fte / actual_pay in the 1191EDF role table.

    model_fte and model_dollars come from the apportionment PDF and are
    unaffected; only the S-275 side moved.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools", "duty_funding"))
    from model_roles import ROLES, MAPPED_ROOTS, UNFUNDED_LABEL

    raw = q(f"""
        SELECT a.duty_root_code, round(sum(a.fte_in_assignment), 3),
               round(sum(pa.c_est_total_final_salary), 2)
        FROM assignment a
        JOIN report r USING (report_id)
        LEFT JOIN private_assignment pa USING (assignment_id)
        WHERE {WHERE} GROUP BY 1""")
    fte = {int(r[0]): float(r[1]) for r in raw}
    sal = {int(r[0]): float(r[2] or 0) for r in raw}

    cls_of = {}
    for _label, cls, _keys, roots in ROLES:
        for rt in roots:
            cls_of[rt] = cls
    # duty roots the model funds nothing for, kept per class
    CIS = {39, 40, 43, 45, 48, 51, 52, 61}
    unmapped = {}
    for rt in fte:
        if rt in MAPPED_ROOTS:
            continue
        c = "CIS" if rt in CIS or 31 <= rt <= 61 else "CLS"
        unmapped.setdefault(c, [0.0, 0.0])
        unmapped[c][0] += fte[rt]
        unmapped[c][1] += sal[rt]

    path = os.path.join(DUTY_FUNDING, "sps_2024-25_model_roles.csv")
    with open(path) as f:
        old = list(csv.DictReader(f))
    out = []
    for row in old:
        label, cls = row["role"], row["staff_class"]
        if label.startswith(UNFUNDED_LABEL[:20]):
            f_, s_ = unmapped.get(cls, [0.0, 0.0])
        else:
            roots = next(rts for lbl, c, _k, rts in ROLES
                         if lbl == label and c == cls)
            f_ = sum(fte.get(rt, 0.0) for rt in roots)
            s_ = sum(sal.get(rt, 0.0) for rt in roots)
        out.append({**row, "actual_fte": "%.3f" % f_,
                    "actual_pay": "%.2f" % (s_ * BENEFIT_RATIO)})
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(old[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("wrote %s (%d roles)" % (path, len(out)))
    for c, (f_, _s) in sorted(unmapped.items()):
        print("   no-staff-unit FTE  %s %.3f" % (c, f_))


def main():
    by_duty()
    admin_employees()
    headcounts()
    staff()
    model_roles()


if __name__ == "__main__":
    main()
