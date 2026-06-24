#!/bin/bash
# Rebuild the whole staffing analysis from scratch.
# Run from the repo root:  ./analysis/staffing/run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
PY=../../venv/bin/python3

echo "== extract =="            ; $PY extract.py
echo "== per-duty ratios =="    ; $PY plot_ratios.py
echo "== program ratios =="     ; $PY plot_program_ratios.py
echo "== experience plots =="   ; $PY plot_experience.py
echo "== HTML report =="        ; $PY gen_report.py
echo "Done. Outputs (figures + seattle_s275_salary_by_duty.html) are in the repo root."
