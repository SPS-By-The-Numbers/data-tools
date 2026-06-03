#!/usr/bin/env python3
"""Idea #1: district random-effects / partial-pooling model for STARS cost.

    ln(cost_dy) = X_dy . beta  +  u_d  +  eps_dy ,   u_d ~ N(0, tau^2),  eps ~ N(0, sigma^2)

A single REML fit over the whole panel estimates the shared STARS coefficients
(beta), the between-district variance (tau^2) and within-district residual
variance (sigma^2) jointly, and produces a partial-pooled (BLUP) intercept u_d
for every district. u_d is the persistent offset the cross-sectional formula
throws into its residual -- Seattle's ~+0.48, Everett's ~-0.58 -- shrunk toward 0
by exactly the credibility factor. This is the generative model the closed-form
credibility blend (stars_credibility.py) approximates; expect tau^2/sigma^2 here
to match the credibility hyperparameters.

Two reports:
  (A) IN-SAMPLE structural fit with year fixed effects (each year's overall cost
      level absorbed exactly, like the per-year collective). Shows variance
      components, ICC, and the BLUP offsets for the fat-end districts.
  (B) WALK-FORWARD forecast: for each target year Y, refit on prior non-COVID
      years (linear year trend so it extrapolates), predict Y as
      X.beta + u_d (BLUP from prior years only). Compared head-to-head with the
      SAME model minus the random effect (pooled OLS), so the APE gap is purely
      the partial-pooling contribution.

Usage:
    python3 analysis/stars_mixed.py
    python3 analysis/stars_mixed.py --min-prior 2
"""

import argparse
import importlib.util
import math
import os
import warnings
from collections import defaultdict

import numpy as np
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
COVID = {"2020-2021", "2021-2022"}
warnings.filterwarnings("ignore")  # MixedLM convergence chatter


def _se():
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def gather(se, rows):
    """records: list of (ccddd, class_of_int, year_str, vec7, ln_cost), non-COVID."""
    recs = []
    for (sy, ccddd), rec in rows.items():
        if sy in COVID:
            continue
        x = se.design_row(rec)
        c = rec.get("cost")
        if x is None or c is None or c <= 0:
            continue
        recs.append((ccddd, int(rec["class_of"]), sy, x, math.log(c), c))
    return recs


def fit_mixed(y, X, groups):
    md = sm.MixedLM(y, X, groups=groups, exog_re=np.ones((len(y), 1)))
    return md.fit(reml=True, method="lbfgs", maxiter=200)


def district_names():
    import csv
    dn = {}
    with open("out_stars/stars_operations_allocation.csv") as f:
        for r in csv.DictReader(f):
            dn[r["ccddd"]] = r["district"]
    return dn


def report_insample(se, recs, dn):
    years = sorted({r[2] for r in recs})
    ycol = {y: i for i, y in enumerate(years)}
    # design: const + year dummies (drop first) + 7 predictors
    X, y, groups = [], [], []
    for ccddd, _c, sy, vec, lc, _cost in recs:
        onehot = [1.0 if ycol[sy] == j else 0.0 for j in range(1, len(years))]
        X.append([1.0] + onehot + vec)
        y.append(lc)
        groups.append(ccddd)
    X = np.array(X); y = np.array(y)
    res = fit_mixed(y, X, groups)
    tau2 = float(np.asarray(res.cov_re)[0,0]); sigma2 = float(res.scale)
    icc = tau2 / (tau2 + sigma2)
    print("=== (A) In-sample random-intercept fit (year fixed effects) ===")
    print(f"  observations={len(y)}  districts={len(set(groups))}")
    print(f"  tau^2 (between-district) = {tau2:.4f}")
    print(f"  sigma^2 (within-district) = {sigma2:.4f}")
    print(f"  ICC = tau^2/(tau^2+sigma^2) = {icc:.3f}  "
          f"({icc*100:.0f}% of residual cost variance is persistent district identity)")
    print("  (compare to credibility hyperparameters tau^2~0.050, sigma^2~0.015)")
    # fixed-effect STARS coefficients (last 7 columns)
    fe = res.fe_params
    coef_names = se.PRED_CODES
    print("\n  Jointly-estimated STARS coefficients (pooled across all years):")
    for nm, b in zip(coef_names, np.asarray(fe)[-7:]):
        print(f"    {nm:18s} {b:+.4f}")
    # BLUP offsets for fat-end districts
    re = res.random_effects
    size = defaultdict(list)
    for ccddd, _c, _sy, _v, _lc, cost in recs:
        size[ccddd].append(cost)
    top = sorted(size, key=lambda c: np.mean(size[c]), reverse=True)[:15]
    print("\n  Partial-pooled (BLUP) district offsets u_d, fat end "
          "(positive = costs above formula):")
    print(f"    {'district':34s} {'mean cost':>13s} {'u_d (BLUP)':>11s} {'~x dollars':>11s}")
    for c in top:
        u = float(np.asarray(re[c]).ravel()[0])
        print(f"    {dn.get(c, c)[:34]:34s} {np.mean(size[c]):>13,.0f} "
              f"{u:>+11.3f} {math.exp(u):>10.2f}x")
    return tau2, sigma2


