#!/bin/sh
# Screenshot the three standalone charts to PNG at 2x device scale.
set -e
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="$(cd "$(dirname "$0")/../../output/sea_chart_critique" && pwd)"
for spec in "img1 1054 1400" "img2 1054 2400" "img3 1252 2600" "img3_noline 1252 2600"; do
  set -- $spec
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size="$2","$3" \
    --virtual-time-budget=8000 \
    --screenshot="$OUT/$1.png" "file://$OUT/$1.html" 2>/dev/null
  python3 - "$OUT/$1.png" <<'PY'
import sys
from PIL import Image
import numpy as np
p = sys.argv[1]
im = Image.open(p).convert("RGB")
a = np.array(im)
# trim to the card: rows/cols that are not the page background
bg = a[2, 2].tolist()
mask = (np.abs(a.astype(int) - bg).sum(axis=2) > 12)
ys, xs = np.where(mask)
if len(ys):
    im = im.crop((max(0, xs.min() - 2), max(0, ys.min() - 2),
                  min(im.width, xs.max() + 3), min(im.height, ys.max() + 3)))
im.save(p)
print(p, im.size)
PY
done
