#!/usr/bin/env python3
"""Random slope on basic_program: does each district need its own ridership elasticity?

Extends the random-intercept model (stars_mixed.py) with a random slope on
ln(basic_program), the dominant predictor:

    ln(cost_dy) = X_dy . beta + u_d + v_d * (ln basic_program_dy - mean) + eps

  u_d ~ district intercept (persistent level),  v_d ~ district-specific deviation
  in the ridership elasticity. ln(basic_program) is CENTERED on its grand mean so
  u_d and v_d are not mechanically collinear (intercept = effect at mean ridership).

Compares random-intercept (RI) vs random-intercept+slope (RIS):
  (A) in-sample: variance components, intercept/slope correlation, a REML
      likelihood-ratio test (fixed effects identical, so the LRT on the 2 extra
      random params is valid; boundary test => conservative), and the per-district
      total elasticity (beta_basic + v_d) for the fat-end districts.
  (B) walk-forward: does the random slope improve out-of-sample APE over RI?

Caveat up front: a random slope is identified from WITHIN-district variation in
ln(basic_program) over the ~6-year panel, which is modest. Expect it to be weakly
identified -- the honest question is whether it earns its keep.

Usage:
    python3 analysis/stars_mixed_slope.py
"""

import argparse
import importlib.util
import math
import os
import warnings
from collections import defaultdict

import numpy as np
import statsmodels.api as sm
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
COVID = {"2020-2021", "2021-2022"}
BASIC_IDX = 3   # position of basic_program in se.PRED_CODES
warnings.filterwarnings("ignore")


def _se():
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def gather(se, rows):
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


def fit(y, X, groups, re_exog):
    md = sm.MixedLM(y, X, groups=groups, exog_re=re_exog)
    return md.fit(reml=True, method="lbfgs", maxiter=300)


def names():
    import csv
    dn = {}
    with open("out_stars/stars_operations_allocation.csv") as f:
        for r in csv.DictReader(f):
            dn[r["ccddd"]] = r["district"]
    return dn


def insample(se, recs, dn):
    years = sorted({r[2] for r in recs})
    ycol = {y: i for i, y in enumerate(years)}
    basic_mean = float(np.mean([r[3][BASIC_IDX] for r in recs]))
    X, y, grp, bc = [], [], [], []
    for ccddd, _c, sy, vec, lc, _cost in recs:
        onehot = [1.0 if ycol[sy] == j else 0.0 for j in range(1, len(years))]
        X.append([1.0] + onehot + vec)
        y.append(lc); grp.append(ccddd)
        bc.append(vec[BASIC_IDX] - basic_mean)
    X = np.array(X); y = np.array(y); bc = np.array(bc)
    ri = fit(y, X, grp, np.ones((len(y), 1)))
    ris = fit(y, X, grp, np.column_stack([np.ones(len(y)), bc]))

    cr = np.asarray(ris.cov_re)
    v_int, v_slope, cov_is = cr[0, 0], cr[1, 1], cr[0, 1]
    corr = cov_is / math.sqrt(v_int * v_slope) if v_int > 0 and v_slope > 0 else float("nan")
    lr = 2 * (ris.llf - ri.llf)
    # mixture chi2 for testing a variance + covariance on the boundary (df 1 & 2)
    p = 0.5 * stats.chi2.sf(lr, 1) + 0.5 * stats.chi2.sf(lr, 2)

    print("=== (A) In-sample: RI vs RI+slope(basic_program) ===")
    print(f"  RI : tau^2(intercept)={np.asarray(ri.cov_re)[0,0]:.4f}  sigma^2={ri.scale:.4f}  llf={ri.llf:.1f}")
    print(f"  RIS: var(intercept)={v_int:.4f}  var(slope)={v_slope:.5f}  "
          f"corr(int,slope)={corr:+.2f}  sigma^2={ris.scale:.4f}  llf={ris.llf:.1f}")
    print(f"  LR test (RIS vs RI): LR={lr:.1f}, mixture-chi2 p={p:.2e}  "
          f"{'-> slope justified' if p < 0.05 else '-> slope NOT justified'}")
    sd_slope = math.sqrt(v_slope) if v_slope > 0 else 0.0
    beta_basic = float(np.asarray(ris.fe_params)[-7 + BASIC_IDX])
    print(f"\n  Fixed elasticity beta_basic = {beta_basic:.3f}; district slopes SD = {sd_slope:.3f}")
    print(f"  => ~95% of districts have ridership elasticity in "
          f"[{beta_basic-2*sd_slope:.2f}, {beta_basic+2*sd_slope:.2f}]")

    re = ris.random_effects
    size = defaultdict(list)
    for ccddd, _c, _sy, _v, _lc, cost in recs:
        size[ccddd].append(cost)
    top = sorted(size, key=lambda c: np.mean(size[c]), reverse=True)[:12]
    print("\n  Fat-end districts: intercept u_d and total elasticity (beta_basic + v_d):")
    print(f"    {'district':34s} {'u_d':>8s} {'v_d':>8s} {'elasticity':>11s}")
    for c in top:
        u, v = np.asarray(re[c]).ravel()[:2]
        print(f"    {dn.get(c, c)[:34]:34s} {u:>+8.3f} {v:>+8.3f} {beta_basic+v:>11.3f}")
    return basic_mean