def backtest(se, recs, dn, min_prior):
    years = sorted({r[2] for r in recs})
    by_year = defaultdict(list)
    for r in recs:
        by_year[r[2]].append(r)
    # prior-year history count per district (non-COVID)
    out = []
    for i, sy in enumerate(years):
        prior = years[:i]
        if len(prior) < min_prior:
            continue
        prior_recs = [r for py in prior for r in by_year[py]]
        prior_classes = [r[1] for r in prior_recs]
        ybar = float(np.mean(prior_classes))
        # design: const + yr_centered + 7 preds
        Xp = np.array([[1.0, r[1] - ybar] + r[3] for r in prior_recs])
        yp = np.array([r[4] for r in prior_recs])
        grp = [r[0] for r in prior_recs]
        hist_count = defaultdict(int)
        for g in grp:
            hist_count[g] += 1
        mixed = fit_mixed(yp, Xp, grp)
        ols = sm.OLS(yp, Xp).fit()
        re = mixed.random_effects
        fe = np.asarray(mixed.fe_params)
        for ccddd, cls, _sy, vec, _lc, cost in by_year[sy]:
            if hist_count.get(ccddd, 0) < min_prior or ccddd not in re:
                continue
            xnew = np.array([1.0, cls - ybar] + vec)
            pred_re = math.exp(float(xnew @ fe) + float(np.asarray(re[ccddd]).ravel()[0]))
            pred_no = math.exp(float(xnew @ ols.params))
            out.append({
                "ccddd": ccddd, "year": sy, "actual": cost,
                "ape_re": abs(pred_re - cost) / cost,
                "ape_no": abs(pred_no - cost) / cost,
            })
    return out


def block(title, recs):
    if not recs:
        return
    re = np.array([r["ape_re"] for r in recs])
    no = np.array([r["ape_no"] for r in recs])
    win = np.mean(re < no) * 100
    print(f"\n{title}  (n={len(recs)})")
    print(f"  {'':18s} {'median':>8s} {'mean':>8s} {'90th':>8s} {'95th':>8s}")
    print(f"  {'pooled OLS (no RE)':18s} {np.median(no)*100:7.1f}% {np.mean(no)*100:7.1f}% "
          f"{np.percentile(no,90)*100:7.1f}% {np.percentile(no,95)*100:7.1f}%")
    print(f"  {'mixed (+ RE)':18s} {np.median(re)*100:7.1f}% {np.mean(re)*100:7.1f}% "
          f"{np.percentile(re,90)*100:7.1f}% {np.percentile(re,95)*100:7.1f}%")
    print(f"  random effect beats pooled on {win:.0f}% of district-years")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--cost-csv", default="transit-expenditures.csv")
    ap.add_argument("--min-prior", type=int, default=2)
    args = ap.parse_args()

    se = _se()
    rows, _pub, _raw = se.load(args.csv)
    if not os.path.exists(args.cost_csv):
        raise SystemExit(f"needs {args.cost_csv}")
    totals, _k, _d = se.load_costs(args.cost_csv)
    n = se.attach_costs(rows, totals, lag=0)
    print(f"Attached F-196 cost (ex obj 0/1/9) to {n} district-years.\n")

    recs = gather(se, rows)
    dn = district_names()
    report_insample(se, recs, dn)

    print("\n=== (B) Walk-forward forecast: mixed (+RE) vs pooled OLS (no RE) ===")
    bt = backtest(se, recs, dn, args.min_prior)
    block("ALL evaluated district-years", bt)
    size = defaultdict(list)
    for r in bt:
        size[r["ccddd"]].append(r["actual"])
    top = set(sorted(size, key=lambda c: np.mean(size[c]), reverse=True)[:15])
    block("FAT END (top 15 by mean cost)", [r for r in bt if r["ccddd"] in top])

    sps = sorted([r for r in bt if r["ccddd"] == "17001"], key=lambda r: r["year"])
    if sps:
        print("\nSeattle Public Schools (17001) per target year:")
        print(f"  {'year':10s} {'pooled APE':>11s} {'mixed APE':>11s}")
        for r in sps:
            print(f"  {r['year']:10s} {r['ape_no']*100:10.1f}% {r['ape_re']*100:10.1f}%")


if __name__ == "__main__":
    main()
