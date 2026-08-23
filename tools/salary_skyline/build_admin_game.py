#!/usr/bin/env python3
"""Build "Who would you axe?" — the central-office payroll redistribution game.

One bubble per cuttable employee (area = total_final_salary), clustered by
CUTTABLE component from sea_units.py.  Click or sweep-drag a bubble (or its
skyline bar) to cross the position out; its salary is redistributed live across
the SEA-represented RECIPIENTS groups per the player's include/weight settings.
A two-row skyline below the game board mirrors the state: row 1 is every
cuttable position (cut bars grey out), row 2 is every SEA salary with the
redistributed amount stacked on top in central-office blue.

  python3 tools/salary_skyline/build_admin_game.py            # from repo root

Input CSV columns: cat,duty,duty_name,salary,fte (see query.sql).  Only
`duty`, `duty_name` and `salary` are read.  The output HTML is artifact-shaped
(no doctype/html/head/body wrapper) and fully self-contained apart from the
Google Fonts stylesheet link.
"""
import argparse, csv, json, math, statistics as st
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sea_units import CUTTABLE, RECIPIENTS

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--data", default="out_salary_skyline/staff.csv")
ap.add_argument("-o", "--out", default="out_salary_skyline/admin_game.html")
args = ap.parse_args()

SRC, OUT = Path(args.data), Path(args.out)
OUT.parent.mkdir(parents=True, exist_ok=True)

K = 0.039        # bubble radius = max(MIN_R, K * sqrt(salary)) px
MIN_R = 3.0
PACK_GAP = 0.8   # packed with r + gap/2 so neighbours don't visually touch

# F-196 General Fund actuals for SPS (ccddd 17001), school_year 2024-2025,
# from sps-btn-data.safs_f19x.general_fund_expenditures (data_type='actuals'):
#   SELECT object_code, SUM(amount) ... WHERE object_code IN (2,3,4)
# Used for the employer-benefits toggle: Object 4 (benefits + payroll taxes)
# is attributed to S-275 salaries by the ratio sum(s275 total_final_salary)
# / sum(F-196 objects 2+3), which works out to Object4/Objects23 per salary $.
F196_OBJ2 = 519_721_722   # Salaries - Certificated Employees
F196_OBJ3 = 218_001_654   # Salaries - Classified Employees
F196_OBJ4 = 240_895_971   # Employee Benefits and Payroll Taxes

# 2026-27 Budget Book (~/Downloads/26-27-Budget-Book-Online.pdf):
#   PDF p.14 (printed 7, "All Funds History") — General Fund 2026-27 net
#   change in fund balance = -21,247,124: the budget deficit (confirmed on
#   PDF p.20 as the "Calculated Gap in Revenues & Other Financing Sources
#   Under Expenditures").
#   PDF p.21 (printed 14, "General Fund Summary Details") — "Committed to
#   Economic Stabilization" is $0 in every 2026-27 fund-balance column; board
#   policy floor is 3% of the total budget.
DEFICIT_2627 = 21_247_124
GF_BUDGET_2627 = 1_338_853_189            # GF total expenditures 2026-27
ESF_TARGET = round(GF_BUDGET_2627 * 0.03) # 40,165,596
ESF_COMMITTED = 0
# default refill pace: the floor spread over 5 years, rounded to $0.1M
ESF_START = round((ESF_TARGET - ESF_COMMITTED) / 5 / 1e5) * 100_000

# --- circle packing: a straight port of d3-hierarchy packSiblings ------------

class _Node:
    __slots__ = ("c", "next", "previous")
    def __init__(self, c):
        self.c = c
        self.next = None
        self.previous = None

def _place(b, a, c):
    dx = b["x"] - a["x"]; dy = b["y"] - a["y"]
    d2 = dx * dx + dy * dy
    if d2:
        a2 = (a["pr"] + c["pr"]) ** 2
        b2 = (b["pr"] + c["pr"]) ** 2
        if a2 > b2:
            x = (d2 + b2 - a2) / (2 * d2)
            y = math.sqrt(max(0.0, b2 / d2 - x * x))
            c["x"] = b["x"] - x * dx - y * dy
            c["y"] = b["y"] - x * dy + y * dx
        else:
            x = (d2 + a2 - b2) / (2 * d2)
            y = math.sqrt(max(0.0, a2 / d2 - x * x))
            c["x"] = a["x"] + x * dx - y * dy
            c["y"] = a["y"] + x * dy + y * dx
    else:
        c["x"] = a["x"] + c["pr"]
        c["y"] = a["y"]

