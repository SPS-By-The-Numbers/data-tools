#!python3
"""Budget/variance charts for the duty-title state-funding join.

Two bullet-style charts, each drawing the state's allocation as the budget
with the district's actual overlaid on it:

  1. Dollars -- total_final_salary paid per duty title, over a stack of every
     state apportionment account attributed to that title.
  2. FTE -- actual S-275 FTE per staff class, over the prototypical FTE the
     state funded.

Reads the CSV from `build_duty_funding.py`; writes one standalone HTML file.

    python3 -m tools.duty_funding.build_variance_charts \
        --data output/duty_funding/sps_2024-25_duty_state_funding.csv \
        -o output/duty_funding/sps_2024-25_variance.html
"""

import argparse
import csv
import html
from decimal import Decimal
from pathlib import Path

from .funding_sources import SEGMENT_KEYS, SEGMENT_LABEL, SEGMENT_SLOT

CLASS_NAME = {
    "CIS": "Certificated instructional (CIS)",
    "CAS": "Certificated administrative (CAS)",
    "CLS": "Classified (CLS)",
}

# Geometry
LABEL_W, PLOT_W, VALUE_W = 250, 620, 130
PAD_L, PAD_T = 16, 8
BUDGET_H, ACTUAL_H = 24, 11


def money(v):
    v = float(v)
    if v == 0:
        return "$0"
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.1f}M"
    return f"${v / 1e3:,.0f}K"


def fte(v):
    return f"{float(v):,.0f}"


def nice_ticks(vmax, step):
    """Ticks covering vmax, always with one step of headroom left over.

    Without it a bar that lands on the last tick runs the full width of the
    plot and collides with the value column beside it.
    """
    ticks, t = [], 0.0
    while t <= vmax * 1.0001:
        ticks.append(t)
        t += step
    while ticks[-1] < vmax * 1.04:
        ticks.append(ticks[-1] + step)
    return ticks


HATCH_PITCH = 6


def hatch_lines(x, y, w, h, pitch=HATCH_PITCH):
    """45-degree stripes across one segment, as explicit line elements.

    Deliberately not an SVG <pattern>: a pattern has to be referenced as
    `fill="url(#id)"`, which silently fails wherever the document carries a
    <base> tag, and its `var()` colours do not resolve in every engine
    because the pattern content sits outside the element that uses it.
    Drawing the stripes in the chart's own SVG renders identically
    everywhere and inherits the surrounding stroke tokens.

    Each stripe runs up and to the right, trimmed to the segment box by
    intersecting it directly rather than by a second clip path.
    """
    out, b = [], x - h
    while b < x + w:
        x1, x2 = max(b, x), min(b + h, x + w)
        if x2 > x1:
            out.append(f'<line class="hatch" x1="{x1:.2f}" y1="{y + h - (x1 - b):.2f}" '
                       f'x2="{x2:.2f}" y2="{y + h - (x2 - b):.2f}"/>')
        b += pitch
    return out


def cap_ears(x, y, w, h, r=4):
    """The two slivers between a right-rounded bar and its bounding box.

    Hatch stripes are trimmed to the box, so they overhang the rounded cap.
    Painting these two shapes in the surface colour erases the overhang and
    lets the stripes run the full length of the segment -- otherwise the tip
    is a solid block of ink that reads as a separate mark.
    """
    r = min(r, w / 2, h / 2)
    if r <= 0:
        return []
    return [f'<path class="cap-ear" d="M{x + w - r},{y} H{x + w} V{y + r} '
            f'A{r},{r} 0 0 0 {x + w - r},{y} Z"/>',
            f'<path class="cap-ear" d="M{x + w},{y + h - r} V{y + h} H{x + w - r} '
            f'A{r},{r} 0 0 0 {x + w},{y + h - r} Z"/>']


def bar_path(x, y, w, h, r=4):
    """Rect anchored to the left baseline, right corners rounded."""
    r = min(r, max(w, 0) / 2, h / 2)
    if w <= 0:
        return ""
    return (f"M{x},{y} H{x + w - r} A{r},{r} 0 0 1 {x + w},{y + r} "
            f"V{y + h - r} A{r},{r} 0 0 1 {x + w - r},{y + h} H{x} Z")


