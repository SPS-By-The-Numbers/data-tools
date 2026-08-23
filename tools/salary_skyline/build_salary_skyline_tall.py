#!/usr/bin/env python3
"""Tall (axes-flipped) standalone SVG of every SPS S-275 salary.

X = total_final_salary, Y = staff (one 1.4px bar per employee, ~17k px tall).
Bands are nested inside groups (see salary_bands.py); fonts are inlined as
woff2 data URIs so the file stands alone anywhere.

  python3 tools/salary_skyline/build_salary_skyline_tall.py       # from repo root
  python3 tools/salary_skyline/build_salary_skyline_tall.py \
      --data out_salary_skyline/staff.csv -o out_salary_skyline/tall.svg

Rasterize (no ImageMagick/rsvg needed):
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
    --disable-gpu --hide-scrollbars --virtual-time-budget=20000 \
    --window-size=1560,<svg height> \
    --screenshot=out_salary_skyline/salary_skyline_tall.png \
    "file://$PWD/out_salary_skyline/salary_skyline_tall.svg"
"""
import argparse, csv, statistics as st, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from salary_bands import BANDS, GROUPS, COLORS, band_of, bands_of_group

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--data", default="out_salary_skyline/staff.csv",
                help="per-employee CSV from query.sql")
ap.add_argument("--fonts", default="out_salary_skyline/fonts_inline.css",
                help="inlined woff2 CSS from fetch_fonts.py")
ap.add_argument("-o", "--out", default="out_salary_skyline/salary_skyline_tall.svg")
args = ap.parse_args()

SRC, FONTS, OUT = Path(args.data), Path(args.fonts), Path(args.out)
OUT.parent.mkdir(parents=True, exist_ok=True)

# ---- geometry ---------------------------------------------------------------
W         = 1560
PAD       = 40
PLOT_X    = 116          # x of $0
PLOT_W    = 1150         # $0 .. X_MAX
X_MAX     = 375000
PITCH     = 2.0
BARW      = 1.4
GROUP_HD  = 58
BAND_HD   = 74
BAND_GAP  = 24
GROUP_GAP = 34
PLOT_TOP  = 470
FOOT_H    = 232
TICKS     = [0, 50000, 100000, 150000, 200000, 250000, 300000, 350000]

xOf = lambda v: PLOT_X + v / X_MAX * PLOT_W
esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
usd = lambda v: "$" + format(round(v), ",")

# ---- data -------------------------------------------------------------------
rows = list(csv.DictReader(SRC.open()))
by_band = defaultdict(list)
for r in rows:
    by_band[band_of(int(r["duty"]))].append(
        (round(float(r["salary"])), r["duty_name"], float(r["fte"])))
for b in by_band:
    by_band[b].sort(key=lambda t: -t[0])

all_sal = sorted(round(float(r["salary"])) for r in rows)
N = len(rows)
TOT = {
    "n": N, "total": sum(all_sal), "median": round(st.median(all_sal)),
    "fte": round(sum(float(r["fte"]) for r in rows), 1),
    "p10": all_sal[int(0.10 * (N - 1))], "p90": all_sal[int(0.90 * (N - 1))],
    "max": all_sal[-1],
}

def group_stats(key):
    sal = [s for i, _, _ in bands_of_group(key) for s, _, _ in by_band[i]]
    return len(sal), sum(sal)

# ---- height -----------------------------------------------------------------
plot_h = 0
for gi, (gk, _, _) in enumerate(GROUPS):
    plot_h += GROUP_HD + (GROUP_GAP if gi else 0)
    for j, (bi, _, _) in enumerate(bands_of_group(gk)):
        plot_h += (BAND_GAP if j else 0) + BAND_HD + len(by_band[bi]) * PITCH
H = int(PLOT_TOP + plot_h + FOOT_H)

o = []
add = o.append
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" role="img" '
    f'aria-label="Total final salary of every Seattle Public Schools employee, 2024-25 S-275, '
    f'grouped by OSPI duty band and sorted highest to lowest">')
add('<title>Every SPS salary, longest to shortest</title>')

light = "; ".join(f"--{k}:{v[0]}" for k, v in COLORS.items())
dark  = "; ".join(f"--{k}:{v[1]}" for k, v in COLORS.items())
bar_classes = " ".join(f".b{k}{{fill:var(--{k});}} .s{k}{{fill:var(--{k});}}" for k in COLORS)

