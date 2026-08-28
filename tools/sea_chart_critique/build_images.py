"""Three standalone PNG-ready charts for sharing outside the artifact page.

    $ venv/bin/python3 tools/sea_chart_critique/build_images.py
    $ tools/sea_chart_critique/render_images.sh

Writes output/sea_chart_critique/img{1,2,3}.html; the shell script screenshots
each to a .png at 2x. Light theme only -- these are flat images, so there is no
viewer theme to follow.
"""
import csv
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402
from decimal import Decimal as D  # noqa: E402

OUT = data.OUT
INK, INK2, INK3 = "#0d1117", "#4a5462", "#727d8c"
ACCENT, TRACK, GRID, AXIS = "#2a78d6", "#aab7c7", "#e4e8ee", "#9aa3b0"
SURFACE, PLANE, RULE = "#ffffff", "#f2f4f7", "#d8dde5"
MARK = "#d1481f"      # the unit-cost overlay line, image 3


def esc(s):
    return html.escape(str(s))


def money(v, dp=0):
    return "$%s" % f"{float(v):,.{dp}f}"


def mil(v):
    return "$%.1fM" % (float(v) / 1e6)


def nice_max(v, steps=5, headroom=1.04):
    import math
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15, 20):
        if m * mag >= v * headroom:
            return m * mag, m * mag / steps
    return 20 * mag, 4 * mag


PAGE = """<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;padding:26px;background:{plane};
       font-family:"Archivo",Helvetica,Arial,sans-serif;
       color:{ink};-webkit-font-smoothing:antialiased}}
  .card{{width:{w}px;background:{surface};padding:30px 34px 22px;
        border:1px solid {rule}}}
  h1{{font-size:{ts}px;line-height:1.18;letter-spacing:-.02em;font-weight:700;
     margin:0 0 6px;text-wrap:balance}}
  .sub{{font-size:14.5px;line-height:1.5;color:{ink2};margin:0 0 4px;max-width:88ch}}
  .legend{{display:flex;gap:22px;flex-wrap:wrap;margin:16px 0 4px;font-size:13px;
          color:{ink2}}}
  .legend span{{display:flex;align-items:center;gap:7px}}
  .sw{{width:13px;height:13px;border-radius:2px;display:inline-block}}
  .rule{{width:20px;height:0;border-top:2.5px solid {mark};display:inline-block}}
  svg{{display:block;width:100%;height:auto;overflow:visible}}
  text{{font-family:"Archivo",Helvetica,Arial,sans-serif}}
  .foot{{margin-top:14px;padding-top:12px;border-top:1px solid {rule};
        font-size:12px;line-height:1.5;color:{ink3};max-width:96ch}}
</style>
<div class="card">{body}</div>"""


def page(w, title, sub, legend, svg, foot, ts=26):
    body = f"<h1>{title}</h1><p class='sub'>{sub}</p>{legend}{svg}<p class='foot'>{foot}</p>"
    return PAGE.format(w=w, ts=ts, body=body, plane=PLANE, surface=SURFACE,
                       ink=INK, ink2=INK2, ink3=INK3, rule=RULE, mark=MARK)


# ============================================================ image 1
def _headcounts():
    p = os.path.join(OUT, "group_headcount.csv")
    with open(p) as f:
        return {r["grp"]: int(r["people"]) for r in csv.DictReader(f)}


