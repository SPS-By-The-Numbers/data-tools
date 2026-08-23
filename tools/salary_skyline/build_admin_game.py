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
ap.add_argument("--services", default="out_salary_skyline/services.csv",
                help="F-196 object-7 CSV from services_query.sql")
ap.add_argument("-o", "--out", default="out_salary_skyline/admin_game.html")
args = ap.parse_args()

SRC, OUT = Path(args.data), Path(args.out)
SVC = Path(args.services)
if not SVC.exists():
    raise SystemExit("missing %s — run services_query.sql (see file header)" % SVC)
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

# Benefits are ALWAYS included: every staff dollar downstream — bubble areas,
# skyline bars/silhouettes, medians, EMP values, freed money — is total
# compensation = salary × ben_mult. Purchased services carry no benefits.
rg_salaries = [[v * ben_mult for v in l] for l in rg_salaries]
rg_split = [[[v * ben_mult for v in sl] for sl in g] for g in rg_split]

# --- pack each component, build bubble svg + data ----------------------------

def fmt_m(v):
    return "$%.1fM" % (v / 1e6)

duties, duty_ix = [], {}
emp = []            # [salary, comp index, duty index]
cluster_html = []
comps_js = []

# unified component list: staff clusters from CUTTABLE, then the F-196
# object-7 purchased-services partitions (one bubble per NCES class)
SPED_SVC_WARN = ("warning: cuts here impact vulnerable students and may just "
                 "decrease revenue leading to no deficit impact. This simulator "
                 "incorrectly treats it all as redistributable funds but at "
                 "least $20M is Safety Net that would just go away.")
component_defs = [
    (key, label, "duty " + codes,
     sorted(((sal * ben_mult, dname) for sal, dname in comp_staff[ci]), reverse=True),
     default_on, False, None)
    for ci, (key, label, codes, _roots, default_on) in enumerate(CUTTABLE)
]
svc_parts = [[], []]
for r in csv.DictReader(SVC.open()):
    svc_parts[int(r["sped"])].append(
        (float(r["amount"]), "NCES %s · %s" % (r["nces"], r["nces_name"])))
component_defs.append(("svcother", "Purchased services — other programs",
                       "F-196 obj 7", sorted(svc_parts[0], reverse=True),
                       True, True, None))
component_defs.append(("svcsped", "Purchased services — SpEd",
                       "F-196 obj 7 · prog 21+24", sorted(svc_parts[1], reverse=True),
                       True, True, SPED_SVC_WARN))

for ci, (key, label, caption, items, default_on, is_svc, warn) in enumerate(component_defs):
    circles = []
    for sal, dname in items:
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
    color = ("var(--svc)" if is_svc
             else "var(--school)" if key == "school" else "var(--central)")
    parts = []
    start_id = len(emp)
    for c in circles:
        if c["d"] not in duty_ix:
            duty_ix[c["d"]] = len(duties); duties.append(c["d"])
        eid = len(emp)
        emp.append([round(c["s"]), ci, duty_ix[c["d"]]])
        x, y, rr = c["x"], c["y"], c["r"]
        fs = min(max(rr * 1.5, 7.0), 64.0)   # axe glyph size, floored + capped
        rot = (eid * 37) % 44 - 22           # deterministic per-bubble tilt
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
    meta = ("%s · %d spend classes · %s actuals" % (caption, len(circles), fmt_m(total))
            if is_svc else
            "%s · %d staff · %s comp" % (caption, len(circles), fmt_m(total)))
    aria = ("%d purchased-services classes, one bubble each, sized by annual spend"
            % len(circles) if is_svc else
            "%d %s positions, one bubble each, sized by total compensation" % (len(circles), label))
    cluster_html.append(
        '<article class="cluster" id="cl-%s" data-c="%d"%s%s>\n'
        '<header><div class="chead"><h3>%s</h3>'
        '<span class="cmeta">%s · <b class="cutn" id="cutn-%d">0 cut</b></span></div>'
        '<div class="cbtns"><button type="button" data-cutall="%d">Cut all</button>'
        '<button type="button" data-restore="%d">Restore</button></div></header>\n'
        '%s'
        '<svg viewBox="%.1f %.1f %.1f %.1f" width="%.0f" height="%.0f" style="--dot:%s" role="img" '
        'aria-label="%s">\n%s\n</svg>\n'
        "</article>"
        % (key, ci, ' data-svc="1"' if is_svc else "",
           "" if default_on else ' style="display:none"',
           label, meta, ci, ci, ci,
           ('<p class="cwarn"><span class="wico">&#9888;</span> %s</p>\n' % warn) if warn else "",
           x0, y0, w, h, w, h, color, aria, "\n".join(parts))
    )
    comps_js.append({
        "key": key, "label": label, "n": len(circles), "total": round(total),
        "on": default_on, "a": start_id, "b": len(emp), "svc": is_svc,
    })