def _intersects(a, b):
    dr = a["pr"] + b["pr"] - 1e-6
    dx = b["x"] - a["x"]; dy = b["y"] - a["y"]
    return dr > 0 and dr * dr > dx * dx + dy * dy

def _score(n):
    a, b = n.c, n.next.c
    ab = a["pr"] + b["pr"]
    dx = (a["x"] * b["pr"] + b["x"] * a["pr"]) / ab
    dy = (a["y"] * b["pr"] + b["y"] * a["pr"]) / ab
    return dx * dx + dy * dy

def pack_siblings(circles):
    """Mutates each circle dict ({'pr': packing radius}) adding x/y."""
    n = len(circles)
    if n == 0:
        return
    a = circles[0]; a["x"] = 0.0; a["y"] = 0.0
    if n == 1:
        return
    b = circles[1]; a["x"] = -b["pr"]; b["x"] = a["pr"]; b["y"] = 0.0
    if n == 2:
        return
    c = circles[2]; _place(b, a, c)
    na, nb, nc = _Node(a), _Node(b), _Node(c)
    na.next = nc.previous = nb
    nb.next = na.previous = nc
    nc.next = nb.previous = na
    i = 3
    while i < n:
        c = circles[i]; _place(na.c, nb.c, c); nc = _Node(c)
        j, k = nb.next, na.previous
        sj, sk = nb.c["pr"], na.c["pr"]
        retry = False
        while True:
            if sj <= sk:
                if _intersects(j.c, c):
                    nb = j; na.next = nb; nb.previous = na
                    retry = True
                    break
                sj += j.c["pr"]; j = j.next
            else:
                if _intersects(k.c, c):
                    na = k; na.next = nb; nb.previous = na
                    retry = True
                    break
                sk += k.c["pr"]; k = k.previous
            if j is k.next:
                break
        if retry:
            continue
        nc.previous = na; nc.next = nb
        na.next = nb.previous = nc
        nb = nc
        aa = _score(na)
        node = nb.next
        while node is not nb:
            ca = _score(node)
            if ca < aa:
                na = node; aa = ca
            node = node.next
        nb = na.next
        i += 1

# --- load & aggregate --------------------------------------------------------

rows = list(csv.DictReader(SRC.open()))
cut_root = {}   # duty root -> comp index
for ci, (_, _, _, roots, _) in enumerate(CUTTABLE):
    for r in roots:
        cut_root[r] = ci
rg_root = {}
for gi, (_, _, roots, _) in enumerate(RECIPIENTS):
    for r in roots:
        rg_root[r] = gi

comp_staff = [[] for _ in CUTTABLE]      # (salary, duty_name)
rg_salaries = [[] for _ in RECIPIENTS]           # combined (panel stats)
rg_split = [[[], [], [], []] for _ in RECIPIENTS]  # basic / LAP / Title I / sped
s275_total = 0.0
for r in rows:
    duty = int(r["duty"]); sal = float(r["salary"])
    s275_total += sal
    if duty in cut_root:
        comp_staff[cut_root[duty]].append((sal, r["duty_name"]))
    elif duty in rg_root:
        gi = rg_root[duty]
        rg_salaries[gi].append(sal)
        rg_split[gi][int(r.get("pgroup", 0))].append(sal)

obj23 = F196_OBJ2 + F196_OBJ3
ben_rate = F196_OBJ4 / obj23
ben_mult = 1.0 + ben_rate
ben_pool = F196_OBJ4 * s275_total / obj23

# --- pack each component, build bubble svg + data ----------------------------

def fmt_m(v):
    return "$%.1fM" % (v / 1e6)

duties, duty_ix = [], {}
emp = []            # [salary, comp index, duty index]
cluster_html = []
comps_js = []