add(f"""<style>
{FONTS.read_text()}
svg {{
  --page:#eeeeec; --surface:#fcfcfb;
  --ink:#17181a; --ink-2:#55554f; --ink-3:#86867d;
  --rule:#dedcd5; --grid:#e6e4dd;
  {light};
}}
@media (prefers-color-scheme: dark) {{
  svg {{
    --page:#0e0e0d; --surface:#1a1a19;
    --ink:#f4f4f0; --ink-2:#b6b5ab; --ink-3:#7d7c73;
    --rule:#35342f; --grid:#2e2e29;
    {dark};
  }}
}}
text {{ font-family:'Public Sans',-apple-system,'Helvetica Neue',Arial,sans-serif; fill:var(--ink); }}
.page {{ fill:var(--page); }}
.card {{ fill:var(--surface); stroke:var(--rule); stroke-width:1; }}
.eyebrow {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:11.5px; font-weight:500;
            letter-spacing:1.6px; fill:var(--ink-3); }}
.eyebrow tspan.b {{ fill:var(--ink-2); }}
.h1 {{ font-family:'Zilla Slab',Georgia,serif; font-weight:700; font-size:50px; letter-spacing:-0.7px; }}
.h1b {{ fill:var(--A2); }}
.stand {{ font-size:16.5px; fill:var(--ink-2); }}
.stat-k {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:10.5px; font-weight:500;
           letter-spacing:1.1px; fill:var(--ink-3); }}
.stat-v {{ font-family:'Zilla Slab',Georgia,serif; font-weight:600; font-size:25px; letter-spacing:-0.2px; }}
.stat-s {{ font-size:13px; fill:var(--ink-3); font-weight:500; }}
.leg {{ font-size:12.5px; fill:var(--ink-2); }}
.axis-t {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:10.5px; fill:var(--ink-3); }}
.axis-cap {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:10.5px; font-weight:500;
             letter-spacing:1.3px; fill:var(--ink-3); }}
.rank {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:9.5px; fill:var(--ink-3); }}
.grp-n {{ font-family:'Zilla Slab',Georgia,serif; font-weight:700; font-size:25px; letter-spacing:-0.3px; }}
.grp-m {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:11px; fill:var(--ink-3); }}
.band-n {{ font-family:'Zilla Slab',Georgia,serif; font-weight:600; font-size:17px; }}
.band-m {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:11px; fill:var(--ink-3); }}
.callout {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:10.5px; fill:var(--ink-2); }}
.callout tspan.q {{ fill:var(--ink-3); }}
.note-h {{ font-family:'IBM Plex Mono',Menlo,monospace; font-size:10.5px; font-weight:500;
           letter-spacing:1.1px; fill:var(--ink-3); }}
.note {{ font-size:13px; fill:var(--ink-2); }}
.grid {{ stroke:var(--grid); stroke-width:1; }}
.rule {{ stroke:var(--rule); stroke-width:1; }}
.tickmk {{ stroke:var(--rule); stroke-width:1; }}
.med {{ stroke-width:1.5; stroke-dasharray:3 3; opacity:.9; fill:none; }}
{bar_classes}
</style>""")

add(f'<rect class="page" x="0" y="0" width="{W}" height="{H}"/>')

# ---------- masthead ----------
add(f'<text class="eyebrow" x="{PAD}" y="52">SEATTLE PUBLIC SCHOOLS &#183; <tspan class="b">CCDDD 17001</tspan>'
    f'&#160;&#160;&#160;S-275 &#183; <tspan class="b">2024–25 FINAL REPORT</tspan>'
    f'&#160;&#160;&#160;MEASURE &#183; <tspan class="b">TOTAL_FINAL_SALARY</tspan></text>')
add(f'<text class="h1" x="{PAD}" y="112">Every SPS salary,</text>')
add(f'<text class="h1 h1b" x="{PAD}" y="162">longest to shortest</text>')
for i, line in enumerate([
    f"One bar per employee — {N:,} of them — drawn at the salary payroll actually paid out over the year.",
    "Staff are banded by their primary OSPI duty title; within each band the highest paid sits at the top.",
    "Scroll down: the whole district runs about sixteen thousand pixels deep.",
]):
    add(f'<text class="stand" x="{PAD}" y="{200 + i * 23}">{esc(line)}</text>')

SY, SH = 288, 76
cells = [("EMPLOYEES", f"{N:,}", None), ("TOTAL FTE", f"{TOT['fte']:,.1f}", None),
         ("TOTAL FINAL SALARY", f"${TOT['total']/1e6:,.1f}M", None),
         ("MEDIAN", usd(TOT["median"]), None),
         ("10TH–90TH PCT", usd(TOT["p10"]), usd(TOT["p90"])),
         ("HIGHEST PAID", usd(TOT["max"]), None)]
