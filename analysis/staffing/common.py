"""Shared constants, paths, and plotting helpers for the teaching-staffing analysis.

See ../../STAFFING_ANALYSIS_GUIDE.md for data locations, joins, and gotchas.
Run order:  extract.py  ->  plot_*.py  ->  gen_report.py   (or just ./run_all.sh)
"""
import os, re, pickle

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
BUILD = os.path.join(HERE, 'build')
CACHE = os.path.join(BUILD, 'staffing.pkl')

# inputs
SAFS    = os.path.join(REPO, 'safs_prod')
S275    = os.path.join(SAFS, 's275')
DOMAINS = os.path.join(SAFS, 'domains')
ENROLL_CSV = os.path.join(REPO, 'data', 'enrollment', 'rc_enrollment_17001.csv')
SPSBTN_XLSX = os.path.join(REPO, 'data', 'safs', 'spsbtn', '9998-9999-spsbtn.xlsx')

# domain constants (see guide §4/§5)
SEATTLE = '17001'
TEACHER_DUTIES = [31, 32, 33, 34]          # classroom teachers (G3)
AIDE = 91                                   # classified paraeducators
RATIO_DUTIES = [31, 32, 33, 34, 91, 94, 42, 44]
LEVEL = {31: {'Elementary'}, 34: {'Elementary'}, 32: {'Middle', 'High'}}  # off-level restriction (G12)
BASIC_PROGRAM = 1                           # Basic Education / Regular Instruction (G11)
SPECED_PROGRAMS = {21, 22, 23, 24, 25, 26, 29}   # Special Education (G11)
MINFTE = 0.5                                # below half-time the per-FTE ratio is noise (G12)

# shared plot style
PLASMA = 'plasma'


def load():
    with open(CACHE, 'rb') as fh:
        return pickle.load(fh)


def short(name):
    """Abbreviate a school name for axis labels."""
    n = re.sub(r'\s*-\s*Seattle$', '', name or '')
    n = re.sub(r'\s+(Elementary School|Middle School|High School|International Middle School|Elementary|School)$', '', n)
    return n.strip()


def build_areas(sch):
    """sch dict -> {ms_assignment_code: [school_code,...]} for regular schools."""
    areas = {}
    for sc, m in sch.items():
        if m['type'] not in ('Elementary', 'Middle', 'High') or m['ms'] is None:
            continue
        areas.setdefault(m['ms'], []).append(sc)
    return areas


def facet_scatter(C, valfn, title, sub, outfile, ylabel='students : FTE', types=None, dpi=110):
    """Generic 12-facet (by attendance area) per-year-band scatter used by the ratio plots.

    valfn(year, school_code) -> float or None  (the y value for a school in a year).
    Facets = attendance areas; x = schools; dots = one per year arranged oldest->newest
    left-to-right, plasma-colored by year; black line = school mean; linear y capped ~p98;
    facets ordered by the most-recent-year value (high->low).  types restricts school level.
    """
    import numpy as np
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    sch, areas = C['sch'], C['areas']
    years = C['years_enr']
    yidx = {y: i for i, y in enumerate(years)}
    ypos = np.linspace(-0.34, 0.34, len(years))
    cmap = plt.get_cmap(PLASMA)
    rng = np.random.default_rng(7)
    latest = years[-1]

    def aschools(ms):
        return [c for c in areas[ms] if (types is None or sch[c]['type'] in types)]

    allv = [valfn(y, sc) for ms in areas for sc in aschools(ms) for y in years]
    allv = [v for v in allv if v is not None]
    if not allv:
        print('no data for', outfile); return
    ytop = float(np.ceil(np.percentile(allv, 98) / 10) * 10)
    clipped = sum(1 for v in allv if v > ytop)

    def recent(ms):
        vs = [valfn(latest, sc) for sc in aschools(ms)]; vs = [v for v in vs if v is not None]
        return float(np.mean(vs)) if vs else None

    def hasd(ms):
        return any(valfn(y, sc) is not None for sc in aschools(ms) for y in years)

    order = sorted([ms for ms in areas if hasd(ms)],
                   key=lambda ms: (recent(ms) if recent(ms) is not None else -1), reverse=True)

    fig, axes = plt.subplots(4, 3, figsize=(26, 21)); axes = axes.flatten()
    fig.subplots_adjust(top=0.9, bottom=0.05, left=0.04, right=0.99, hspace=0.6, wspace=0.13)
    for ai, ms in enumerate(order):
        ax = axes[ai]
        scs = sorted(aschools(ms), key=lambda c: (0 if c == ms else 1, short(sch[c]['name'])))
        labels = []
        for xi, sc in enumerate(scs):
            labels.append(short(sch[sc]['name']))
            xs = []; ys = []; cs = []
            for y in years:
                r = valfn(y, sc)
                if r is None: continue
                xs.append(xi + ypos[yidx[y]] + rng.uniform(-0.02, 0.02)); ys.append(r); cs.append(yidx[y])
            if xs:
                ax.scatter(xs, ys, c=cs, cmap=cmap, vmin=0, vmax=len(years) - 1,
                           s=30, alpha=0.9, edgecolors='none', zorder=3)
                ax.hlines(np.mean(ys), xi - 0.36, xi + 0.36, color='#111111', lw=2.0, zorder=5)
        for xi in range(len(scs) - 1):
            ax.axvline(xi + 0.5, color='#dddddd', lw=0.6, zorder=0)
        ax.set_ylim(0, ytop); ax.set_xlim(-0.6, len(scs) - 0.4)
        ax.set_xticks(range(len(scs))); ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
        rv = recent(ms)
        ax.set_title(f'{short(sch[ms]["name"])} area  (’24-25: {rv:.0f})' if rv is not None
                     else f'{short(sch[ms]["name"])} area', fontsize=11, fontweight='bold')
        ax.grid(axis='y', color='#eeeeee', lw=0.6); ax.set_ylabel(ylabel, fontsize=9)
    for j in range(len(order), len(axes)):
        axes[j].axis('off')

    fig.suptitle(title, fontsize=17, fontweight='bold', y=0.972)
    fig.text(0.5, 0.952, sub + f'  Linear y capped at {ytop:.0f} ({clipped} outlier dots above not shown). '
             'Dots = one per year in per-year bands (oldest left → newest right), plasma-colored by year; '
             'black line = school mean. Facets ordered by 2024-25 value, high → low.',
             ha='center', fontsize=10.5, color='#444')
    fig.legend(handles=[Line2D([0], [0], color='#111111', lw=2.0, label='School mean')],
               loc='center', bbox_to_anchor=(0.20, 0.928), fontsize=11, frameon=False)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, len(years) - 1)); sm.set_array([])
    cax = fig.add_axes([0.62, 0.924, 0.28, 0.011]); cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
    cb.set_ticks([0, len(years) - 1]); cb.set_ticklabels([years[0], years[-1]])
    cb.set_label('school year (dot band L→R)', fontsize=10)
    path = os.path.join(REPO, outfile)
    fig.savefig(path, dpi=dpi, pil_kwargs={'quality': 85} if outfile.endswith(('.jpg', '.jpeg')) else None)
    plt.close(fig)
    print('wrote', outfile, 'ytop=', ytop, 'clipped=', clipped)
