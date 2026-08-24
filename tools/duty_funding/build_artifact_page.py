#!python3
"""Shareable page version of the duty-title funding charts.

Same two bullet charts as `build_variance_charts.py`, wrapped for publishing
as an Artifact: page content only (no doctype/html/head/body -- those are
added at publish time), Google Fonts, and full light/dark token coverage
including the un-stamped `prefers-color-scheme` state.

    python3 -m tools.duty_funding.build_artifact_page \
        -o output/duty_funding/artifact.html
"""

import argparse
import csv
import html
from decimal import Decimal
from pathlib import Path

from .funding_sources import SEGMENT_KEYS, SEGMENT_LABEL
from .build_variance_charts import (
    CLASS_NAME, ROLLUP_HEADERS, class_dollar_rollup, duty_rows_by_class, fte,
    money, nice_ticks, render_chart, rollup_cells, times_model,
    times_salary,
)

FONTS = ("https://fonts.googleapis.com/css2?"
         "family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&"
         "family=Public+Sans:wght@400;500;600&"
         "family=IBM+Plex+Mono:wght@400;500&display=swap")

CSS = """
:root {
  color-scheme: light;
  --plane:#f9f9f7; --surface-1:#fcfcfb;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --budget:#86b6ef; --actual:#39372f; --accent:#2a78d6;
  --seg-1:#2a78d6;
  --seg-2:#eb6834;
  --serif:"Newsreader", Georgia, "Times New Roman", serif;
  --sans:"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane:#0d0d0d; --surface-1:#1a1a19;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --budget:#184f95; --actual:#e6e5dd; --accent:#3987e5;
    --seg-1:#3987e5;
    --seg-2:#d95926;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane:#0d0d0d; --surface-1:#1a1a19;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --budget:#184f95; --actual:#e6e5dd; --accent:#3987e5;
  --seg-1:#3987e5;
  --seg-2:#d95926;
}

body { background:var(--plane); color:var(--text-primary); font-family:var(--sans); margin:0; }
.wrap { max-width:1140px; margin:0 auto; padding:56px 24px 72px;
        display:flex; flex-direction:column; gap:40px; }
*:focus-visible { outline:2px solid var(--accent); outline-offset:3px; border-radius:3px; }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; } }

/* --- masthead ---------------------------------------------------- */
.masthead { display:flex; flex-direction:column; gap:18px;
            border-bottom:1px solid var(--grid); padding-bottom:32px; }
.slug { font-family:var(--mono); font-size:11px; letter-spacing:.09em;
        text-transform:uppercase; color:var(--muted);
        display:flex; flex-wrap:wrap; gap:8px 14px; }
.slug span { white-space:nowrap; }
.slug span + span::before { content:"/"; margin-right:14px; color:var(--grid); }
h1 { font-family:var(--serif); font-weight:600; font-size:clamp(34px,5.2vw,54px);
     line-height:1.04; letter-spacing:-0.02em; margin:0; text-wrap:balance; max-width:19ch; }
.dek { font-size:17px; line-height:1.6; color:var(--text-secondary);
       max-width:62ch; margin:0; }
.dek em { font-style:italic; font-family:var(--serif); font-size:18px; color:var(--text-primary); }

/* --- hero figure + stats ----------------------------------------- */
.headline { display:grid; gap:28px 44px; align-items:end;
            grid-template-columns:minmax(210px,auto) 1fr; }
.hero .fig { font-family:var(--mono); font-weight:500;
             font-size:clamp(72px,11vw,116px); line-height:.86;
             letter-spacing:-0.045em; color:var(--accent); }
.hero .cap { font-size:14px; line-height:1.5; color:var(--text-secondary);
             margin-top:12px; max-width:24ch; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
         gap:1px; background:var(--grid); border:1px solid var(--grid); }
.stat { background:var(--surface-1); padding:14px 16px; display:flex;
        flex-direction:column; gap:5px; }
.stat .k { font-family:var(--mono); font-size:10.5px; letter-spacing:.08em;
           text-transform:uppercase; color:var(--muted); }
.stat .v { font-family:var(--mono); font-size:23px; font-weight:500;
           letter-spacing:-0.02em; font-variant-numeric:tabular-nums; }

/* --- how to read -------------------------------------------------- */
.howto { display:flex; align-items:center; gap:22px; flex-wrap:wrap;
         background:var(--surface-1); border:1px solid var(--border);
         border-radius:8px; padding:16px 20px; font-size:13.5px;
         color:var(--text-secondary); line-height:1.55; }
.howto svg { flex:none; }
.howto p { margin:0; max-width:58ch; }
.howto b { color:var(--text-primary); font-weight:600; }

/* --- chart sections ----------------------------------------------- */
section { display:flex; flex-direction:column; gap:16px; }
.eyebrow { font-family:var(--mono); font-size:11px; letter-spacing:.09em;
           text-transform:uppercase; color:var(--accent); }
h2 { font-family:var(--serif); font-weight:600; font-size:27px; line-height:1.2;
     letter-spacing:-0.015em; margin:0; text-wrap:balance; max-width:30ch; }
.note { font-size:14px; line-height:1.6; color:var(--text-secondary);
        max-width:66ch; margin:0; }
.note code { font-family:var(--mono); font-size:12.5px; color:var(--text-primary); }
.plot { background:var(--surface-1); border:1px solid var(--border);
        border-radius:10px; padding:22px 18px 12px; overflow-x:auto; }
.chart { width:100%; min-width:760px; height:auto; display:block; overflow:visible; }
.grid { stroke:var(--grid); stroke-width:1; }
.axis { stroke:var(--axis); stroke-width:1; }
.tick, .rowlabel, .value { font-family:var(--sans); font-size:12.5px; fill:var(--text-secondary); }
.tick { font-family:var(--mono); fill:var(--muted); font-size:11px; }
.rowlabel { fill:var(--text-primary); }
.value { font-family:var(--mono); font-size:12px; font-variant-numeric:tabular-nums; }
.pct { fill:var(--muted); }
.budget { fill:var(--budget); }
.seg.apportionment { fill:var(--seg-1); }
.seg.sped          { fill:var(--seg-2); }

/* --- stack key ----------------------------------------------------- */
.key { display:flex; flex-wrap:wrap; gap:8px 20px; font-size:12.5px;
       color:var(--text-secondary); }
.key span { display:flex; align-items:center; gap:7px; white-space:nowrap; }
.key i { width:11px; height:11px; border-radius:2px; flex:none; }
.key .apportionment { background:var(--seg-1); }
.key .sped          { background:var(--seg-2); }
.key .measure { background:var(--actual); width:16px; height:6px; border-radius:2px; }
.key .hatch { width:16px; height:9px; border-radius:2px;
  background:repeating-linear-gradient(45deg,
    var(--actual) 0 2.4px, var(--surface-1) 2.4px 4.6px); }
.key .budget { background:var(--budget); width:16px; height:9px; border-radius:2px; }
.act-group { stroke:var(--surface-1); stroke-width:2; paint-order:stroke; }
.act.salary   { fill:var(--actual); }
.act.budget   { fill:var(--actual); }
.act.benefits { fill:var(--actual); }
.hatch { stroke:var(--surface-1); stroke-width:2.2; stroke-linecap:butt; }
.cap-ear { fill:var(--surface-1); stroke:var(--surface-1); stroke-width:1.6; }
.hit { fill:transparent; }
.row { outline:none; }
.row:hover .hit, .row:focus .hit { fill:var(--grid); opacity:.5; }

.chk .sw.cas   { background:var(--seg-2); }
.chk .sw.cls   { background:var(--seg-3); }
.chk .sw.sped  { background:var(--seg-4); }
.chk input:not(:checked) ~ .sw { opacity:.25; }
.chk:has(input:not(:checked)) { color:var(--muted); }

/* --- class facets -------------------------------------------------- */
.facets { display:flex; flex-direction:column; gap:30px; }
.facet { margin:0; display:flex; flex-direction:column; gap:12px; }
figcaption { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 24px;
             border-bottom:1px solid var(--grid); padding-bottom:10px; }
.facet h3 { font-family:var(--serif); font-size:19px; font-weight:600;
            letter-spacing:-0.01em; margin:0; }
.facet-stats { display:flex; flex-wrap:wrap; gap:4px 20px; margin-left:auto;
               font-size:12.5px; color:var(--text-secondary); }
.facet-stats em { font-family:var(--mono); font-style:normal; font-weight:500;
                  color:var(--text-primary); font-variant-numeric:tabular-nums; }

/* --- tables ------------------------------------------------------- */
.rollup { border:1px solid var(--border); border-radius:10px;
          background:var(--surface-1); padding:4px 18px 6px; overflow-x:auto; }
.rollup table { margin-bottom:0; font-size:13px; }
.rollup td { padding:9px 10px; }
.rollup tbody tr:last-child td { font-weight:600; border-bottom:none;
          color:var(--text-primary); }
.rollup tbody tr:last-child td:first-child { font-family:var(--sans); }
details { border-top:1px solid var(--grid); }
summary { font-family:var(--mono); font-size:11px; letter-spacing:.08em;
          text-transform:uppercase; color:var(--muted); cursor:pointer;
          padding:12px 0; list-style:none; }
summary::-webkit-details-marker { display:none; }
summary::before { content:"+ "; }
details[open] summary::before { content:"- "; }
summary:hover { color:var(--text-primary); }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:12.5px;
        font-variant-numeric:tabular-nums; margin-bottom:14px; }
th, td { text-align:right; padding:7px 10px; border-bottom:1px solid var(--grid);
         white-space:nowrap; }
/* labels may wrap so a long one never pushes numeric columns out of view */
th:first-child, td:first-child { text-align:left; white-space:normal;
                                 min-width:16ch; }
td { font-family:var(--mono); }
td:first-child { font-family:var(--sans); }
th { font-family:var(--mono); font-size:10.5px; font-weight:500; color:var(--muted);
     letter-spacing:.07em; text-transform:uppercase; }

/* --- method ------------------------------------------------------- */
.method { border-top:1px solid var(--grid); padding-top:32px;
          display:grid; gap:26px 44px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
.method h3 { font-family:var(--mono); font-size:11px; letter-spacing:.08em;
             text-transform:uppercase; color:var(--muted); margin:0; font-weight:500; }
.method > div { display:flex; flex-direction:column; gap:12px; }
.method p { margin:0; font-size:13.5px; line-height:1.65; color:var(--text-secondary); }
.method p b { color:var(--text-primary); font-weight:600;
              font-family:var(--mono); font-size:12.5px; }
.method code { font-family:var(--mono); font-size:12px; color:var(--text-primary); }
footer { font-family:var(--mono); font-size:11.5px; line-height:1.7; color:var(--muted);
         border-top:1px solid var(--grid); padding-top:22px; max-width:78ch; }

#tip { position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
       background:var(--surface-1); color:var(--text-primary);
       border:1px solid var(--border); border-radius:8px; padding:10px 12px;
       font-size:12.5px; line-height:1.6; box-shadow:0 8px 26px rgba(0,0,0,.18);
       font-variant-numeric:tabular-nums; z-index:99; max-width:310px;
       font-family:var(--sans); }
#tip b { font-weight:600; }
#tip .m { font-family:var(--mono); }

@media (max-width:720px) {
  .headline { grid-template-columns:1fr; align-items:start; }
  .wrap { padding:36px 16px 56px; gap:32px; }
}
"""