n_staff = comps_js[len(CUTTABLE) - 1]["b"]

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
        '<span class="rgn">%s staff · med comp $%sk</span>'
        '<div class="wctl"><button type="button" data-g="%d" data-dw="-1" aria-label="less weight">&minus;</button>'
        '<span class="wval" id="w-%d">&times;1.0</span>'
        '<button type="button" data-g="%d" data-dw="1" aria-label="more weight">+</button></div>'
        '<div class="rgout"><b id="per-%d">$0</b><span id="pct-%d">&nbsp;</span></div>'
        "</div>"
        % (gi, gi, label, CHIP[fam], label, format(len(sals), ","),
           format(round(med / 1000)), gi, gi, gi, gi, gi)
    )

# --- dashboard skyline: three stacked rows, one $ scale, one bar width -------
# Row 1: every cuttable position. Row 2: the hole (area-true rects). Row 3:
# every SEA salary. All rows share the same dollars-per-unit scale and the
# same per-person bar width, so lengths compare headcounts across rows and
# heights compare pay.

SKY_W = 1160.0
GROUP_GAP = 10.0
SECTION_GAP = 26.0
PROGRAMS = [(0, "Basic ed + other"), (1, "LAP"), (2, "Title I"),
            (3, "Special education")]

n_cut = n_staff
n_sea = sum(len(sl) for g in rg_split for sl in g)
max_sea = max(max(sl) for g in rg_split for sl in g if sl)
seg_counts = [[len(rg_split[gi][p]) for gi in range(len(RECIPIENTS))]
              for p, _ in PROGRAMS]
n_segs = sum(1 for row in seg_counts for c in row if c)
sea_gaps = SECTION_GAP * (len(PROGRAMS) - 1) + GROUP_GAP * (n_segs - len(PROGRAMS))
# the hole shares the SEA row, so solve the per-person step jointly with the
# hole rects' area-true width (8.0 = gap between the two rects)
HOLE_X0 = 34.0
hole_dollars = DEFICIT_2627 + (ESF_TARGET - ESF_COMMITTED)
step = ((SKY_W - HOLE_X0 - 8.0 - SECTION_GAP - sea_gaps)
        / (n_sea + hole_dollars / max_sea))     # width of one person

AX_BLK = max(e[0] for e in emp[:n_staff]) * 1.03
H_BLK = 75.0
scale = AX_BLK / H_BLK                          # dollars per viewBox unit
HRECT_GAP = 8.0
CAP_SKIRT = 2000.0
rect_h = max_sea / scale                        # area-true rect height = max SEA salary
wpd = step / max_sea                            # viewBox units per dollar at that height
H_SEA = max_sea * 1.45 / scale                  # headroom for the blue stacks
LBL3 = 32.0                                     # labels under the shared row
B1 = H_BLK                                      # row baselines; titles go BELOW rows
B2 = B1 + 18.0 + H_SEA                          # shared baseline: hole + SEA
TOTAL_H = B2 + LBL3

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