for ci, (key, label, codes, _roots, default_on) in enumerate(CUTTABLE):
    staff = sorted(comp_staff[ci], reverse=True)
    circles = []
    for sal, dname in staff:
        rr = max(MIN_R, K * math.sqrt(sal))
        circles.append({"pr": rr + PACK_GAP / 2, "r": rr, "s": sal, "d": dname})
    pack_siblings(circles)
    pad = 5
    x0 = min(c["x"] - c["r"] for c in circles) - pad
    x1 = max(c["x"] + c["r"] for c in circles) + pad
    y0 = min(c["y"] - c["r"] for c in circles) - pad
    y1 = max(c["y"] + c["r"] for c in circles) + pad
    w, h = x1 - x0, y1 - y0
    total = sum(c["s"] for c in circles)
    color = "var(--school)" if key == "school" else "var(--central)"
    parts = []
    start_id = len(emp)
    for c in circles:
        if c["d"] not in duty_ix:
            duty_ix[c["d"]] = len(duties); duties.append(c["d"])
        eid = len(emp)
        emp.append([round(c["s"]), ci, duty_ix[c["d"]]])
        x, y, rr = c["x"], c["y"], c["r"]
        fs = max(rr * 1.5, 7.0)          # axe glyph size, floor for tiny bubbles
        rot = (eid * 37) % 44 - 22       # deterministic per-bubble tilt
        parts.append(
            '<g class="emp" data-id="%d">'
            '<circle class="dot" cx="%.1f" cy="%.1f" r="%.1f"/>'
            '<text class="x" x="%.1f" y="%.1f" font-size="%.1f" '
            'transform="rotate(%d %.1f %.1f)">\U0001fa93</text>'
            '<circle class="hit" cx="%.1f" cy="%.1f" r="%.1f"/>'
            "</g>"
            % (eid, x, y, rr, x, y, fs, rot, x, y,
               x, y, max(rr + 1.5, 6.0))
        )
    cluster_html.append(
        '<article class="cluster" id="cl-%s" data-c="%d"%s>\n'
        '<header><div class="chead"><h3>%s</h3>'
        '<span class="cmeta">duty %s · %d staff · %s payroll · <b class="cutn" id="cutn-%d">0 cut</b></span></div>'
        '<div class="cbtns"><button type="button" data-cutall="%d">Cut all</button>'
        '<button type="button" data-restore="%d">Restore</button></div></header>\n'
        '<svg viewBox="%.1f %.1f %.1f %.1f" width="%.0f" height="%.0f" style="--dot:%s" role="img" '
        'aria-label="%d %s positions, one bubble each, sized by salary">\n%s\n</svg>\n'
        "</article>"
        % (key, ci, "" if default_on else ' style="display:none"',
           label, codes, len(circles), fmt_m(total), ci, ci, ci,
           x0, y0, w, h, w, h, color, len(circles), label, "\n".join(parts))
    )
    comps_js.append({
        "key": key, "label": label, "n": len(circles), "total": round(total),
        "on": default_on, "a": start_id, "b": len(emp),
    })

# --- recipient stats + control rows ------------------------------------------

CHIP = {"B": "var(--chipB)", "C": "var(--chipC)", "D": "var(--chipD)"}
rg_js, rg_rows = [], []
for gi, (key, label, _roots, fam) in enumerate(RECIPIENTS):
    sals = rg_salaries[gi]
    med = st.median(sals) if sals else 0
    rg_js.append({"key": key, "label": label, "n": len(sals),
                  "median": round(med), "on": True, "w": 1.0})
    rg_rows.append(
        '<div class="rgrow" data-g="%d">'
        '<input type="checkbox" checked data-rg="%d" aria-label="include %s">'
        '<span class="chip" style="background:%s"></span>'
        '<div class="rgname">%s</div>'
        '<span class="rgn">%s staff · med $%s</span>'
        '<div class="wctl"><button type="button" data-g="%d" data-dw="-1" aria-label="less weight">&minus;</button>'
        '<span class="wval" id="w-%d">&times;1.0</span>'
        '<button type="button" data-g="%d" data-dw="1" aria-label="more weight">+</button></div>'
        '<div class="rgout"><b id="per-%d">$0</b><span id="pct-%d">&nbsp;</span></div>'
        "</div>"
        % (gi, gi, label, CHIP[fam], label, format(len(sals), ","),
           format(round(med), ","), gi, gi, gi, gi, gi)
    )