def pct_funded(budget, actual):
    return f"{float(budget) / float(actual) * 100:.0f}% funded" if float(actual) else ""


def times_salary(budget, actual):
    """Share of a duty title's compensation covered by the streams shown.

    A percentage rather than a ratio, because the bar is now a subset of
    revenue: the levy, transportation, food service, other federal grants,
    private gifts and transfers are excluded, so nothing reaches 100%.
    """
    return f"{float(budget) / float(actual) * 100:.0f}% of pay" if float(actual) else ""


def times_model(budget, actual):
    return f"{float(actual) / float(budget):.2f}&times; model" if float(budget) else ""


def render_chart(rows, vmax, ticks, fmt, chart_id, row_h=34, suffix=pct_funded):
    """rows: (label, budget, actual, tooltip_html).

    `budget` is either a number or a list of (segment key, amount) drawn as
    a stack, so the bar can show every revenue account behind a duty title.
    """
    height = PAD_T + len(rows) * row_h + 34
    scale = lambda v: PLOT_W * float(v) / float(vmax)
    x0 = PAD_L + LABEL_W
    out = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 '
           f'{PAD_L * 2 + LABEL_W + PLOT_W + VALUE_W} {height}" '
           f'role="img" aria-label="funding sources versus pay">']

    # gridlines + x axis, drawn under the marks
    axis_y = PAD_T + len(rows) * row_h + 6
    for t in ticks:
        x = x0 + scale(t)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{PAD_T}" '
                   f'x2="{x:.1f}" y2="{axis_y}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{axis_y + 16}" '
                   f'text-anchor="middle">{fmt(t)}</text>')

    for i, (label, budget, actual, tip) in enumerate(rows):
        y = PAD_T + i * row_h
        by = y + (row_h - BUDGET_H) / 2 - 2
        ay = y + (row_h - ACTUAL_H) / 2 - 2
        b_stack = budget if isinstance(budget, list) else [("budget", budget)]
        a_stack = actual if isinstance(actual, list) else [("salary", actual)]
        b_total = sum(float(v) for _k, v in b_stack)
        a_total = sum(float(v) for _k, v in a_stack)

        def draw_stack(stack, top, height, css):
            """One bar: rounded right end on the last segment, square inner
            segments separated by a 2px surface gap so the boundaries read
            without any border being drawn.

            No clip path -- the rounded end is drawn as geometry instead, so
            the chart carries no `url(#id)` fragment references at all and
            renders the same wherever it is embedded.
            """
            frag = [f'<g class="{css}-group">']
            drawn = [(k, scale(v)) for k, v in stack if scale(v) > 0]
            run = 0.0
            for n, (key, w) in enumerate(drawn):
                last = n == len(drawn) - 1
                width = w if last else max(w - 2, 0.5)
                if last:
                    frag.append(f'<path class="{css} {key}" '
                                f'd="{bar_path(x0 + run, top, width, height)}"/>')
                else:
                    frag.append(f'<rect class="{css} {key}" x="{x0 + run:.2f}" '
                                f'y="{top}" width="{width:.2f}" height="{height}"/>')
                if key == "benefits":
                    frag += hatch_lines(x0 + run, top, width, height)
                    if last:
                        frag += cap_ears(x0 + run, top, width, height)
                run += w
            frag.append("</g>")
            return frag

        out.append(f'<g class="row" tabindex="0" data-tip="{html.escape(tip)}">')
        out.append(f'<rect class="hit" x="{PAD_L}" y="{y}" '
                   f'width="{LABEL_W + PLOT_W + VALUE_W}" height="{row_h}"/>')
        out.append(f'<text class="rowlabel" x="{x0 - 12}" y="{y + row_h / 2 + 1}" '
                   f'text-anchor="end">{html.escape(label)}</text>')
        out += draw_stack(b_stack, by, BUDGET_H, "seg")
        out += draw_stack(a_stack, ay, ACTUAL_H, "act")
        out.append(f'<text class="value" x="{x0 + PLOT_W + VALUE_W - 8}" '
                   f'y="{y + row_h / 2 + 1}" text-anchor="end">'
                   f'{fmt(a_total)} <tspan class="pct">{suffix(b_total, a_total)}</tspan></text>')
        out.append('</g>')

    out.append(f'<line class="axis" x1="{x0}" y1="{axis_y}" '
               f'x2="{x0 + PLOT_W}" y2="{axis_y}"/>')
    out.append('</svg>')
    return "\n".join(out)


