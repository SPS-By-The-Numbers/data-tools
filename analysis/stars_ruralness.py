#!/usr/bin/env python3
"""Extend the STARS log-linear model with a 'ruralness' density predictor and
test whether it adds explanatory power.

Ruralness proxy: density = population / land_area, where the population proxy is
the basic-transportation ridership (`basic_program`, the closest student-count in
the STARS ledger). Low density = few students spread over a large area = rural.

IMPORTANT modelling note. The base STARS model already contains ln(land_area)
and ln(basic_program). Adding ln(density) = ln(basic_program) - ln(land_area)
would be an exact linear combination of those two regressors -> perfect
collinearity, zero new information, singular design. So density MUST enter in
LEVEL (ratio) form, which is a genuinely new nonlinear transform. This script
adds `density` (raw) on top of the 7 base predictors.

Dependent variable matters:
  * dep=a4  -> A.4 expected allocation is, by construction, an exact function of
               the 7 base predictors. Density therefore CANNOT help (delta-R^2 ~ 0,
               t ~ 0). Useful as a negative control / sanity check.
  * dep=cost-> F-196 reported transportation cost (the real-world target). This is
               where an omitted ruralness effect could actually show up.

Reports, per year: base vs extended R^2, the density coefficient with its t-stat
and p-value, and the change in adjusted R^2 / AIC.

Usage:
    python3 analysis/stars_ruralness.py                 # dep=cost (default)
    python3 analysis/stars_ruralness.py --dep a4        # negative control
    python3 analysis/stars_ruralness.py --pop total     # basic+special ridership
"""

import argparse
import importlib.util
import math
import os

import numpy as np
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
COVID_YEARS = {"2020-2021", "2021-2022"}


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)
    return se


def density(rec, pop):
    """population / land_area in level form. pop='basic' uses basic_program;
    pop='total' uses basic+special program ridership."""
    area = rec.get("land_area")
    basic = rec.get("basic_program")
    special = rec.get("special_program") or 0.0
    if area is None or area <= 0 or basic is None:
        return None
    population = basic + (special if pop == "total" else 0.0)
    return population / area


def build(se, rows, sy, dep, pop):
    """Return (X_base, X_ext, y) numpy arrays for one school year, or None.
    X_base is the 7 STARS predictors (with the usual transforms); X_ext appends
    the level-form density column."""
    Xb, Xe, y = [], [], []
    spec = se.DEPENDENTS[dep]
    for k in [k for k in rows if k[0] == sy]:
        rec = rows[k]
        base = se.design_row(rec)          # 7 transformed predictors
        dval = density(rec, pop)
        yv = rec.get(dep)
        if base is None or dval is None or yv is None:
            continue
        if spec["logged"]:
            yval = yv
        else:
            if yv <= 0:
                continue
            yval = math.log(yv)
        Xb.append(base)
        Xe.append(base + [dval])
        y.append(yval)
    if len(y) < 25:
        return None
    return np.array(Xb), np.array(Xe), np.array(y)


def fit(X, y):
    return sm.OLS(y, sm.add_constant(X)).fit()


def run(se, rows, dep, pop, drop_covid):
    label = "ex-COVID" if drop_covid else "all years"
    print(f"\n=== Ruralness (density = {pop}_ridership / land_area, level form) "
          f"added to STARS  [dep={dep}, {label}] ===")
    print(f"{'year':10s} {'n':>4s} {'R2 base':>8s} {'R2 ext':>8s} {'dR2':>7s} "
          f"{'adjR2 b':>8s} {'adjR2 e':>8s} {'dens coef':>11s} {'t':>7s} "
          f"{'p':>7s} {'dAIC':>8s}")
    years = sorted({k[0] for k in rows})
    dr2s, ts, sig = [], [], 0
    for sy in years:
        if drop_covid and sy in COVID_YEARS:
            continue
        built = build(se, rows, sy, dep, pop)
        if built is None:
            continue
        Xb, Xe, y = built
        rb, re = fit(Xb, y), fit(Xe, y)
        dcoef = re.params[-1]      # density is the last column after const+7
        dt = re.tvalues[-1]
        dp = re.pvalues[-1]
        dr2 = re.rsquared - rb.rsquared
        daic = re.aic - rb.aic
        dr2s.append(dr2); ts.append(dt)
        if dp < 0.05:
            sig += 1
        star = "*" if dp < 0.05 else " "
        print(f"{sy:10s} {len(y):4d} {rb.rsquared:8.4f} {re.rsquared:8.4f} "
              f"{dr2:7.4f} {rb.rsquared_adj:8.4f} {re.rsquared_adj:8.4f} "
              f"{dcoef:11.3e} {dt:7.2f} {dp:7.3f}{star}{daic:7.1f}")
    if dr2s:
        n = len(dr2s)
        print(f"\n  years tested: {n} | density significant (p<0.05): {sig}/{n} | "
              f"mean dR2: {np.mean(dr2s):+.4f} | mean t: {np.mean(ts):+.2f}")
        print("  (dAIC<0 favors the extended model; dR2 is the gain in raw R^2)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--cost-csv", default="transit-expenditures.csv")
    ap.add_argument("--dep", default="cost", choices=["cost", "a4", "a3", "d8", "d2"])
    ap.add_argument("--pop", default="basic", choices=["basic", "total"],
                    help="population proxy: basic_program, or basic+special ridership")
    args = ap.parse_args()

    se = _load_module()
    rows, _pub, _raw = se.load(args.csv)
    if args.dep == "cost":
        if not os.path.exists(args.cost_csv):
            raise SystemExit(f"--dep cost needs {args.cost_csv}")
        totals, _k, _d = se.load_costs(args.cost_csv)
        matched = se.attach_costs(rows, totals, lag=0)
        print(f"Attached F-196 cost (ex obj 0/1/9) to {matched} district-years.")

    for drop in (False, True):
        run(se, rows, args.dep, args.pop, drop)


if __name__ == "__main__":
    main()