def image1(rates, duties):
    groups = sorted(data.group_rows(duties, rates), key=lambda g: -float(g["salary"]))
    hc = _headcounts()
    funded = data.funded_units_by_group(duties)
    VB, label_w, pad_r = 1000, 268, 150
    row_h, top = 62, 26
    n = len(groups)
    h = top + n * row_h + 54
    plot_w = VB - label_w - pad_r
    span, step = nice_max(max(float(g["salary"]) for g in groups), 4)
    s = [f'<svg viewBox="0 0 {VB} {h}">']
    for i in range(int(round(span / step)) + 1):
        v = i * step
        x = label_w + plot_w * v / span
        s.append(f'<line x1="{x:.1f}" y1="{top - 10}" x2="{x:.1f}" '
                 f'y2="{top + n * row_h + 6}" stroke="{AXIS if i == 0 else GRID}"/>')
        s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 26}" fill="{INK3}" '
                 f'font-size="12.5" text-anchor="middle">${v / 1e6:.0f}M</text>')
    OH, IH = 26, 13
    for i, g in enumerate(groups):
        paid = float(g["salary"])
        alloc = float(g["rate"] * funded[g["name"]])
        pct = alloc / paid * 100
        cy = top + i * row_h + row_h / 2 - 4
        wo, wi = max(1.5, plot_w * paid / span), max(1.5, plot_w * alloc / span)
        s.append(f'<rect x="{label_w}" y="{cy - OH / 2:.1f}" width="{wo:.1f}" '
                 f'height="{OH}" rx="3" fill="{TRACK}"/>')
        s.append(f'<rect x="{label_w}" y="{cy - IH / 2:.1f}" width="{wi:.1f}" '
                 f'height="{IH}" rx="2" fill="{ACCENT}" stroke="{SURFACE}" '
                 f'stroke-width="1.5"/>')
        s.append(f'<text x="{label_w - 14}" y="{cy - 7:.1f}" fill="{INK}" '
                 f'font-size="14.5" font-weight="600" text-anchor="end">'
                 f'{esc(g["name"])}</text>')
        s.append(f'<text x="{label_w - 14}" y="{cy + 8:.1f}" fill="{INK3}" '
                 f'font-size="11.5" text-anchor="end">'
                 f'{_fte(g["fte"])} FTE employed · '
                 f'{_fte(funded[g["name"]])} funded</text>')
        s.append(f'<text x="{label_w - 14}" y="{cy + 21:.1f}" fill="{INK3}" '
                 f'font-size="11.5" text-anchor="end">'
                 f'{g["class"]} rate {money(g["rate"])} per staff unit'
                 f'</text>')
        lx = label_w + wo + 12
        s.append(f'<text x="{lx:.1f}" y="{cy - 1:.1f}" fill="{INK2}" '
                 f'font-size="13.5" font-weight="600">{mil(paid)}</text>')
        s.append(f'<text x="{lx:.1f}" y="{cy + 13:.1f}" fill="{INK3}" '
                 f'font-size="11.5">{pct:.0f}% state-funded</text>')
    s.append('</svg>')
    tot_p = sum(float(g["salary"]) for g in groups)
    tot_a = sum(float(g["rate"] * funded[g["name"]]) for g in groups)
    legend = (f'<div class="legend">'
              f'<span><i class="sw" style="background:{TRACK}"></i>'
              f'salary SPS paid</span>'
              f'<span><i class="sw" style="background:{ACCENT}"></i>'
              f'what the state’s formula allocates</span></div>')
    foot = (f"Across these eight groups SPS paid {mil(tot_p)} in salary against "
            f"{mil(tot_a)} the state allocates — {tot_a / tot_p * 100:.0f}% covered, "
            f"{mil(tot_p - tot_a)} short. Salary only on both sides, no benefits. "
            f"The state figure is the staff units the prototypical school model "
            f"generates for that job, times the salary rate for its class. That "
            f"unit count comes from enrollment and does not move when the "
            f"district hires, which is why coverage falls hardest where SPS "
            f"staffs furthest above the model. Instructional aides are the "
            f"extreme, and the most heavily caveated: basic education staff "
            f"units ignore the special education and MLL money that pays for "
            f"most paraeducators, so their real support is higher than shown. "
            f"Sources: OSPI S-275 final 2024-25 and Final Apportionment Summary "
            f"(Reports 1191F and 1191EDF), Seattle Public Schools.")
    return page(1000, "What SPS pays its staff, and what the state pays for",
                "Every salary dollar SPS paid each group in 2024-25, with the "
                "state’s actual allocation for that job overlaid — its funded "
                "staff units at the rate for their class. The uncovered "
                "remainder is what levy, federal and local money must fill.",
                legend, "\n".join(s), foot)


def _people(n):
    return "1 person" if n == 1 else f"{n:,} people"


def _fte(v):
    v = float(v)
    return f"{v:,.1f}" if v < 10 else f"{v:,.0f}"


# ============================================================ image 2
CLASS_NAME = {"CIS": "Certificated instructional (CIS)",
              "CAS": "Certificated administrative (CAS)",
              "CLS": "Classified (CLS)"}
