#!/usr/bin/env python3
"""Wide interactive HTML of every SPS S-275 salary (one vertical bar per employee).

~14,500px-wide scrolling SVG with a sticky $-axis, a draggable district minimap,
per-bar hover, and a grouped stats table. Bands come from salary_bands.py.

  python3 tools/salary_skyline/build_salary_skyline.py             # from repo root
  python3 tools/salary_skyline/build_salary_skyline.py \
      --data out_salary_skyline/staff.csv -o out_salary_skyline/wide.html

Input CSV columns: cat,duty,duty_name,salary,fte (see query.sql). Only `duty`,
`duty_name`, `salary` and `fte` are read; `cat` is legacy and ignored.
"""
import argparse, csv, json, statistics as st
from collections import defaultdict, Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--data", default="out_salary_skyline/staff.csv",
                help="per-employee CSV from query.sql")
ap.add_argument("-o", "--out", default="out_salary_skyline/salary_skyline.html")
args = ap.parse_args()

SRC, OUT = Path(args.data), Path(args.out)
OUT.parent.mkdir(parents=True, exist_ok=True)

from salary_bands import BANDS, GROUPS, COLORS, band_of, bands_of_group
CATS = [(i, label, fam, codes) for i, (label, fam, codes, _) in enumerate(BANDS)]

# --- load --------------------------------------------------------------------
rows = list(csv.DictReader(SRC.open()))
by_cat = defaultdict(list)
for r in rows:
    by_cat[band_of(int(r["duty"]))].append(
        (round(float(r["salary"])), r["duty_name"], round(float(r["fte"]) * 100), int(r["duty"]))
    )
for c in by_cat:
    by_cat[c].sort(key=lambda t: -t[0])

duty_names = {}
for r in rows:
    duty_names[int(r["duty"])] = r["duty_name"]
duty_list = sorted(duty_names)
duty_idx = {d: i for i, d in enumerate(duty_list)}

cat_payload, table_rows = [], []
all_sal = sorted((round(float(r["salary"])) for r in rows))
for cid, label, fam, codes in CATS:
    items = by_cat[cid]
    sal = [t[0] for t in items]
    cat_payload.append({
        "id": cid, "label": label, "fam": fam, "codes": codes,
        "s": sal,
        "d": [duty_idx[t[3]] for t in items],
        "f": [t[2] for t in items],
    })
    table_rows.append({
        "label": label, "fam": fam, "codes": codes, "n": len(sal),
        "min": sal[-1], "p25": sal[int(0.75 * (len(sal) - 1))],
        "med": round(st.median(sal)), "p75": sal[int(0.25 * (len(sal) - 1))],
        "max": sal[0], "total": sum(sal),
        "fte": round(sum(float(r["fte"]) for r in rows if band_of(int(r["duty"])) == cid), 1),
    })

# --- geometry ----------------------------------------------------------------
PITCH, BARW, CATGAP = 2.0, 1.4, 16
PAD_L, PAD_R, PLOT_H, HEAD_H, FOOT_H = 76, 300, 640, 100, 40
N = len(rows)
plot_w = N * PITCH + (len(CATS) - 1) * CATGAP
svg_w = PAD_L + plot_w + PAD_R
svg_h = HEAD_H + PLOT_H + FOOT_H
Y_MAX = 375000

starts, x = [], PAD_L
for c in cat_payload:
    starts.append(x)
    x += len(c["s"]) * PITCH + CATGAP

# --- minimap (max-salary skyline, 720 buckets) -------------------------------
MM_W, MM_H = 720, 44
flat_sal, flat_fam = [], []
for c in cat_payload:
    flat_sal += c["s"]
    flat_fam += [c["fam"]] * len(c["s"])
mm = []
for i in range(MM_W):
    lo, hi = i * N // MM_W, max(i * N // MM_W + 1, (i + 1) * N // MM_W)
    seg = flat_sal[lo:hi]
    mm.append([max(seg), Counter(flat_fam[lo:hi]).most_common(1)[0][0]])

groups = []
for gk, glabel, gshort in GROUPS:
    idxs = [i for i, _, _ in bands_of_group(gk)]
    gsal = [v for i in idxs for v in cat_payload[i]["s"]]
    groups.append({
        "key": gk, "label": glabel, "short": gshort,
        "x0": starts[idxs[0]],
        "x1": starts[idxs[-1]] + len(cat_payload[idxs[-1]]["s"]) * PITCH,
        "n": len(gsal), "total": sum(gsal),
    })