CSS = """
:root { color-scheme: light; }
.viz {
  --surface-1:#fcfcfb; --plane:#f9f9f7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7;
  --budget:#86b6ef; --actual:#39372f;
  --seg-1:#2a78d6;
  --seg-2:#eb6834;
  --border:rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz {
    color-scheme: dark;
    --surface-1:#1a1a19; --plane:#0d0d0d;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835;
    --budget:#184f95; --actual:#e6e5dd;
    --seg-1:#3987e5;
    --seg-2:#d95926;
    --border:rgba(255,255,255,0.10);
  }
}
:root[data-theme="dark"] .viz {
  color-scheme: dark;
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835;
  --budget:#184f95; --actual:#e6e5dd;
  --seg-1:#3987e5;
  --seg-2:#d95926;
  --border:rgba(255,255,255,0.10);
}
body { margin:0; background:var(--plane); }
.viz {
  background:var(--plane); color:var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  padding:32px 24px 48px; max-width:1120px; margin:0 auto;
}
h1 { font-size:22px; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em; }
.sub { color:var(--text-secondary); font-size:13px; margin:0 0 28px; max-width:76ch; line-height:1.5; }
section { background:var(--surface-1); border:1px solid var(--border); border-radius:10px;
          padding:20px 20px 12px; margin-bottom:28px; position:relative; }
h2 { font-size:15px; font-weight:600; margin:0 0 2px; }
h3 { font-size:12px; font-weight:600; margin:18px 0 2px; display:flex;
     flex-wrap:wrap; gap:4px 12px; align-items:baseline;
     padding-bottom:6px; border-bottom:1px solid var(--grid); }
h3 span { font-weight:400; color:var(--muted); font-variant-numeric:tabular-nums; }
.note { color:var(--text-secondary); font-size:12.5px; margin:0 0 14px; line-height:1.5; max-width:78ch; }
.stats { display:flex; gap:28px; flex-wrap:wrap; margin:0 0 18px; }
.stat .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.06em; }
.stat .v { font-size:24px; font-weight:600; letter-spacing:-0.02em; }
.legend { display:flex; gap:18px; align-items:center; font-size:12px;
          color:var(--text-secondary); margin:16px 0 4px; }
.legend i { display:inline-block; border-radius:2px; margin-right:6px; vertical-align:-1px; }
.legend .b { width:18px; height:9px; background:var(--budget); }
.legend .a { width:18px; height:5px; background:var(--actual); }
.legend .a.hatch { height:9px; background:repeating-linear-gradient(45deg,
  var(--actual) 0 2.4px, var(--surface-1) 2.4px 4.6px); }
.legend .s { width:12px; height:12px; border-radius:2px; }
.legend .s.apportionment { background:var(--seg-1); }
.legend .s.sped          { background:var(--seg-2); }
.legend { flex-wrap:wrap; gap:6px 16px; }
.legend .hint { color:var(--muted); }

.chk .sw.cas   { background:var(--seg-2); }
.chk .sw.cls   { background:var(--seg-3); }
.chk .sw.sped  { background:var(--seg-4); }
.chk input:not(:checked) ~ .sw { opacity:.28; }
.chk:has(input:not(:checked)) { color:var(--muted); }
.chart { width:100%; height:auto; display:block; overflow:visible; }
.grid { stroke:var(--grid); stroke-width:1; }
.axis { stroke:var(--axis); stroke-width:1; }
.tick, .rowlabel, .value { font-size:12px; fill:var(--text-secondary); }
.tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
.rowlabel { fill:var(--text-primary); }
.value { font-variant-numeric:tabular-nums; }
.pct { fill:var(--muted); }
.budget { fill:var(--budget); }
.seg.apportionment { fill:var(--seg-1); }
.seg.sped          { fill:var(--seg-2); }
.act-group { stroke:var(--surface-1); stroke-width:2; paint-order:stroke; }
.act.salary   { fill:var(--actual); }
.act.budget   { fill:var(--actual); }
.act.benefits { fill:var(--actual); }
.hatch { stroke:var(--surface-1); stroke-width:2.2; stroke-linecap:butt; }
/* erases hatch overhang outside the rounded cap; stroked as well as filled so
   no fringe of stripe survives along the curve */
.cap-ear { fill:var(--surface-1); stroke:var(--surface-1); stroke-width:1.6; }
.hit { fill:transparent; }
.row:hover .hit, .row:focus .hit { fill:var(--grid); opacity:.5; }
.row { outline:none; }
#tip { position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
       background:var(--surface-1); color:var(--text-primary);
       border:1px solid var(--border); border-radius:8px; padding:9px 11px;
       font-size:12px; line-height:1.55; box-shadow:0 6px 20px rgba(0,0,0,.16);
       font-variant-numeric:tabular-nums; z-index:9; max-width:300px; }
#tip b { font-weight:600; }
details { margin-top:8px; }
summary { font-size:12.5px; color:var(--text-secondary); cursor:pointer; padding:6px 0; }
table { border-collapse:collapse; font-size:12px; width:100%;
        font-variant-numeric:tabular-nums; margin-top:8px; }
th, td { text-align:right; padding:5px 8px; border-bottom:1px solid var(--grid); }
th:first-child, td:first-child { text-align:left; }
th { color:var(--muted); font-weight:500; font-size:11px;
     text-transform:uppercase; letter-spacing:0.05em; }
tbody tr:last-child td { font-weight:600; border-bottom:none; }
footer { color:var(--muted); font-size:11.5px; line-height:1.6; max-width:80ch; }
"""

