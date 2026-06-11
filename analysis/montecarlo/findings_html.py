"""Generate the scenario-findings report page (self-contained HTML, inline
SVG, no external dependencies) into the GitHub Pages tree:
docs/montecarlo/findings.html, published at
https://sps-by-the-numbers.github.io/data-tools/montecarlo/findings.html

Run:  python3 -m analysis.montecarlo.findings_html
Reads every run listed in SCENARIOS from simulate/<name>/ via the report-stage
summary functions, so the page always matches the tracked run outputs.
"""

from __future__ import annotations

import datetime
import html
from pathlib import Path

from analysis.montecarlo import breakdown as bdn
from analysis.montecarlo import report as rpt
from analysis.montecarlo import simulate as sim

OUT = (Path(__file__).resolve().parents[2]
       / "docs" / "montecarlo" / "findings.html")
OVERVIEW_URL = ("https://github.com/SPS-By-The-Numbers/data-tools/"
                "blob/main/analysis/montecarlo/OVERVIEW.md")

# Display order, grouping, and one-line interpretations (kept here, not in the
# specs, because they are editorial).
SCENARIOS = [
    ("ms_walk_1mi", "Shrink MS walk zones to 1 mile", "Expand service",
     "Students 1–2 mi from middle school become bus-eligible. All 12 middle "
     "schools gain riders; the MS bell shift has spare buses, so the fleet "
     "does not grow."),
    ("hs_bussing", "Re-add HS yellow bus (2-mi walk zone)", "Expand service",
     "High schoolers are currently ORCA-only. Modeled as a fraction of MS "
     "ridership (×0.7 for independent transit travel, 11th–12th graders "
     "additionally ×0.5 — cars)."),
    ("hs_bussing_1mi", "Re-add HS yellow bus + 1-mi walk zone", "Expand service",
     "Same HS service, but students 1–2 mi out are also eligible. Roughly "
     "doubles the HS rider gain; still fleet-free."),
    ("hs_ms_bussing_1mi", "HS bus + 1-mi walk zones for MS and HS", "Expand service",
     "The maximal secondary-service package: restore high-school yellow bus "
     "and make every middle- and high-schooler beyond a mile bus-eligible. "
     "Effects are additive — the component scenarios don't interact."),
    ("es_walk_1p5mi", "Expand ES walk zones to 1.5 miles", "Reduce service",
     "The reverse lever: ES students inside 1.5 mi lose bus eligibility. "
     "Big bus savings, big reimbursement loss — they nearly cancel."),
    ("close_fab4", "Close 4 ES (named receivers)", "Closures",
     "North Beach→Viewlands, Sacajawea→Rogers, Stevens→Montlake, "
     "Sanislo→Highland Park. Every receiver gains more riders than its "
     "partner lost: ex-walkers convert to riders."),
    ("close_sacajawea", "Close Sacajawea ES only", "Closures",
     "Single closure with default (3-nearest) receivers; the smallest "
     "scenario, included as a reference point."),
    ("close_option_a", "KUOW Option A: close 21 schools", "Closures",
     "The “well-resourced schools” plan — eliminates most option/K-8 "
     "programs. Displaced riders go to the remaining schools; 18 served "
     "destinations disappear from the funding formula."),
    ("close_option_b", "KUOW Option B: close 17 schools", "Closures",
     "The “choice” plan — keeps more option schools but closes Thurgood "
     "Marshall; its HCC pathway moves to Beacon Hill International per the "
     "plan."),
    ("close_option_b_dearborn", "Option B, HCC → Dearborn Park", "Closures",
     "Identical to Option B except Thurgood Marshall’s HCC service lands at "
     "Dearborn Park — the other receiver the plan names. District deltas "
     "are essentially unchanged."),
    ("convert_optA_rand1", "Convert 5 option schools (combo 1)", "Conversions",
     "Cedar Park, TOPS, Orca, Salmon Bay, Licton Springs become neighborhood "
     "schools. Lottery riders become walkers, but displaced enrollees "
     "scatter to non-walkable seats — the effects nearly cancel."),
    ("convert_optA_rand2", "Convert 5 option schools (combo 2)", "Conversions",
     "Same experiment with Boren swapped in for Salmon Bay. The near-equal "
     "result shows WHICH five barely matters."),
]

GROUP_ORDER = ["Expand service", "Reduce service", "Closures", "Conversions"]


