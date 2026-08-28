"""Build output/sea_chart_critique/index.html -- the marked-up SEA chart plus
replacement charts.

    $ venv/bin/python3 tools/sea_chart_critique/build.py
"""
import base64
import html
import io
import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402

from PIL import Image  # noqa: E402

OUT = data.OUT
ROOT = data.ROOT

# ------------------------------------------------------------------ svg bits
VB_W = 900
GRID = 'var(--grid)'


def esc(s):
    return html.escape(str(s))


def money(v, dp=0):
    return "$%s" % f"{v:,.{dp}f}"


def millions(v):
    return "$%.1fM" % (float(v) / 1e6)


def nice_max(v, steps=5):
    """Round a max up to a friendly tick, always leaving a step of headroom."""
    import math
    if v <= 0:
        return 1, 1
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15, 20):
        top = m * mag
        if top >= v * 1.04:
            return top, top / steps
    return 20 * mag, 4 * mag


def hbar_chart(rows, *, value_key, label_key, note_key, fmt, title_fmt,
               row_h=38, label_w=250, pad_r=118, diverging=False,
               steps=5, tick_fmt=None, axis_label=""):
    """Horizontal bars. rows: list of dicts. Returns an <svg> string."""
    n = len(rows)
    top, bottom = 30, 46
    h = top + n * row_h + bottom
    plot_x0 = label_w
    plot_w = VB_W - label_w - pad_r

    vals = [float(r[value_key]) for r in rows]
    if diverging:
        lo = min(0.0, min(vals))
        hi = max(0.0, max(vals))
        span_hi, step = nice_max(hi)
        span_lo = -nice_max(-lo)[0] if lo < 0 else 0.0
        # keep the same tick step on both arms
        span_lo = -(abs(span_lo))
        rng = span_hi - span_lo
        zero_x = plot_x0 + plot_w * (0 - span_lo) / rng
        ticks = []
        t = 0.0
        while t <= span_hi + 1e-9:
            ticks.append(t)
            t += step
        t = -step
        while t >= span_lo - 1e-9:
            ticks.append(t)
            t -= step
    else:
        span_lo = 0.0
        span_hi, step = nice_max(max(vals), steps)
        rng = span_hi - span_lo
        zero_x = plot_x0
        ticks = [i * step for i in range(int(round(span_hi / step)) + 1)]

    def x_of(v):
        return plot_x0 + plot_w * (v - span_lo) / rng

    tick_fmt = tick_fmt or fmt
    s = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" class="chart" '
         f'preserveAspectRatio="xMidYMid meet">']
    # gridlines
    for t in ticks:
        x = x_of(t)
        strong = abs(t) < 1e-9
        s.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" '
                 f'y2="{top + n * row_h + 6}" stroke="{"var(--axis)" if strong else GRID}" '
                 f'stroke-width="{1.5 if strong else 1}"/>')
        s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 24}" class="tick" '
                 f'text-anchor="middle">{esc(tick_fmt(t))}</text>')
    if axis_label:
        s.append(f'<text x="{plot_x0 + plot_w / 2:.1f}" y="{h - 6}" class="axlab" '
                 f'text-anchor="middle">{esc(axis_label)}</text>')

    bh = row_h - 14
    for i, r in enumerate(rows):
        v = float(r[value_key])
        y = top + i * row_h + 7
        x0, x1 = (zero_x, x_of(v)) if v >= 0 else (x_of(v), zero_x)
        w = max(2.0, x1 - x0)
        rx = min(4, w / 2)
        s.append(f'<g class="mk" data-tip="{esc(title_fmt(r))}">')
        s.append(f'<rect x="{x0:.1f}" y="{y}" width="{w:.1f}" height="{bh}" '
                 f'rx="{rx:.1f}" fill="var(--series-1)"/>')
        s.append(f'<rect x="{plot_x0 - 6}" y="{y - 3}" width="{plot_w + pad_r}" '
                 f'height="{bh + 6}" fill="transparent"/>')
        s.append('</g>')
        s.append(f'<text x="{plot_x0 - 12}" y="{y + bh / 2 + 4:.0f}" class="rowlab" '
                 f'text-anchor="end">{esc(r[label_key])}</text>')
        lx = (x1 + 8) if v >= 0 else (x0 - 8)
        anc = "start" if v >= 0 else "end"
        s.append(f'<text x="{lx:.1f}" y="{y + bh / 2 + 4:.0f}" class="vallab" '
                 f'text-anchor="{anc}">{esc(fmt(v))}</text>')
        if note_key and r.get(note_key):
            s.append(f'<text x="{plot_x0 - 12}" y="{y + bh / 2 + 16:.0f}" '
                     f'class="rownote" text-anchor="end">{esc(r[note_key])}</text>')
    s.append('</svg>')
    return "\n".join(s)


def stacked_coverage(rows):
    """rows: [{label, funded, pay}] -> one stacked bar per row, funded vs not."""
    row_h, top, label_w = 46, 26, 250
    n = len(rows)
    h = top + n * row_h + 46
    plot_w = VB_W - label_w - 118
    mx = max(float(r["pay"]) for r in rows)
    span, step = nice_max(mx)
    s = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" class="chart" '
         f'preserveAspectRatio="xMidYMid meet">']
    for i in range(int(round(span / step)) + 1):
        t = i * step
        x = label_w + plot_w * t / span
        s.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" '
                 f'y2="{top + n * row_h + 6}" stroke="{GRID}"/>')
        s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 24}" class="tick" '
                 f'text-anchor="middle">${t / 1e6:.0f}M</text>')
    s.append(f'<text x="{label_w + plot_w / 2:.1f}" y="{h - 6}" class="axlab" '
             f'text-anchor="middle">total salary + benefits, 2024-25</text>')
    bh = row_h - 18
    for i, r in enumerate(rows):
        y = top + i * row_h + 9
        pay, funded = float(r["pay"]), float(r["funded"])
        wpay = plot_w * pay / span
        wfund = plot_w * funded / span
        pct = funded / pay * 100
        tip = (f'{r["label"]}: state funds {millions(funded)} of {millions(pay)} '
               f'({pct:.0f}%)')
        s.append(f'<g class="mk" data-tip="{esc(tip)}">')
        s.append(f'<rect x="{label_w}" y="{y}" width="{wpay:.1f}" height="{bh}" '
                 f'rx="4" fill="var(--muted-fill)"/>')
        s.append(f'<rect x="{label_w}" y="{y}" width="{max(4, wfund - 2):.1f}" '
                 f'height="{bh}" rx="4" fill="var(--series-1)"/>')
        s.append(f'<rect x="{label_w - 6}" y="{y - 4}" width="{plot_w + 118}" '
                 f'height="{bh + 8}" fill="transparent"/></g>')
        s.append(f'<text x="{label_w - 12}" y="{y + bh / 2 + 4:.0f}" class="rowlab" '
                 f'text-anchor="end">{esc(r["label"])}</text>')
        s.append(f'<text x="{label_w + wpay + 10:.1f}" y="{y + bh / 2 + 4:.0f}" '
                 f'class="vallab" text-anchor="start">{pct:.0f}%</text>')
    s.append('</svg>')
    return "\n".join(s)


