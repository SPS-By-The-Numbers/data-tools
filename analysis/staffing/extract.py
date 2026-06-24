"""One-shot extraction: read the S-275 AVRO, enrollment CSV, and spsbtn xlsx, and write a single
cache (build/staffing.pkl) that all the plot/report scripts consume.

Grain notes (see ../../STAFFING_ANALYSIS_GUIDE.md):
  - emp records: one per person-year, classified by their is_major assignment (duty + school).
  - fte_* dicts: assignment-grain FTE summed to (year, school, duty).
  - district aggregates: fte_by_yr_duty, enr_district.
"""
import pickle, csv
from collections import defaultdict
import fastavro
import openpyxl
import common as C


def reader(name):
    return fastavro.reader(open(f'{C.S275}/{name}.avro', 'rb'))


def dom(name):
    return fastavro.reader(open(f'{C.DOMAINS}/{name}.avro', 'rb'))


def main():
    # ---- domains ----
    duty_name, duty_cat = {}, {}
    for r in dom('d_duty_root'):
        duty_name[r['duty_root']] = r['duty_name']; duty_cat[r['duty_root']] = r['duty_name_category']
    do_codes = {x['school_code'] for x in dom('d_school') if x['is_district_office']}   # G9

    # ---- school metadata + attendance areas from spsbtn xlsx ----
    wb = openpyxl.load_workbook(C.SPSBTN_XLSX, read_only=True, data_only=True)
    it = wb['schools'].iter_rows(values_only=True); next(it)
    sch = {}
    for row in it:
        if row[1] is None: continue
        sch[int(row[1])] = {'name': row[2], 'type': row[3], 'region': row[5],
                            'ms': int(row[6]) if row[6] else None}
    areas = C.build_areas(sch)

    # ---- Seattle reports: report_id -> school_year ----
    rid_year = {r['report_id']: r['school_year'] for r in reader('report') if str(r['ccddd']) == C.SEATTLE}
    years_s275 = sorted(set(rid_year.values()))

    # ---- report_employee: experience (G7) ----
    re_meta = {}
    for r in reader('report_employee'):
        if r['report_id'] in rid_year:
            re_meta[r['report_employee_id']] = (rid_year[r['report_id']], r['experience_years'])
    re_ids = set(re_meta)

    # ---- salary (G1/G2) ----
    sal = {}
    for r in reader('private_report_employee'):
        if r['report_employee_id'] in re_ids:
            v = r['total_final_salary']; sal[r['report_employee_id']] = float(v) if v is not None else None

    # ---- assignments: one streaming pass builds everything assignment-grain ----
    emp_fte = defaultdict(float)
    major = {}                                   # re_id -> (duty, school)
    fte_by_yr_duty = defaultdict(float)          # (year, duty) district aggregate
    fte_all = defaultdict(float)                 # (year, school, duty)
    fte_basic = defaultdict(float)               # program == 1
    fte_speced = defaultdict(float)              # program in 21-29
    for a in reader('assignment'):
        yr = rid_year.get(a['report_id'])
        if yr is None: continue
        d = a['duty_root_code']; sc = a['school_code']; f = float(a['fte_in_assignment'] or 0)
        if a['report_employee_id'] in re_ids:
            emp_fte[a['report_employee_id']] += f
            if a['is_major']: major[a['report_employee_id']] = (d, sc)
        if f <= 0: continue
        fte_by_yr_duty[(yr, d)] += f
        fte_all[(yr, sc, d)] += f
        if a['program_code'] == C.BASIC_PROGRAM: fte_basic[(yr, sc, d)] += f
        if a['program_code'] in C.SPECED_PROGRAMS: fte_speced[(yr, sc, d)] += f

    # ---- per-person-year records (classified by major assignment) ----
    emp = []
    for re_id, (yr, exp) in re_meta.items():
        if re_id not in major: continue
        d, sc = major[re_id]
        emp.append({'year': yr, 'major_duty': d, 'major_school': sc,
                    'is_do': sc in do_codes, 'salary': sal.get(re_id),
                    'emp_fte': emp_fte.get(re_id, 0.0), 'experience': exp})

    # ---- enrollment: per-school All Grades (incl PK) + district totals (G13) ----
    enr_all, swd, nonswd = {}, {}, {}
    enr_district = defaultdict(int)
    for r in csv.DictReader(open(C.ENROLL_CSV)):
        if r['grade'] != 'All Grades':
            continue
        y = r['school_year'][:4] + '-20' + r['school_year'][5:7]     # 2014-15 -> 2014-2015
        try:
            alls = int(r['all_students'])
        except (ValueError, TypeError):
            continue
        if r['school_name'] == 'District Total' and not r['school_code']:
            enr_district[y] += alls
        elif r['school_code']:
            sc = int(float(r['school_code']))
            enr_all[(y, sc)] = alls
            try:
                sd = int(r['students_with_disabilities']); swd[(y, sc)] = sd; nonswd[(y, sc)] = alls - sd
            except (ValueError, TypeError):
                pass

    years_enr = sorted(y for y in years_s275 if any((y, sc) in enr_all for sc in sch))

    cache = dict(
        years_s275=years_s275, years_enr=years_enr, rid_year=rid_year,
        sch=sch, areas=areas, do_codes=do_codes,
        duty_name=duty_name, duty_cat=duty_cat,
        emp=emp, fte_by_yr_duty=dict(fte_by_yr_duty),
        fte_all=dict(fte_all), fte_basic=dict(fte_basic), fte_speced=dict(fte_speced),
        enr_all=enr_all, swd=swd, nonswd=nonswd, enr_district=dict(enr_district),
    )
    with open(C.CACHE, 'wb') as fh:
        pickle.dump(cache, fh)
    print(f'cache -> {C.CACHE}')
    print(f'  years_s275={len(years_s275)} years_enr={len(years_enr)} emp_records={len(emp)} '
          f'schools={len(sch)} areas={len(areas)} district_office_codes={len(do_codes)}')


if __name__ == '__main__':
    main()