def _no_unit():
    """FTE in duty roots the basic education allocation funds nothing for,
    read from the role table rather than pinned, so a data refresh moves it."""
    out = {"CIS": D(0), "CAS": D(0), "CLS": D(0)}
    with open(os.path.join(data.DUTY_FUNDING,
                           "sps_2024-25_model_roles.csv")) as f:
        for r in csv.DictReader(f):
            if r["role"].startswith("Roles with no basic"):
                out[r["staff_class"]] += D(r["actual_fte"])
    return out


NO_UNIT = _no_unit()


def _under_note(roles):
    under = [r for r in roles if r["actual_fte"] < r["model_fte"]]
    names = " and ".join(r["role"].split(" (")[0].lower() for r in under)
    return ("Only %s %s funded more generously than SPS staffs them."
            % (names, "is" if len(under) == 1 else "are"))


def image2(roles):
    by_class = {}
    for r in roles:
        by_class.setdefault(r["class"], []).append(r)
    for k in by_class:
        by_class[k].sort(key=lambda r: -float(r["actual_fte"]))
    VB, label_w, pad_r = 1000, 262, 96
    plot_w = VB - label_w - pad_r
    span, step = nice_max(max(float(r["actual_fte"]) for r in roles), 4,
                          headroom=1.0)
    row_h, gap_h = 42, 30
    out = []
    for cls in ("CIS", "CAS", "CLS"):
        rs = by_class[cls]
        n = len(rs)
        top = 46
        h = top + n * row_h + 44
        mf = sum(r["model_fte"] for r in rs)
        af = sum(r["actual_fte"] for r in rs) + NO_UNIT[cls]
        s = [f'<svg viewBox="0 0 {VB} {h}" style="margin-bottom:{gap_h}px">']
        s.append(f'<text x="0" y="16" fill="{INK}" font-size="15" '
                 f'font-weight="700">{esc(CLASS_NAME[cls])}</text>')
        s.append(f'<text x="{VB}" y="16" fill="{INK3}" font-size="12.5" '
                 f'text-anchor="end">{af:,.0f} FTE employed · {mf:,.0f} '
                 f'funded staff units</text>')
        for i in range(int(round(span / step)) + 1):
            v = i * step
            x = label_w + plot_w * v / span
            s.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" '
                     f'y2="{top + n * row_h + 4}" '
                     f'stroke="{AXIS if i == 0 else GRID}"/>')
            s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 22}" fill="{INK3}" '
                     f'font-size="11.5" text-anchor="middle">{v:,.0f}</text>')
        bh = 12
        for i, r in enumerate(rs):
            cy = top + i * row_h + row_h / 2 - 3
            for j, (val, fill) in enumerate(((r["model_fte"], ACCENT),
                                             (r["actual_fte"], INK))):
                w = max(1.2, plot_w * float(val) / span)
                y = cy - bh - 1 + j * (bh + 2)
                s.append(f'<rect x="{label_w}" y="{y:.1f}" width="{w:.1f}" '
                         f'height="{bh}" rx="2" fill="{fill}"/>')
                s.append(f'<text x="{label_w + w + 8:.1f}" y="{y + bh - 2:.1f}" '
                         f'fill="{INK3}" font-size="11">{float(val):,.0f}</text>')
            ratio = float(r["actual_fte"] / r["model_fte"]) if r["model_fte"] else 0
            s.append(f'<text x="{label_w - 14}" y="{cy - 2:.1f}" fill="{INK}" '
                     f'font-size="13" text-anchor="end">{esc(r["role"])}</text>')
            s.append(f'<text x="{label_w - 14}" y="{cy + 12:.1f}" '
                     f'fill="{INK if ratio > 1 else ACCENT}" '
                     f'font-size="11.5" font-weight="600" text-anchor="end">'
                     f'{ratio:.2f}×</text>')
        s.append('</svg>')
        out.append("\n".join(s))
    legend = (f'<div class="legend">'
              f'<span><i class="sw" style="background:{ACCENT}"></i>'
              f'staff units the state funds</span>'
              f'<span><i class="sw" style="background:{INK}"></i>'
              f'FTE SPS actually employs</span></div>')
    foot = ("Report 1191EDF builds the state’s certificated and classified "
            "totals one role at a time, and the roles sum exactly to those "
            "totals — so this is the state’s own decomposition, matched to the "
            "S-275 duty codes that do each job. " + _under_note(roles) +
            " A further %.0f FTE do jobs the basic education allocation has no staff unit "
            % float(sum(NO_UNIT.values())) +
            "for at all — therapists, speech pathologists, behaviour analysts, "
            "substitutes — and are counted in the FTE totals above but have no "
            "role row. Sources: OSPI Final Apportionment Summary reports 1191F "
            "and 1191EDF, and S-275 final, Seattle Public Schools 2024-25.")
    return page(1000, "Every role the model funds, against the staff who fill it",
                "The state’s prototypical school model generates 3,647 staff "
                "units for Seattle. SPS employs 6,362 FTE. This is where the "
                "difference sits, role by role, on one shared scale.",
                legend, "\n".join(out), foot)


