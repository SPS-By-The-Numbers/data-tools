#!/usr/bin/env python3
"""Which cost target + timing best reproduces the published STARS coefficients?

The expected-allocation regression is calibrated to predicted COST. The question
is which cost series, at which lag, recovers the published coefficients:

  * D.4 "adjusted prior-year expenditures" is OSPI's OWN cost number, already in
    the ledger (= D.2 + D.3 federal indirects) and the basis of the D.5 cap.
    Critically D.4 in year Y's record is the year-(Y-1) expenditure, so it must
    be paired with the ADJACENT (prior) year's predictors to be contemporaneous.
  * D.2 raw prior-year expenditures (same one-year lag).
  * F-196 reconstructed cost (external, same-year) -- the earlier baseline.

For a fit indexed by predictor-year c we regress  ln(dep[c + dep_lag]) ~ X[c]
and compare the recovered coefficients to the PUBLISHED coefficients of year c
(the formula coefficients that sit alongside X[c]). dep_lag=+1 pulls the
dependent from the NEXT record, which for a prior-year quantity like D.4/D.2
makes cost and predictors describe the SAME real year.

Alignment cheat-sheet (c = predictor year):
  dep=d4 dep_lag=0  ->  D.4[c]   = cost of year c-1  vs X[c]      (mismatched)
  dep=d4 dep_lag=+1 ->  D.4[c+1] = cost of year c    vs X[c]      (contemporaneous)
  dep=cost dep_lag=0 -> F196[c]  = cost of year c    vs X[c]      (contemporaneous)

Usage:
    python3 analysis/stars_target_timing.py
"""

import importlib.util
import math
import os
from collections import defaultdict

import numpy as np
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
COVID = {"2020-2021", "2021-2022"}


def _se():
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fit_aligned(se, rows, by_year, sy, dep, dep_lag):
    """Regress ln(dep[c+dep_lag]) ~ X[c] for predictor-year sy. Returns coef dict
    or None. by_year maps class_of(int) -> {ccddd: rec}."""
    try:
        c = int(rows_year_to_class(rows, sy))
    except Exception:
        return None
    src = by_year.get(c + dep_lag, {})
    X, y = [], []
    for ccddd, rec in by_year.get(c, {}).items():
        x = se.design_row(rec)
        if x is None:
            continue
        drec = src.get(ccddd)
        if drec is None:
            continue
        dv = drec.get(dep)
        if dv is None or dv <= 0:
            continue
        X.append(x)
        y.append(math.log(dv))
    if len(y) < 25:
        return None
    res = sm.OLS(np.array(y), sm.add_constant(np.array(X))).fit()
    coef = {"intercept": res.params[0]}
    for j, code in enumerate(se.PRED_CODES):
        coef[code] = res.params[j + 1]
    return coef, len(y), res.rsquared


def rows_year_to_class(rows, sy):
    for (s, _c), rec in rows.items():
        if s == sy:
            return rec["class_of"]
    raise KeyError(sy)


def maxdiff(se, coef, pub):
    keys = ["intercept"] + se.PRED_CODES
    d = [abs(coef[k] - pub[k]) for k in keys if k in pub]
    return max(d) if d else float("nan")


def main():
    se = _se()
    rows, published, _ = se.load("out_stars/stars_operations_allocation.csv")
    # attach F196 cost (same-year) as the 'cost' dependent baseline
    if os.path.exists("transit-expenditures.csv"):
        totals, _k, _d = se.load_costs("transit-expenditures.csv")
        se.attach_costs(rows, totals, lag=0)

    # index records by class_of year
    by_year = defaultdict(dict)
    sy_of_class = {}
    for (sy, ccddd), rec in rows.items():
        c = int(rec["class_of"])
        by_year[c][ccddd] = rec
        sy_of_class[c] = sy

    configs = [
        ("d4", +1, "D.4 adj prior-yr exp, contemporaneous (X[c] vs cost-of-c)"),
        ("d4", 0,  "D.4 adj prior-yr exp, as-stored   (X[c] vs cost-of-c-1)"),
        ("d2", +1, "D.2 prior-yr exp, contemporaneous (X[c] vs cost-of-c)"),
        ("cost", 0, "F-196 reconstructed cost, same-year (baseline)"),
        ("a4", 0,  "A.4 expected allocation (formula output; self-consistency)"),
    ]

    years = sorted({k[0] for k in rows})
    print("Mean (over non-COVID predictor-years) of max|recovered - published| coef diff,")
    print("comparing each recovered fit to the published coefficients of predictor-year c.\n")
    print(f"{'dependent / timing':58s} {'years':>5s} {'meanR2':>7s} {'mean maxdiff':>13s}")
    print("-" * 86)
    for dep, lag, label in configs:
        diffs, r2s = [], []
        for sy in years:
            if sy in COVID:
                continue
            out = fit_aligned(se, rows, by_year, sy, dep, lag)
            if out is None or sy not in published:
                continue
            coef, n, r2 = out
            diffs.append(maxdiff(se, coef, published[sy]))
            r2s.append(r2)
        if diffs:
            print(f"{label:58s} {len(diffs):5d} {np.mean(r2s):7.3f} {np.mean(diffs):13.4f}")

    # Test the "fit on year-c cost, apply NEXT year" framing: compare the
    # contemporaneous-cost fit (year-c cost vs year-c predictors) to the published
    # coefficients of year c+1, not year c.
    nextyear = {c: sy_of_class.get(c + 1) for c in by_year}
    print("\n'Fit on year-c cost, applied year c+1' test:")
    print("mean max|recovered - published[c+1]| over non-COVID years:")
    for dep, lag, label in [("d4", 1, "D.4 (=cost of c)"),
                            ("d2", 1, "D.2 (=cost of c)"),
                            ("cost", 0, "F-196 cost of c")]:
        diffs = []
        for sy in years:
            if sy in COVID:
                continue
            c = int(rows_year_to_class(rows, sy))
            nsy = nextyear.get(c)
            out = fit_aligned(se, rows, by_year, sy, dep, lag)
            if out and nsy in published:
                diffs.append(maxdiff(se, out[0], published[nsy]))
        if diffs:
            print(f"   {label:20s} vs pub[c+1]: {np.mean(diffs):.4f}  (n={len(diffs)})")

    # per-year detail, both comparison targets
    print("\nPer-year max-diff (non-COVID).  d4+1 = D.4 contemporaneous fit:")
    print(f"{'pred-yr c':10s} {'d4+1 vs pub[c]':>15s} {'d4+1 vs pub[c+1]':>17s} "
          f"{'cost vs pub[c]':>15s} {'cost vs pub[c+1]':>17s}")
    for sy in years:
        if sy in COVID:
            continue
        c = int(rows_year_to_class(rows, sy))
        nsy = nextyear.get(c)
        d4 = fit_aligned(se, rows, by_year, sy, "d4", 1)
        co = fit_aligned(se, rows, by_year, sy, "cost", 0)
        def cell(out, target):
            return f"{maxdiff(se, out[0], published[target]):.4f}" if out and target in published else "   -"
        print(f"{sy:10s} {cell(d4, sy):>15s} {cell(d4, nsy):>17s} "
              f"{cell(co, sy):>15s} {cell(co, nsy):>17s}")


if __name__ == "__main__":
    main()