JS = """
const tip = document.getElementById('tip');
function show(e, t) {
  tip.innerHTML = t; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 10) + 'px';
  tip.style.top  = Math.min(e.clientY + 14, innerHeight - r.height - 10) + 'px';
}
for (const g of document.querySelectorAll('.row')) {
  const t = g.dataset.tip;
  g.addEventListener('mousemove', e => show(e, t));
  g.addEventListener('mouseleave', () => tip.style.opacity = 0);
  g.addEventListener('focus', () => {
    const b = g.getBoundingClientRect();
    show({clientX: b.left + 40, clientY: b.top}, t);
  });
  g.addEventListener('blur', () => tip.style.opacity = 0);
}
"""


def duty_rows_by_class(data, tip_fn):
    """{staff class: [(duty title, budget, actual, tooltip), ...]} paid desc.

    tip_fn(csv_row, paid, allocation) returns the tooltip markup, which
    differs between the local page and the shareable one.
    """
    by_class = {}
    for r in sorted(data, key=lambda r: -float(r["total_final_salary"])):
        paid = Decimal(r["total_final_salary"] or "0")
        comp = [("salary", paid), ("benefits", Decimal(r["benefits_paid"] or "0"))]
        stack = [(k, Decimal(r[f"rev_{k}"] or "0")) for k in SEGMENT_KEYS]
        by_class.setdefault(r["state_staff_class"], []).append(
            (r["duty_title"], stack, comp, tip_fn(r, comp, stack)))
    return by_class


def stack_tip(r, comp, stack):
    """Tooltip listing every revenue segment behind a duty title."""
    total = sum(v for _k, v in stack)
    paid = dict(comp)
    comp_total = sum(paid.values())
    lines = "".join(
        f'<br>{html.escape(SEGMENT_LABEL[k])} {money(v)}'
        for k, v in stack if v > 0)
    return (f'<b>{html.escape(r["duty_title"])}</b> &middot; {r["state_staff_class"]}<br>'
            f'Salary {money(paid["salary"])} + benefits {money(paid["benefits"])} '
            f'= {money(comp_total)}<br>'
            f'Revenue that pays them {money(total)} '
            f'({total / comp_total:.2f}&times; comp){lines}<br>'
            f'{float(r["assignment_fte"]):,.1f} FTE &middot; {r["employees"]} staff')


def class_dollar_rollup(data):
    """Per staff class: (name, total paid, state allocation), paid desc."""
    acc, order = {}, []
    for r in data:
        c = r["state_staff_class"]
        if c not in acc:
            acc[c] = [Decimal(0), Decimal(0), Decimal(0)]
            order.append(c)
        acc[c][0] += Decimal(r["total_compensation"] or "0")
        acc[c][1] += Decimal(r["rev_apportionment"] or "0")
        acc[c][2] += Decimal(r["staff_revenue_all_sources"] or "0")
    order.sort(key=lambda c: -acc[c][0])
    return [(CLASS_NAME[c], *acc[c]) for c in order]