DATA = {
    "groups": groups,
    "cats": cat_payload, "starts": starts, "duties": [duty_names[d] for d in duty_list],
    "pitch": PITCH, "barw": BARW, "padL": PAD_L, "plotH": PLOT_H, "headH": HEAD_H,
    "svgW": svg_w, "svgH": svg_h, "grandTotal": sum(all_sal), "yMax": Y_MAX, "n": N, "mm": mm, "mmW": MM_W, "mmH": MM_H,
}

TOTALS = {
    "n": N,
    "total": sum(all_sal),
    "median": round(st.median(all_sal)),
    "mean": round(sum(all_sal) / N),
    "fte": round(sum(float(r["fte"]) for r in rows), 1),
    "p10": all_sal[int(0.10 * (N - 1))],
    "p90": all_sal[int(0.90 * (N - 1))],
    "max": all_sal[-1],
    "min": all_sal[0],
}

FAM_JSON = json.dumps({k: {"name": n, "short": sh} for k, n, sh in GROUPS})

def money(v, dec=0):
    return "$" + format(round(v), ",")

trs = []
for gk, glabel, gshort in GROUPS:
    idxs = [i for i, _, _ in bands_of_group(gk)]
    gs = sorted(v for i in idxs for v in cat_payload[i]["s"])
    gfte = sum(table_rows[i]["fte"] for i in idxs)
    trs.append(
        f'<tr class="grp"><td class="tl"><span class="sw sw-{gk}"></span><b>{glabel}</b></td>'
        f'<td class="mono dim">&mdash;</td><td class="mono">{len(gs):,}</td>'
        f'<td class="mono">{gfte:,.1f}</td>'
        f'<td class="mono">{money(gs[0])}</td><td class="mono">{money(gs[int(0.25*(len(gs)-1))])}</td>'
        f'<td class="mono strong">{money(st.median(gs))}</td>'
        f'<td class="mono">{money(gs[int(0.75*(len(gs)-1))])}</td>'
        f'<td class="mono">{money(gs[-1])}</td>'
        f'<td class="mono">${sum(gs)/1e6:,.1f}M</td></tr>'
    )
    for i in idxs:
        t = table_rows[i]
        trs.append(
            f'<tr><td class="tl sub">{t["label"]}</td>'
            f'<td class="mono dim">{t["codes"]}</td><td class="mono">{t["n"]:,}</td>'
            f'<td class="mono">{t["fte"]:,.1f}</td>'
            f'<td class="mono">{money(t["min"])}</td><td class="mono">{money(t["p25"])}</td>'
            f'<td class="mono strong">{money(t["med"])}</td><td class="mono">{money(t["p75"])}</td>'
            f'<td class="mono">{money(t["max"])}</td>'
            f'<td class="mono">${t["total"]/1e6:,.1f}M</td></tr>'
        )
TABLE_BODY = "\n".join(trs)

_cen = [v for i, _, _ in bands_of_group("A1") for v in cat_payload[i]["s"]]
_sch = [v for i, _, _ in bands_of_group("A2") for v in cat_payload[i]["s"]]
cen_n, cen_tot = len(_cen), sum(_cen)
sch_n, sch_tot, sch_max = len(_sch), sum(_sch), max(_sch)
dir_max = max(cat_payload[i]["s"][0] for i, _, _ in bands_of_group("A1") if BANDS[i][2] == "99")
dist2 = sorted((v for i, _, _ in bands_of_group("A1") if BANDS[i][2] == "11–13"
                for v in cat_payload[i]["s"]), reverse=True)[1]

leg = []
for k, name, short in GROUPS:
    leg.append(f'<span class="legend-item"><span class="sw sw-{k}"></span>{short}</span>')
LEGEND = "\n".join(leg)

