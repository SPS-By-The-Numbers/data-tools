#!/usr/bin/env bash
# Rasterize the standalone tall SVG to PNG using headless Chrome.
#
# There is no rsvg-convert / cairosvg / ImageMagick in this checkout, and the
# canvas is far past any single-texture limit, so Chrome's --screenshot is the
# path that actually works. Height is read out of the SVG so it stays in sync.
#
#   scripts/../tools/salary_skyline/render_png.sh [svg] [png]
set -euo pipefail

SVG="${1:-out_salary_skyline/salary_skyline_tall.svg}"
PNG="${2:-out_salary_skyline/salary_skyline_tall.png}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

[ -x "$CHROME" ] || { echo "Chrome not found; set CHROME=/path/to/chrome" >&2; exit 1; }

W=$(sed -n '1,3p' "$SVG" | grep -o 'width="[0-9]*"'  | head -1 | tr -dc 0-9)
H=$(sed -n '1,3p' "$SVG" | grep -o 'height="[0-9]*"' | head -1 | tr -dc 0-9)
echo "rendering ${W}x${H} -> $PNG"

"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --virtual-time-budget=20000 --window-size="$W,$H" \
  --screenshot="$PNG" "file://$(cd "$(dirname "$SVG")" && pwd)/$(basename "$SVG")" 2>/dev/null

ls -la "$PNG"