comp_rows = []
for ci, (key, label, codes, _roots, default_on) in enumerate(CUTTABLE):
    color = "var(--school)" if key == "school" else "var(--central)"
    comp_rows.append(
        '<label class="comprow"><input type="checkbox" data-comp="%d"%s>'
        '<span class="swatch" style="background:%s"></span>'
        '<span class="cl">%s <span class="codes">duty %s</span></span>'
        '<span class="cn">%d · %s</span></label>'
        % (ci, " checked" if default_on else "", color, label, codes,
           comps_js[ci]["n"], fmt_m(comps_js[ci]["total"]))
    )

# --- dashboard skyline: one svg, one $ scale, one per-person bar width -------
# Every person — cuttable or SEA — gets the same bar width and the same dollar
# axis, so section widths compare headcounts directly and heights compare pay.
# The SEA side is split by program — Basic ed + other, LAP, Title I, Special
# education — by FTE plurality over each person's assignments (see query.sql).

SKY_W = 1160.0
GROUP_GAP = 10.0
SECTION_GAP = 26.0
PROGRAMS = [(0, "Basic ed + other"), (1, "LAP"), (2, "Title I"),
            (3, "Special education")]

n_cut = len(emp)
n_sea = sum(len(sl) for g in rg_split for sl in g)
max_sea = max(max(sl) for g in rg_split for sl in g if sl)
AX = max(max(e[0] for e in emp) * 1.03, max_sea * 1.45)
H = 120.0
LBL = 32.0            # two label lines under the baseline: groups + sections
scale = AX / H        # dollars per viewBox unit
CAP_SKIRT = 2000.0    # cap paths extend this far below the baseline so a
                      # translate(0,-h) never opens a gap under a short bar

seg_counts = [[len(rg_split[gi][p]) for gi in range(len(RECIPIENTS))]
              for p, _ in PROGRAMS]
n_segs = sum(1 for row in seg_counts for c in row if c)
gaps_total = (GROUP_GAP * (len(CUTTABLE) - 1)      # between cuttable groups
              + SECTION_GAP * len(PROGRAMS)        # block|basic and basic|sped
              + GROUP_GAP * (n_segs - len(PROGRAMS)))
step = (SKY_W - gaps_total) / (n_cut + n_sea)   # width of one person

# short in-chart names; full names live in the panel, headers and fine print
SHORT = {"teach": "Teachers", "subs": "Subs", "cert": "Cert",
         "para": "Paras", "office": "Office"}

def fit_label(label, cx, gw, y, cls):
    """Centered label, clamped into the viewBox; '' if it can't fit."""
    halfw = len(label) * 3.75   # ~7.5 units/char at font-size 13.5
    if 2 * halfw > gw + 22:     # allow a little spill into the gaps
        return ""
    cx = min(max(cx, halfw + 2), SKY_W - halfw - 2)
    return '<text class="%s" x="%.1f" y="%.1f">%s</text>' % (cls, cx, y, label)