# ============================================================ image 3
DUTY_GROUP = {**{d: "Teachers" for d in ("31", "32", "33", "34")},
              "91": "Instructional aides (paras)",
              "96": "Classified professionals",
              "99": "Directors & supervisors",
              **{d: "Principals & vice principals"
                 for d in ("21", "22", "23", "24", "25")},
              "94": "Office & clerical",
              "12": "Cabinet & district admin",
              "13": "Cabinet & district admin",
              "11": "Superintendent"}
STAFF_CSV = os.path.join(OUT, "staff_2425.csv")


def _split_by_fte(items, n_rows):
    """Split [(salary_per_fte, fte)] into n_rows chunks of roughly equal FTE."""
    total = sum(f for _v, f in items)
    target, out, cur, acc = total / n_rows, [], [], 0.0
    for it in items:
        cur.append(it)
        acc += it[1]
        if acc >= target and len(out) < n_rows - 1:
            out.append(cur)
            cur, acc = [], 0.0
    if cur:
        out.append(cur)
    return out


def _row_plan(buckets, order, teacher_rows=3, aide_rows=2):
    """Rows of roughly equal FTE: teachers over N, aides over M, rest together.

    Each row is a list of (label, group, [(salary_per_fte, fte), ...]).
    """
    rows = []
    for name, n in ((order[0], teacher_rows), (order[1], aide_rows)):
        for k, chunk in enumerate(_split_by_fte(buckets[name], n)):
            label = name if k == 0 else f"{name} Cont'd ({k})"
            rows.append([(label, name, chunk)])
    rows.append([(g, g, buckets[g]) for g in order[2:] if buckets[g]])
    return rows