JS = """
const tip = document.getElementById('tip');
function show(x, y, t) {
  tip.innerHTML = t; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(x + 16, innerWidth - r.width - 12) + 'px';
  tip.style.top  = Math.min(y + 16, innerHeight - r.height - 12) + 'px';
}
for (const g of document.querySelectorAll('.row')) {
  const t = g.dataset.tip;
  g.addEventListener('mousemove', e => show(e.clientX, e.clientY, t));
  g.addEventListener('mouseleave', () => tip.style.opacity = 0);
  g.addEventListener('focus', () => {
    const b = g.getBoundingClientRect();
    show(b.left + 40, b.top, t);
  });
  g.addEventListener('blur', () => tip.style.opacity = 0);
}
"""

HOWTO_SVG = """<svg width="176" height="54" viewBox="0 0 176 54" aria-hidden="true">
  <rect x="1" y="2" width="70" height="26" fill="var(--seg-1)"/>
  <rect x="73" y="2" width="30" height="26" fill="var(--seg-2)"/>
  <path d="M105,2 H114 a4,4 0 0 1 4,4 V24 a4,4 0 0 1 -4,4 H105 Z" fill="var(--seg-3)"/>
  <g stroke="var(--surface-1)" stroke-width="2" paint-order="stroke">
    <rect x="1" y="9" width="118" height="12" fill="var(--actual)"/>
    <path d="M121,9 H157 a4,4 0 0 1 4,4 V17 a4,4 0 0 1 -4,4 H121 Z" fill="var(--actual)"/>
    <line class="hatch" x1="121.00" y1="15.00" x2="127.00" y2="9.00"/><line class="hatch" x1="121.00" y1="21.00" x2="133.00" y2="9.00"/><line class="hatch" x1="127.00" y1="21.00" x2="139.00" y2="9.00"/><line class="hatch" x1="133.00" y1="21.00" x2="145.00" y2="9.00"/><line class="hatch" x1="139.00" y1="21.00" x2="151.00" y2="9.00"/><line class="hatch" x1="145.00" y1="21.00" x2="157.00" y2="9.00"/><line class="hatch" x1="151.00" y1="21.00" x2="161.00" y2="11.00"/><line class="hatch" x1="157.00" y1="21.00" x2="161.00" y2="17.00"/><path class="cap-ear" d="M157,9 H161 V13 A4,4 0 0 0 157,9 Z"/><path class="cap-ear" d="M161,17 V21 H157 A4,4 0 0 0 161,17 Z"/>
  </g>
  <text x="59" y="47" text-anchor="middle" font-family="var(--mono)" font-size="9.5"
        letter-spacing=".08em" fill="var(--muted)">BUDGET</text>
  <text x="166" y="47" text-anchor="end" font-family="var(--mono)" font-size="9.5"
        letter-spacing=".08em" fill="var(--muted)">ACTUAL</text>
</svg>"""


