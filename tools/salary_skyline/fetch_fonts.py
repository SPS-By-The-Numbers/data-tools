#!/usr/bin/env python3
"""Inline the three Google faces the standalone SVG uses, as woff2 data URIs.

Writes out_salary_skyline/fonts_inline.css (~106 KB). Needs network access;
the output is stable, so it only has to run once per checkout.

  python3 tools/salary_skyline/fetch_fonts.py
"""
import base64, re, urllib.request
from pathlib import Path

OUT = Path("out_salary_skyline/fonts_inline.css")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
CSS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
       "&family=Public+Sans:wght@400;500;600&family=Zilla+Slab:wght@600;700&display=swap")


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()


def main():
    css = get(CSS).decode()
    faces, seen = [], {}
    for sub, block in re.findall(r"/\*\s*([\w\-\[\]]+)\s*\*/\s*@font-face\s*\{([^}]*)\}", css):
        if sub != "latin":
            continue
        fam = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https[^)]+\.woff2)\)", block).group(1)
        if url not in seen:
            seen[url] = base64.b64encode(get(url)).decode()
        # Public Sans ships as one variable file for every weight
        faces.append((fam, "100 900" if fam == "Public Sans" else weight, seen[url]))

    dedup, out = set(), []
    for fam, weight, b64 in faces:
        if (fam, weight) in dedup:
            continue
        dedup.add((fam, weight))
        out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}  {OUT.stat().st_size/1024:.0f} KB  ({len(out)} faces)")


if __name__ == "__main__":
    main()