def collect() -> list[dict]:
    rows = []
    for name, label, group, blurb in SCENARIOS:
        run = sim.load_run(name)
        ds = rpt.district_summary(run).set_index("program")
        bc = rpt.bus_cost_summary(run)
        fs = rpt.funding_summary(run)
        b = ds.loc["basic"]
        db = run["district"][run["district"].program == "basic"]
        d_dist = (db["scen_dist_mean"] - db["base_dist_mean"]).mean()
        net = (fs.set_index("draw")["d_revenue"]
               - bc.set_index("draw")["d_cost"]) / 1e6
        rows.append({
            "name": name, "label": label, "group": group, "blurb": blurb,
            "riders": b["d_riders_mean"], "riders_lo": b["d_riders_lo"],
            "riders_hi": b["d_riders_hi"],
            "gifted": ds.loc["gifted", "d_riders_mean"] if "gifted" in ds.index else 0.0,
            "routes": b["d_routes_mean"],
            "buses": bc["d_buses"].mean(),
            "cost": bc["d_cost"].mean() / 1e6,
            "cost_fleet": bc["d_cost_fleet"].mean() / 1e6,
            "rev": fs["d_revenue"].mean() / 1e6,
            "rev_lo": fs["d_revenue"].quantile(0.025) / 1e6,
            "rev_hi": fs["d_revenue"].quantile(0.975) / 1e6,
            "net": net.mean(), "net_lo": net.quantile(0.025),
            "net_hi": net.quantile(0.975),
            "dist": d_dist,
            "n_draws": run["meta"]["n_draws"], "seed": run["meta"]["seed"],
        })
    return rows


# ---------------------------------------------------------------------------
# SVG helpers — hand-rolled horizontal diverging bar charts
# ---------------------------------------------------------------------------

INK = "#16130e"
YELLOW = "#f7c200"
SLATE = "#46618a"   # funding bars — deliberately valence-neutral (the bar
BRICK = "#a03123"   # direction, not the hue, says good/bad)
PAPER = "#faf6ec"
MUTED = "#8c8475"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def _scale(lo: float, hi: float, x0: float, x1: float):
    span = hi - lo or 1.0
    return lambda v: x0 + (v - lo) / span * (x1 - x0)


def fmt_riders(v: float) -> str:
    return f"{v:+,.0f}"


def fmt_money(v: float) -> str:
    return f"{v:+,.1f}"