def backtest(se, recs, min_prior):
    years = sorted({r[2] for r in recs})
    by_year = defaultdict(list)
    for r in recs:
        by_year[r[2]].append(r)
    out = []
    for i, sy in enumerate(years):
        prior = years[:i]
        if len(prior) < min_prior:
            continue
        pr = [r for py in prior for r in by_year[py]]
        ybar = float(np.mean([r[1] for r in pr]))
        bmean = float(np.mean([r[3][BASIC_IDX] for r in pr]))
        X = np.array([[1.0, r[1] - ybar] + r[3] for r in pr])
        y = np.array([r[4] for r in pr])
        grp = [r[0] for r in pr]
        bc = np.array([r[3][BASIC_IDX] - bmean for r in pr])
        hist = defaultdict(int)
        for g in grp:
            hist[g] += 1
        ri = fit(y, X, grp, np.ones((len(y), 1)))
        ris = fit(y, X, grp, np.column_stack([np.ones(len(y)), bc]))
        re_ri, re_ris = ri.random_effects, ris.random_effects
        fe_ri, fe_ris = np.asarray(ri.fe_params), np.asarray(ris.fe_params)
        for ccddd, cls, _sy, vec, _lc, cost in by_year[sy]:
            if hist.get(ccddd, 0) < min_prior or ccddd not in re_ri:
                continue
            xnew = np.array([1.0, cls - ybar] + vec)
            p_ri = math.exp(float(xnew @ fe_ri) + float(np.asarray(re_ri[ccddd]).ravel()[0]))
            uv = np.asarray(re_ris[ccddd]).ravel()
            p_ris = math.exp(float(xnew @ fe_ris) + uv[0] + uv[1] * (vec[BASIC_IDX] - bmean))
            out.append({"ccddd": ccddd, "year": sy, "actual": cost,
                        "ape_ri": abs(p_ri - cost) / cost,
                        "ape_ris": abs(p_ris - cost) / cost})
    return out


def block(title, recs):
    if not recs:
        return
    ri = np.array([r["ape_ri"] for r in recs])
    ris = np.array([r["ape_ris"] for r in recs])
    print(f"\n{title}  (n={len(recs)})")
    print(f"  {'':22s} {'median':>8s} {'mean':>8s} {'90th':>8s} {'95th':>8s}")
    print(f"  {'RI (intercept only)':22s} {np.median(ri)*100:7.1f}% {np.mean(ri)*100:7.1f}% "
          f"{np.percentile(ri,90)*100:7.1f}% {np.percentile(ri,95)*100:7.1f}%")
    print(f"  {'RIS (+ basic slope)':22s} {np.median(ris)*100:7.1f}% {np.mean(ris)*100:7.1f}% "
          f"{np.percentile(ris,90)*100:7.1f}% {np.percentile(ris,95)*100:7.1f}%")
    print(f"  RIS beats RI on {np.mean(ris < ri)*100:.0f}% of district-years")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--cost-csv", default="transit-expenditures.csv")
    ap.add_argument("--min-prior", type=int, default=2)
    args = ap.parse_args()

    se = _se()
    rows, _pub, _raw = se.load(args.csv)
    totals, _k, _d = se.load_costs(args.cost_csv)
    n = se.attach_costs(rows, totals, lag=0)
    print(f"Attached F-196 cost to {n} district-years.\n")

    recs = gather(se, rows)
    insample(se, recs, names())
    print("\n=== (B) Walk-forward: RI vs RIS ===")
    bt = backtest(se, recs, args.min_prior)
    block("ALL evaluated district-years", bt)
    size = defaultdict(list)
    for r in bt:
        size[r["ccddd"]].append(r["actual"])
    top = set(sorted(size, key=lambda c: np.mean(size[c]), reverse=True)[:15])
    block("FAT END (top 15 by mean cost)", [r for r in bt if r["ccddd"] in top])
    sps = sorted([r for r in bt if r["ccddd"] == "17001"], key=lambda r: r["year"])
    if sps:
        print("\nSeattle Public Schools (17001) per target year:")
        print(f"  {'year':10s} {'RI APE':>9s} {'RIS APE':>9s}")
        for r in sps:
            print(f"  {r['year']:10s} {r['ape_ri']*100:8.1f}% {r['ape_ris']*100:8.1f}%")


if __name__ == "__main__":
    main()