def rollup_cells(rollup):
    """Table rows for a dollar roll-up, with a districtwide total."""
    def row(name, paid, staff, allacc):
        return (name, money(paid), money(staff), f"{staff / paid * 100:.0f}%",
                money(allacc), f"{allacc / paid * 100:.0f}%")
    out = [row(*r) for r in rollup]
    out.append(row("All staff", *(sum(r[i] for r in rollup) for i in (1, 2, 3))))
    return out


ROLLUP_HEADERS = ["Staff class", "Pay", "Apportionment staff units",
                  "Share", "Sources shown", "% of pay"]


def table(headers, rows, open=False, summary="Table view"):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<details{" open" if open else ""}><summary>{summary}</summary>'
            f"<table><thead><tr>{head}</tr>"
            f"</thead><tbody>{body}</tbody></table></details>")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path,
                    default=Path("output/duty_funding/sps_2024-25_duty_state_funding.csv"))
    ap.add_argument("--title", default="Seattle Public Schools, 2024-25")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("output/duty_funding/sps_2024-25_variance.html"))
    args = ap.parse_args()

    data = [r for r in csv.DictReader(args.data.open()) if r["state_staff_class"] != "unmapped"]
    D = lambda r, k: Decimal(r[k] or "0")

    # --- chart 1: dollars per duty title -------------------------------
    by_class = duty_rows_by_class(data, stack_tip)
    rows1 = [row for rows in by_class.values() for row in rows]
    comp_tot = sum(v for _l, _s, comp, _t in rows1 for _k, v in comp)
    salary_tot = sum(dict(comp)["salary"] for _l, _s, comp, _t in rows1)
    state_tot = sum(v for _l, stack, _a, _t in rows1 for _k, v in stack)
    # the scale must clear the tallest stack on either bar
    # the axis is fixed at the all-sources maximum so bars never jump when a
    # source is switched on or off
    ticks1 = nice_ticks(max(max(sum(float(v) for _k, v in r[2]) for r in rows1),
                            max(sum(float(v) for _k, v in r[1]) for r in rows1)), 25e6)
    rollup = class_dollar_rollup(data)
    code_of = {v: k for k, v in CLASS_NAME.items()}
    facets = "\n".join(
        f'<h3>{html.escape(name)}'
        f'<span>{money(paid)} pay &middot; {money(allacc)} state '
        f'&middot; {allacc / paid * 100:.0f}% of pay</span></h3>'
        f'{render_chart(by_class[code_of[name]], ticks1[-1], ticks1, money,
                        "c1" + code_of[name], suffix=times_salary)}'
        for name, paid, _staff, allacc in rollup)

    seg_totals = {k: sum(v for _l, stack, _a, _t in rows1
                         for kk, v in stack if kk == k) for k in SEGMENT_KEYS}
    account_rows = [(SEGMENT_LABEL[k], money(seg_totals[k]),
                     f"{seg_totals[k] / state_tot * 100:.1f}%")
                    for k in SEGMENT_KEYS if seg_totals[k]]
    account_rows.append(("The sources shown, paying people", money(state_tot), "100.0%"))

    # --- chart 2: FTE per staff class ----------------------------------
    classes, order = {}, []
    for r in data:
        c = r["state_staff_class"]
        if c not in classes:
            classes[c] = {"actual": Decimal(0),
                          "model": D(r, "state_model_fte_for_class")}
            order.append(c)
        classes[c]["actual"] += D(r, "assignment_fte")
    order.sort(key=lambda c: -float(classes[c]["actual"]))

    rows2 = []
    for c in order:
        model, actual = classes[c]["model"], classes[c]["actual"]
        rows2.append((
            CLASS_NAME[c], model, actual,
            f'<b>{html.escape(CLASS_NAME[c])}</b><br>'
            f'Actual {actual:,.1f} FTE<br>Prototypical {model:,.1f} FTE<br>'
            f'Over model by {actual - model:,.1f} FTE '
            f'({actual / model:.2f}&times;)'))
    fte_actual = sum(r[2] for r in rows2)
    fte_model = sum(r[1] for r in rows2)
    ticks2 = nice_ticks(max(float(r[2]) for r in rows2), 1000)

    legend = ('<div class="legend">'
              + "".join(f'<span><i class="s {k}"></i>{html.escape(SEGMENT_LABEL[k])}</span>'
                        for k in SEGMENT_KEYS)
              + '<span><i class="a"></i>Salary paid (S-275)</span>'
              + '<span><i class="a hatch"></i>Benefits (F-196 object 4)</span></div>')
    legend2 = ('<div class="legend">'
               '<span><i class="b"></i>Prototypical staff units</span>'
               '<span><i class="a"></i>Actual FTE</span></div>')

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revenue vs pay by duty title</title>
<style>{CSS}</style></head>
<body><div class="viz">
<h1>How much of the payroll the state pays for</h1>
<p class="sub">{html.escape(args.title)}. Dev preview &mdash; the shareable
version is built by <code>build_artifact_page.py</code>. The budget bar is state
funding: the 1191F prototypical CIS/CAS/CLS staff units plus state special
education. The measure bar is S-275 salary plus F-196 benefits.</p>