SW = (W - 2 * PAD) / len(cells)
add(f'<rect class="card" x="{PAD}.5" y="{SY}.5" width="{W-2*PAD-1}" height="{SH}" rx="2"/>')
for i, (k, v, v2) in enumerate(cells):
    cx = PAD + i * SW
    if i:
        add(f'<line class="rule" x1="{cx:.1f}" x2="{cx:.1f}" y1="{SY}" y2="{SY+SH}"/>')
    add(f'<text class="stat-k" x="{cx+17:.1f}" y="{SY+26}">{k}</text>')
    if v2:
        add(f'<text class="stat-v" x="{cx+17:.1f}" y="{SY+56}" font-size="20">{v}'
            f'<tspan class="stat-s"> to </tspan>{v2}</text>')
    else:
        add(f'<text class="stat-v" x="{cx+17:.1f}" y="{SY+58}">{v}</text>')

LY, lx = 404, PAD
for gk, _, short in GROUPS:
    add(f'<rect class="s{gk}" x="{lx}" y="{LY-9}" width="10" height="10" rx="2"/>')
    add(f'<text class="leg" x="{lx+16}" y="{LY}">{esc(short)}</text>')
    lx += 22 + len(short) * 6.65 + 20
add(f'<text class="axis-cap" x="{W-PAD}" y="{LY}" text-anchor="end">'
    f'DASHED RULE = BAND MEDIAN &#183; ONE BAR = ONE EMPLOYEE</text>')

# ---------- plot ----------
plot_bottom = PLOT_TOP + plot_h
for t in TICKS:
    add(f'<line class="{"rule" if t == 0 else "grid"}" x1="{xOf(t):.1f}" x2="{xOf(t):.1f}" '
        f'y1="{PLOT_TOP-22}" y2="{plot_bottom:.1f}"/>')
add(f'<text class="axis-cap" x="{PLOT_X}" y="{PLOT_TOP-48}">TOTAL FINAL SALARY →</text>')
for t in TICKS:
    add(f'<text class="axis-t" x="{xOf(t):.1f}" y="{PLOT_TOP-30}" '
        f'text-anchor="{"start" if t == 0 else "middle"}">{"$0" if t == 0 else f"${t//1000}k"}</text>')

y = PLOT_TOP
for gi, (gk, glabel, _) in enumerate(GROUPS):
    if gi:
        y += GROUP_GAP
    gn, gtot = group_stats(gk)
    add(f'<rect class="s{gk}" x="{PAD}" y="{y:.1f}" width="{W-2*PAD}" height="4"/>')
    add(f'<text class="grp-n" x="{PAD}" y="{y+35:.1f}">{esc(glabel)}</text>')
    add(f'<text class="grp-m" x="{W-PAD}" y="{y+34:.1f}" text-anchor="end">'
        f'{gn:,} STAFF &#183; ${gtot/1e6:,.1f}M &#183; {gtot/TOT["total"]*100:.1f}% OF PAYROLL</text>')
    y += GROUP_HD

    for j, (bi, label, codes) in enumerate(bands_of_group(gk)):
        if j:
            y += BAND_GAP
        items = by_band[bi]
        sal = [t[0] for t in items]
        n = len(sal)
        med = st.median(sal)
        bars_top = y + BAND_HD
        bars_bot = bars_top + n * PITCH

        add(f'<line class="rule" x1="{PAD}" x2="{W-PAD}" y1="{y:.1f}" y2="{y:.1f}"/>')
        add(f'<rect class="s{gk}" x="{PAD}" y="{y:.1f}" width="46" height="3"/>')
        add(f'<text class="band-n" x="{PAD}" y="{y+28:.1f}">{esc(label)}</text>')
        add(f'<text class="band-m" x="{PAD}" y="{y+46:.1f}">{n:,} staff &#183; duty {esc(codes)} '
            f'&#183; median {usd(med)} &#183; ${sum(sal)/1e6:,.1f}M total</text>')
        add(f'<text class="axis-t" x="{PLOT_X}" y="{y+68:.1f}">$0</text>')
        for t in TICKS[1:]:
            add(f'<text class="axis-t" x="{xOf(t):.1f}" y="{y+68:.1f}" text-anchor="middle">${t//1000}k</text>')

        add(f'<g class="b{gk}">' + "".join(
            f'<rect y="{bars_top + i * PITCH:.1f}" x="{PLOT_X}" '
            f'width="{max(0.6, xOf(s)-PLOT_X):.1f}" height="{BARW}"/>'
            for i, s in enumerate(sal)) + "</g>")
        add(f'<line class="med" stroke="var(--{gk})" x1="{xOf(med):.1f}" x2="{xOf(med):.1f}" '
            f'y1="{bars_top-3:.1f}" y2="{bars_bot+1:.1f}"/>')

        step = 250 if n >= 1000 else 100 if n >= 400 else 50 if n >= 150 else 25 if n >= 60 else 10
        for rk in [1] + list(range(step, n + 1, step)):
            ry = bars_top + (rk - 1) * PITCH + BARW / 2
            add(f'<line class="tickmk" x1="{PLOT_X-7}" x2="{PLOT_X-2}" y1="{ry:.1f}" y2="{ry:.1f}"/>')
            add(f'<text class="rank" x="{PLOT_X-11}" y="{ry+3.2:.1f}" text-anchor="end">{rk}</text>')

        add(f'<text class="callout" x="{xOf(sal[0])+9:.1f}" y="{bars_top+4.5:.1f}">'
            f'{usd(sal[0])}&#160;&#160;<tspan class="q">{esc(items[0][1])}</tspan></text>')
        y = bars_bot