def row_grid(base, height, texts=True):
    """Per-row $100k gridlines + axis, labels with the shared scale."""
    out = []
    v = 100_000
    while v / scale < height:
        y = base - v / scale
        out.append('<line class="grid" x1="0" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                   % (y, SKY_W, y))
        if texts:
            out.append('<text class="gl" x="%.1f" y="%.1f">$%dk</text>'
                       % (SKY_W - 3, y - 2.5, v // 1000))
        v += 100_000
    out.append('<line class="axis" x1="0" y1="%.1f" x2="%.1f" y2="%.1f"/>'
               % (base, SKY_W, base))
    return "\n".join(out)

parts = [row_grid(B1, H_BLK), row_grid(B2, H_SEA)]

# row 1 — cuttable positions
x = 0.0
for ci, c in enumerate(comps_js[:len(CUTTABLE)]):
    key = c["key"]
    bars = []
    for eid in range(c["a"], c["b"]):
        bh = emp[eid][0] / scale
        bars.append('<rect class="bar" data-id="%d" x="%.3f" y="%.2f" width="%.3f" height="%.2f"/>'
                    % (eid, x, B1 - bh, step * 0.92, bh))
        x += step
    color = "var(--school)" if key == "school" else "var(--central)"
    style = "--dot:%s%s" % (color, "" if c["on"] else ";display:none")
    parts.append('<g id="r1-%s" style="%s">%s</g>' % (key, style, "".join(bars)))
    if ci < len(CUTTABLE) - 1:
        x += GROUP_GAP
admin_end = x
parts.append('<text class="rowt" x="0" y="%.1f">On the block</text>' % (B1 + 13))

# row 2 — the hole: two area-true rects (height = max SEA salary)
w_def = DEFICIT_2627 * wpd
w_esf_slot = (ESF_TARGET - ESF_COMMITTED) * wpd   # reserved slot (the 3% floor)
w_esf_start = max(ESF_START * wpd, 1.5)
esf_x = HOLE_X0 + w_def + HRECT_GAP
esf_rx = esf_x + (w_esf_slot - w_esf_start) / 2   # centered in its slot
for i, (rx, rw) in enumerate([(HOLE_X0, w_def), (esf_rx, w_esf_start)]):
    parts.append('<rect class="hrect" id="hbg-%d" x="%.2f" y="%.2f" width="%.2f" height="%.2f"/>'
                 % (i, rx, B2 - rect_h, rw, rect_h))
    parts.append('<rect class="hfillr" id="hfr-%d" x="%.2f" y="%.2f" width="%.2f" height="0"/>'
                 % (i, rx, B2, rw))
last_end = 0.0
for hlabel, cx0 in [("Deficit", HOLE_X0 + w_def / 2), ("ESF", esf_x + w_esf_slot / 2)]:
    halfw = len(hlabel) * 3.75
    cx = min(max(cx0, last_end + 2 + halfw), SKY_W - halfw - 2)
    parts.append('<text class="glabel" x="%.1f" y="%.1f">%s</text>' % (cx, B2 + 13, hlabel))
    last_end = cx + halfw
parts.append('<text class="rowt" x="0" y="%.1f">The hole</text>' % (B2 + 27))
sea_x0 = esf_x + w_esf_slot + SECTION_GAP
SEA_TITLE_END = sea_x0 + 150.0
parts.append('<line class="sect" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
             % (sea_x0 - SECTION_GAP / 2, B2 - H_SEA, sea_x0 - SECTION_GAP / 2, B2))

# row 3 — SEA staff: silhouettes + translatable blue caps, two toggleable layers
parts.append('<defs><clipPath id="clip2"><rect x="0" y="%.1f" width="%.0f" height="%.1f"/></clipPath></defs>'
             % (B2 - H_SEA, SKY_W, H_SEA))

def silhouette(sals, gx, bottom):
    """Compact step-function path (H/V commands) for desc-sorted salaries."""
    pts = []
    xx = gx
    for sal in sals:
        y = B2 - sal / scale
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

def sea_layer(sections, layer_id, visible):
    """One SEA rendering: sections = [(label, per-group salary lists)]."""
    lp, caps, bases, labels = [], [], [], []
    x = sea_x0
    sect_spans = []
    for si, (plabel, per_group) in enumerate(sections):
        if si > 0:
            lp.append('<line class="sect" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                      % (x + SECTION_GAP / 2, B2 - H_SEA, x + SECTION_GAP / 2, B2))
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
                        % (gi, silhouette(sals, x, B2 + CAP_SKIRT)))
            bases.append('<path class="sil" style="fill:%s" d="%s"/>'
                         % (CHIP[fam], silhouette(sals, x, B2)))
            lbl = fit_label(SHORT[key], x + gw / 2, gw, B2 + 13, "glabel")
            if lbl:
                labels.append(lbl)
            x += gw
        sect_spans.append((plabel, px0, x))
    lp.append('<g clip-path="url(#clip2)">%s</g>' % "\n".join(caps + bases))
    lp += labels
    last_end = SEA_TITLE_END
    for plabel, sx0, sx1 in sect_spans:
        if not plabel:
            continue
        halfw = len(plabel) * 3.75
        cx = min(max((sx0 + sx1) / 2, last_end + 10 + halfw), SKY_W - halfw - 2)
        lp.append('<text class="gsect" x="%.1f" y="%.1f">%s</text>' % (cx, B2 + 27, plabel))
        last_end = cx + halfw
    return ('<g id="%s"%s>%s</g>'
            % (layer_id, "" if visible else ' style="display:none"', "\n".join(lp)))

parts.append('<text class="rowt" x="%.1f" y="%.1f">SEA-represented staff</text>'
             % (sea_x0, B2 + 27))
parts.append(sea_layer(
    [("", [rg_salaries[gi] for gi in range(len(RECIPIENTS))])],
    "seaAll", True))
parts.append(sea_layer(
    [(plabel, [rg_split[gi][p] for gi in range(len(RECIPIENTS))]) for p, plabel in PROGRAMS],
    "seaSplit", False))
sky_svg = ('<svg viewBox="0 0 %.0f %.0f" role="img" '
           'aria-label="two-row salary skyline: cuttable positions, then the 2026-27 hole beside every SEA-represented salary, one shared bar width and dollar scale">\n%s\n</svg>'
           % (SKY_W, TOTAL_H, "\n".join(parts)))

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
    ("@@HOLE0@@", "$%.1fM" % ((DEFICIT_2627 + ESF_START) / 1e6)),
    ("@@ESF_TARGET@@", format(ESF_TARGET, ",")),
    ("@@ESF_FLOOR@@", str(ESF_TARGET - ESF_COMMITTED)),
    ("@@WPD@@", "%.9f" % wpd),
    ("@@ESF_SLOT_W@@", "%.2f" % w_esf_slot),
    ("@@ESF_SLOT_X@@", "%.2f" % esf_x),
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