<section>
<h2>1 &middot; Pay per duty title, and how much of it state funding covers</h2>
<p class="note">Apportionment staff units are divided within each class by FTE,
reproducing the model's flat rate per unit. State special education follows
program 21 payroll instead, scaled by the share of program 21 spending that is
salaries and benefits. The measure bar is S-275 salary plus benefits, at the
F-196 ratio of object 4 to objects 2 and 3
({(comp_tot - salary_tot) / salary_tot * 100:.1f}% of salary).</p>
<div class="stats">
  <div class="stat"><div class="k">Salary paid</div><div class="v">{money(salary_tot)}</div></div>
  <div class="stat"><div class="k">+ Benefits (F-196)</div><div class="v">{money(comp_tot - salary_tot)}</div></div>
  <div class="stat"><div class="k">State funding</div><div class="v">{money(state_tot)}</div></div>

  <div class="stat"><div class="k">Share of pay</div><div class="v">{state_tot / comp_tot * 100:.0f}%</div></div>
</div>
{table(["Revenue source", "Amount", "Share of sources shown"], account_rows, open=True,
        summary="Where the money comes from")}
{table(ROLLUP_HEADERS, rollup_cells(rollup), open=True,
        summary="Staff class roll-up")}
{legend}
{facets}
{table(["Duty title"] + [SEGMENT_LABEL[k] for k in SEGMENT_KEYS]
       + ["These streams", "Compensation", "% of pay"],
       [(html.escape(l), *[money(v) for _k, v in stack],
         money(sum(v for _k, v in stack)), money(sum(v for _k, v in comp)),
         f"{sum(v for _k, v in stack) / sum(v for _k, v in comp):.2f}x")
        for l, stack, comp, _ in rows1])}
</section>

<section>
<h2>2 &middot; Actual FTE against the prototypical staff units the state funded</h2>
<p class="note">The state funds three staff classes at flat per-FTE rates. Every
S-275 duty root maps to exactly one. Districtwide SPS reports
{fte_actual:,.0f} FTE against a model of {fte_model:,.0f} &mdash;
{fte_actual / fte_model:.2f}&times;.</p>
{legend2}
{render_chart(rows2, ticks2[-1], ticks2, fte, "c2", row_h=48, suffix=times_model)}
{table(["Staff class", "Actual FTE", "Prototypical FTE", "Over model", "Ratio"],
       [(html.escape(l), f"{a:,.1f}", f"{b:,.1f}", f"{a - b:,.1f}", f"{a / b:.2f}x")
        for l, b, a, _ in rows2])}
</section>

<footer>Sources: <code>safs_s275</code> (BigQuery, 2024-25 final report,
ccddd 17001) and pages 1&ndash;7 of the district's 1191F Final Apportionment
Summary, parsed by <code>tools/duty_funding/parse_bea_pages.py</code>. The S-275
covers all staff regardless of funding source, so the gap in chart 1 is levy,
federal, grant and separately-allocated state money &mdash; not a deficit.</footer>
</div><div id="tip"></div>
<script>{JS}</script></body></html>"""

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