def ratio_dots(rows, *, ticks=(0.5, 0.75, 1, 1.5, 2, 3, 5, 10), row_h=34, label_w=268,
               pad_r=136):
    """Dot plot on a log ratio axis. rows: {label, ratio, note, tip}."""
    import math
    n = len(rows)
    top, bottom = 30, 48
    h = top + n * row_h + bottom
    x0 = label_w
    plot_w = VB_W - label_w - pad_r
    lo, hi = math.log10(min(ticks)), math.log10(max(ticks))

    def X(v):
        return x0 + plot_w * (math.log10(v) - lo) / (hi - lo)

    s = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" class="chart" '
         f'preserveAspectRatio="xMidYMid meet">']
    for t in ticks:
        x = X(t)
        one = (t == 1)
        s.append(f'<line x1="{x:.1f}" y1="{top - 10}" x2="{x:.1f}" '
                 f'y2="{top + n * row_h + 4}" '
                 f'stroke="{"var(--axis)" if one else GRID}" '
                 f'stroke-width="{1.5 if one else 1}"/>')
        lab = ("%g" % t) + "\u00d7"
        s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 22}" class="tick" '
                 f'text-anchor="middle">{lab}</text>')
    s.append(f'<text x="{X(1):.1f}" y="{top - 16}" class="axlab" '
             f'text-anchor="middle">exactly as many as the state funds</text>')
    s.append(f'<text x="{x0 + plot_w / 2:.1f}" y="{h - 8}" class="axlab" '
             f'text-anchor="middle">SPS staff FTE \u00f7 state-funded staff units '
             f'(log scale)</text>')
    for i, r in enumerate(rows):
        cy = top + i * row_h + row_h / 2 - 3
        v = float(r["ratio"])
        xv = X(max(min(v, max(ticks)), min(ticks)))
        a, b = (X(1), xv) if v >= 1 else (xv, X(1))
        s.append(f'<g class="mk" data-tip="{esc(r["tip"])}">')
        s.append(f'<line x1="{a:.1f}" y1="{cy:.1f}" x2="{b:.1f}" y2="{cy:.1f}" '
                 f'stroke="var(--series-1)" stroke-width="2" opacity=".38"/>')
        s.append(f'<circle cx="{xv:.1f}" cy="{cy:.1f}" r="6" '
                 f'fill="var(--series-1)" stroke="var(--surface-1)" '
                 f'stroke-width="2"/>')
        s.append(f'<rect x="{x0 - 6}" y="{cy - row_h / 2:.1f}" '
                 f'width="{plot_w + pad_r}" height="{row_h}" fill="transparent"/>')
        s.append('</g>')
        s.append(f'<text x="{x0 - 14}" y="{cy + 1:.1f}" class="rowlab" '
                 f'text-anchor="end">{esc(r["label"])}</text>')
        s.append(f'<text x="{x0 - 14}" y="{cy + 14:.1f}" class="rownote" '
                 f'text-anchor="end">{esc(r["note"])}</text>')
        lx = xv + 13 if v >= 1 else xv - 13
        anc = "start" if v >= 1 else "end"
        s.append(f'<text x="{lx:.1f}" y="{cy + 4:.1f}" class="vallab" '
                 f'text-anchor="{anc}">{v:.2f}\u00d7</text>')
    s.append('</svg>')
    return "\n".join(s)


def grouped_bars(rows, *, height=430, label_w=78, pad_r=16):
    """Vertical paired bars: what SPS pays per position vs what the state
    allocates per staff unit. Deliberately side-by-side, never overlapping."""
    n = len(rows)
    top, axis_h = 34, 74
    h = top + height + axis_h
    x0 = label_w
    plot_w = VB_W - label_w - pad_r
    span, step = nice_max(max(float(r["per"]) for r in rows))

    def Y(v):
        return top + height - height * v / span

    gw = plot_w / n
    bw = min(48.0, gw * 0.30)
    s = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" class="chart" '
         f'preserveAspectRatio="xMidYMid meet">']
    for i in range(int(round(span / step)) + 1):
        v = i * step
        y = Y(v)
        s.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + plot_w:.1f}" '
                 f'y2="{y:.1f}" stroke="{"var(--axis)" if i == 0 else GRID}"/>')
        s.append(f'<text x="{x0 - 10}" y="{y + 4:.1f}" class="tick" '
                 f'text-anchor="end">${v / 1000:.0f}k</text>')

    for i, r in enumerate(rows):
        cx = x0 + gw * (i + 0.5)
        pay, rate = float(r["per"]), float(r["rate"])
        for j, (v, fill, who) in enumerate((
                (pay, "var(--ink)", "SPS pays"),
                (rate, "var(--series-1)", "state allocates"))):
            bx = cx - bw - 1 + j * (bw + 2)
            by, bh = Y(v), top + height - Y(v)
            tip = ("%s — %s %s per %s" % (r["name"], who, money(v),
                                          "position" if r["basis"] == "positions"
                                          else "1.0 FTE"))
            s.append(f'<g class="mk" data-tip="{esc(tip)}">'
                     f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" '
                     f'height="{max(1.0, bh):.1f}" rx="3" fill="{fill}"/>'
                     f'<rect x="{bx:.1f}" y="{top}" width="{bw:.1f}" '
                     f'height="{height}" fill="transparent"/></g>')
            s.append(f'<text x="{bx + bw / 2:.1f}" y="{by - 7:.1f}" '
                     f'class="barval" text-anchor="middle">'
                     f'${v / 1000:,.0f}k</text>')
        ly = top + height + 20
        words = _wrap(r["name"], 15)
        for k, w in enumerate(words):
            s.append(f'<text x="{cx:.1f}" y="{ly + k * 14:.0f}" class="grouplab" '
                     f'text-anchor="middle">{esc(w)}</text>')
        pos = r["positions"]
        unit = "position" if float(pos) == 1 else (
            "positions" if r["basis"] == "positions" else "FTE")
        s.append(f'<text x="{cx:.1f}" y="{ly + len(words) * 14 + 2:.0f}" '
                 f'class="grouplab poscount" text-anchor="middle">'
                 f'{float(pos):,.0f} {unit}</text>')
    s.append('</svg>')
    return "\n".join(s)


def _wrap(text, width):
    out, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def variance_bars(rows, *, row_h=46, label_w=250, pad_r=126):
    """Budget-versus-actual: a full bar for salary actually paid, with the
    state's allocation overlaid inside it. The overhang is the variance.

    Overlap is legitimate here and was not in SEA's chart: these two
    quantities genuinely compose -- the allocation is a portion of the money
    paid, off the same denominator.
    """
    n = len(rows)
    top, bottom = 30, 48
    h = top + n * row_h + bottom
    x0 = label_w
    plot_w = VB_W - label_w - pad_r
    span, step = nice_max(max(float(r["paid"]) for r in rows), 4)

    def W(v):
        return plot_w * v / span

    s = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" class="chart" '
         f'preserveAspectRatio="xMidYMid meet">']
    for i in range(int(round(span / step)) + 1):
        v = i * step
        x = x0 + W(v)
        s.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" '
                 f'y2="{top + n * row_h + 6}" '
                 f'stroke="{"var(--axis)" if i == 0 else GRID}"/>')
        s.append(f'<text x="{x:.1f}" y="{top + n * row_h + 24}" class="tick" '
                 f'text-anchor="middle">${v / 1e6:.0f}M</text>')
    s.append(f'<text x="{x0 + plot_w / 2:.1f}" y="{h - 8}" class="axlab" '
             f'text-anchor="middle">salary paid, 2024-25</text>')

    OH, IH = 24, 12          # outer / inner bar heights
    for i, r in enumerate(rows):
        paid, alloc = float(r["paid"]), float(r["alloc"])
        pct = alloc / paid * 100
        cy = top + i * row_h + row_h / 2 - 4
        wo, wi = max(1.5, W(paid)), max(1.5, W(alloc))
        tip = ("%s — SPS paid %s; state allocation %s (%.0f%%); "
               "unfunded %s" % (r["name"], millions(paid), millions(alloc),
                                pct, millions(paid - alloc)))
        s.append(f'<g class="mk" data-tip="{esc(tip)}">')
        s.append(f'<rect x="{x0}" y="{cy - OH / 2:.1f}" width="{wo:.1f}" '
                 f'height="{OH}" rx="3" fill="var(--track)"/>')
        s.append(f'<rect x="{x0}" y="{cy - IH / 2:.1f}" width="{wi:.1f}" '
                 f'height="{IH}" rx="2" fill="var(--series-1)" '
                 f'stroke="var(--surface-1)" stroke-width="1.5"/>')
        s.append(f'<rect x="{x0 - 6}" y="{cy - row_h / 2:.1f}" '
                 f'width="{plot_w + pad_r}" height="{row_h}" '
                 f'fill="transparent"/></g>')
        s.append(f'<text x="{x0 - 13}" y="{cy - 2:.1f}" class="rowlab" '
                 f'text-anchor="end">{esc(r["name"])}</text>')
        s.append(f'<text x="{x0 - 13}" y="{cy + 12:.1f}" class="rownote" '
                 f'text-anchor="end">{esc(r["note"])}</text>')
        lx = x0 + wo + 11
        s.append(f'<text x="{lx:.1f}" y="{cy - 1:.1f}" class="vallab" '
                 f'text-anchor="start">{esc(millions(paid))}</text>')
        s.append(f'<text x="{lx:.1f}" y="{cy + 12:.1f}" class="rownote" '
                 f'text-anchor="start">{pct:.0f}% state-funded</text>')
    s.append('</svg>')
    return "\n".join(s)