def image3(rates, duties, rate_line=True):
    """Skyline where bar WIDTH is FTE and HEIGHT is salary per FTE, so each
    bar's area is what that person is paid.

    Width has to be FTE, not one slot per person: the state funds staff units,
    which are FTE, so a mark placed at the funded-unit count only lands in the
    right place if the axis is in the same units. On a per-person axis the aide
    mark sat 31% short of where the funding actually reaches.
    """
    rate_of = {g["name"]: float(g["rate"]) for g in data.group_rows(duties, rates)}
    funded = {k: float(v) for k, v in data.funded_units_by_group(duties).items()}
    order = [g["name"] for g in
             sorted(data.group_rows(duties, rates), key=lambda g: -float(g["salary"]))]
    buckets, heads = {k: [] for k in order}, {k: 0 for k in order}
    with open(STAFF_CSV) as f:
        for r in csv.DictReader(f):
            g = DUTY_GROUP.get(r["duty"])
            if not (g and r["salary"]):
                continue
            fte = float(r["fte"] or 0)
            heads[g] += 1
            if fte > 0:
                buckets[g].append((float(r["salary"]) / fte, fte))
    for g in buckets:
        buckets[g].sort(reverse=True)
    rows = _row_plan(buckets, order)
    total_fte = sum(f for b in buckets.values() for _v, f in b)

    VB, ml, mr = 1200, 60, 34
    plot_w = VB - ml - mr
    lab_h, plot_h, foot_h = 86, 158, 28
    row_total = lab_h + plot_h + foot_h
    h = len(rows) * row_total + 6
    span, step = nice_max(max(v for b in buckets.values() for v, _f in b), 4)
    widest = max(sum(f for _l, _g, c in row for _v, f in c) for row in rows)
    pitch = plot_w / widest                      # pixels per FTE

    s = [f'<svg viewBox="0 0 {VB} {h}">']
    seen = 0.0
    drawn = {g: 0.0 for g in buckets}
    for ri, row in enumerate(rows):
        y0 = ri * row_total + lab_h
        yb = y0 + plot_h

        def Y(v):
            return yb - plot_h * min(v, span) / span

        for i in range(int(round(span / step)) + 1):
            v = i * step
            s.append(f'<line x1="{ml}" y1="{Y(v):.1f}" x2="{ml + plot_w}" '
                     f'y2="{Y(v):.1f}" stroke="{AXIS if i == 0 else GRID}"/>')
            s.append(f'<text x="{ml - 8}" y="{Y(v) + 4:.1f}" fill="{INK3}" '
                     f'font-size="11.5" text-anchor="end">${v / 1000:.0f}k</text>')
        cursor, narrow, marks = 0.0, 0, []
        mark_end, mark_level = -1e9, 0
        row_fte = sum(f for _l, _g, c in row for _v, f in c)
        for si, (label, g, vals) in enumerate(row):
            seg_fte = sum(f for _v, f in vals)
            x0 = ml + cursor * pitch
            x1 = ml + (cursor + seg_fte) * pitch
            w = x1 - x0
            x = x0
            for v, f in vals:
                bw = f * pitch
                s.append(f'<rect x="{x:.2f}" y="{Y(v):.2f}" '
                         f'width="{max(bw, 0.4):.2f}" height="{yb - Y(v):.2f}" '
                         f'fill="{ACCENT}"/>')
                x += bw
            r = rate_of[g]
            left = funded[g] - drawn[g]
            band = max(0.0, min(left, seg_fte))
            drawn[g] += seg_fte
            if si > 0:
                s.append(f'<line x1="{x0:.1f}" y1="{y0 - 4}" x2="{x0:.1f}" '
                         f'y2="{yb}" stroke="{RULE}" stroke-width="1"/>')
            if rate_line and band > 0:
                bw = band * pitch
                s.append(f'<rect x="{x0:.2f}" y="{Y(r):.2f}" width="{bw:.2f}" '
                         f'height="{yb - Y(r):.2f}" fill="{MARK}" '
                         f'fill-opacity="0.16"/>')
                s.append(f'<line x1="{x0:.2f}" y1="{yb:.1f}" '
                         f'x2="{x0 + bw:.2f}" y2="{yb:.1f}" stroke="{MARK}" '
                         f'stroke-width="2"/>')
            if rate_line:
                s.append(f'<line x1="{x0:.1f}" y1="{Y(r):.1f}" x2="{x1:.1f}" '
                         f'y2="{Y(r):.1f}" stroke="{MARK}" stroke-width="2.5"/>')
            if rate_line and 0 < left <= seg_fte:
                xf = x0 + left * pitch
                txt = f"{funded[g]:,.0f} FTE funded"
                mark_level = (mark_level + 1) % 3 if xf < mark_end else 0
                ly2 = Y(r) - 20 - mark_level * 14
                mark_end = xf + 8 + len(txt) * 5.6
                marks.append(
                    f'<line x1="{xf:.2f}" y1="{ly2 - 4:.1f}" x2="{xf:.2f}" '
                    f'y2="{yb:.1f}" stroke="{MARK}" stroke-width="2"/>'
                    f'<text x="{xf + 5:.1f}" y="{ly2:.1f}" fill="{MARK}" '
                    f'font-size="11" font-weight="600">{txt}</text>')
            cont = label != g
            if w >= 128:
                s.append(f'<text x="{x0 + 5:.1f}" y="{y0 - 30}" fill="{INK}" '
                         f'font-size="12.5" font-weight="600">{esc(label)}</text>')
                if cont:
                    sub = f"state rate {money(r)}/FTE"
                else:
                    sub = (f"{heads[g]:,} people · {buckets_fte(buckets, g):,.0f}"
                           f" FTE · rate {money(r)}/FTE")
                    # drop the rate rather than run into the next group's label
                    if len(sub) * 5.6 > w - 6:
                        sub = (f"{heads[g]:,} people · "
                               f"{buckets_fte(buckets, g):,.0f} FTE")
                s.append(f'<text x="{x0 + 5:.1f}" y="{y0 - 15}" fill="{INK3}" '
                         f'font-size="11.5">{esc(sub)}</text>')
            else:
                lbl = f"{label} — {buckets_fte(buckets, g):,.0f} FTE"
                ly = y0 - 13 - narrow * 17
                narrow += 1
                s.append(f'<line x1="{x0:.1f}" y1="{ly + 3:.1f}" x2="{x0:.1f}" '
                         f'y2="{yb:.1f}" stroke="{INK3}" stroke-width="0.8" '
                         f'stroke-dasharray="2 2"/>')
                lx = min(x0 + 5, VB - 8 - len(lbl) * 5.9)
                s.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{INK2}" '
                         f'font-size="11.5">{esc(lbl)}</text>')
            cursor += seg_fte
        s.extend(marks)
        s.append(f'<text x="{ml}" y="{yb + 22}" fill="{INK3}" font-size="11.5">'
                 f'FTE {seen:,.0f}–{seen + row_fte:,.0f} of {total_fte:,.0f}, '
                 f'sorted by pay per FTE within each group</text>')
        seen += row_fte
    s.append('</svg>')
    legend = (f'<div class="legend">'
              f'<span><i class="sw" style="background:{ACCENT}"></i>'
              f'one bar = one employee — width their FTE, height their pay per '
              f'FTE, so area is what they are paid</span>'
              + (f'<span><i class="rule"></i>the state’s rate per staff '
                 f'unit</span>'
                 f'<span><i class="sw" style="background:{MARK};opacity:.34">'
                 f'</i>what the state funds: its staff units at that rate</span>'
                 if rate_line else '')
              + '</div>')
    foot = ("Every SPS employee in the eight job groups above, one bar each, "
            "2024-25 S-275 final salary. The axis is FTE, not headcount: bar "
            "width is a person's FTE and height is their pay per FTE, so every "
            "area on the chart is dollars and the horizontal space a group "
            "takes up is its FTE. "
            + ("The red line is the state's per-staff-unit salary rate for that "
               "group's staff class — not a salary anyone is paid, but the unit "
               "price the funding formula multiplies by a generated headcount. "
               "The vertical mark is how many staff units the formula generates "
               "for that group, and the shaded block is those units at that "
               "rate: the state's whole salary allocation for the job, $272.3M "
               "across the eight. Because the axis is in FTE, the mark lands "
               "exactly where the funding reaches. " if rate_line else "") +
            "Each person is counted once, under the duty of their major "
            "assignment; 3 people below 0.2 FTE are included and are sub-pixel. "
            "Source: OSPI S-275 final 2024-25"
            + (" and Final Apportionment Summary (Report 1191F)" if rate_line
               else "") + ", Seattle Public Schools.")
    title = ("Every SPS salary, against what the state's formula pays "
             "per position" if rate_line else "Every SPS salary, one bar each")
    sub = ("The funding rate is a flat price per staff unit. Laid over the "
           "actual payroll it clears almost nobody — and the width of each "
           "block is how much FTE that is." if rate_line else
           "Seattle Public Schools payroll, 2024-25, grouped by job. Bar width "
           "is FTE and height is pay per FTE, so each area is what that person "
           "is paid.")
    return page(1200, title, sub, legend, "\n".join(s), foot, ts=30)


def buckets_fte(buckets, g):
    return sum(f for _v, f in buckets[g])


def main():
    rates = data.load_1191f()
    duties = data.load_duties()
    roles = data.model_roles()
    os.makedirs(OUT, exist_ok=True)
    for name, markup in (("img1", image1(rates, duties)),
                         ("img2", image2(roles)),
                         ("img3", image3(rates, duties)),
                         ("img3_noline", image3(rates, duties, rate_line=False))):
        p = os.path.join(OUT, name + ".html")
        with open(p, "w") as f:
            f.write(markup)
        print("wrote", p)


if __name__ == "__main__":
    main()