def gridlines(axmax, height, sc, width):
    out = []
    step_d = 100_000
    v = step_d
    while v < axmax:
        y = height - v / sc
        out.append('<line class="grid" x1="0" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                   % (y, width, y))
        out.append('<text class="gl" x="3" y="%.1f">$%dk</text>' % (y - 2.5, v // 1000))
        v += step_d
    out.append('<line class="axis" x1="0" y1="%.1f" x2="%.1f" y2="%.1f"/>'
               % (height, width, height))
    return "\n".join(out)

parts = [gridlines(AX, H, scale, SKY_W)]

# cuttable section: individual bars (sub-pixel wide, but per-person state shows)
x = 0.0
for ci, c in enumerate(comps_js):
    key = c["key"]
    bars = []
    for eid in range(c["a"], c["b"]):
        bh = emp[eid][0] / scale
        bars.append('<rect class="bar" data-id="%d" x="%.3f" y="%.2f" width="%.3f" height="%.2f"/>'
                    % (eid, x, H - bh, step * 0.92, bh))
        x += step
    color = "var(--school)" if key == "school" else "var(--central)"
    style = "--dot:%s%s" % (color, "" if c["on"] else ";display:none")
    parts.append('<g id="r1-%s" style="%s">%s</g>' % (key, style, "".join(bars)))
    if ci < len(comps_js) - 1:
        x += GROUP_GAP
admin_end = x

# SEA side: silhouette per (section, group) + translatable blue cap, rendered
# twice — one combined layer (default) and one program-split layer, toggled by
# the "Show program splits" control. Both share `step`, so bar width holds.
def silhouette(sals, gx, bottom):
    """Compact step-function path (H/V commands) for desc-sorted salaries."""
    pts = []               # (x_start, y_top) runs, merged when y is ~equal
    xx = gx
    for sal in sals:
        y = H - sal / scale
        if pts and abs(pts[-1][1] - y) < 0.15:
            pass
        else:
            pts.append((xx, y))
        xx += step
    d = ["M%.2f %.1fV%.1f" % (gx, bottom, pts[0][1])]
    for i, (px, py) in enumerate(pts):
        nx = pts[i + 1][0] if i + 1 < len(pts) else xx
        if i > 0:
            d.append("V%.1f" % py)
        d.append("H%.2f" % nx)
    d.append("V%.1fZ" % bottom)
    return "".join(d)

parts.append('<defs><clipPath id="clip2"><rect x="0" y="0" width="%.0f" height="%.1f"/></clipPath></defs>'
             % (SKY_W, H))
parts.append('<line class="sect" x1="%.1f" y1="0" x2="%.1f" y2="%.1f"/>'
             % (admin_end + SECTION_GAP / 2, admin_end + SECTION_GAP / 2, H))
sea_x0 = admin_end + SECTION_GAP

blk_halfw = len("On the block") * 3.75
blk_cx = min(max(admin_end / 2, blk_halfw + 2), SKY_W - blk_halfw - 2)
parts.append('<text class="gsect" x="%.1f" y="%.1f">On the block</text>' % (blk_cx, H + 27))
blk_end = blk_cx + blk_halfw

def sea_layer(sections, layer_id, visible):
    """One SEA rendering: sections = [(label, per-group salary lists)]."""
    lp, caps, bases, labels = [], [], [], []
    x = sea_x0
    sect_spans = []
    for si, (plabel, per_group) in enumerate(sections):
        if si > 0:
            lp.append('<line class="sect" x1="%.1f" y1="0" x2="%.1f" y2="%.1f"/>'
                      % (x + SECTION_GAP / 2, x + SECTION_GAP / 2, H))
            x += SECTION_GAP
        px0 = x
        first = True
        for gi, (key, label, _roots, fam) in enumerate(RECIPIENTS):
            sals = sorted(per_group[gi], reverse=True)
            if not sals:
                continue
            if not first:
                x += GROUP_GAP
            first = False
            gw = len(sals) * step
            caps.append('<path class="cap" data-cap="%d" d="%s"/>'
                        % (gi, silhouette(sals, x, H + CAP_SKIRT)))
            bases.append('<path class="sil" style="fill:%s" d="%s"/>'
                         % (CHIP[fam], silhouette(sals, x, H)))
            lbl = fit_label(SHORT[key], x + gw / 2, gw, H + 13, "glabel")
            if lbl:
                labels.append(lbl)
            x += gw
        sect_spans.append((plabel, px0, x))
    lp.append('<g clip-path="url(#clip2)">%s</g>' % "\n".join(caps + bases))
    lp += labels
    last_end = blk_end
    for plabel, sx0, sx1 in sect_spans:
        halfw = len(plabel) * 3.75
        cx = min(max((sx0 + sx1) / 2, last_end + 10 + halfw), SKY_W - halfw - 2)
        lp.append('<text class="gsect" x="%.1f" y="%.1f">%s</text>' % (cx, H + 27, plabel))
        last_end = cx + halfw
    return ('<g id="%s"%s>%s</g>'
            % (layer_id, "" if visible else ' style="display:none"', "\n".join(lp)))

parts.append(sea_layer(
    [("SEA-represented staff", [rg_salaries[gi] for gi in range(len(RECIPIENTS))])],
    "seaAll", True))
parts.append(sea_layer(
    [(plabel, [rg_split[gi][p] for gi in range(len(RECIPIENTS))]) for p, plabel in PROGRAMS],
    "seaSplit", False))
sky_svg = ('<svg viewBox="0 0 %.0f %.0f" role="img" '
           'aria-label="salary skyline: every cuttable position and every SEA-represented salary at one shared bar width and dollar scale, SEA split into basic and special education">\n%s\n</svg>'
           % (SKY_W, H + LBL, "\n".join(parts)))

pg_counts = [sum(len(rg_split[gi][p]) for gi in range(len(RECIPIENTS)))
             for p, _ in PROGRAMS]
pgroup_counts_str = " &middot; ".join(
    "%s %s" % (label, format(n, ",")) for (_, label), n in zip(PROGRAMS, pg_counts))

# --- assemble ----------------------------------------------------------------

pool_n = sum(g["n"] for g in rg_js)
pool_label = format(pool_n, ",")
marg0 = "$%s" % format(round(1e6 / pool_n), ",")

html = (Path(__file__).resolve().parent / "admin_game_template.html").read_text()

for token, value in [
    ("@@CLUSTERS@@", "\n".join(cluster_html)),
    ("@@COMP_ROWS@@", "\n".join(comp_rows)),
    ("@@RG_ROWS@@", "\n".join(rg_rows)),
    ("@@SKY@@", sky_svg),
    ("@@PGROUP_COUNTS@@", pgroup_counts_str),
    ("@@EMP@@", json.dumps(emp, separators=(",", ":"))),
    ("@@DUTIES@@", json.dumps(duties, separators=(",", ":"))),
    ("@@COMPS@@", json.dumps(comps_js, separators=(",", ":"))),
    ("@@RG@@", json.dumps(rg_js, separators=(",", ":"))),
    ("@@POOL_N@@", pool_label),
    ("@@MARG0@@", marg0),
    ("@@BENMULT@@", "%.5f" % ben_mult),
    ("@@SCALE2@@", "%.3f" % scale),
    ("@@BEN_PCT@@", "%.1f" % (ben_rate * 100)),
    ("@@BENMULT3@@", "%.3f" % ben_mult),
    ("@@DEFS@@", json.dumps([
        {"label": "2026\u201327 budget deficit", "total": DEFICIT_2627, "on": True},
        {"label": "Economic Stabilization Fund", "total": ESF_START, "on": True},
    ], separators=(",", ":"))),
    ("@@DEF1M@@", "$%.1fM" % (DEFICIT_2627 / 1e6)),
    ("@@ESF_START_$@@", "$%.1fM" % (ESF_START / 1e6)),
    ("@@HOLE0@@", "$%.1fM" % ((DEFICIT_2627 + ESF_START) / 1e6)),
    ("@@ESF_TARGET@@", format(ESF_TARGET, ",")),
    ("@@ESF_FLOOR@@", str(ESF_TARGET - ESF_COMMITTED)),
    ("@@ESF_START_M@@", "%.1f" % (ESF_START / 1e6)),
    ("@@GF_BUDGET@@", format(GF_BUDGET_2627, ",")),
    ("@@DEFICIT@@", format(DEFICIT_2627, ",")),
    ("@@OBJ4M@@", "$%.1fM" % (F196_OBJ4 / 1e6)),
    ("@@OBJ23M@@", "$%.1fM" % (obj23 / 1e6)),
    ("@@S275M@@", "$%.1fM" % (s275_total / 1e6)),
    ("@@BENPOOLM@@", "$%.1fM" % (ben_pool / 1e6)),
]:
    assert token in html, "missing token " + token
    html = html.replace(token, value)

OUT.write_text(html)
print("wrote %s  (%d cuttable, %d recipients, benefits x%.4f)"
      % (OUT, len(emp), pool_n, ben_mult))
