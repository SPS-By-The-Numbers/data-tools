"""Build the self-contained HTML report (seattle_s275_salary_by_duty.html) from the cache and the
figures produced by the plot_* scripts. Salary/FTE tables are recomputed from the per-person-year
records; figures are base64-embedded.  Run the plot_* scripts first.
"""
import os, html, base64, statistics as st
from collections import defaultdict
import common as C

COMBO = 3134  # synthetic "Elementary teachers (31+34)" pooled at the employee level (G4)


def compute(cache):
    years = cache['years_s275']
    emp = cache['emp']; fbyd = cache['fte_by_yr_duty']
    name = dict(cache['duty_name']); cat = dict(cache['duty_cat'])
    name[COMBO] = 'Elementary teachers (31+34, combined)'; cat[COMBO] = 'teacher'

    by = defaultdict(list)           # (year, duty) -> emp records
    for r in emp:
        by[(r['year'], r['major_duty'])].append(r)

    def stats(members):
        members = [m for m in members if m['salary'] is not None]
        n = len(members); sals = [m['salary'] for m in members]
        tot_sal = sum(sals); tot_fte = sum(m['emp_fte'] for m in members)
        return dict(n=n, avg=tot_sal / n if n else None, med=st.median(sals) if n else None,
                    per_fte=tot_sal / tot_fte if tot_fte else None)

    allduties = sorted({d for (_, d) in by}, key=lambda d: (cat.get(d, 'zz'), d))
    S, ND = {}, {}
    for yr in years:
        for d in allduties:
            s = stats(by.get((yr, d), [])); s['tot_fte'] = fbyd.get((yr, d), 0.0); S[(yr, d)] = s
            nd = stats([m for m in by.get((yr, d), []) if not m['is_do']]); ND[(yr, d)] = nd
        cm = stats(by.get((yr, 31), []) + by.get((yr, 34), []))
        cm['tot_fte'] = fbyd.get((yr, 31), 0.0) + fbyd.get((yr, 34), 0.0); S[(yr, COMBO)] = cm
    return years, S, ND, allduties, name, cat


CSS = """
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a2330;margin:0;background:#f6f8fb}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 6px;border-bottom:2px solid #2b4a6f;padding-bottom:4px;color:#1f3a5c}
h3{font-size:15.5px;margin:26px 0 2px;color:#1f3a5c}
.sub{color:#5a6b80;margin:0 0 8px;font-size:12.5px;max-width:760px}
.lead{color:#33414f;max-width:820px}
.meta{color:#6a7888;font-size:12.5px}
.scroll{overflow-x:auto;border:1px solid #d8e0ea;border-radius:8px;background:#fff}
table.mat{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
.mat th,.mat td{padding:5px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid #eef2f7}
.mat thead th{position:sticky;top:0;background:#2b4a6f;color:#fff;font-weight:600;font-size:12px}
.mat th.role{text-align:left;position:sticky;left:0;z-index:2}
.mat td.role{text-align:left;position:sticky;left:0;background:#fff;font-weight:500;box-shadow:1px 0 0 #e3e9f1}
.dc{display:inline-block;min-width:22px;color:#8294aa;font-size:11px;font-weight:700}
.catrow td{background:#eef2f7;color:#54657a;font-weight:700;font-size:11px;letter-spacing:.05em;text-align:left;position:sticky;left:0}
hr{border:none;border-top:1px solid #d8e0ea;margin:30px 0}
code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12.5px}
.note{background:#fff;border:1px solid #d8e0ea;border-left:4px solid #c9a227;border-radius:6px;padding:10px 14px;margin:14px 0;font-size:13px}
.fig{width:100%;height:auto;border:1px solid #d8e0ea;border-radius:8px;background:#fff;margin:6px 0 4px}
"""