# ------------------------------------------------------------------- assets
def embed_original():
    """Crop the SEA chart out of the Facebook screenshot, downscale, embed."""
    src = os.path.join(ROOT, "SEA- bad graph.png")
    im = Image.open(src)
    s = im.size[0] / 2000.0
    im = im.crop((int(105 * s), int(118 * s), int(1392 * s), int(1122 * s)))
    im.thumbnail((1500, 1500), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# Pin positions are percentages of the cropped chart image.
PINS = [
    (1, 27.5, 72.0),    # just right of the red Superintendent bar
    (2, 82.5, 76.0),    # just right of the yellow Teachers bar
    (3, 27.5, 21.5),    # left of the red legend swatch
    (4, 47.5, 94.5),    # left of the "Program Directors" axis label
    (5, 45.5, 80.0),    # right of the Executive Cabinet bar cluster
    (6, 20.0, 46.0),    # on the Superintendent black bar
    (7, 12.0, 6.5),     # left of the title block
]


CSS = """
/* ---------------------------------------------------------------------------
   Design plan
   Color   Cool blue-grey neutrals biased toward the accent (never cream), so
           the ground reads as chosen. Ink #0d1117 / #f2f5f8. Accent
           #2a78d6 / #3987e5 -- the dataviz-validated categorical slot 1, the
           only saturated hue on the page. Flag #c0342d / #f07470 for the
           error pins and the two caveat blocks. Nothing else is colored.
   Type    Archivo for headings, labels and every chart mark -- a semi-condensed
           grotesque with the density of a newspaper data desk. Source Serif 4
           for running prose, because the page is an argument to be read.
           IBM Plex Mono for figures and file paths.
   Layout  One 960px measure column. The marked-up screenshot is the hero and
           runs full column width; each replacement chart sits in a bordered
           card so the reader can tell an original from a rebuild at a glance.
--------------------------------------------------------------------------- */
:root{
  color-scheme: light dark;
  --surface-0:#f2f4f7; --surface-1:#ffffff; --surface-2:#e8ebf0;
  --ink:#0d1117; --ink-2:#4a5462; --ink-3:#727d8c;
  --rule:#d8dde5; --grid:#e4e8ee; --axis:#9aa3b0;
  --series-1:#2a78d6; --muted-fill:#cfd6e0; --track:#aab7c7;
  --flag:#c0342d; --flag-soft:#fdeceb; --flag-edge:#f0c9c6;
  --good:#1b7a4b;
  --pin:#c0342d;
  --font-ui:"Archivo","Helvetica Neue",Helvetica,Arial,sans-serif;
  --font-body:"Source Serif 4",Georgia,"Times New Roman",serif;
  --font-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --surface-0:#0f1216; --surface-1:#171b21; --surface-2:#1f242b;
    --ink:#f2f5f8; --ink-2:#b3bcc7; --ink-3:#8a94a1;
    --rule:#2b3138; --grid:#232830; --axis:#5a6470;
    --series-1:#3987e5; --muted-fill:#333a43; --track:#4b5563;
    --flag:#f07470; --flag-soft:#251518; --flag-edge:#4a2b2b;
    --good:#5fbf8c;
    --pin:#e0554f;
  }
}
:root[data-theme="dark"]{
  --surface-0:#0f1216; --surface-1:#171b21; --surface-2:#1f242b;
  --ink:#f2f5f8; --ink-2:#b3bcc7; --ink-3:#8a94a1;
  --rule:#2b3138; --grid:#232830; --axis:#5a6470;
  --series-1:#3987e5; --muted-fill:#333a43; --track:#4b5563;
  --flag:#f07470; --flag-soft:#251518; --flag-edge:#4a2b2b;
  --good:#5fbf8c;
  --pin:#e0554f;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--surface-0); color:var(--ink);
  font-family:var(--font-body); font-size:18px; line-height:1.66;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
.wrap{max-width:960px; margin:0 auto; padding:64px 24px 104px}
h1,h2,h3{font-family:var(--font-ui); text-wrap:balance}
h1{font-size:2.9rem; line-height:1.04; letter-spacing:-.03em;
   font-weight:700; margin:0 0 .7rem}
h2{font-size:1.55rem; line-height:1.2; letter-spacing:-.018em; font-weight:660;
   margin:4rem 0 .4rem; padding-top:1.7rem; border-top:1px solid var(--rule)}
h3{font-size:1.12rem; margin:2.3rem 0 .35rem; font-weight:660;
   letter-spacing:-.01em}
p{margin:0 0 1.1rem; max-width:66ch}
.lede{font-size:1.2rem; line-height:1.55; color:var(--ink-2); max-width:62ch}
.kicker{font-family:var(--font-ui); font-size:.72rem; letter-spacing:.17em;
  text-transform:uppercase; color:var(--ink-3); font-weight:620;
  margin-bottom:.85rem}
.sub{font-family:var(--font-ui); color:var(--ink-2); font-size:.96rem;
  line-height:1.55; margin:.15rem 0 1.4rem; max-width:66ch}
a{color:var(--series-1)}
strong{font-weight:640}
em{font-style:italic}
code,.num{font-family:var(--font-mono); font-size:.86em;
  font-variant-numeric:tabular-nums}
:focus-visible{outline:2px solid var(--series-1); outline-offset:3px;
  border-radius:3px}

/* ---- marked-up original ---- */
.shot{position:relative; margin:1.7rem 0 1.2rem; border-radius:6px;
  overflow:hidden; border:1px solid var(--rule); background:#fff;
  box-shadow:0 1px 2px rgba(13,17,23,.08)}
.shot img{display:block; width:100%; height:auto}
.pin{position:absolute; width:30px; height:30px; margin:-15px 0 0 -15px;
  border-radius:50%; background:var(--pin); color:#fff;
  font-family:var(--font-ui); font-weight:700; font-size:.9rem;
  font-variant-numeric:tabular-nums; display:flex; align-items:center;
  justify-content:center;
  box-shadow:0 0 0 3px rgba(255,255,255,.94), 0 2px 6px rgba(0,0,0,.4)}
.pin::after{content:""; position:absolute; inset:-9px; border-radius:50%;
  border:2px solid var(--pin); opacity:.4}

/* ---- error list ---- */
ol.errs{list-style:none; counter-reset:e; padding:0; margin:2.1rem 0 0;
  display:flex; flex-direction:column; gap:2rem}
ol.errs>li{counter-increment:e; position:relative; padding:0 0 0 54px;
  margin:0}
ol.errs>li::before{content:counter(e); position:absolute; left:0; top:2px;
  width:30px; height:30px; border-radius:50%; background:var(--pin); color:#fff;
  font-family:var(--font-ui); font-weight:700; font-size:.9rem;
  font-variant-numeric:tabular-nums; display:flex; align-items:center;
  justify-content:center}
ol.errs h3{margin:0 0 .35rem; font-size:1.06rem}
ol.errs p{margin:0}

/* ---- tables ---- */
.tw{overflow-x:auto; margin:1.4rem 0 1.7rem; border:1px solid var(--rule);
  border-radius:6px; background:var(--surface-1)}
table{border-collapse:collapse; width:100%; font-family:var(--font-ui);
  font-size:.9rem; font-variant-numeric:tabular-nums}
th,td{padding:9px 15px; text-align:right; border-bottom:1px solid var(--rule);
  white-space:nowrap}
th:first-child,td:first-child{text-align:left; white-space:normal}
thead th{font-size:.7rem; letter-spacing:.09em; text-transform:uppercase;
  color:var(--ink-3); font-weight:620; background:var(--surface-2)}
tbody tr:last-child td{border-bottom:none}
tr.tot td{font-weight:660; background:var(--surface-2)}
.ok{color:var(--good); font-weight:640}

/* ---- figures ---- */
figure{margin:1.6rem 0 2.2rem; padding:22px 22px 14px; background:var(--surface-1);
  border:1px solid var(--rule); border-radius:6px}
figure .ftitle{font-family:var(--font-ui); font-weight:660; font-size:1.03rem;
  letter-spacing:-.008em; margin-bottom:.2rem}
figure .fsub{font-family:var(--font-ui); color:var(--ink-2); font-size:.89rem;
  line-height:1.5; margin-bottom:1.1rem; max-width:62ch}
figcaption{font-family:var(--font-ui); color:var(--ink-2); font-size:.83rem;
  line-height:1.55; margin-top:.6rem; padding-top:.8rem;
  border-top:1px solid var(--rule); max-width:72ch}
.chart{width:100%; height:auto; display:block; overflow:visible}
.chart text{font-family:var(--font-ui)}
.tick{fill:var(--ink-3); font-size:11.5px}
.axlab{fill:var(--ink-3); font-size:11.5px}
.rowlab{fill:var(--ink); font-size:13px; font-weight:520}
.rownote{fill:var(--ink-3); font-size:11px}
.vallab{fill:var(--ink-2); font-size:12px; font-weight:620;
  font-variant-numeric:tabular-nums}
.barval{fill:var(--ink-2); font-size:11.5px; font-weight:620;
  font-variant-numeric:tabular-nums}
.grouplab{fill:var(--ink); font-size:12.5px; font-weight:560}
.poscount{fill:var(--ink-3); font-size:11px; font-weight:500;
  font-variant-numeric:tabular-nums}
.mk{cursor:default}
.mk:hover rect:first-of-type,.mk:hover circle{opacity:.8}
.legend{display:flex; gap:22px; flex-wrap:wrap; margin:0 0 1rem;
  font-family:var(--font-ui); font-size:.84rem; color:var(--ink-2)}
.legend span{display:flex; align-items:center; gap:7px}
.sw{width:12px; height:12px; border-radius:2px; display:inline-block}

/* ---- callouts ---- */
.note{background:var(--surface-2); border:1px solid var(--rule);
  border-left:3px solid var(--axis); border-radius:0 6px 6px 0;
  padding:16px 20px; margin:1.6rem 0}
.note p{margin-bottom:0; max-width:64ch}
.flag{background:var(--flag-soft); border-color:var(--flag-edge);
  border-left-color:var(--flag)}
.chain{display:flex; flex-wrap:wrap; align-items:stretch; gap:10px;
  margin:1.6rem 0 1.3rem}
.chain .step{flex:1 1 152px; background:var(--surface-1);
  border:1px solid var(--rule); border-radius:6px; padding:14px 16px;
  font-family:var(--font-ui)}
.chain .step .k{font-size:.68rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); font-weight:620}
.chain .step .v{font-size:1.3rem; font-weight:700; letter-spacing:-.025em;
  font-variant-numeric:tabular-nums; margin-top:3px; line-height:1.15}
.chain .step .d{font-size:.8rem; line-height:1.45; color:var(--ink-2);
  margin-top:4px}
.chain .op{display:flex; align-items:center; color:var(--ink-3);
  font-size:1.25rem}
.tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px; margin:1.6rem 0}
.tile{background:var(--surface-1); border:1px solid var(--rule);
  border-radius:6px; padding:17px 19px; font-family:var(--font-ui)}
.tile .k{font-size:.72rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--ink-3); font-weight:620}
.tile .v{font-size:2.15rem; font-weight:700; letter-spacing:-.035em;
  line-height:1.08; margin:7px 0 3px; font-variant-numeric:tabular-nums}
.tile .d{font-size:.83rem; line-height:1.45; color:var(--ink-2)}
details{margin:.7rem 0 0}
summary{cursor:pointer; color:var(--ink-2); font-family:var(--font-ui);
  font-size:.86rem; padding:5px 0}
#tip{position:fixed; z-index:50; pointer-events:none; opacity:0;
  transition:opacity .1s; background:var(--surface-1); color:var(--ink);
  border:1px solid var(--rule); border-radius:6px; padding:8px 12px;
  font-family:var(--font-ui); font-size:.82rem; line-height:1.45;
  max-width:310px; box-shadow:0 6px 20px rgba(13,17,23,.28)}
footer{margin-top:4.5rem; padding-top:1.7rem; border-top:1px solid var(--rule);
  font-family:var(--font-ui); color:var(--ink-3); font-size:.84rem;
  line-height:1.6}
footer p{max-width:74ch}
@media (prefers-reduced-motion: reduce){
  *{transition:none !important; animation:none !important}
}
@media (max-width:640px){
  .wrap{padding:36px 16px 72px}
  h1{font-size:2.1rem}
  body{font-size:17px}
  .pin{width:22px; height:22px; margin:-11px 0 0 -11px; font-size:.72rem}
  .pin::after{inset:-6px}
  ol.errs>li{padding-left:42px}
}
"""

JS = """
(function(){
  var tip=document.getElementById('tip');
  document.addEventListener('mouseover',function(e){
    var t=e.target.closest('[data-tip]');
    if(!t){tip.style.opacity=0;return;}
    tip.textContent=t.getAttribute('data-tip'); tip.style.opacity=1;
  });
  document.addEventListener('mousemove',function(e){
    if(tip.style.opacity!=1) return;
    var x=e.clientX+14, y=e.clientY+16;
    var r=tip.getBoundingClientRect();
    if(x+r.width>innerWidth-8) x=e.clientX-r.width-14;
    if(y+r.height>innerHeight-8) y=e.clientY-r.height-14;
    tip.style.left=x+'px'; tip.style.top=y+'px';
  });
})();
"""


ERRORS = [
    ("The three benchmark bars are not from the same year.",
     "Red is the <strong>2024-25</strong> administrative rate "
     "($136,988.56). Blue is the <strong>2025-26</strong> classified rate "
     "($67,859.00) &mdash; the 2024-25 figure is $66,203.90. Both cannot be "
     "right, and the chart carries no year label to adjudicate. Whichever year "
     "it means, it is wrong by a material amount: read as 2024-25, blue is "
     "$1,655 too high and understates the classified gap; read as 2025-26, red "
     "is $3,425 too low and widens every administrator gap on the chart."),
    ("The yellow bar is built to a different recipe than the other two.",
     "$96,170 matches no plain rate in either year, but it reproduces to the "
     "cent as the 2025-26 instructional rate <strong>plus "
     "professional-learning-day money</strong>: $94,593.79 + $1,576.56 = "
     "$96,170.35. That add-on has no counterpart in the red or blue bars, and "
     "professional-learning days are a certificated-instructional pot with no "
     "administrative or classified analogue &mdash; so the one bar that gets an "
     "extra ingredient is the one measuring teachers. It makes teaching look "
     "closer to fully funded than the chart&rsquo;s own method would show, by "
     "$1,577 per position at a minimum and by $3,883 if the chart is meant to "
     "be 2024-25."),
    ("&ldquo;State Funded &hellip; Salary&rdquo; is not a salary.",
     "It is a unit price inside the prototypical school funding formula. The "
     "state takes enrollment, generates a notional number of staff units, and "
     "multiplies by a statewide rate. The rate is not attached to a job, a "
     "person, or a contract, and the state has never said what any SPS "
     "position ought to be paid. Labeling it &ldquo;state funded salary&rdquo; "
     "invites exactly the reading the chart depends on."),
    ("Two of the three administrator categories are matched to the wrong "
     "staff class.",
     "&ldquo;Program Directors&rdquo; and most of the executive cabinet at SPS "
     "are <em>classified</em> staff &mdash; coded to S-275 duty 99, Director "
     "or Supervisor, not to any certificated administrator code. The red "
     "certificated-administrative bar is the wrong benchmark for the majority "
     "of both groups. Drawing a red and a blue bar together is the right "
     "instinct, since those groups genuinely straddle two staff classes; what "
     "is missing is the mix. Without knowing that eight of the ten cabinet "
     "members are classified, the reader cannot weight the two bars and will "
     "default to the taller one."),
    ("Overlapping bars imply a part-of-whole relationship that does not exist.",
     "The colored bar sits in front of the black one on a shared baseline, "
     "which reads as &ldquo;the state funds <em>this much</em> of that "
     "salary.&rdquo; It does not. The two bars have different denominators "
     "&mdash; actual people hired versus formula-generated units &mdash; and "
     "they do not compose. Nothing is left over when you subtract one from the "
     "other."),
    ("One position and 3,035 teacher FTE get the same bar width.",
     "That is the load-bearing deception. The superintendent bar and the "
     "teacher bar occupy the same visual space, which invites a dollar "
     "comparison the chart cannot support. Paying one employee $5,000 above a "
     "rate and paying a thousand employees $5,000 above the same rate are not "
     "the same fact. In 2024-25 the superintendent&rsquo;s gap was "
     "<strong>$0.25M</strong>; the teacher gap was <strong>$70.6M</strong>."),
    ("No year, no source line, no category definitions, no headcounts.",
     "&ldquo;Executive Cabinet&rdquo; and &ldquo;Program Directors&rdquo; are "
     "not S-275 categories, and neither $284,518 nor $230,970 can be "
     "reproduced from any published file without knowing who was put in each "
     "bucket. A chart that is precise to the dollar owes the reader the "
     "definitions behind the dollars."),
]


def main():
    rates = data.load_1191f()
    duties = data.load_duties()
    groups = data.group_rows(duties, rates)
    classes = data.class_totals(duties, rates)
    roles = data.model_roles()
    ipd = data.IPD_2526

    cis, cas, cls = rates["cis"], rates["cas"], rates["cls"]
    pld = rates["pld_per_cis_fte"]
    cas_emp = sum(int(duties[r]["employees"]) for r in data.CAS_ROOTS if r in duties)
    cas_fte = sum(D(duties[r]["fte"]) for r in data.CAS_ROOTS if r in duties)
    total_gap = sum(g["gap_total"] for g in groups)
    teach_gap = next(g for g in groups if g["name"] == "Teachers")["gap_total"]
    admin_gap = sum(g["gap_total"] for g in groups
                    if g["name"] in ("Superintendent", "Cabinet & district admin",
                                     "Principals & vice principals"))
    supt = next(g for g in groups if g["name"] == "Superintendent")

    h = []
    A = h.append
    A('<title>Anatomy of a Bad Chart</title>')
    A('<link rel="preconnect" href="https://fonts.googleapis.com">')
    A('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    A('<link href="https://fonts.googleapis.com/css2?'
      'family=Archivo:wght@400;500;600;700&'
      'family=IBM+Plex+Mono:wght@400;500&'
      'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;'
      '1,8..60,400&display=swap" rel="stylesheet">')
    A('<style>%s</style>' % CSS)
    A('<div id="tip"></div><div class="wrap">')

    # ---------------------------------------------------------------- intro
    A('<p class="kicker">Seattle Public Schools &middot; school funding</p>')
    A('<h1>Anatomy of a bad chart</h1>')
    A('<p class="lede">The Seattle Education Association published a chart '
      'setting SPS salaries against &ldquo;state funded salaries.&rdquo; Its '
      'three benchmark numbers cannot all be from the same year, one of them is '
      'built to a different recipe than the other two, and four of its design '
      'choices mislead. Below: every bar reproduced from the sources, '
      'the errors marked on the chart itself, and three replacements that '
      'answer the question it was reaching for.</p>')
    A('<div class="note"><p><strong>The short version.</strong> The state&rsquo;s '
      'prototypical school model is not a salary schedule. It converts '
      'enrollment into a notional headcount and pays a flat rate per notional '
      'position &mdash; a rate that is below what SPS pays in '
      '<em>every single category on the chart</em>, teachers included. Ranking '
      'job titles by how far above that rate they sit measures the rate, not '
      'the jobs. And because the chart drops headcount, it gives one '
      'superintendent the same visual weight as 3,035 teacher FTE.</p></div>')

    # ---------------------------------------------------------- the markup
    A('<h2>1. The chart, marked up</h2>')
    A('<p class="sub">Published by the Seattle Education Association on '
      'Facebook. The numbered markers correspond to the list below; the chart '
      'itself is unaltered.</p>')
    A('<div class="shot"><img alt="The SEA chart, with numbered error markers" '
      'src="%s">' % embed_original())
    for num, x, y in PINS:
        A('<div class="pin" style="left:%.1f%%;top:%.1f%%">%d</div>' % (x, y, num))
    A('</div>')
    A('<ol class="errs">')
    for title, body in ERRORS:
        A('<li><h3>%s</h3><p>%s</p></li>' % (title, body))
    A('</ol>')

    # ------------------------------------------------------- reproduction
    A('<h2>2. Every bar, reproduced from the source</h2>')
    A('<p>The three colored bars all come from one document: the OSPI Final '
      'Apportionment Summary (Report 1191F) for Seattle, pages 1&ndash;7. Each '
      'rate is a statewide base salary figure multiplied by Seattle&rsquo;s '
      'regionalization factor of 1.180. The 2025-26 column applies the '
      '2.5% salary inflator &mdash; which the chart&rsquo;s own yellow bar '
      'confirms, since it lands on $96,170 to the dollar.</p>')
    A('<div class="tw"><table><thead><tr>'
      '<th>Bar</th><th>SEA printed</th><th>2024-25</th><th>2025-26</th>'
      '<th>Derivation</th></tr></thead><tbody>')
    rep = [
        ("Red &mdash; administrative certificated (CAS)", "$136,988",
         cas, cas * ipd, "$116,092 &times; 1.180", "24"),
        ("Blue &mdash; classified (CLS)", "$67,858",
         cls, cls * ipd, "$56,105 &times; 1.180", "25"),
        ("Yellow &mdash; certificated instructional (CIS)", "$96,170",
         cis, cis * ipd, "$78,209 &times; 1.180", ""),
        ("&nbsp;&nbsp;&nbsp;&nbsp;&hellip; plus professional-learning days",
         "&nbsp;", cis + pld, (cis + pld) * ipd,
         "+ $4,068,604.84 &divide; 2,645.197 units", "25"),
    ]
    for label, printed, v24, v25, deriv, hit in rep:
        m24 = ' class="ok"' if hit == "24" else ''
        m25 = ' class="ok"' if hit == "25" else ''
        A('<tr><td>%s</td><td><strong>%s</strong></td><td%s>%s</td>'
          '<td%s>%s</td><td style="text-align:left"><code>%s</code></td></tr>'
          % (label, printed, m24, money(v24, 2), m25, money(v25, 2), deriv))
    A('</tbody></table></div>')
    A('<p class="sub">Green marks the cell each printed figure actually '
      'matches. The red bar is 2024-25; the blue bar is 2025-26; they cannot '
      'both be right. The yellow bar matches no plain rate in either year '
      '&mdash; only the 2025-26 instructional rate with professional-learning-'
      'day money folded in, an ingredient the other two bars do not get.</p>')

    # ------------------------------------------- what the rate actually buys
    A('<h2>3. What $136,988 actually buys</h2>')
    A('<p>Follow the number back through the formula and the problem is '
      'obvious. Nothing in this chain refers to a person, a title, or a '
      'contract.</p>')
    A('<div class="chain">')
    A('<div class="step"><div class="k">Enrollment</div><div class="v">%s</div>'
      '<div class="d">annual average FTE students, 2024-25</div></div>'
      % f'{rates["enrollment_aafte"]:,.0f}')
    A('<div class="op">&rarr;</div>')
    A('<div class="step"><div class="k">Formula generates</div>'
      '<div class="v">%s</div><div class="d">school administrative staff '
      'units (+ %s central)</div></div>'
      % (f'{rates["cas_fte"]:,.3f}', f'{rates["central_cas_fte"]:,.3f}'))
    A('<div class="op">&times;</div>')
    A('<div class="step"><div class="k">Rate per unit</div>'
      '<div class="v">%s</div><div class="d">statewide base &times; 1.180 '
      'regionalization</div></div>' % money(cas, 2))
    A('<div class="op">=</div>')
    A('<div class="step"><div class="k">Allocation</div><div class="v">%s</div>'
      '<div class="d">what the state sends for school CAS salary</div></div>'
      % millions(rates["cas_allocation"]))
    A('</div>')
    A('<p>The unit count is generated from enrollment. It is not a count of '
      'anyone SPS hired, it does not change when SPS hires or fires, and the '
      'money is not restricted to the positions that generated it. In the same '
      'year, SPS employed <strong>%d certificated administrators</strong> '
      '(%s FTE). The model generated %s. Dividing one by the other '
      'produces a number; it does not produce a meaning.</p>'
      % (cas_emp, f'{cas_fte:,.1f}', f'{rates["district_cas_fte"]:,.3f}'))
    # ------------------------------------------------------- chart 0: rebuild
    buckets = data.sea_buckets(duties, rates)
    b = {x["name"]: x for x in buckets}
    A('<h2>4. Five charts that answer the actual question</h2>')
    A('<h3>Chart 1 &mdash; The same chart, rebuilt</h3>')
    A('<p>Same job categories, same two quantities, same form. Two things '
      'change, and both are corrections rather than reframings.</p>')
    A('<p><strong>The membership.</strong> S-275 has no names, so the buckets '
      'are rebuilt by salary tier and checked against the SPS leadership pages '
      'as they stood in 2024-25: one superintendent, ten senior cabinet, five '
      'regional executive directors. Ten people are paid $275,613 or more '
      'excluding the superintendent, and the next-highest is $21,047 below '
      'them &mdash; the cabinet tier falls out of the data on its own, and it '
      'is exactly the size the roster says.</p>')
    A('<p><strong>The benchmark.</strong> Each category is measured against the '
      'staff class its people are actually in. That matters most for the '
      'cabinet: <strong>eight of the ten are classified staff</strong> in '
      'SPS&rsquo;s own filing, coded to duty 99, &ldquo;Director or '
      'Supervisor,&rdquo; rather than to any certificated administrator code. '
      'Only two of the ten carry one. Their blended benchmark is therefore '
      'mostly the classified rate, roughly half the certificated one &mdash; '
      'and that, not a hedge, is the real reason a chart of this group needs '
      'two colored bars.</p>')
    A('<figure>')
    A('<div class="ftitle">What SPS pays per position, against what the state '
      'allocates per staff unit &mdash; 2024-25</div>')
    A('<div class="fsub">One year, one construction, one divisor rule. The '
      'state bar is the salary allocation for the staff class each group is '
      'actually coded to, blended by headcount where a group spans two '
      'classes.</div>')
    A('<div class="legend">'
      '<span><i class="sw" style="background:var(--ink)"></i>'
      'SPS pays, per position</span>'
      '<span><i class="sw" style="background:var(--series-1)"></i>'
      'state allocates, per staff unit</span></div>')
    A(grouped_bars(buckets))
    A('<figcaption>Correcting the benchmark cuts against administration as '
      'often as for it. The cabinet&rsquo;s applicable rate is %s, not '
      '$136,989, because most of them are classified &mdash; so the cabinet '
      'multiple gets <em>worse</em>, not better: %.2f&times; the state rate '
      'against %.2f&times; for teachers. What collapses is the '
      '<strong>program directors</strong> bar. Sources: S-275 final 2024-25; '
      'OSPI 1191F; SPS leadership pages (Wayback, March 2025).</figcaption>'
      % (money(b["Executive cabinet"]["rate"]),
         float(b["Executive cabinet"]["per"] / b["Executive cabinet"]["rate"]),
         float(b["Teachers"]["per"] / b["Teachers"]["rate"])))
    A('<details><summary>Show the numbers</summary><div class="tw"><table>'
      '<thead><tr><th>Category</th><th>Basis</th><th>Positions</th>'
      '<th>Cert. / class.</th><th>SPS pays</th><th>State rate</th>'
      '<th>Multiple</th></tr></thead><tbody>')
    for x in buckets:
        mix = ("%d / %d" % (x["n_cas"], x["n_cls"])) if x["basis"] == "positions" \
            else "&mdash;"
        A('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
          '<td>%s</td><td>%.2f&times;</td></tr>'
          % (x["name"], "per position" if x["basis"] == "positions" else "per FTE",
             f'{float(x["positions"]):,.0f}', mix, money(x["per"]),
             money(x["rate"]), float(x["per"] / x["rate"])))
    A('</tbody></table></div></details></figure>')

    pd_ = b["Program directors"]
    A('<h3>Where the guess is, and how far off SEA&rsquo;s bar is</h3>')
    A('<p>&ldquo;Program Directors&rdquo; is the one bucket the roster '
      'cannot pin down, so this is a stated guess: <strong>every remaining '
      'district administrator and director/supervisor</strong> &mdash; %d '
      'certificated (duty 13) and %d classified (duty 99), %d people, paid from '
      '$78,177 to $254,566. Their average is <strong>%s</strong> per position, '
      'or %s carried forward to 2025-26.</p>'
      % (pd_["n_cas"], pd_["n_cls"], pd_["headcount"], money(pd_["per"]),
         money(pd_["per"] * ipd)))
    A('<p>SEA printed <strong>$230,970</strong>. That figure is reachable only '
      'from roughly the <strong>top 25 of those 143 people</strong> &mdash; the '
      'top sixth, an 82nd-percentile slice. Against the whole director layer, '
      'the bar is overstated by about <strong>$60,000 per position, some 35%'
      '</strong>. Either SEA meant a much narrower group than &ldquo;program '
      'directors&rdquo; conveys, or the bucket was drawn from the top down. '
      'Without a published definition the reader cannot tell &mdash; which is '
      'error 7 doing real damage rather than being a matter of housekeeping.</p>')
    A('<p><strong>Two of the black bars do check out, and it is worth saying '
      'so.</strong> The ten-person cabinet averages %s in 2024-25 &mdash; %s '
      'carried to 2025-26, against SEA&rsquo;s printed $284,518, a 0.3%% gap. '
      'The superintendent lands within 0.2%% the same way. That match is what '
      'makes the rest of the reconstruction credible.</p>'
      % (money(b["Executive cabinet"]["per"]),
         money(b["Executive cabinet"]["per"] * ipd)))
    A('<p>It does not settle the year, though, and the pattern is odd enough '
      'to be worth showing. The two administrator bars fit 2025-26 almost '
      'exactly and sit 2.2% high against 2024-25. The teacher and para bars do '
      'the reverse &mdash; they fit 2024-25 within about a percent and drift 2 '
      'to 4% low against 2025-26. No single year fits all four within one '
      'percent.</p>')
    A('<div class="tw"><table><thead><tr><th>Bar</th><th>SEA printed</th>'
      '<th>Rebuilt, 2024-25</th><th>&times;1.025 &rarr; 2025-26</th>'
      '<th>Closer fit</th></tr></thead><tbody>')
    for name, printed in (("Superintendent", D("365000")),
                          ("Executive cabinet", D("284518")),
                          ("Teachers", D("117000")),
                          ("Paras & office staff", D("82249"))):
        v24 = b[name]["per"]
        v25 = v24 * ipd
        d24 = abs(v24 / printed - 1)
        d25 = abs(v25 / printed - 1)
        best = "2024-25" if d24 < d25 else "2025-26"
        A('<tr><td>%s</td><td><strong>%s</strong></td><td%s>%s</td>'
          '<td%s>%s</td><td>%s</td></tr>'
          % (name, money(printed),
             ' class="ok"' if best == "2024-25" else '', money(v24),
             ' class="ok"' if best == "2025-26" else '', money(v25),
             "%s, %.1f%% off" % (best, float(min(d24, d25)) * 100)))
    A('</tbody></table></div>')
    A('<p class="sub">Program directors are left out of this table: with no '
      'published definition there is nothing to compare against.</p>')

    # ------------------------------------------------------------- chart 1
    A('<h3>Chart 2 &mdash; Where SPS staffing diverges from the model</h3>')
    A('<p>The state does not fund job titles, but it does publish a staffing '
      'model, role by role, in Report 1191EDF. Those roles sum exactly to the '
      'certificated and classified totals, so this is the state&rsquo;s own '
      'decomposition, not an invented mapping. Setting each role&rsquo;s funded '
      'staff units against the FTE SPS actually employs is the comparison the '
      'original chart was groping for &mdash; and it points the other way on '
      'administration.</p>')
    rrows = []
    for r in sorted(roles, key=lambda r: -float(r["actual_fte"] / r["model_fte"])):
        ratio = r["actual_fte"] / r["model_fte"]
        rrows.append({
            "label": r["role"], "ratio": ratio,
            "note": "state funds %s → SPS employs %s FTE"
                    % (f'{r["model_fte"]:,.0f}', f'{r["actual_fte"]:,.0f}'),
            "tip": "%s: state funds %s staff units, SPS employs %s FTE (%.2f×)"
                   % (r["role"], f'{r["model_fte"]:,.3f}',
                      f'{r["actual_fte"]:,.3f}', ratio),
        })
    A('<figure>')
    A('<div class="ftitle">SPS staffing versus the state’s own model, '
      '2024-25</div>')
    A('<div class="fsub">Each dot is one staffing role from Report 1191EDF. '
      'Right of the line, SPS employs more people than the model funds; left of '
      'it, fewer. Log scale &mdash; the spread runs from 0.72&times; to '
      '10.17&times;.</div>')
    A(ratio_dots(rrows))
    under = [r for r in roles if r["actual_fte"] < r["model_fte"]]
    aides = next(r for r in roles if r["role"].startswith("Teaching assistance"))
    cadmin = next(r for r in roles if r["role"] == "Central administration (CAS)")
    A('<figcaption>%s sit left of the line &mdash; the state funds more of '
      'them than SPS employs: %s. Certificated central administration, which '
      'an earlier version of this page had among them, is in fact at '
      '<strong>%.2f&times;</strong> &mdash; the model funds %s units and SPS '
      'employs %s FTE, near enough parity. Instructional aides run '
      '%.2f&times;. Sources: OSPI Report 1191EDF pages 8&ndash;15; S-275 final '
      '2024-25.</figcaption>'
      % ("Two roles" if len(under) == 2 else "%d roles" % len(under),
         " and ".join("%s (%.2f&times;)"
                      % (r["role"].split(" (")[0].lower(),
                         float(r["actual_fte"] / r["model_fte"])) for r in under),
         float(cadmin["actual_fte"] / cadmin["model_fte"]),
         f'{cadmin["model_fte"]:,.1f}', f'{cadmin["actual_fte"]:,.1f}',
         float(aides["actual_fte"] / aides["model_fte"])))
    A('<details><summary>Show the numbers</summary><div class="tw"><table>'
      '<thead><tr><th>Role</th><th>Class</th><th>State units</th>'
      '<th>SPS FTE</th><th>Ratio</th></tr></thead><tbody>')
    for r in sorted(roles, key=lambda r: -float(r["actual_fte"] / r["model_fte"])):
        A('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%.2f&times;</td></tr>'
          % (r["role"], r["class"], f'{r["model_fte"]:,.3f}',
             f'{r["actual_fte"]:,.3f}', r["actual_fte"] / r["model_fte"]))
    A('</tbody></table></div></details></figure>')

    # ------------------------------------------------------------- chart 2
    A('<h3>Chart 3 &mdash; The original’s own arithmetic, at full scale</h3>')
    A('<p>Take the chart&rsquo;s premise at face value: every dollar paid above '
      'the state&rsquo;s per-unit rate is a dollar the state did not fund. Then '
      'restore the one thing the original throws away &mdash; how many people '
      'are in each bucket &mdash; and multiply it out. The ranking inverts '
      'completely.</p>')
    grows = []
    for g in sorted(groups, key=lambda g: -float(g["gap_total"])):
        grows.append({
            "label": g["name"], "value": float(g["gap_total"]) / 1e6,
            "note": "%s FTE · %s over the %s rate/FTE"
                    % (_fte(g["fte"]), money(g["gap_per_fte"]), g["class"]),
            "tip": "%s: %s FTE, %s in salary, %s above the %s rate "
                   "of %s per unit → %s"
                   % (g["name"], f'{g["fte"]:,.1f}',
                      money(g["salary"]), money(g["gap_per_fte"]), g["class"],
                      money(g["rate"]), millions(g["gap_total"])),
        })
    A('<figure>')
    A('<div class="ftitle">Salary paid above the state’s per-unit rate, '
      '2024-25</div>')
    A('<div class="fsub">The same comparison the original makes, multiplied by '
      'headcount. All eight groups are S-275 duty codes anyone can re-run; all '
      'figures are one year, one method.</div>')
    A(hbar_chart(grows, value_key="value", label_key="label", note_key="note",
                 fmt=lambda v: "$%.1fM" % v,
                 tick_fmt=lambda v: "$%.0fM" % v,
                 title_fmt=lambda r: r["tip"], row_h=44, label_w=290,
                 steps=4,
                 axis_label="millions of dollars above the state rate"))
    A('<figcaption>Teachers account for <strong>%s of the %s total</strong> '
      '(%.0f%%). Everyone the original chart calls an administrator &mdash; the '
      'superintendent, the cabinet, district administrators, and every '
      'principal and vice principal &mdash; comes to %s, or %.1f%%. The '
      'superintendent alone is %s.</figcaption>'
      % (millions(teach_gap), millions(total_gap),
         float(teach_gap / total_gap * 100), millions(admin_gap),
         float(admin_gap / total_gap * 100), money(supt["gap_total"])))
    A('<details><summary>Show the numbers</summary><div class="tw"><table>'
      '<thead><tr><th>Group</th><th>S-275 duty</th><th>FTE</th>'
      '<th>Salary</th><th>$/FTE</th><th>State rate</th><th>Above rate</th>'
      '</tr></thead><tbody>')
    for g in sorted(groups, key=lambda g: -float(g["gap_total"])):
        A('<tr><td>%s</td><td><code>%s</code></td><td>%s</td>'
          '<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
          % (g["name"], ", ".join(g["roots"]),
             f'{g["fte"]:,.1f}', money(g["salary"]), money(g["per_fte"]),
             money(g["rate"]), millions(g["gap_total"])))
    A('<tr class="tot"><td>Total</td><td></td><td>%s</td><td>%s</td>'
      '<td></td><td></td><td>%s</td></tr>'
      % (f'{sum(g["fte"] for g in groups):,.1f}',
         money(sum(g["salary"] for g in groups)), millions(total_gap)))
    A('</tbody></table></div></details></figure>')
    A('<div class="note flag"><p><strong>This is not a claim that teachers are '
      'overpaid.</strong> It is a demonstration that &ldquo;paid above the '
      'state rate&rdquo; is a fact about the state rate, not about any job. '
      'Every group on the list clears it, because the rate was never set to '
      'cover a Seattle salary. Once you notice that, the interesting question '
      'stops being which titles sit furthest above the line and becomes how far '
      'below a Seattle salary the line itself sits.</p></div>')

    # ------------------------------------------------- chart 4: variance bars
    A('<h3>Chart 4 &mdash; The same money as budget versus actual</h3>')
    A('<p>Chart 3 plots an overhang against the state&rsquo;s <em>rate</em>. '
      'Here is the whole quantity against the state&rsquo;s actual '
      '<em>allocation</em>: the full bar is every salary dollar SPS paid that '
      'group, and the bar inside it is the money the formula really sends for '
      'that job &mdash; its funded staff units at that rate.</p>')
    A('<div class="note"><p><strong>Why this is not the same arithmetic as '
      'Chart 3.</strong> Chart 3 multiplies the state rate by the FTE SPS '
      'employs, which is what SEA&rsquo;s premise implies and is why that chart '
      'is a reductio rather than a measurement: hire more people and the '
      '&ldquo;state contribution&rdquo; grows. The formula does not work that '
      'way. It generates a fixed number of staff units from enrollment, and '
      'that number does not move when the district hires. This chart uses the '
      'generated units, so it is the one to read as coverage.</p></div>')
    A('<p>These bars overlap on purpose, and this is the case where overlap is '
      'honest. Error 5 was not that SEA drew one bar in front of another '
      '&mdash; it was that the two bars did not compose: an average salary and '
      'a per-unit rate come off different denominators, so nothing is left over '
      'when you subtract them. Here they do compose. The allocation is a '
      'portion of the money paid, off the same denominator, and the gap between '
      'the two bar ends is a real number of dollars.</p>')
    funded = data.funded_units_by_group(duties)
    vrows = []
    for g in sorted(groups, key=lambda g: -float(g["salary"])):
        vrows.append({
            "name": g["name"], "paid": g["salary"],
            "alloc": g["rate"] * funded[g["name"]],
            "note": "%s FTE employed · %s funded"
                    % (_fte(g["fte"]), _fte(funded[g["name"]])),
        })
    v_paid = sum(float(r["paid"]) for r in vrows)
    v_alloc = sum(float(r["alloc"]) for r in vrows)
    A('<figure>')
    A('<div class="ftitle">Salary paid, with the state’s allocation overlaid '
      '&mdash; 2024-25</div>')
    A('<div class="fsub">Salary only on both sides, no benefits. The state bar '
      'is that group&rsquo;s funded staff units times its class rate &mdash; '
      'the allocation the formula actually generates, not a rate applied to '
      'the people SPS hired.</div>')
    A('<div class="legend">'
      '<span><i class="sw" style="background:var(--track)"></i>'
      'salary SPS paid</span>'
      '<span><i class="sw" style="background:var(--series-1)"></i>'
      'state salary allocation</span></div>')
    A(variance_bars(vrows))
    worst = min(vrows, key=lambda r: float(r["alloc"]) / float(r["paid"]))
    A('<figcaption>Across the eight groups, %s of salary against %s the state '
      'allocates &mdash; <strong>%.0f%% covered</strong>, %s short. Coverage is '
      'lowest for %s at %.0f%%, because the model generates so few units for '
      'that job: everything past them is paid from levy, federal and local '
      'money. One caveat on that row &mdash; basic education staff units ignore '
      'the special education and MLL funding that pays for most '
      'paraeducators, so their real support is higher than %.0f%%.</figcaption>'
      % (millions(v_paid), millions(v_alloc), v_alloc / v_paid * 100,
         millions(v_paid - v_alloc), worst["name"].split(" (")[0].lower(),
         float(worst["alloc"]) / float(worst["paid"]) * 100,
         float(worst["alloc"]) / float(worst["paid"]) * 100))
    A('<details><summary>Show the numbers</summary><div class="tw"><table>'
      '<thead><tr><th>Group</th><th>FTE employed</th><th>Units funded</th>'
      '<th>Salary paid</th><th>State allocation</th><th>Unfunded</th>'
      '<th>Covered</th></tr></thead><tbody>')
    for g in sorted(groups, key=lambda g: -float(g["salary"])):
        alloc = g["rate"] * funded[g["name"]]
        A('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
          '<td>%s</td><td>%.1f%%</td></tr>'
          % (g["name"], f'{g["fte"]:,.1f}', f'{funded[g["name"]]:,.1f}',
             money(g["salary"]), money(alloc), money(g["salary"] - alloc),
             float(alloc / g["salary"] * 100)))
    A('<tr class="tot"><td>All eight groups</td><td>%s</td><td>%s</td>'
      '<td>%s</td><td>%s</td><td>%s</td><td>%.1f%%</td></tr>'
      % (f'{sum(g["fte"] for g in groups):,.1f}',
         f'{sum(funded.values()):,.1f}', money(v_paid), money(v_alloc),
         money(v_paid - v_alloc), v_alloc / v_paid * 100))
    A('</tbody></table></div></details></figure>')

    # ------------------------------------------------------------- chart 5
    A('<h3>Chart 5 &mdash; The number SEA should have led with</h3>')
    A('<p>Across all 6,362 FTE that SPS employs, the state pays for 62% of the '
      'payroll. That is the argument, it survives every objection above, and it '
      'is far stronger than a bar chart about the superintendent.</p>')
    cov = [
        {"label": "Certificated instructional", "pay": 571.3e6, "funded": 401.6e6},
        {"label": "Certificated administrative", "pay": 61.5e6, "funded": 33.7e6},
        {"label": "Classified", "pay": 274.7e6, "funded": 126.6e6},
        {"label": "All SPS staff", "pay": 907.4e6, "funded": 561.9e6},
    ]
    A('<figure>')
    A('<div class="ftitle">Share of SPS staff pay covered by state funding, '
      '2024-25</div>')
    A('<div class="fsub">Salary plus benefits on both sides. State funding is '
      'the 1191F staff-unit allocation ($447.6M) plus state special education '
      '($114.2M).</div>')
    A('<div class="legend">'
      '<span><i class="sw" style="background:var(--series-1)"></i>'
      'paid for by the state</span>'
      '<span><i class="sw" style="background:var(--muted-fill)"></i>'
      'paid for from levy, federal and other funds</span></div>')
    A(stacked_coverage(cov))
    A('<figcaption>Method, reconciliation checks and every judgment call: '
      '<code>docs/guides/DUTY_FUNDING.md</code>. The whole attribution run over '
      'all revenue lands within 0.5% of actual F-196 staff spending, reached '
      'independently from the revenue side.</figcaption></figure>')
    A('<div class="tiles">')
    for k, v, d in [
        ("State pays", "62%", "of the $907.4M SPS spends on staff"),
        ("Unfunded", "$345.5M", "covered by levy, federal and local money"),
        ("Classified staff", "46%", "the worst-covered class, by a wide margin"),
        ("Instructional aides", "10.17×", "SPS FTE per state-funded unit"),
    ]:
        A('<div class="tile"><div class="k">%s</div><div class="v">%s</div>'
          '<div class="d">%s</div></div>' % (k, v, d))
    A('</div>')

    # ----------------------------------------------------------- conclusion
    A('<h2>5. What the chart should have said</h2>')
    A('<p>There is a real finding buried under the design. The prototypical '
      'school model funds roughly three-fifths of what it costs to staff '
      'Seattle Public Schools, and it is furthest from reality on classified '
      'staff, where it covers 46%. That gap is what the local levy exists to '
      'fill, and it is the same gap in every district in the state.</p>')
    A('<p>What the model does <em>not</em> do is set a salary, endorse a '
      'salary, or tell you which job titles a district over-pays. It converts '
      'enrollment into notional positions at a flat statewide price. A chart '
      'built on the premise that the flat price is a per-title budget will '
      'always find that highly paid titles exceed it &mdash; and will always '
      'find that teachers exceed it too, by more dollars than everyone else '
      'combined. That is a property of the arithmetic, not a finding about '
      'anyone&rsquo;s pay.</p>')
    A('<p>If the point is that SPS spends too much on central administration, '
      'the state model is a poor witness: by its own role-level decomposition '
      'SPS employs %s certificated central administrators against the %s units '
      'the model funds &mdash; parity, not bloat. The district runs far over '
      'the model on instructional aides, custodians and classified central '
      'staff, and those are where the FTE actually is. There are better '
      'arguments available. This chart is not one of them.</p>'
      % (f'{cadmin["actual_fte"]:,.1f}', f'{cadmin["model_fte"]:,.1f}'))

    A('<footer><p><strong>Sources.</strong> '
      'OSPI Final Apportionment Summary (Report 1191F) and Report 1191EDF for '
      'Seattle Public Schools, 2024-25, pages 1&ndash;15, parsed by '
      '<code>tools/duty_funding/parse_bea_pages.py</code>. '
      'OSPI SAFS S-275 final personnel report, Seattle, 2024-25 '
      '(<code>tools/sea_chart_critique/s275_by_duty_2425.sql</code>). '
      'F-196 revenues and expenditures, 2024-25. '
      'Coverage percentages and the role mapping come from '
      '<code>docs/guides/DUTY_FUNDING.md</code>.</p>'
      '<p>2025-26 rates are the 2024-25 rates times the 2.5% salary inflator; '
      'SEA’s own $96,170 confirms the factor to the dollar. S-275 data '
      'for 2025-26 is not yet final, so every SPS figure here is 2024-25.</p>'
      '<p>Built by <code>tools/sea_chart_critique/build.py</code>.</p>'
      '</footer>')
    A('</div><script>%s</script>' % JS)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "index.html")
    with open(path, "w") as f:
        f.write("\n".join(h))
    print("wrote %s (%.0f KB)" % (path, os.path.getsize(path) / 1024))


def _fte(v):
    v = float(v)
    return f"{v:,.1f}" if v < 10 else f"{v:,.0f}"


def _people(n):
    return "1 person" if n == 1 else f"{n:,} people"


def _numify(s):
    s = s.replace("&mdash;", "0").replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return -1.0


if __name__ == "__main__":
    main()
