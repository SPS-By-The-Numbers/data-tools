"""Teacher experience plots:
  1. seattle_school_experience_scatter.jpg — per-school distribution of individual teacher experience,
     faceted by attendance area (dots in per-year bands oldest->newest, black school-mean line,
     facets ordered by most-recent-year mean experience).  Aides omitted (experience_years is
     certificated-only, G7).
  2. seattle_teacher_salary_experience.png — salary schedule: median per-1.0-FTE salary vs experience,
     one plasma curve per year.
"""
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from collections import defaultdict
import statistics as st
import os
import common as C


def teacher_records(cache):
    """Teacher person-years with experience: (year, school, exp, salary, emp_fte)."""
    out = []
    for r in cache['emp']:
        if r['major_duty'] not in C.TEACHER_DUTIES or r['experience'] is None:
            continue
        out.append((r['year'], r['major_school'], float(r['experience']), r['salary'], r['emp_fte']))
    return out


def scatter_by_school(cache):
    sch, areas = cache['sch'], cache['areas']
    years = cache['years_s275']; yidx = {y: i for i, y in enumerate(years)}
    ypos = np.linspace(-0.34, 0.34, len(years)); jit = 0.40 * (ypos[1] - ypos[0])
    cmap = plt.get_cmap(C.PLASMA); rng = np.random.default_rng(11)
    latest_i = len(years) - 1

    byschool = defaultdict(list)
    for yr, sc, exp, sal, fte in teacher_records(cache):
        byschool[sc].append((exp, yidx[yr]))

    def recent(ms):
        e = [exp for sc in areas[ms] for exp, yi in byschool.get(sc, []) if yi == latest_i]
        return float(np.mean(e)) if e else None
    order = sorted(areas, key=lambda ms: (recent(ms) if recent(ms) is not None else -1), reverse=True)

    fig, axes = plt.subplots(4, 3, figsize=(26, 21)); axes = axes.flatten()
    fig.subplots_adjust(top=0.895, bottom=0.05, left=0.04, right=0.99, hspace=0.6, wspace=0.13)
    for ai, ms in enumerate(order):
        ax = axes[ai]
        scs = sorted(areas[ms], key=lambda c: (0 if c == ms else 1, C.short(sch[c]['name'])))
        labels = []
        for xi, sc in enumerate(scs):
            labels.append(C.short(sch[sc]['name']))
            pts = byschool.get(sc, [])
            if not pts: continue
            exps = np.array([p[0] for p in pts]); yi = np.array([p[1] for p in pts])
            xs = xi + ypos[yi] + rng.uniform(-jit, jit, len(pts))
            ax.scatter(xs, exps, c=yi, cmap=cmap, vmin=0, vmax=len(years) - 1,
                       s=10, alpha=0.55, edgecolors='none', zorder=3)
            ax.hlines(exps.mean(), xi - 0.36, xi + 0.36, color='#111111', lw=2.2, zorder=5)
        for xi in range(len(scs) - 1):
            ax.axvline(xi + 0.5, color='#dddddd', lw=0.6, zorder=0)
        ax.set_ylim(0, 40); ax.set_xticks(range(len(scs)))
        ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        rv = recent(ms)
        ax.set_title((f'{C.short(sch[ms]["name"])} attendance area  (’24-25: {rv:.1f} yrs)' if rv is not None
                      else f'{C.short(sch[ms]["name"])} attendance area'), fontsize=11, fontweight='bold')
        ax.grid(axis='y', color='#eeeeee', lw=0.6); ax.set_ylabel('years experience', fontsize=9)
    for j in range(len(order), len(axes)):
        axes[j].axis('off')

    fig.suptitle('Seattle Public Schools — teacher experience distribution by school, faceted by middle-school attendance area',
                 fontsize=17, fontweight='bold', y=0.975)
    fig.text(0.5, 0.955, 'Black line = school mean; dots = individual teacher-years in per-year bands (oldest left → '
             'newest right), colored by year (plasma). Facets ordered by 2024-25 mean experience (high → low).',
             ha='center', fontsize=11, color='#444')
    fig.legend(handles=[Line2D([0], [0], color='#111111', lw=2.2, label='School mean')],
               loc='center', bbox_to_anchor=(0.27, 0.928), fontsize=11, frameon=False)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, len(years) - 1)); sm.set_array([])
    cax = fig.add_axes([0.60, 0.923, 0.30, 0.011]); cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
    cb.set_ticks([0, len(years) - 1]); cb.set_ticklabels([years[0], years[-1]])
    cb.set_label('school year (dot band: left→right)', fontsize=10)
    fig.savefig(os.path.join(C.REPO, 'seattle_school_experience_scatter.jpg'), dpi=200, pil_kwargs={'quality': 85})
    plt.close(fig); print('wrote seattle_school_experience_scatter.jpg; teacher points:', sum(len(v) for v in byschool.values()))


def salary_curve(cache):
    years = cache['years_s275']; yidx = {y: i for i, y in enumerate(years)}
    cmap = plt.get_cmap(C.PLASMA); rng = np.random.default_rng(3); EXPMAX = 35
    curve = defaultdict(lambda: defaultdict(list)); scatter = []
    for yr, sc, exp, sal, fte in teacher_records(cache):
        if sal is None or fte < 0.5: continue
        b = int(round(exp))
        if b > EXPMAX: continue
        pf = sal / fte; curve[yr][b].append(pf); scatter.append((b, pf, yidx[yr]))

    fig, ax = plt.subplots(figsize=(13, 8))
    sc = np.array(scatter)
    idx = rng.choice(len(sc), size=min(7000, len(sc)), replace=False)
    ax.scatter(sc[idx, 0] + rng.uniform(-0.25, 0.25, len(idx)), sc[idx, 1],
               c=sc[idx, 2], cmap=cmap, vmin=0, vmax=len(years) - 1, s=7, alpha=0.10, edgecolors='none')
    for yr in years:
        xs = [b for b in sorted(curve[yr]) if len(curve[yr][b]) >= 8]
        ys = [st.median(curve[yr][b]) for b in xs]
        if xs: ax.plot(xs, ys, color=cmap(yidx[yr] / (len(years) - 1)), lw=2.2, alpha=0.95)
    ax.set_xlim(-0.5, EXPMAX + 0.5); ax.set_ylim(40000, 150000)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'${v/1000:.0f}k'))
    ax.set_xlabel('Years of experience', fontsize=12)
    ax.set_ylabel('Salary per 1.0 FTE (total_final_salary ÷ FTE)', fontsize=12)
    ax.grid(color='#eeeeee', lw=0.6)
    ax.set_title('Seattle teacher salary schedule by experience (duties 31-34, ≥0.5 FTE)\n'
                 'one median curve per year; faint dots are individuals; plasma: dark 2013-14 → bright 2024-25',
                 fontsize=13.5, fontweight='bold')
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, len(years) - 1)); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.01); cb.set_ticks([0, len(years) - 1])
    cb.set_ticklabels([years[0], years[-1]]); cb.set_label('school year', fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(C.REPO, 'seattle_teacher_salary_experience.png'), dpi=120)
    plt.close(fig); print('wrote seattle_teacher_salary_experience.png')


def main():
    cache = C.load()
    scatter_by_school(cache)
    salary_curve(cache)


if __name__ == '__main__':
    main()