def bar_chart(rows: list[dict], key: str, lo_key: str, hi_key: str,
              fmt, unit: str, pos_color: str = YELLOW,
              neg_color: str = MUTED) -> str:
    """Horizontal diverging bars with CI whiskers, sorted by value."""
    rows = sorted(rows, key=lambda r: -r[key])
    W, LABEL_W, VAL_W, ROW_H, PAD_T = 960, 300, 90, 34, 26
    H = PAD_T + ROW_H * len(rows) + 30
    x0, x1 = LABEL_W + 8, W - VAL_W
    vlo = min(0.0, *(r[lo_key] for r in rows)) * 1.06
    vhi = max(0.0, *(r[hi_key] for r in rows)) * 1.06
    sx = _scale(vlo, vhi, x0, x1)
    zero = sx(0.0)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13">']
    parts.append(f'<line x1="{zero:.1f}" y1="{PAD_T - 12}" x2="{zero:.1f}" '
                 f'y2="{H - 24}" stroke="{INK}" stroke-width="1.5"/>')
    for i, r in enumerate(rows):
        y = PAD_T + i * ROW_H
        cy = y + ROW_H / 2
        v, lo_v, hi_v = r[key], r[lo_key], r[hi_key]
        bx = sx(min(v, 0.0)) if v < 0 else zero
        bw = abs(sx(v) - zero)
        color = pos_color if v >= 0 else neg_color
        parts.append(f'<text x="{LABEL_W}" y="{cy + 4:.1f}" text-anchor="end" '
                     f'fill="{INK}" font-family="inherit">{esc(r["label"])}</text>')
        parts.append(f'<rect x="{bx:.1f}" y="{y + 8:.1f}" width="{max(bw, 1):.1f}" '
                     f'height="{ROW_H - 16}" fill="{color}" stroke="{INK}" '
                     f'stroke-width="1.2"/>')
        parts.append(f'<line x1="{sx(lo_v):.1f}" y1="{cy:.1f}" x2="{sx(hi_v):.1f}" '
                     f'y2="{cy:.1f}" stroke="{INK}" stroke-width="1.5"/>')
        for w in (lo_v, hi_v):
            parts.append(f'<line x1="{sx(w):.1f}" y1="{cy - 5:.1f}" '
                         f'x2="{sx(w):.1f}" y2="{cy + 5:.1f}" stroke="{INK}" '
                         f'stroke-width="1.5"/>')
        tx = sx(max(v, hi_v)) + 8 if v >= 0 else sx(min(v, lo_v)) - 8
        anchor = "start" if v >= 0 else "end"
        parts.append(f'<text x="{tx:.1f}" y="{cy + 4:.1f}" text-anchor="{anchor}" '
                     f'fill="{INK}" font-weight="bold">{fmt(v)}</text>')
    parts.append(f'<text x="{zero:.1f}" y="{H - 8}" text-anchor="middle" '
                 f'fill="{MUTED}">0 {esc(unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def fiscal_chart(rows: list[dict]) -> str:
    """Per scenario: revenue bar (up-ink green), cost bar (brick), net ◆ + CI."""
    rows = sorted(rows, key=lambda r: -r["net"])
    W, LABEL_W, VAL_W, ROW_H, PAD_T = 960, 300, 95, 46, 30
    H = PAD_T + ROW_H * len(rows) + 34
    x0, x1 = LABEL_W + 8, W - VAL_W
    vlo = min(0.0, *(min(r["net_lo"], r["rev_lo"], -r["cost"]) for r in rows)) * 1.08
    vhi = max(0.0, *(max(r["net_hi"], r["rev_hi"], -r["cost"]) for r in rows)) * 1.08
    sx = _scale(vlo, vhi, x0, x1)
    zero = sx(0.0)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13">']
    parts.append(f'<line x1="{zero:.1f}" y1="{PAD_T - 12}" x2="{zero:.1f}" '
                 f'y2="{H - 26}" stroke="{INK}" stroke-width="1.5"/>')
    for i, r in enumerate(rows):
        y = PAD_T + i * ROW_H
        parts.append(f'<text x="{LABEL_W}" y="{y + 14:.1f}" text-anchor="end" '
                     f'fill="{INK}">{esc(r["label"])}</text>')
        # funding bar (thin, top)
        rv = r["rev"]
        bx = sx(min(rv, 0.0)) if rv < 0 else zero
        parts.append(f'<rect x="{bx:.1f}" y="{y + 4:.1f}" '
                     f'width="{max(abs(sx(rv) - zero), 1):.1f}" height="9" '
                     f'fill="{SLATE}"/>')
        # cost bar plotted as negative (money out), below
        cv = -r["cost"]
        bx = sx(min(cv, 0.0)) if cv < 0 else zero
        parts.append(f'<rect x="{bx:.1f}" y="{y + 16:.1f}" '
                     f'width="{max(abs(sx(cv) - zero), 1):.1f}" height="9" '
                     f'fill="{YELLOW}" stroke="{INK}" stroke-width="1"/>')
        # net diamond + CI whisker on the centerline below the bars
        cy = y + 33
        parts.append(f'<line x1="{sx(r["net_lo"]):.1f}" y1="{cy}" '
                     f'x2="{sx(r["net_hi"]):.1f}" y2="{cy}" stroke="{INK}" '
                     f'stroke-width="1.5"/>')
        nx = sx(r["net"])
        parts.append(f'<path d="M {nx:.1f} {cy - 6} L {nx + 6:.1f} {cy} '
                     f'L {nx:.1f} {cy + 6} L {nx - 6:.1f} {cy} Z" fill="{INK}"/>')
        anchor = "start" if r["net"] >= 0 else "end"
        tx = sx(max(r["net"], r["net_hi"])) + 9 if r["net"] >= 0 \
            else sx(min(r["net"], r["net_lo"])) - 9
        parts.append(f'<text x="{tx:.1f}" y="{cy + 4}" text-anchor="{anchor}" '
                     f'font-weight="bold" fill="{INK}">{fmt_money(r["net"])}</text>')
    parts.append(f'<text x="{zero:.1f}" y="{H - 10}" text-anchor="middle" '
                 f'fill="{MUTED}">$0M / yr</text>')
    parts.append("</svg>")
    return "".join(parts)


def routes_buses_chart(rows: list[dict]) -> str:
    """Routes (outline) vs buses (solid) — the bell-shift effect."""
    rows = sorted(rows, key=lambda r: -r["routes"])
    W, LABEL_W, VAL_W, ROW_H, PAD_T = 960, 300, 170, 40, 26
    H = PAD_T + ROW_H * len(rows) + 32
    x0, x1 = LABEL_W + 8, W - VAL_W
    vlo = min(0.0, *(min(r["routes"], r["buses"]) for r in rows)) * 1.08
    vhi = max(0.0, *(max(r["routes"], r["buses"]) for r in rows)) * 1.08
    sx = _scale(vlo, vhi, x0, x1)
    zero = sx(0.0)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13">']
    parts.append(f'<line x1="{zero:.1f}" y1="{PAD_T - 12}" x2="{zero:.1f}" '
                 f'y2="{H - 24}" stroke="{INK}" stroke-width="1.5"/>')
    for i, r in enumerate(rows):
        y = PAD_T + i * ROW_H
        parts.append(f'<text x="{LABEL_W}" y="{y + ROW_H / 2 + 4:.1f}" '
                     f'text-anchor="end" fill="{INK}">{esc(r["label"])}</text>')
        for j, (key, fill, stroke) in enumerate(
                (("routes", "none", INK), ("buses", YELLOW, INK))):
            v = r[key]
            bx = sx(min(v, 0.0)) if v < 0 else zero
            parts.append(f'<rect x="{bx:.1f}" y="{y + 6 + j * 14:.1f}" '
                         f'width="{max(abs(sx(v) - zero), 1):.1f}" height="11" '
                         f'fill="{fill}" stroke="{stroke}" stroke-width="1.3" '
                         f'{"stroke-dasharray=\'3 2\'" if key == "routes" else ""}/>')
        parts.append(f'<text x="{x1 + 10}" y="{y + ROW_H / 2 + 4:.1f}" fill="{INK}">'
                     f'{r["routes"]:+.0f} rt / {r["buses"]:+.0f} bus</text>')
    parts.append(f'<text x="{zero:.1f}" y="{H - 8}" text-anchor="middle" '
                 f'fill="{MUTED}">0</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

CSS = """
:root{
  --ink:#16130e; --paper:#faf6ec; --paper2:#f3ecdc; --yellow:#f7c200;
  --green:#2a6f4e; --brick:#a03123; --muted:#8c8475; --rule:#d8cfba;
}
*{box-sizing:border-box}
html{background:var(--paper2)}
body{
  margin:0; color:var(--ink); background:var(--paper);
  font:17px/1.62 Charter,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  max-width:1060px; margin-inline:auto; padding:0 28px 80px;
  box-shadow:0 0 60px rgba(22,19,14,.18);
}
.stripe{height:14px; margin:0 -28px;
  background:repeating-linear-gradient(135deg,var(--yellow) 0 26px,var(--ink) 26px 38px)}
header{padding:38px 0 18px; border-bottom:4px double var(--ink)}
.kicker{font:700 13px/1 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  letter-spacing:.22em; text-transform:uppercase; color:var(--brick)}
h1{font:900 clamp(34px,5.4vw,58px)/1.04 Superclarendon,"Bookman Old Style",
  "Clarendon Text Pro",Rockwell,Charter,Georgia,serif; margin:.25em 0 .15em;
  letter-spacing:-.01em}
.dek{font-size:20px; color:#3d382e; max-width:62ch; margin:.2em 0 1em}
.byline{font:13px/1.5 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  color:var(--muted); letter-spacing:.05em}
h2{font:800 26px/1.2 Superclarendon,"Bookman Old Style",Rockwell,Charter,Georgia,serif;
  margin:2.2em 0 .5em; padding-top:1.1em; border-top:1.5px solid var(--ink)}
h2 .no{display:inline-block; background:var(--yellow); border:1.5px solid var(--ink);
  padding:1px 9px; margin-right:10px; font-size:18px; vertical-align:3px}
p{max-width:72ch}
figure{margin:1.6em 0 2.2em; padding:18px 16px 10px; background:#fffdf6;
  border:1.5px solid var(--ink); box-shadow:6px 6px 0 var(--paper2)}
figcaption{font:13px/1.55 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  color:#4a4438; margin-top:8px; max-width:90ch}
figcaption b{color:var(--ink)}
svg{width:100%; height:auto; display:block}
.legend{font:12px/1 Avenir,"Avenir Next",Seravek,Verdana,sans-serif; color:#4a4438;
  display:flex; gap:18px; flex-wrap:wrap; margin:4px 2px 10px}
.legend span{display:inline-flex; align-items:center; gap:6px}
.sw{width:22px; height:11px; border:1.3px solid var(--ink); display:inline-block}
.callout{background:var(--paper2); border-left:6px solid var(--yellow);
  padding:14px 20px; margin:1.4em 0; max-width:78ch}
.callout p{margin:.4em 0}
.tw{overflow-x:auto; margin:1.4em 0; max-width:100%}
.tw table{margin:0}
table{border-collapse:collapse; width:100%; margin:1.4em 0;
  font:14px/1.45 ui-monospace,Menlo,Consolas,monospace}
caption{caption-side:top; text-align:left;
  font:700 13px/2 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  letter-spacing:.12em; text-transform:uppercase}
th{font:700 12px/1.3 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  letter-spacing:.06em; text-transform:uppercase; text-align:right;
  border-bottom:2px solid var(--ink); padding:6px 8px}
th:first-child,td:first-child{text-align:left}
td{padding:6px 8px; border-bottom:1px solid var(--rule); text-align:right;
  white-space:nowrap}
tr.grp td{border-bottom:none; padding-top:16px;
  font:700 12px/1 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  letter-spacing:.14em; text-transform:uppercase; color:var(--brick)}
.pos{color:var(--green); font-weight:700}
.neg{color:var(--brick); font-weight:700}
.cards{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
  gap:16px; margin:1.4em 0}
.card{border:1.5px solid var(--ink); background:#fffdf6; padding:14px 16px 12px}
.card h3{margin:0 0 2px; font:800 17px/1.25 Superclarendon,"Bookman Old Style",
  Rockwell,Georgia,serif}
.card .tag{font:700 10px/1 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  letter-spacing:.16em; text-transform:uppercase; color:var(--brick)}
.card p{font-size:14.5px; line-height:1.5; margin:.5em 0; color:#3d382e}
.card .nums{font:13px/1.7 ui-monospace,Menlo,Consolas,monospace;
  border-top:1px solid var(--rule); padding-top:7px}
details.bd{border:1.5px solid var(--ink); background:#fffdf6; margin:10px 0}
details.bd summary{cursor:pointer; padding:11px 16px;
  font:700 14px/1.3 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  list-style-position:outside}
details.bd summary span{font-weight:400; color:var(--muted)}
details.bd summary::marker{color:#b8930a}
details.bd[open] summary{border-bottom:1.5px solid var(--ink);
  background:var(--paper2)}
.bdc{padding:2px 18px 14px}
.bdc table{font-size:13px; margin:1em 0}
.bdc p{font-size:14.5px; max-width:90ch}
.bnote{font:12.5px/1.55 Avenir,"Avenir Next",Seravek,Verdana,sans-serif;
  color:#4a4438; max-width:95ch}
ul.bnote{padding-left:1.2em}
ol.findings{max-width:74ch; padding-left:1.3em}
ol.findings li{margin:.7em 0}
.foot{margin-top:3em; border-top:4px double var(--ink); padding-top:14px;
  font:13px/1.7 Avenir,"Avenir Next",Seravek,Verdana,sans-serif; color:#4a4438}
.foot ol{padding-left:1.2em}
.foot li{margin:.35em 0}
code{font:.92em ui-monospace,Menlo,Consolas,monospace; background:var(--paper2);
  padding:0 4px}
@media print{body{box-shadow:none; max-width:none} figure{box-shadow:none}}
"""


def breakdown_details(label: str, d: dict) -> str:
    """One expandable per-school breakdown section (resolved assumptions +
    enrollment/eligible/rides deltas per affected school)."""
    p = []
    for i, op in enumerate(d["ops"]):
        if op["kind"] == "close_school":
            how = ("receivers <b>named in the spec</b>" if op["named_receivers"]
                   else "the <b>engine-default receivers</b> (3 nearest open "
                        "same-level neighborhood schools, split per residence "
                        "area in proportion to existing draw)")
            p.append(f"<b>op[{i}] <code>close_school</code></b> — close "
                     f"<b>{esc(op['school'])}</b> ({op['sid']}); its "
                     f"{op['kids_out']:.0f} assigned students stay where they "
                     f"live and re-assign to {how}.")
        else:
            p.append(f"<b>op[{i}] <code>{esc(op['kind'])}</code></b> — "
                     f"<code>{esc(str(op['params']))}</code>")
    ops_html = "<p>" + "<br>".join(p) + "</p>"

    recv_html = ""
    if d["receivers"]:
        rws = "".join(
            f"<tr><td>{esc(r['name'])} ({r['sid']})</td>"
            f"<td>{r['kids']:,.1f}</td><td>{r['share']:.0%}</td></tr>"
            for r in d["receivers"])
        recv_html = ('<div class="tw"><table><caption>Receiving schools (all '
                     "displacements combined)</caption><tr><th>Receiver</th>"
                     f"<th>Kids received</th><th>Share</th></tr>{rws}</table></div>")

    trs = []
    for r in d["rows"]:
        mc = "—" if r["mc"] is None else \
            f"{r['mc'][0]:+.1f} [{r['mc'][1]:+.1f}, {r['mc'][2]:+.1f}]"
        trs.append(
            f"<tr><td>{esc(r['name'])} ({r['sid']})</td><td>{r['role']}</td>"
            f"<td>{r['enroll_b']:,.0f} → {r['enroll_s']:,.0f} "
            f"({r['enroll_s'] - r['enroll_b']:+,.0f})</td>"
            f"<td>{r['elig_b']:,.0f} → {r['elig_s']:,.0f} "
            f"({r['elig_s'] - r['elig_b']:+,.0f})</td>"
            f"<td>{r['ev_b']:,.1f} → {r['ev_s']:,.1f} "
            f"({r['ev_s'] - r['ev_b']:+,.1f})</td><td>{mc}</td></tr>")
    b, s = d["district"]
    trs.append(f"<tr><td><b>district total</b></td><td></td><td></td><td></td>"
               f"<td><b>{b:,.1f} → {s:,.1f} ({s - b:+,.1f})</b></td><td></td></tr>")
    table = ('<div class="tw"><table><tr><th>School</th><th>Role</th>'
             "<th>Enrolled base→scen (Δ)</th><th>Bus-eligible base→scen (Δ)</th>"
             "<th>EV rides/day base→scen (Δ)</th><th>MC Δ rides [95% CI]</th>"
             f"</tr>{''.join(trs)}</table></div>")

    if d["gifted_rows"]:
        grs = "".join(
            f"<tr><td>{esc(r['name'])} ({r['sid']})</td>"
            f"<td>{r['ev_b']:,.1f} → {r['ev_s']:,.1f} "
            f"({r['ev_s'] - r['ev_b']:+,.1f})</td></tr>"
            for r in d["gifted_rows"])
        gift = ('<div class="tw"><table><caption>Gifted program (HCC pathway '
                "touched)</caption><tr><th>School</th>"
                f"<th>EV rides/day base→scen (Δ)</th></tr>{grs}</table></div>")
    else:
        gift = "<p class='bnote'>Gifted program: unchanged.</p>"

    notes = "".join(f"<li><b>{esc(t)}</b> — {esc(n)}</li>"
                    for t, n in bdn.COLUMN_NOTES)
    return (f'<details class="bd" id="bd-{esc(d["name"])}">'
            f"<summary>{esc(label)} <span>per-school breakdown &amp; "
            "resolved assumptions</span></summary>"
            f'<div class="bdc">{ops_html}{recv_html}'
            f"<p class='bnote'>{esc(bdn.INVARIANTS)}</p>{table}{gift}"
            f"<ul class='bnote'>{notes}</ul></div></details>")


def td_signed(v: float, fmt: str = "+,.0f", flip: bool = False) -> str:
    cls = "pos" if (v < 0 if flip else v >= 0) else "neg"
    if abs(v) < 0.05:
        cls = ""
    return f'<td class="{cls}">{v:{fmt}}</td>'


_NUM_WORDS = {10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
              14: "fourteen", 15: "fifteen", 16: "sixteen"}


def build(rows: list[dict]) -> str:
    today = datetime.date.today().isoformat()
    n_draws = rows[0]["n_draws"]
    seed = rows[0]["seed"]
    n_word = _NUM_WORDS.get(len(rows), str(len(rows)))

    riders_svg = bar_chart(rows, "riders", "riders_lo", "riders_hi",
                           fmt_riders, "rides/day")
    fiscal_svg = fiscal_chart(rows)
    rb_svg = routes_buses_chart(rows)
    details_blocks = [breakdown_details(r["label"], bdn.compute(r["name"]))
                      for r in rows]

    # summary table grouped
    trows = []
    for g in GROUP_ORDER:
        members = [r for r in rows if r["group"] == g]
        if not members:
            continue
        trows.append(f'<tr class="grp"><td colspan="8">{esc(g)}</td></tr>')
        for r in members:
            trows.append(
                "<tr>"
                f"<td>{esc(r['label'])}</td>"
                + td_signed(r["riders"])
                + f"<td>[{r['riders_lo']:+,.0f}, {r['riders_hi']:+,.0f}]</td>"
                + td_signed(r["routes"], "+.1f")
                + td_signed(r["buses"], "+.1f", flip=True)
                + (f'<td class="{"pos" if r["cost"] < 0.005 else "neg"}">'
                   f'{-r["cost"]:+.2f} ({-r["cost_fleet"]:+.2f})</td>')
                + td_signed(r["rev"], "+.2f")
                + td_signed(r["net"], "+.2f")
                + "</tr>")
    table = (
        '<div class="tw"><table><caption>All scenarios — district deltas vs '
        "the 2024-25 baseline (10,008.5 basic rides/day; 202 routes; ~180 "
        "buses). Bus cost shows with-overage-hours (fleet-only in "
        "parentheses)</caption>"
        "<tr><th>Scenario</th><th>Δ rides/day</th><th>95% CI</th>"
        "<th>Δ routes</th><th>Δ buses</th><th>Δ bus $M (fleet)</th>"
        "<th>Δ funding $M</th><th>Net $M/yr</th></tr>"
        + "".join(trows) + "</table></div>")

    cards = []
    for g in GROUP_ORDER:
        for r in (x for x in rows if x["group"] == g):
            gift = (f" &nbsp;gifted {r['gifted']:+,.0f}"
                    if abs(r["gifted"]) >= 1 else "")
            cards.append(
                '<div class="card">'
                f'<div class="tag">{esc(g)}</div>'
                f'<h3>{esc(r["label"])}</h3>'
                f'<p>{r["blurb"]}</p>'
                '<div class="nums">'
                f'rides/day {fmt_riders(r["riders"])} '
                f'[{r["riders_lo"]:+,.0f}, {r["riders_hi"]:+,.0f}]{gift}<br>'
                f'routes {r["routes"]:+.1f} &nbsp;·&nbsp; buses {r["buses"]:+.1f} '
                f'&nbsp;·&nbsp; avg dist {r["dist"]:+.2f} mi<br>'
                f'<b>net fiscal {fmt_money(r["net"])} '
                f'[{fmt_money(r["net_lo"])}, {fmt_money(r["net_hi"])}] $M/yr</b>'
                '</div></div>')

    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What Would It Do to the Buses? — SPS scenario findings</title>
<style>{CSS}</style>
<body>
<div class="stripe"></div>
<header>
  <div class="kicker">SPS By The Numbers · Transportation Simulation Findings</div>
  <h1>What Would It Do to the Buses?</h1>
  <p class="dek">Monte Carlo estimates of how {n_word} policy scenarios —
  walk-zone changes, restored high-school service, school closures, and
  option-school conversions — would change Seattle Public Schools yellow-bus
  ridership, fleet size, and state transportation funding.</p>
  <div class="byline">Generated {today} · {n_draws} paired draws per scenario
  (seed {seed}) · baseline school year 2024-25 ·
  methods: <a href="{OVERVIEW_URL}">OVERVIEW.md</a></div>
</header>

<h2><span class="no">§1</span>How to read this</h2>
<p>Every number is a <b>change from the 2024-25 baseline</b> (10,008.5 basic
rides/day, 202 routes, ≈180 buses, $36.7M state reimbursement). “Rides per
day” counts boardings the way the state does: morning and afternoon each
count once, so a student riding both ways counts as 2. Brackets are 95%
intervals over a few hundred simulated worlds that vary <i>where students
live</i> (census uncertainty) and <i>how readily families use the bus</i>
(behavioral-parameter uncertainty) — they are not year-to-year noise.</p>
<div class="callout"><p><b>The one-sentence summary:</b> expanding service
<i>earns</i> the district money — added riders raise the state’s funding
formula faster than they raise costs, and middle/high-school routes reuse
buses the elementary shift already pays for — while school closures
<i>lose</i> transportation money from both directions at once.</p></div>

<h2><span class="no">§2</span>Ridership: who gains, who loses</h2>
<figure>
{riders_svg}
<figcaption><b>Fig. 1 — Change in basic yellow-bus rides per day.</b>
Bars are the mean across draws; whiskers are 95% intervals. Service
expansions dominate; the wide whiskers on the two high-school scenarios
reflect the untestable assumption about how many high-schoolers would
actually ride (modeled as a discounted fraction of middle-school behavior).
Closures <i>add</i> riders: students who walked to a closed school usually
live outside the receiving school’s walk zone.</figcaption>
</figure>

<h2><span class="no">§3</span>Routes need not mean buses</h2>
<figure>
<div class="legend"><span><span class="sw" style="background:none;border-style:dashed"></span>Δ routes (dashed outline)</span>
<span><span class="sw" style="background:var(--yellow)"></span>Δ buses (solid)</span></div>
{rb_svg}
<figcaption><b>Fig. 2 — Added routes vs added buses.</b> SPS runs two bell
shifts: elementary rides at a different time from middle/high school, so one
bus can serve a route on each shift and the fleet size is set by the
<i>busier</i> shift — currently elementary. Middle- and high-school route
additions therefore need <b>zero new buses</b>, while closures and
conversions add elementary-shift routes and pay full price (≈$149k per
bus-year). A route on an existing bus is still not free: cost figures add
an <b>assumed 2.0 overage driver-hours per route per day</b> ($61.50/hr ×
175 service days ≈ $21.5k per route-year) for every route beyond the fleet
change — an assumption, since the district's ~$9.8M/yr extras bucket
cannot be broken down (fleet-only figures are shown alongside as the lower
bound).</figcaption>
</figure>

<h2><span class="no">§4</span>The money: funding formula vs bus costs</h2>
<p>Washington reimburses districts through the STARS “Expected Allocation”
formula. It pays for <i>more riders</i>, <i>more served schools</i>, and
<i>longer average routes</i> — at the current margin roughly
<b>$2,650 per daily boarding-count per year</b> and roughly
<b>$550k per served school</b>.</p>
<figure>
<div class="legend"><span><span class="sw" style="background:#46618a;border:none"></span>Δ state funding</span>
<span><span class="sw" style="background:var(--yellow)"></span>Δ bus cost (shown as money out)</span>
<span>◆ net, with 95% whisker</span></div>
{fiscal_svg}
<figcaption><b>Fig. 3 — Annual fiscal impact, $M/yr.</b> Net = funding change
minus bus-cost change. Closures lose money twice over: displaced walkers
become riders the district must carry, while every closed served school
forfeits its Destinations term in the formula. Building-operations savings
(the stated rationale for closures, $25–31M in the district’s plans) are
<i>outside</i> this model — these bars are the transportation offset against
those savings.</figcaption>
</figure>

<h2><span class="no">§5</span>All {n_word} scenarios</h2>
{table}
<div class="cards">
{''.join(cards)}
</div>

<p>To examine the arithmetic behind any scenario — which schools the model
re-assigns students to, who becomes bus-eligible, and how the per-school
numbers add up to the district delta — expand its breakdown:</p>
{''.join(details_blocks)}

<h2><span class="no">§6</span>Key findings</h2>
<ol class="findings">
<li><b>Service expansion pays for itself under the funding formula.</b>
Shrinking middle-school walk zones to 1 mile adds ≈2,070 rides/day, zero
buses, and ≈+$5.3M/yr net. Restoring high-school yellow bus adds
≈+$13.6M/yr net even at heavily discounted HS ridership.</li>
<li><b>Closures cost transportation money from both directions.</b> The
21-school Option A plan: +850 rides/day to carry (+$2.6M bus cost) and
−$7.0M/yr in state funding — net ≈ <b>−$9.6M/yr</b>, an offset of roughly a
third of its claimed $31.5M building savings. Option B nets ≈ −$7.5M/yr.</li>
<li><b>Every consolidation receiver gains more riders than its closed
partner had.</b> Walkers at the closed school become bus riders at the
receiver — e.g. Sanislo has ≈0 riders today, yet closing it adds ~74
rides/day at Highland Park.</li>
<li><b>The bell-shift structure makes middle/high-school service nearly
free in fleet terms</b> while the elementary shift remains larger — the
cheapest capacity in the system is on the MS/HS shift.</li>
<li><b>Option-school conversions are roughly transportation-neutral</b>
(net ≈ −$0.4M/yr): lottery riders become walkers, but their replacement
assignments scatter to non-walkable seats — and which five schools convert
barely matters.</li>
<li><b>Rider gains under closures skew toward higher-poverty schools</b> —
the consolidation receivers sit in poorer attendance areas than the schools
being closed (see per-run equity cuts in the full reports).</li>
</ol>

<div class="foot">
<b>Methods &amp; caveats</b>
<ol>
<li>Full technical documentation, calibration and validation:
<a href="{OVERVIEW_URL}">OVERVIEW.md</a>. Per-scenario detail (per-school
movers, distance distributions, equity cuts):
<code>simulate/&lt;scenario&gt;/report.txt</code>.</li>
<li>High-school ridership is an uncalibrated assumption (SPS has never run
HS yellow bus in the data): modeled as middle-school behavior ×0.7 for
independent transit travel, with 11th–12th graders additionally ×0.5 for
cars. Both factors are sampled, which is why HS intervals are wide.</li>
<li>Funding deltas assume the EXAL formula’s coefficients hold and the
prior-year cap never binds (true for every scenario shown), and apply
modeled deltas to the official SY2024-25 formula inputs.</li>
<li>Closure scenarios use the district’s named receivers where published
(fab-4, Thurgood Marshall’s HCC) and distance-based defaults elsewhere —
not official boundary redraws. Building-operations savings are out of
scope.</li>
<li>Bus cost = Δfleet × the all-in vendor average ($148.9k/bus-yr) plus an
<b>assumed</b> 2.0 overage driver-hours/route/day ($61.50/hr × 175 days ≈
$21.5k/route-yr) for routes riding existing buses. The hours figure is a
judgment call — the district’s ~$9.8M/yr “extras” bucket can’t be broken
down — so the table shows the fleet-only cost alongside as the lower
bound.</li>
</ol>
Source: <code>analysis/montecarlo/</code> in the
<a href="https://github.com/SPS-By-The-Numbers/data-tools">SPS-By-The-Numbers/data-tools</a>
repository. Regenerate this page with
<code>python3 -m analysis.montecarlo.findings_html</code>.
</div>
<div class="stripe" style="margin-top:34px"></div>
</body>
</html>
"""


def main() -> None:
    rows = collect()
    OUT.write_text(build(rows))
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(rows)} scenarios)")


if __name__ == "__main__":
    main()
