#!/usr/bin/env python3
"""Wrap the standalone tall SVG in a responsive HTML page (for publishing/viewing).

The SVG is fixed at 1560px wide; this re-emits its root tag with a viewBox and
width:100% so it scales to the viewport, and paints a themed page ground behind it.

  python3 tools/salary_skyline/wrap_page.py
"""
import argparse, re
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--svg", default="out_salary_skyline/salary_skyline_tall.svg")
ap.add_argument("-o", "--out", default="out_salary_skyline/salary_skyline_tall_page.html")
a = ap.parse_args()

src = Path(a.svg).read_text()
w = int(re.search(r'\bwidth="(\d+)"', src).group(1))
h = int(re.search(r'\bheight="(\d+)"', src).group(1))
body = src.split("\n", 1)[1]          # drop the fixed-size root tag; re-open it below

Path(a.out).write_text(f"""<title>SPS Salary Skyline, Vertical</title>
<style>
:root {{ color-scheme: light; --bg:#eeeeec; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --bg:#0e0e0d; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --bg:#0e0e0d; }}
body {{ margin:0; background:var(--bg); }}
.frame {{ max-width:{w}px; margin:0 auto; }}
</style>
<div class="frame">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" \
style="width:100%;height:auto;display:block" role="img" \
aria-label="Total final salary of every Seattle Public Schools employee, 2024-25 S-275, \
grouped by OSPI duty band and sorted highest to lowest">
{body}
</div>
""")
print(f"wrote {a.out}  ({w} x {h})")