def table(headers, rows, open=False, summary="Table view"):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<details{" open" if open else ""}><summary>{summary}</summary>'
            f'<div class="scroll"><table>'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path,
                    default=Path("output/duty_funding/sps_2024-25_duty_state_funding.csv"))
    ap.add_argument("--revenue", type=Path,
                    default=Path("output/duty_funding/sps_2024-25_revenue_sources.csv"),
                    help="revenue-source summary from build_duty_funding")
    ap.add_argument("--roles", type=Path,
                    default=Path("output/duty_funding/sps_2024-25_model_roles.csv"),
                    help="1191EDF staffing roles from build_duty_funding")
    ap.add_argument("-o", "--out", type=Path,
                    default=Path("output/duty_funding/artifact.html"))
    args = ap.parse_args()

    data = [r for r in csv.DictReader(args.data.open()) if r["state_staff_class"] != "unmapped"]
    summary = {r["segment"]: Decimal(r["staff_revenue"])
               for r in csv.DictReader(args.revenue.open())}
    gross_revenue = summary["_gross"]
    off_chart = summary["_off_chart"]
    staff_spend = summary["_staff_spend"]
    sped_share = summary["_sped_staff_share"]
    model_benefits = summary["_model_benefits"]
    non_staff = summary["_non_staff"]
    D = lambda r, k: Decimal(r[k] or "0")

    def tip(r, comp, stack):
        total = sum(v for _k, v in stack)
        paid = dict(comp)
        comp_total = sum(paid.values())
        lines = "".join(f'<br>{html.escape(SEGMENT_LABEL[k])} {money(v)}'
                        for k, v in stack if v > 0)
        return (f'<b>{html.escape(r["duty_title"])}</b><br><span class="m">'
                f'Salary {money(paid["salary"])} + benefits {money(paid["benefits"])}'
                f' = {money(comp_total)}<br>'
                f'Revenue that pays them {money(total)} '
                f'({total / comp_total:.2f}&times; comp){lines}<br>'
                f'{float(r["assignment_fte"]):,.1f} FTE across {r["employees"]} staff</span>')

    by_class = duty_rows_by_class(data, tip)
    rows1 = [row for rows in by_class.values() for row in rows]
    comp_tot = sum(v for _l, _s, comp, _t in rows1 for _k, v in comp)
    salary_tot = sum(dict(comp)["salary"] for _l, _s, comp, _t in rows1)
    state_tot = sum(v for _l, stack, _a, _t in rows1 for _k, v in stack)
    seg_totals = {k: sum(v for _l, stack, _a, _t in rows1
                         for kk, v in stack if kk == k) for k in SEGMENT_KEYS}
    staff_tot = seg_totals["apportionment"]
    # one scale shared by all three facets; it must clear the tallest stack too
    ticks1 = nice_ticks(max(max(sum(float(v) for _k, v in r[2]) for r in rows1),
                            max(sum(float(v) for _k, v in r[1]) for r in rows1)), 25e6)
    rollup = class_dollar_rollup(data)
    code_of = {v: k for k, v in CLASS_NAME.items()}
    facets = "\n".join(
        f'<figure class="facet" data-cls="{code_of[name]}">'
        f'<figcaption><h3>{html.escape(name)}</h3>'
        f'<div class="facet-stats">'
        f'<span><em>{money(paid)}</em> pay</span>'
        f'<span><em>{money(allacc)}</em> state funding</span>'
        f'<span><em>{allacc / paid * 100:.0f}%</em> of pay</span>'
        f'</div></figcaption>'
        f'<div class="plot">'
        f'{render_chart(by_class[code_of[name]], ticks1[-1], ticks1, money,
                        "c1" + code_of[name], suffix=times_salary)}'
        f'</div></figure>'
        for name, paid, _staff, allacc in rollup)

    stack_key = ('<div class="key">'
                 + "".join(f'<span><i class="{k}"></i>{html.escape(SEGMENT_LABEL[k])}</span>'
                           for k in SEGMENT_KEYS)
                 + '<span><i class="measure"></i>Salary paid (S-275)</span>'
                 + '<span><i class="hatch"></i>Benefits (F-196 object 4)</span></div>')
    def gf(v):
        return f"{v / gross_revenue * 100:.1f}%"
    account_rows = [(SEGMENT_LABEL[k], money(seg_totals[k]),
                     f"{seg_totals[k] / state_tot * 100:.1f}%", gf(seg_totals[k]))
                    for k in SEGMENT_KEYS if seg_totals[k]]
    account_rows.append(("<b>The sources shown, paying people</b>",
                         f"<b>{money(state_tot)}</b>", "<b>100.0%</b>",
                         f"<b>{gf(state_tot)}</b>"))
    account_rows.append(("Not attributed: these sources buy things, not people",
                         money(non_staff), "", gf(non_staff)))
    account_rows.append(("Not shown: LAP, bilingual, highly capable, "
                         "transportation, food service, Title I, other federal, "
                         "the local levy, private gifts and transfers",
                         money(off_chart), "", gf(off_chart)))
    account_rows.append(("<b>All General Fund revenue</b>",
                         f"<b>{money(gross_revenue)}</b>", "",
                         f"<b>{gf(gross_revenue)}</b>"))

    classes, order = {}, []
    for r in data:
        c = r["state_staff_class"]
        if c not in classes:
            classes[c] = {"actual": Decimal(0), "model": D(r, "state_model_fte_for_class")}
            order.append(c)
        classes[c]["actual"] += D(r, "assignment_fte")
    order.sort(key=lambda c: -float(classes[c]["actual"]))
    rows2 = []
    for c in order:
        model, actual = classes[c]["model"], classes[c]["actual"]
        rows2.append((
            CLASS_NAME[c], model, actual,
            f'<b>{html.escape(CLASS_NAME[c])}</b><br><span class="m">'
            f'Actual {actual:,.1f} FTE &middot; model {model:,.1f} FTE<br>'
            f'Over model by {actual - model:,.1f} ({actual / model:.2f}&times;)</span>'))
    fte_actual = sum(r[2] for r in rows2)
    fte_model = sum(r[1] for r in rows2)
    ticks2 = nice_ticks(max(float(r[2]) for r in rows2), 1000)

    # --- chart 3: the same three classes, in dollars --------------------
    per_class = {}
    for r in data:
        c = per_class.setdefault(r["state_staff_class"],
                                 {k: Decimal(0) for k in
                                  ("salary", "benefits", *SEGMENT_KEYS)})
        c["salary"] += D(r, "total_final_salary")
        c["benefits"] += D(r, "benefits_paid")
        for k in SEGMENT_KEYS:
            c[k] += D(r, f"rev_{k}")
    rows3 = []
    for cls in sorted(per_class, key=lambda c: -(per_class[c]["salary"]
                                                 + per_class[c]["benefits"])):
        c = per_class[cls]
        pay = c["salary"] + c["benefits"]
        state = sum(c[k] for k in SEGMENT_KEYS)
        rows3.append((
            CLASS_NAME[cls],
            [(k, c[k]) for k in SEGMENT_KEYS],
            [("salary", c["salary"]), ("benefits", c["benefits"])],
            f'<b>{html.escape(CLASS_NAME[cls])}</b><br><span class="m">'
            f'Salary {money(c["salary"])} + benefits {money(c["benefits"])} '
            f'= {money(pay)}<br>'
            f'State funding {money(state)} ({state / pay * 100:.0f}% of pay)'
            + "".join(f'<br>{html.escape(SEGMENT_LABEL[k])} {money(c[k])}'
                      for k in SEGMENT_KEYS if c[k])
            + '</span>'))
    ticks3 = nice_ticks(max(sum(float(v) for _k, v in r[2]) for r in rows3), 100e6)


    cls = classes  # shorthand for the copy below

    # --- chart 4: the model's own staffing roles ------------------------
    roles = list(csv.DictReader(args.roles.open()))
    by_class_role = {}
    for r in sorted(roles, key=lambda r: -float(r["actual_fte"])):
        model_f, actual_f = Decimal(r["model_fte"]), Decimal(r["actual_fte"])
        model_d, actual_d = Decimal(r["model_dollars"]), Decimal(r["actual_pay"])
        by_class_role.setdefault(r["staff_class"], []).append((
            r["role"], model_f, actual_f,
            f'<b>{html.escape(r["role"])}</b><br><span class="m">'
            f'{actual_f:,.1f} FTE employed against {model_f:,.1f} funded'
            + (f' ({actual_f / model_f:.2f}&times;)' if model_f else
               ' &mdash; no staff unit at all')
            + f'<br>Pay {money(actual_d)} against {money(model_d)} allocated'
            + (f' ({model_d / actual_d * 100:.0f}% of pay)' if actual_d else '')
            + '</span>'))
    ticks5 = nice_ticks(max(float(r["actual_fte"]) for r in roles), 500)
    role_by = {r["role"]: r for r in roles}
    counselors_model = Decimal(role_by["Guidance counselors"]["model_fte"])
    counselors_actual = Decimal(role_by["Guidance counselors"]["actual_fte"])
    nurses_model = Decimal(role_by["School nurses"]["model_fte"])
    nurses_actual = Decimal(role_by["School nurses"]["actual_fte"])
    ta = role_by["Teaching assistance and family involvement"]
    ta_model, ta_actual = Decimal(ta["model_fte"]), Decimal(ta["actual_fte"])
    unfunded_fte = sum(Decimal(r["actual_fte"]) for r in roles
                       if not Decimal(r["model_fte"]))
    facets_roles = "\n".join(
        f'<figure class="facet">'
        f'<figcaption><h3>{html.escape(name)}</h3>'
        f'<div class="facet-stats">'
        f'<span><em>{cls[code_of[name]]["actual"]:,.0f}</em> FTE</span>'
        f'<span><em>{cls[code_of[name]]["model"]:,.0f}</em> funded units</span>'
        f'</div></figcaption>'
        f'<div class="plot">'
        f'{render_chart(by_class_role[code_of[name]], ticks5[-1], ticks5, fte,
                        "c5" + code_of[name], row_h=44, suffix=times_model)}'
        f'</div></figure>'
        for name, _paid, _staff, _allacc in rollup)

    doc = f"""<title>The Prototypical Gap</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{CSS}</style>

<div class="wrap">

<header class="masthead">
  <div class="slug">
    <span>Seattle Public Schools</span><span>2024&ndash;25</span>
    <span>1191F &amp; F-196 &times; S-275</span><span>General Fund</span>
  </div>
  <h1>How much of the payroll the state pays for</h1>
  <p class="dek">Washington buys school staff by formula. Its
  <em>prototypical school</em> model funds a set number of certificated
  instructional, certificated administrative and classified staff units, each at
  a flat rate, and adds a separate allocation for special education. Seattle then
  hires and pays what it actually needs. Setting the two side by side answers one
  question: for each block of spending, how far does state money go?</p>
</header>

<div class="headline">
  <div class="hero">
    <div class="fig">{state_tot / comp_tot * 100:.0f}%</div>
    <p class="cap">of what SPS pays its staff is covered by state apportionment
    and special education together. The other {money(comp_tot - state_tot)} comes
    from the local levy, federal grants and the categorical programs.</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="k">Salary</div><div class="v">{money(salary_tot)}</div></div>
    <div class="stat"><div class="k">Benefits</div><div class="v">{money(comp_tot - salary_tot)}</div></div>
    <div class="stat"><div class="k">Total pay</div><div class="v">{money(comp_tot)}</div></div>
    <div class="stat"><div class="k">State funding</div><div class="v">{money(state_tot)}</div></div>
    <div class="stat"><div class="k">Shortfall</div><div class="v">{money(comp_tot - state_tot)}</div></div>
  </div>
</div>

<div class="howto">
  {HOWTO_SVG}
  <p>Every row is one block of spending. The wide coloured bar is the state
  money behind it; the narrow dark bar on top is what SPS actually pays &mdash;
  salary, then benefits in hatching. Where the dark bar runs past the colour,
  the state stopped paying and something else picked it up. Hover any row for
  the numbers.</p>
</div>

{stack_key}

<section>
  <div class="eyebrow">Staff class &middot; dollars</div>
  <h2>The three classes the model funds, and what each actually costs</h2>
  <p class="note">The prototypical model does not fund a district in bulk. It
  funds three classes of staff separately, at a flat rate each, and every S-275
  duty code belongs to one of them. This is the whole answer in three rows: what
  SPS pays each class, and how much of that the state covers.</p>
  <p class="note"><b>Both sides include benefits.</b> The state figure is the
  model's salary allocation plus the insurance and payroll benefits the same
  pages compute on top of it &mdash; {money(model_benefits)} of the
  {money(staff_tot)}, or {model_benefits / staff_tot * 100:.0f}&nbsp;percent
  &mdash; along with substitutes and professional learning days. The pay bar is
  S-275 salary plus benefits at the F-196 ratio. The comparison is like for
  like; neither side is salary alone.</p>
  <div class="plot">{render_chart(rows3, ticks3[-1], ticks3, money, "c3",
                                  row_h=64, suffix=times_salary)}</div>
  {table(["Staff class", "Salary", "Benefits", "Total pay",
          "State apportionment", "Special education", "State funding",
          "% of pay"],
         [(html.escape(l), money(dict(comp)["salary"]),
           money(dict(comp)["benefits"]), money(sum(v for _k, v in comp)),
           money(dict(stack)["apportionment"]), money(dict(stack)["sped"]),
           money(sum(v for _k, v in stack)),
           f"{sum(v for _k, v in stack) / sum(v for _k, v in comp) * 100:.0f}%")
          for l, stack, comp, _ in rows3])}
</section>

<section>
  <div class="eyebrow">Staff class &middot; headcount</div>
  <h2>The same three classes, counted in people</h2>
  <p class="note">Dollars fall short for two different reasons, and this chart
  separates them. The state funds a fixed number of staff units; SPS employs
  {fte_actual:,.0f} FTE against a model of {fte_model:,.0f}. Where a class runs
  far over its unit count, the shortfall is a headcount the model never
  budgeted for &mdash; classified staff sit at {cls['CLS']['actual']:,.0f} FTE
  against {cls['CLS']['model']:,.0f}, nearly three times over. Where a class is
  close to its unit count, the shortfall is instead a pay rate: the state's flat
  rate is simply below what SPS pays.</p>
  <div class="key"><span><i class="budget"></i>Prototypical staff units</span>
  <span><i class="measure"></i>Actual FTE</span></div>
  <div class="plot">{render_chart(rows2, ticks2[-1], ticks2, fte, "c2",
                                  row_h=64, suffix=times_model)}</div>
  {table(["Staff class", "Actual FTE", "Prototypical FTE", "Over model", "Ratio"],
         [(html.escape(l), f"{{a:,.1f}}", f"{{b:,.1f}}", f"{{a - b:,.1f}}",
           f"{{a / b:.2f}}x")
          for l, b, a, _ in rows2])}
</section>

<section>
  <div class="eyebrow">Job title &middot; dollars</div>
  <h2>Inside each class, title by title</h2>
  <p class="note">A class average hides a wide spread, because the model pays a
  flat rate per staff unit while a district pays each title what it pays. Divide
  each class's pot across its titles by FTE &mdash; which is how the model
  allocates &mdash; and a title paid above its class rate covers less of its own
  pay, one paid below covers more. State special education works the other way:
  it is a lump sum per eligible student, so it follows program 21 payroll rather
  than headcount, and it lands almost entirely on the titles that do that work.</p>
  <p class="note">The pay bar is <code>total_final_salary</code> from the S-275
  plus benefits, scaled by the F-196 ratio of object 4 to objects 2 and 3
  ({(comp_tot - salary_tot) / salary_tot * 100:.1f}&nbsp;cents per dollar of
  salary). All three charts share one dollar scale, so lengths compare across
  classes as well as within them.</p>
  <div class="facets">{facets}</div>
  {table(["Job title", "Class"] + [SEGMENT_LABEL[k] for k in SEGMENT_KEYS]
         + ["State funding", "Total pay", "% of pay"],
         [(html.escape(l), cls, *[money(v) for _k, v in stack],
           money(sum(v for _k, v in stack)), money(sum(v for _k, v in comp)),
           f"{sum(v for _k, v in stack) / sum(v for _k, v in comp) * 100:.0f}%")
          for cls, rows in by_class.items() for l, stack, comp, _ in rows])}
</section>

<section>
  <div class="eyebrow">Staffing roles</div>
  <h2>Every role the model funds, against the staff who fill it</h2>
  <p class="note">The 1191F reports a class total, but Report 1191EDF behind it
  builds that total one role at a time &mdash; principals, classroom teachers,
  librarians, counselors, nurses, social workers, psychologists, teaching
  assistance, office support, custodians, security, family involvement,
  technology, facilities, warehouse and central administration. Those roles sum
  exactly to the three class totals, so this is the state's own decomposition,
  matched to the S-275 duty codes that do each job.</p>
  <p class="note">Two of them are funded more generously than SPS staffs them:
  the model buys {counselors_model:,.0f} guidance counselor units against
  {counselors_actual:,.0f} FTE employed, and {nurses_model:,.0f} nurse units
  against {nurses_actual:,.0f}. Everywhere else the district runs over, most
  sharply in teaching assistance &mdash; {ta_actual:,.0f} FTE against
  {ta_model:,.0f} funded units. And {unfunded_fte:,.0f} FTE do jobs the basic
  education allocation has no staff unit for at all: therapists, speech
  pathologists, behaviour analysts, substitutes.</p>
  <div class="key"><span><i class="budget"></i>Funded staff units</span>
  <span><i class="measure"></i>Actual FTE</span></div>
  <div class="facets">{facets_roles}</div>
  {table(["Role", "Class", "Funded units", "Actual FTE", "Ratio",
          "Allocated", "Actual pay", "% of pay"],
         [(html.escape(r["role"]), r["staff_class"],
           f"{{Decimal(r['model_fte']):,.1f}}", f"{{Decimal(r['actual_fte']):,.1f}}",
           (f"{{Decimal(r['actual_fte']) / Decimal(r['model_fte']):.2f}}x"
            if Decimal(r["model_fte"]) else "&mdash;"),
           money(Decimal(r["model_dollars"])), money(Decimal(r["actual_pay"])),
           (f"{{Decimal(r['model_dollars']) / Decimal(r['actual_pay']) * 100:.0f}}%"
            if Decimal(r["actual_pay"]) else "&mdash;"))
          for r in roles])}
</section>

<section>
  <div class="eyebrow">Sources</div>
  <h2>Where the state money in these charts comes from</h2>
  <p class="note">Two sources are in the bars, and they are the two the state
  ties to staff. Everything else the district receives is real money that pays
  real people &mdash; it is listed here so the arithmetic closes, but it is not
  attributed to a block of spending.</p>
  {table(["Revenue source", "Amount", "Share of state funding",
          "Share of General Fund"], account_rows,
          open=True, summary="Every General Fund dollar")}
</section>

<div class="method">
  <div>
    <h3>Where the apportionment figure comes from</h3>
    <p>Pages 1&ndash;7 of the Final Apportionment Summary derive the guaranteed
    entitlement as staff units: an FTE count per class, a salary rate, insurance,
    payroll benefits, substitutes and professional learning days. Summed per
    class they come to <b>${staff_tot:,.0f}</b> &mdash; line III.A.7 plus III.B.9
    plus substitutes and professional learning, to the penny. The pages print
    this as formulas rather than a table, so it had to be re-parsed from the PDF.</p>
  </div>
  <div>
    <h3>Why special education is treated differently</h3>
    <p>It is not a staff-unit allocation. The state pays a rate per eligible
    student and lets the district staff to it, so there is no FTE count to
    divide by. It is attributed to the staff coded to program 21 and divided by
    payroll, and first scaled by the {sped_share:.0f}&nbsp;percent of program 21
    spending that is salaries and benefits rather than contracted services.</p>
  </div>
  <div>
    <h3>What is not counted</h3>
    <p>{money(off_chart)} of learning assistance, bilingual, highly capable,
    transportation, food service, Title I, other federal grants, the local levy,
    private gifts and transfers. Account 3100 and the 3121 transfer are dropped
    too, but for the opposite reason: they are the apportionment, already counted
    as staff units above.</p>
  </div>
  <div>
    <h3>Counting rules</h3>
    <p>FTE is the sum of <code>fte_in_assignment</code>. Salary is attributed to
    the assignment, not the person, so staff holding more than one duty are not
    counted twice. Benefits use one districtwide F-196 ratio, so they scale every
    title identically &mdash; the real rate differs between certificated and
    classified staff, but the F-196 does not split object 4 that way.</p>
    <p>As a check on the method, run over <em>all</em> revenue rather than these
    two sources it produces {money(Decimal("973577606"))} of pay, against
    {money(staff_spend)} of actual F-196 spending on objects 2, 3 and 4 &mdash;
    a 0.5&nbsp;percent gap, reached from the revenue side independently.</p>
  </div>
</div>

<footer>
  Sources: safs_s275, 2024&ndash;25 final report, CCDDD 17001 &middot;
  safs_f19x General Fund revenues and expenditures, F-196 actuals &middot;
  OSPI Report 1191F Final Apportionment Summary, pages 1&ndash;7 &middot;
  Built from the sps-btn-data warehouse.
</footer>

</div>
<div id="tip"></div>
<script>{JS}</script>
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