def main():
    cache = C.load()
    years, S, ND, allduties, name, cat = compute(cache)
    teacher_aide = [COMBO, 31, 34, 32, 33, 52, 91]

    def money(v): return f"${v:,.0f}" if v is not None else "—"
    def num(v, p=0): return f"{v:,.{p}f}" if v is not None else "—"

    def matrix(src, duties, metric, fmt, title, sub, heat=True, group=None):
        if group is None:
            group = len(duties) > 10
        rows = [(d, [src[(y, d)][metric] for y in years]) for d in duties]
        o = [f'<h3>{html.escape(title)}</h3><p class="sub">{html.escape(sub)}</p>',
             '<div class="scroll"><table class="mat"><thead><tr><th class="role">Duty / Role</th>']
        for y in years: o.append(f'<th>{y[2:4]}–{y[7:9]}</th>')
        o.append('</tr></thead><tbody>')
        lastcat = None
        for d, rv in rows:
            if group and cat.get(d) != lastcat:
                lastcat = cat.get(d)
                o.append(f'<tr class="catrow"><td colspan="{len(years)+1}">{html.escape(str(lastcat)).upper()}</td></tr>')
            vals = [v for v in rv if v is not None]
            lo, hi = (min(vals), max(vals)) if vals else (0, 1)
            o.append(f'<tr><td class="role"><span class="dc">{d}</span> {html.escape(name[d])}</td>')
            for v in rv:
                style = ''
                if heat and v is not None and hi > lo:
                    t = (v - lo) / (hi - lo)
                    style = f' style="background:rgb({int(232-t*120)},{int(238-t*70)},{int(246-t*30)})"'
                o.append(f'<td{style}>{fmt(v)}</td>')
            o.append('</tr>')
        o.append('</tbody></table></div>')
        return '\n'.join(o)

    # enrollment + ratios
    enr_d = cache['enr_district']; fbyd = cache['fte_by_yr_duty']
    ryears = [y for y in years if y in enr_d]

    def fte(y, duties): return sum(fbyd.get((y, d), 0.0) for d in duties)

    def ratio_table():
        o = ['<h3>Enrollment &amp; student-to-staff ratios</h3>'
             '<p class="sub">District enrollment (All Grades, incl. PK) ÷ S-275 FTE. '
             'Teacher = duties 31/32/33/34; Aide = 91; All-staff = every duty.</p>',
             '<div class="scroll"><table class="mat"><thead><tr><th class="role">Measure</th>']
        for y in ryears: o.append(f'<th>{y[2:4]}–{y[7:9]}</th>')
        o.append('</tr></thead><tbody>')

        def row(label, vals, fmt, heat=True, bold=False):
            vv = [v for v in vals if v is not None]
            lo, hi = (min(vv), max(vv)) if vv else (0, 1)
            o.append(f'<tr><td class="role"{" style=\"font-weight:700\"" if bold else ""}>{label}</td>')
            for v in vals:
                style = ''
                if heat and v is not None and hi > lo:
                    t = (v - lo) / (hi - lo)
                    style = f' style="background:rgb({int(232-t*120)},{int(238-t*70)},{int(246-t*30)})"'
                o.append(f'<td{style}>{fmt(v)}</td>')
            o.append('</tr>')
        En = [enr_d[y] for y in ryears]
        T = [fte(y, [31, 32, 33, 34]) for y in ryears]; A = [fte(y, [91]) for y in ryears]
        Tot = [fte(y, allduties) for y in ryears]
        row('Enrollment (students)', En, lambda v: num(v), heat=False, bold=True)
        o.append(f'<tr class="catrow"><td colspan="{len(ryears)+1}">STAFFING (FTE)</td></tr>')
        row('Teacher FTE (31–34)', T, lambda v: num(v)); row('Aide FTE (91)', A, lambda v: num(v))
        row('All-staff FTE', Tot, lambda v: num(v))
        o.append(f'<tr class="catrow"><td colspan="{len(ryears)+1}">RATIOS</td></tr>')
        row('Students : Teacher FTE', [e/t for e, t in zip(En, T)], lambda v: f'{v:.1f}', bold=True)
        row('Students : Aide FTE', [e/a for e, a in zip(En, A)], lambda v: f'{v:.1f}', bold=True)
        row('Students : All-staff FTE', [e/x for e, x in zip(En, Tot)], lambda v: f'{v:.1f}')
        row('Teacher FTE : Aide FTE', [t/a for t, a in zip(T, A)], lambda v: f'{v:.2f}')
        o.append('</tbody></table></div>')
        return '\n'.join(o)

    def img(fn):
        path = os.path.join(C.REPO, fn)
        mime = 'image/jpeg' if fn.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
        return f'<img class="fig" src="data:{mime};base64,{base64.b64encode(open(path,"rb").read()).decode()}" alt="{fn}">'

    P = []
    P.append('<div class="note" style="border-left-color:#2b7a4b"><b>Reclassification note:</b> in <b>2015-16</b> '
             'Seattle introduced the <i>Elementary Specialist Teacher</i> (34) code; ~79% of the first specialists were '
             'Elementary Homeroom (31) the prior year. The top <b>Elementary teachers (31+34, combined)</b> row pools both '
             'at the employee level so the split does not distort the trend.</div>')
    P.append(matrix(S, teacher_aide, 'avg', money, 'Teachers & Aides — Average total_final_salary',
                    'Mean reported total_final_salary by major-assignment duty. Not FTE-normalized.'))
    P.append(matrix(S, teacher_aide, 'per_fte', money, 'Teachers & Aides — Salary normalized to 1.0 FTE',
                    'Sum of total_final_salary ÷ sum of employee FTE. Comparable across roles.'))
    P.append(matrix(S, teacher_aide, 'med', money, 'Teachers & Aides — Median total_final_salary',
                    'Median reported salary; not FTE-normalized.'))
    P.append(matrix(S, teacher_aide, 'n', lambda v: num(v), 'Teachers & Aides — Headcount',
                    'Employees whose major assignment is this duty.'))
    P.append(matrix(S, teacher_aide, 'tot_fte', lambda v: num(v, 1), 'Teachers & Aides — Total FTE allocation',
                    'Sum of fte_in_assignment over ALL assignments of this duty.'))

    P.append('<hr><h2>Enrollment &amp; staffing ratios</h2>')
    P.append('<p class="lead">Enrollment fell ~9% off its 2019-20 peak (56,051) to ~51,200. The student : teacher ratio '
             'held ~17:1, but the student : aide ratio fell 78→51 as aide FTE grew while enrollment shrank.</p>')
    P.append(ratio_table())

    P.append('<hr><h2>Excluding District-Office staff (school-based employees only)</h2>')
    P.append('<p class="lead">Employees whose major assignment is at a District-Office location '
             '(<code>d_school.is_district_office</code>) are removed, leaving school-based staff.</p>')
    P.append(matrix(ND, allduties, 'avg', money, 'Non-District-Office — Average total_final_salary by duty',
                    'Mean salary, employees whose major assignment is NOT at a district-office location.', group=True))
    P.append(matrix(ND, allduties, 'n', lambda v: num(v), 'Non-District-Office — Headcount by duty',
                    'School-based employees per duty.', group=True))

    P.append('<hr><h2>All duty types</h2>')
    P.append(matrix(S, allduties, 'per_fte', money, 'All duties — Salary normalized to 1.0 FTE',
                    'Every S-275 duty present for Seattle, grouped by category.', group=True))
    P.append(matrix(S, allduties, 'n', lambda v: num(v), 'All duties — Headcount', 'Employees by major-assignment duty.', group=True))
    P.append(matrix(S, allduties, 'tot_fte', lambda v: num(v, 1), 'All duties — Total FTE allocation', 'Assignment FTE by duty.', group=True))

    P.append('<hr><h2>By-school student : staff-FTE ratios — one graph per duty</h2>')
    P.append('<p class="lead">Per-school ratios join enrollment to S-275 assignment FTE, faceted by middle-school '
             'attendance area. One graph per duty title (no duty types combined); linear y capped near the 98th '
             'percentile; per-year dot bands oldest→newest; black school-mean line; facets ordered by 2024-25 value. '
             'A point needs ≥0.5 FTE; Elementary Homeroom/Specialist shown at elementary schools only, Secondary at '
             'middle/high only.</p>')
    for d in [31, 34, 32, 33, 91, 94, 42, 44]:
        P.append(f'<h3>{html.escape(name[d])} ({d})</h3>' + img(f'seattle_ratio_duty_{d}.jpg'))

    P.append('<hr><h2>Teacher ratios — Basic Education program only</h2>')
    P.append('<p class="lead">Same ratios counting only Basic-Education FTE (<code>program_code = 1</code>), which '
             'drops ~30% of teacher FTE (special ed, bilingual, LAP, …), so ratios run higher.</p>')
    for d in [31, 34, 32, 33]:
        P.append(f'<h3>{html.escape(name[d])} ({d}) — Basic Education only</h3>' + img(f'seattle_ratio_basiced_{d}.jpg'))

    P.append('<hr><h2>Program-matched ratios — pairing teachers to the students they serve</h2>')
    P.append('<p class="lead">Teacher FTE summed across duties 31-34 (special-ed teachers are ~92% duty 33). '
             'Special-ed students = <code>students_with_disabilities</code>; non-sped = <code>all_students − SWD</code>.</p>')
    P.append('<h3>Non-SpecEd students : Basic-Education teacher FTE</h3>' + img('seattle_ratio_basiced_teacher_nonsped.jpg'))
    P.append('<h3>SpecEd students : Special-Education teacher FTE (caseload)</h3>'
             '<p class="sub">Special-ed students per special-ed teacher FTE. Middle schools run higher than elementaries.</p>'
             + img('seattle_ratio_sped_teacher_sped.jpg'))

    P.append('<hr><h2>Teacher salary by experience</h2>')
    P.append('<p class="lead">Salary schedule: median per-1.0-FTE salary by experience, one curve per year. '
             'A 10-year teacher went $73k→$118k (+61%); a starting teacher $55k→$84k.</p>')
    P.append(img('seattle_teacher_salary_experience.png'))
    P.append('<h3>Teacher experience distribution by school, faceted by attendance area</h3>')
    P.append('<p class="sub">Every individual teacher (31-34) as a per-year band; black line = school mean; facets ordered '
             'by 2024-25 mean experience. Aides omitted (experience_years is certificated-only).</p>')
    P.append(img('seattle_school_experience_scatter.jpg'))

    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>Seattle S-275 Staffing &amp; Salary by Duty</title><style>{CSS}</style></head><body><div class="wrap">'
           f'<h1>Seattle Public Schools — S-275 Staffing &amp; Salary by Duty</h1>'
           f'<p class="meta">District ccddd <b>17001</b> · {years[0]} → {years[-1]} · source <code>safs_prod/s275</code>, '
           f'<code>data/enrollment</code>, <code>spsbtn</code> · built by <code>analysis/staffing</code></p>'
           f'{"".join(P)}</div></body></html>')
    out = os.path.join(C.REPO, 'seattle_s275_salary_by_duty.html')
    open(out, 'w').write(doc)
    print('wrote', out, f'({len(doc)/1e6:.1f} MB,', doc.count('class="fig"'), 'figures)')


if __name__ == '__main__':
    main()