y = plot_bottom
add(f'<line class="rule" x1="{PAD}" x2="{W-PAD}" y1="{y+10:.1f}" y2="{y+10:.1f}"/>')
add(f'<text class="axis-cap" x="{PLOT_X}" y="{y+32:.1f}">TOTAL FINAL SALARY →</text>')
for t in TICKS:
    add(f'<text class="axis-t" x="{xOf(t):.1f}" y="{y+50:.1f}" '
        f'text-anchor="{"start" if t == 0 else "middle"}">{"$0" if t == 0 else f"${t//1000}k"}</text>')

# ---------- footnotes ----------
cen_n, cen_tot = group_stats("A1")
sch_n, sch_tot = group_stats("A2")
dir_max = max(s for i, _, c in bands_of_group("A1") if c == "99" for s, _, _ in by_band[i])
sch_max = max(s for i, _, _ in bands_of_group("A2") for s, _, _ in by_band[i])
NY = y + 92
COLW = (W - 2 * PAD - 2 * 34) / 3
notes = [
    ("SOURCE", [
        "OSPI S-275 personnel report for Seattle Public",
        "Schools, school year 2024–25, report_type = final.",
        "Salary is total_final_salary from",
        "safs_s275.private_report_employee — one value per",
        "person per report, set by payroll rather than by the",
        "October 1 snapshot.",
    ]),
    ("HOW STAFF WERE BANDED", [
        "An employee can hold several assignments. Each is",
        "assigned the duty root of their major assignment;",
        "ties break on FTE, then on assignment salary.",
        "Bands come from the OSPI duty code, not from the",
        "is_classified flag. Roots 90–99 are the classified",
        "series, but 99 (Director or Supervisor) and 96",
        "(Professional) are counted as central office staff.",
    ]),
    ("CENTRAL OFFICE VS SCHOOLS", [
        f"Central administration and central office staff are",
        f"{cen_n:,} people and ${cen_tot/1e6:,.1f}M — {cen_tot/TOT['total']*100:.1f}% of payroll — against",
        f"{sch_n} people and ${sch_tot/1e6:,.1f}M for school administration.",
        f"The top classified director is paid {usd(dir_max)}, more",
        f"than any principal in the district ({usd(sch_max)}).",
        "Bar length is not FTE-adjusted, so part-time and",
        "partial-year staff sit short by design.",
    ]),
]
for i, (h, lines) in enumerate(notes):
    cx = PAD + i * (COLW + 34)
    add(f'<text class="note-h" x="{cx:.1f}" y="{NY}">{h}</text>')
    add(f'<line class="rule" x1="{cx:.1f}" x2="{cx+COLW:.1f}" y1="{NY+9}" y2="{NY+9}"/>')
    for j, ln in enumerate(lines):
        add(f'<text class="note" x="{cx:.1f}" y="{NY + 30 + j * 19}">{esc(ln)}</text>')

add("</svg>")
svg = "\n".join(o)
OUT.write_text(svg)
print(f"wrote {OUT}  {len(svg)/1024:.0f} KB  — {W} x {H} px")