HTML = f"""<title>SPS Salary Skyline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Public+Sans:wght@400;500;600&family=Zilla+Slab:wght@500;600;700&display=swap">
<style>
:root {{
  color-scheme: light;
  --page:        #eeeeec;
  --surface:     #fcfcfb;
  --surface-2:   #f4f4f1;
  --ink:         #17181a;
  --ink-2:       #55554f;
  --ink-3:       #86867d;
  --rule:        #dedcd5;
  --rule-soft:   #eae8e2;
  --grid:        #e6e4dd;
  --A1:          #184f95;
  --A2:          #2a78d6;
  --B:           #eb6834;
  --C:           #1baf7a;
  --D:           #eda100;
  --E:           #9a9a90;
  --shadow:      0 1px 2px rgba(20,20,16,.06), 0 8px 24px -12px rgba(20,20,16,.18);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --page:      #0e0e0d;
    --surface:   #1a1a19;
    --surface-2: #232322;
    --ink:       #f4f4f0;
    --ink-2:     #b6b5ab;
    --ink-3:     #7d7c73;
    --rule:      #35342f;
    --rule-soft: #282824;
    --grid:      #2e2e29;
    --A1:        #86b6ef;
    --A2:        #3987e5;
    --B:         #d95926;
    --C:         #199e70;
    --D:         #c98500;
    --E:         #83837a;
    --shadow:    0 1px 2px rgba(0,0,0,.5), 0 8px 24px -12px rgba(0,0,0,.7);
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page:      #0e0e0d;
  --surface:   #1a1a19;
  --surface-2: #232322;
  --ink:       #f4f4f0;
  --ink-2:     #b6b5ab;
  --ink-3:     #7d7c73;
  --rule:      #35342f;
  --rule-soft: #282824;
  --grid:      #2e2e29;
  --A1:          #86b6ef;
  --A2:          #3987e5;
  --B:           #d95926;
  --C:           #199e70;
  --D:           #c98500;
  --E:           #83837a;
  --shadow:    0 1px 2px rgba(0,0,0,.5), 0 8px 24px -12px rgba(0,0,0,.7);
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
.mono {{ font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-variant-numeric: tabular-nums; }}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 40px 24px 64px; display: flex; flex-direction: column; gap: 28px; }}

/* ---- masthead ---- */
.eyebrow {{
  font-family: "IBM Plex Mono", monospace; font-size: 11px; font-weight: 500;
  letter-spacing: .14em; text-transform: uppercase; color: var(--ink-3);
  display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center;
}}
.eyebrow b {{ color: var(--ink-2); font-weight: 500; }}
h1 {{
  font-family: "Zilla Slab", Georgia, serif; font-weight: 700;
  font-size: clamp(30px, 4.6vw, 50px); line-height: 1.04; letter-spacing: -.015em;
  margin: 10px 0 0; text-wrap: balance; max-width: 18ch;
}}
h1 em {{ font-style: normal; color: var(--A2); }}
.standfirst {{ margin: 14px 0 0; max-width: 66ch; color: var(--ink-2); font-size: 16.5px; }}

/* ---- stat strip ---- */
.stats {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  border-radius: 3px; overflow: hidden;
}}
.stat {{ background: var(--surface); padding: 14px 16px 15px; }}
.stat dt {{
  font-family: "IBM Plex Mono", monospace; font-size: 10.5px; font-weight: 500;
  letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3); margin: 0 0 5px;
}}
.stat dd {{
  margin: 0; font-family: "Zilla Slab", Georgia, serif; font-weight: 600;
  font-size: 25px; line-height: 1.1; letter-spacing: -.01em;
  font-variant-numeric: tabular-nums;
}}
.stat dd small {{ font-size: 13px; font-weight: 500; color: var(--ink-3); font-family: "Public Sans", sans-serif; letter-spacing: 0; }}

/* ---- chart panel ---- */
.panel {{
  background: var(--surface); border: 1px solid var(--rule); border-radius: 3px;
  box-shadow: var(--shadow); overflow: hidden;
}}
.panel-head {{
  display: flex; flex-wrap: wrap; gap: 12px 22px; align-items: baseline;
  justify-content: space-between; padding: 16px 20px 14px; border-bottom: 1px solid var(--rule-soft);
}}
.panel-title {{ font-family: "Zilla Slab", Georgia, serif; font-weight: 600; font-size: 19px; }}
.panel-title span {{ color: var(--ink-3); font-family: "Public Sans", sans-serif; font-size: 13px; font-weight: 400; margin-left: 8px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; color: var(--ink-2); }}
.legend-item {{ display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }}
.sw {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }}
.sw-A1 {{ background: var(--A1); }}
.sw-A2 {{ background: var(--A2); }}
.sw-B {{ background: var(--B); }}
.sw-C {{ background: var(--C); }}
.sw-D {{ background: var(--D); }}
.sw-E {{ background: var(--E); }}

/* ---- minimap ---- */
.mini-bar {{ display: flex; align-items: center; gap: 14px; padding: 11px 20px; border-bottom: 1px solid var(--rule-soft); }}
.mini-hint {{
  font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: .09em;
  text-transform: uppercase; color: var(--ink-3); white-space: nowrap;
}}
#mini {{ flex: 1; min-width: 0; height: {MM_H}px; cursor: ew-resize; display: block; touch-action: none; }}
#mini:focus-visible {{ outline: 2px solid var(--A2); outline-offset: 2px; }}

/* ---- scroller ---- */
.chart-shell {{ position: relative; background: var(--surface); }}
#scroller {{ overflow-x: auto; overflow-y: hidden; scrollbar-color: var(--ink-3) var(--surface-2); }}
#scroller svg {{ display: block; }}
#axis {{ position: absolute; inset: 0 auto 0 0; width: {PAD_L}px; pointer-events: none; background: var(--surface); }}
#axis::after {{
  content: ""; position: absolute; top: 0; bottom: 0; right: -14px; width: 14px;
  background: linear-gradient(to right, var(--surface), transparent);
}}
.gridline {{ stroke: var(--grid); stroke-width: 1; }}
.baseline {{ stroke: var(--rule); stroke-width: 1; }}
.axis-label {{ font-family: "IBM Plex Mono", monospace; font-size: 10.5px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }}
.cat-label {{ font-family: "Public Sans", sans-serif; font-size: 11.5px; font-weight: 600; fill: var(--ink); }}
.cat-meta {{ font-family: "IBM Plex Mono", monospace; font-size: 10px; fill: var(--ink-3); }}
.cat-tick {{ stroke: var(--rule); stroke-width: 1; }}
.med-line {{ stroke-width: 1.5; stroke-dasharray: 3 3; opacity: .85; }}
.bar-A1 {{ fill: var(--A1); }}
.bar-A2 {{ fill: var(--A2); }}
.bar-B {{ fill: var(--B); }}
.bar-C {{ fill: var(--C); }}
.bar-D {{ fill: var(--D); }}
.bar-E {{ fill: var(--E); }}
.grp-label {{ font-family: "Zilla Slab", Georgia, serif; font-size: 15.5px; font-weight: 700; fill: var(--ink); }}
.grp-meta {{ font-family: "IBM Plex Mono", monospace; font-size: 10px; fill: var(--ink-3); }}
#cursor {{ stroke: var(--ink); stroke-width: 1; opacity: 0; }}
#cursor-bar {{ opacity: 0; }}

/* ---- tooltip ---- */
#tip {{
  position: fixed; z-index: 20; pointer-events: none; opacity: 0;
  transform: translate(-50%, -100%); transition: opacity .09s linear;
  background: var(--surface); color: var(--ink); border: 1px solid var(--rule);
  border-radius: 3px; box-shadow: var(--shadow); padding: 9px 12px 10px; min-width: 200px;
}}
#tip .t-duty {{ font-size: 12.5px; font-weight: 600; display: flex; align-items: center; gap: 7px; }}
#tip .t-sal {{ font-family: "Zilla Slab", serif; font-weight: 600; font-size: 24px; line-height: 1.15; margin-top: 3px; font-variant-numeric: tabular-nums; }}
#tip .t-meta {{ font-family: "IBM Plex Mono", monospace; font-size: 10.5px; color: var(--ink-3); margin-top: 4px; line-height: 1.5; }}

.panel-foot {{
  padding: 12px 20px 14px; border-top: 1px solid var(--rule-soft);
  font-size: 12.5px; color: var(--ink-3); display: flex; flex-wrap: wrap; gap: 4px 20px;
}}

/* ---- table ---- */
.table-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
h2 {{ font-family: "Zilla Slab", Georgia, serif; font-weight: 600; font-size: 21px; margin: 0; }}
.table-note {{ font-size: 13px; color: var(--ink-3); max-width: 52ch; }}
.table-scroll {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--rule); border-radius: 3px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 8px 12px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--rule-soft); }}
th {{
  font-family: "IBM Plex Mono", monospace; font-size: 10px; font-weight: 500;
  letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3);
  border-bottom: 1px solid var(--rule); position: sticky; top: 0; background: var(--surface);
}}
td.tl, th.tl {{ text-align: left; }}
td.tl {{ display: table-cell; }}
td.tl .sw {{ margin-right: 8px; vertical-align: baseline; }}
td.dim {{ color: var(--ink-3); }}
td.strong {{ font-weight: 500; color: var(--ink); }}
tbody tr:last-child td {{ border-bottom: none; }}
tbody tr:hover td {{ background: var(--surface-2); }}
tfoot td {{ border-top: 1px solid var(--rule); font-weight: 600; background: var(--surface-2); }}
tr.grp td {{ background: var(--surface-2); border-bottom-color: var(--rule); }}
tr.grp:hover td {{ background: var(--surface-2); }}
td.sub {{ padding-left: 30px; color: var(--ink-2); }}

/* ---- notes ---- */
.notes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 22px 34px; }}
.note h3 {{
  font-family: "IBM Plex Mono", monospace; font-size: 10.5px; font-weight: 500;
  letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3);
  margin: 0 0 6px; padding-bottom: 6px; border-bottom: 1px solid var(--rule);
}}
.note p {{ margin: 0 0 8px; font-size: 13.5px; color: var(--ink-2); }}
.note code {{ font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--ink); background: var(--surface-2); padding: 1px 4px; border-radius: 2px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">
      <span>Seattle Public Schools &middot; <b>CCDDD 17001</b></span>
      <span>S-275 &middot; <b>2024&ndash;25 final report</b></span>
      <span>Measure &middot; <b>total_final_salary</b></span>
    </div>
    <h1>Every SPS salary, <em>tallest to shortest</em></h1>
    <p class="standfirst">
      One bar per employee &mdash; {TOTALS['n']:,} of them &mdash; drawn at the salary payroll
      actually paid out over the year. Staff are banded by their primary OSPI duty title, and within
      each band sorted highest to lowest. Scroll sideways: the whole district is about fifteen screens wide.
    </p>
  </header>

  <dl class="stats">
    <div class="stat"><dt>Employees</dt><dd>{TOTALS['n']:,}</dd></div>
    <div class="stat"><dt>Total FTE</dt><dd>{TOTALS['fte']:,.1f}</dd></div>
    <div class="stat"><dt>Total final salary</dt><dd>${TOTALS['total']/1e6:,.1f}M</dd></div>
    <div class="stat"><dt>Median</dt><dd>{money(TOTALS['median'])}</dd></div>
    <div class="stat"><dt>10th&ndash;90th pct</dt><dd style="font-size:19px">{money(TOTALS['p10'])} <small>to</small> {money(TOTALS['p90'])}</dd></div>
    <div class="stat"><dt>Highest paid</dt><dd>{money(TOTALS['max'])}</dd></div>
  </dl>

  <section class="panel">
    <div class="panel-head">
      <div class="panel-title">Salary by employee<span>{TOTALS['n']:,} bars &middot; 15 duty bands in 6 groups &middot; dashed rule = band median</span></div>
      <div class="legend">{LEGEND}</div>
    </div>
    <div class="mini-bar">
      <span class="mini-hint">Whole&nbsp;district</span>
      <svg id="mini" viewBox="0 0 {MM_W} {MM_H}" preserveAspectRatio="none" role="slider"
           tabindex="0" aria-label="Scroll position across all employees"
           aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></svg>
      <span class="mini-hint">Drag&nbsp;to&nbsp;pan</span>
    </div>
    <div class="chart-shell">
      <div id="scroller" tabindex="0" aria-label="Salary chart, scroll horizontally"></div>
      <svg id="axis" viewBox="0 0 {PAD_L} {svg_h}" aria-hidden="true"></svg>
    </div>
    <div class="panel-foot">
      <span>Bar height = <code style="font-family:'IBM Plex Mono',monospace">total_final_salary</code>, not FTE-adjusted &mdash; part-time and partial-year staff sit low by design.</span>
    </div>
  </section>

  <section style="display:flex;flex-direction:column;gap:14px">
    <div class="table-head">
      <h2>The same numbers, band by band</h2>
      <p class="table-note">Percentiles are within band. &ldquo;Total&rdquo; is the sum of final salary &mdash; it excludes insurance, mandatory benefits and supplemental (TRI) contracts.</p>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th class="tl">Duty band</th><th>Duty codes</th><th>Staff</th><th>FTE</th>
          <th>Min</th><th>25th</th><th>Median</th><th>75th</th><th>Max</th><th>Total</th>
        </tr></thead>
        <tbody>
{TABLE_BODY}
        </tbody>
        <tfoot><tr>
          <td class="tl">All staff</td><td class="mono dim">&mdash;</td>
          <td class="mono">{TOTALS['n']:,}</td><td class="mono">{TOTALS['fte']:,.1f}</td>
          <td class="mono">{money(TOTALS['min'])}</td><td class="mono">{money(all_sal[int(0.25*(N-1))])}</td>
          <td class="mono">{money(TOTALS['median'])}</td><td class="mono">{money(all_sal[int(0.75*(N-1))])}</td>
          <td class="mono">{money(TOTALS['max'])}</td><td class="mono">${TOTALS['total']/1e6:,.1f}M</td>
        </tr></tfoot>
      </table>
    </div>
  </section>

  <section class="notes">
    <div class="note">
      <h3>Source</h3>
      <p>OSPI S-275 personnel report for Seattle Public Schools, school year 2024&ndash;25,
         <code>report_type = final</code>. Salary is <code>total_final_salary</code> from
         <code>safs_s275.private_report_employee</code> &mdash; one value per person per report,
         determined by payroll rather than the October snapshot.</p>
    </div>
    <div class="note">
      <h3>How staff were banded</h3>
      <p>An employee can hold several assignments. Each is assigned to the duty root of their
         <em>major</em> assignment; ties break on FTE, then assignment salary.</p>
      <p>Bands come from the OSPI duty code, not the <code>is_classified</code> flag. Roots
         90&ndash;99 are the classified series, but <strong>99</strong> (Director or Supervisor)
         and <strong>96</strong> (Professional) are counted as central office staff here &mdash;
         the work is administrative and professional, not support.</p>
    </div>
    <div class="note">
      <h3>Central office vs schools</h3>
      <p>Counting duty 99 and 96 as central office puts {cen_n:,} people and ${cen_tot/1e6:,.1f}M
         &mdash; {cen_tot/TOTALS["total"]*100:.1f}% of payroll &mdash; in that block, against
         {sch_n} people and ${sch_tot/1e6:,.1f}M for school administration.</p>
      <p>The top classified director is paid {money(dir_max)}: more than any principal in the
         district ({money(sch_max)}), and within ${dist2 - dir_max} of the second-highest-paid
         district administrator.</p>
      <p>Substitutes, leave/buy-back and extracurricular base contracts are real employees with
         real payroll but little or no FTE &mdash; they pull the low end of several bands down.</p>
    </div>
  </section>
</div>

<div id="tip" role="status" aria-live="off"></div>

<script>
const D = {json.dumps(DATA, separators=(",", ":"))};
const FAM = {FAM_JSON};
const NS = "http://www.w3.org/2000/svg";
const el = (n, a) => {{ const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; }};
const usd = v => "$" + Math.round(v).toLocaleString("en-US");

const yOf = v => D.headH + D.plotH - (v / D.yMax) * D.plotH;
const TICKS = [0, 50000, 100000, 150000, 200000, 250000, 300000, 350000];

/* ---------- main chart ---------- */
const svg = el("svg", {{viewBox: `0 0 ${{D.svgW}} ${{D.svgH}}`, width: D.svgW, height: D.svgH,
                        role: "img", "aria-label": "Salary of every Seattle Public Schools employee, grouped by duty band"}});

for (const t of TICKS) {{
  svg.appendChild(el("line", {{class: t === 0 ? "baseline" : "gridline",
    x1: D.padL - 8, x2: D.svgW - 6, y1: yOf(t), y2: yOf(t)}}));
}}

D.groups.forEach(g => {{
  svg.appendChild(el("rect", {{class: "bar-" + g.key, x: g.x0 - 1, y: 8,
    width: Math.max(3, g.x1 - g.x0 - D.pitch + D.barw + 2), height: 3}}));
  const gl = el("text", {{class: "grp-label", x: g.x0 + 2, y: 30}});
  gl.textContent = g.label; svg.appendChild(gl);
  const gm = el("text", {{class: "grp-meta", x: g.x0 + 2, y: 43}});
  gm.textContent = `${{g.n.toLocaleString()}} staff · $${{(g.total / 1e6).toFixed(1)}}M · `
    + `${{(g.total / D.grandTotal * 100).toFixed(1)}}% of payroll`;
  svg.appendChild(gm);
}});

const flat = [];   // {{x, sal, fam, duty, fte, cat, rank}}
D.cats.forEach((c, ci) => {{
  const x0 = D.starts[ci], n = c.s.length, w = n * D.pitch;
  const g = el("g", {{}});
  for (let i = 0; i < n; i++) {{
    const x = x0 + i * D.pitch, y = yOf(c.s[i]);
    g.appendChild(el("rect", {{class: "bar-" + c.fam, x: x.toFixed(2), y: y.toFixed(2),
      width: D.barw, height: Math.max(0.6, D.headH + D.plotH - y).toFixed(2), rx: 0.7}}));
    flat.push({{x: x, s: c.s[i], fam: c.fam, d: c.d[i], f: c.f[i], ci: ci, r: i}});
  }}
  svg.appendChild(g);

  // band median rule
  const med = n % 2 ? c.s[(n - 1) >> 1] : (c.s[n / 2 - 1] + c.s[n / 2]) / 2;
  svg.appendChild(el("line", {{class: "med-line", stroke: `var(--${{c.fam}})`,
    x1: x0 - 1, x2: x0 + w - D.pitch + D.barw + 1, y1: yOf(med), y2: yOf(med)}}));

  // band header: tick + two alternating label rows so narrow bands don't collide
  const row = ci % 2 ? 72 : 50;
  svg.appendChild(el("line", {{class: "cat-tick", x1: x0 - 1, x2: x0 - 1, y1: row - 2, y2: D.headH + D.plotH}}));
  const lab = el("text", {{class: "cat-label", x: x0 + 5, y: row + 9}});
  lab.textContent = c.label;
  svg.appendChild(lab);
  const meta = el("text", {{class: "cat-meta", x: x0 + 5, y: row + 21}});
  meta.textContent = `${{c.s.length.toLocaleString()}} staff · duty ${{c.codes}} · median ${{usd(med)}}`;
  svg.appendChild(meta);
}});

const cursor = el("line", {{id: "cursor", y1: D.headH - 4, y2: D.headH + D.plotH}});
const cbar = el("rect", {{id: "cursor-bar", width: Math.max(2.4, D.barw + 1.4), rx: 1}});
svg.appendChild(cursor); svg.appendChild(cbar);

for (const t of TICKS.slice(1)) {{
  const lb = el("text", {{class: "axis-label", x: D.svgW - 10, y: yOf(t) - 4, "text-anchor": "end"}});
  lb.textContent = "$" + (t / 1000) + "k";
  svg.appendChild(lb);
}}
document.getElementById("scroller").appendChild(svg);

/* ---------- sticky y axis ---------- */
const ax = document.getElementById("axis");
for (const t of TICKS) {{
  const lb = el("text", {{class: "axis-label", x: {PAD_L} - 12, y: yOf(t) + 3.5, "text-anchor": "end"}});
  lb.textContent = t === 0 ? "$0" : "$" + (t / 1000) + "k";
  ax.appendChild(lb);
  ax.appendChild(el("line", {{class: t === 0 ? "baseline" : "gridline",
    x1: {PAD_L} - 8, x2: {PAD_L}, y1: yOf(t), y2: yOf(t)}}));
}}

/* ---------- minimap ---------- */
const mini = document.getElementById("mini");
const mmMax = Math.max(...D.mm.map(m => m[0]));
D.mm.forEach((m, i) => {{
  const h = Math.max(1, (m[0] / mmMax) * (D.mmH - 2));
  mini.appendChild(el("rect", {{class: "bar-" + m[1], x: i, y: D.mmH - h, width: 1.05, height: h, opacity: .55}}));
}});
const vp = el("rect", {{y: 0, height: D.mmH, fill: "none", stroke: "var(--ink)", "stroke-width": 1.5, rx: 1.5}});
const vpFill = el("rect", {{y: 0, height: D.mmH, fill: "var(--ink)", opacity: .08}});
mini.appendChild(vpFill); mini.appendChild(vp);

const scroller = document.getElementById("scroller");
function syncMini() {{
  const frac = scroller.scrollLeft / Math.max(1, D.svgW - scroller.clientWidth);
  const w = Math.max(6, (scroller.clientWidth / D.svgW) * D.mmW);
  const x = frac * (D.mmW - w);
  vp.setAttribute("x", x); vp.setAttribute("width", w);
  vpFill.setAttribute("x", x); vpFill.setAttribute("width", w);
  mini.setAttribute("aria-valuenow", Math.round(frac * 100));
}}
scroller.addEventListener("scroll", syncMini, {{passive: true}});
addEventListener("resize", syncMini);
syncMini();

function seek(clientX) {{
  const r = mini.getBoundingClientRect();
  const frac = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
  scroller.scrollLeft = frac * (D.svgW - scroller.clientWidth);
}}
let dragging = false;
mini.addEventListener("pointerdown", e => {{ dragging = true; mini.setPointerCapture(e.pointerId); seek(e.clientX); }});
mini.addEventListener("pointermove", e => {{ if (dragging) seek(e.clientX); }});
mini.addEventListener("pointerup", () => {{ dragging = false; }});
mini.addEventListener("keydown", e => {{
  const step = scroller.clientWidth * (e.shiftKey ? 1 : 0.25);
  if (e.key === "ArrowRight") {{ scroller.scrollLeft += step; e.preventDefault(); }}
  if (e.key === "ArrowLeft")  {{ scroller.scrollLeft -= step; e.preventDefault(); }}
  if (e.key === "Home") {{ scroller.scrollLeft = 0; e.preventDefault(); }}
  if (e.key === "End")  {{ scroller.scrollLeft = D.svgW; e.preventDefault(); }}
}});

/* ---------- hover ---------- */
const tip = document.getElementById("tip");
let lastIdx = -1;
function hide() {{
  tip.style.opacity = 0; cursor.style.opacity = 0; cbar.style.opacity = 0; lastIdx = -1;
}}
scroller.addEventListener("pointermove", e => {{
  const r = svg.getBoundingClientRect();
  const sx = (e.clientX - r.left) * (D.svgW / r.width);
  if (sx < D.padL - 4) return hide();
  // binary search nearest bar by x
  let lo = 0, hi = flat.length - 1;
  while (lo < hi) {{ const mid = (lo + hi) >> 1; if (flat[mid].x < sx) lo = mid + 1; else hi = mid; }}
  if (lo > 0 && Math.abs(flat[lo - 1].x - sx) < Math.abs(flat[lo].x - sx)) lo--;
  const b = flat[lo];
  if (Math.abs(b.x - sx) > 26) return hide();
  if (lo !== lastIdx) {{
    lastIdx = lo;
    const cat = D.cats[b.ci];
    tip.innerHTML =
      `<div class="t-duty"><span class="sw sw-${{b.fam}}"></span>${{D.duties[b.d]}}</div>` +
      `<div class="t-sal">${{usd(b.s)}}</div>` +
      `<div class="t-meta">${{cat.label}} &middot; rank ${{(b.r + 1).toLocaleString()}} of ${{cat.s.length.toLocaleString()}}<br>` +
      `${{(b.f / 100).toFixed(2)}} FTE reported</div>`;
    cursor.setAttribute("x1", b.x + D.barw / 2); cursor.setAttribute("x2", b.x + D.barw / 2);
    cursor.setAttribute("stroke", `var(--${{b.fam}})`);
    const y = yOf(b.s);
    cbar.setAttribute("x", b.x - 0.7); cbar.setAttribute("y", y);
    cbar.setAttribute("height", Math.max(1, D.headH + D.plotH - y));
    cbar.setAttribute("fill", "var(--ink)");
    cursor.style.opacity = .28; cbar.style.opacity = 1;
  }}
  tip.style.left = e.clientX + "px";
  tip.style.top = (e.clientY - 14) + "px";
  tip.style.opacity = 1;
}});
scroller.addEventListener("pointerleave", hide);
</script>
"""

OUT.write_text(HTML)
print(f"wrote {OUT}  ({len(HTML)/1024:.0f} KB)  plot width {plot_w:.0f}px")
