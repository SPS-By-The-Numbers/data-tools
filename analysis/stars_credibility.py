#!/usr/bin/env python3
"""Prototype: credibility-blend correction for the STARS fat-tail bias.

The diagnostic (see stars_rural_interaction / the residual analysis) showed the
formula's error at the big end is a PERSISTENT per-district offset, not noise:
Seattle's actual cost beats its formula-expected cost by ~+0.48 in log terms in
6/6 years; Everett is ~-0.58 in 6/6 years; etc. A single statewide cross-section
cannot represent a per-district level, so it dumps that level into the residual.

This blends the formula with the district's own track record using empirical-Bayes
(Bühlmann) credibility, entirely in log-cost space:

    ln(pred_dY) = m_dY            (the "collective": cross-sectional formula fit)
                + Z_d * offset_d  (credibility-weighted persistent district offset)

where, using ONLY years before the target year Y:
    offset_d = mean_{j<Y} ( ln cost_dj - m_dj )      district's persistent gap
    Z_d      = n_d / ( n_d + sigma2_d / tau2 )        credibility in [0,1)
    n_d      = # prior years of the district's own history
    tau2     = between-district variance of persistent offsets   (the spread we
               saw: +0.48 vs -0.58 ...). Large.
    sigma2_d = that district's own year-to-year noise around its level, shrunk
               toward the panel mean. Small for steady systems -> high Z.

So credibility rises with history length (n_d) AND stability (low sigma2_d). A big
steady district (Seattle) earns Z near 1 and recovers almost its full +0.48; a
small volatile district keeps Z low and stays near the formula -- no overfitting.

The "collective" m_dY is a per-year cross-sectional OLS of ln(F-196 cost) on the
7 STARS inputs -- i.e. the STARS regression re-applied to cost. The offset uses
strictly prior years, so the correction is genuinely out-of-sample; only the two
global hyperparameters (tau2, panel sigma2) are read off the full panel.

Usage:
    python3 analysis/stars_credibility.py
    python3 analysis/stars_credibility.py --prior-strength 3 --min-prior 2
"""

import argparse
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


def fit_collectives(se, rows, years):
    """Per non-COVID year, cross-sectional OLS of ln(cost) on the 7 STARS inputs.
    Returns collective[year][ccddd] = (m_pred_lncost, actual_lncost, cost)."""
    collective = {}
    for sy in years:
        if sy in COVID:
            continue
        data = []
        for (s, ccddd) in [k for k in rows if k[0] == sy]:
            rec = rows[(s, ccddd)]
            x = se.design_row(rec)
            c = rec.get("cost")
            if x is None or c is None or c <= 0:
                continue
            data.append((ccddd, x, math.log(c), c))
        if len(data) < 25:
            continue
        X = sm.add_constant(np.array([d[1] for d in data]))
        y = np.array([d[2] for d in data])
        pred = sm.OLS(y, X).fit().predict(X)
        collective[sy] = {d[0]: (p, d[2], d[3]) for d, p in zip(data, pred)}
    return collective


def estimate_hyperparams(collective, years_order, prior_strength):
    """Bühlmann variance components from the full panel.
    Returns tau2 (between-district offset variance), sigma2_bar (mean within-
    district year-to-year variance), and per-district shrunk sigma2_d."""
    # residual series per district
    series = defaultdict(list)
    for sy in collective:
        for ccddd, (m, y, _c) in collective[sy].items():
            series[ccddd].append(y - m)
    offsets = {}
    within = {}
    for ccddd, r in series.items():
        if len(r) >= 1:
            offsets[ccddd] = float(np.mean(r))
        if len(r) >= 2:
            within[ccddd] = float(np.var(r, ddof=1))
    sigma2_bar = float(np.mean(list(within.values()))) if within else 0.05
    # between-district variance of persistent offsets, de-noised (subtract the
    # part of offset spread that is just averaging noise)
    om = np.array(list(offsets.values()))
    mean_n = np.mean([len(r) for r in series.values()])
    tau2 = max(float(np.var(om, ddof=1)) - sigma2_bar / mean_n, 1e-4)
    # per-district sigma2, shrunk toward sigma2_bar (prior_strength pseudo-obs)
    sigma2_d = {}
    for ccddd in series:
        n_obs = len(series[ccddd])
        s2 = within.get(ccddd, sigma2_bar)
        df = max(n_obs - 1, 0)
        sigma2_d[ccddd] = (prior_strength * sigma2_bar + df * s2) / (prior_strength + df)
    return tau2, sigma2_bar, sigma2_d


def backtest(se, rows, prior_strength, min_prior):
    years = sorted({k[0] for k in rows})
    collective = fit_collectives(se, rows, years)
    nc_years = [y for y in years if y in collective]           # non-COVID, has fit
    tau2, sigma2_bar, sigma2_d = estimate_hyperparams(collective, nc_years, prior_strength)

    records = []   # one per evaluated (district, target-year)
    for i, sy in enumerate(nc_years):
        prior_years = nc_years[:i]                              # strictly earlier
        for ccddd, (m, y_actual, cost) in collective[sy].items():
            prior_res = [collective[py][ccddd][1] - collective[py][ccddd][0]
                         for py in prior_years if ccddd in collective[py]]
            n_d = len(prior_res)
            if n_d < min_prior:
                continue
            offset = float(np.mean(prior_res))
            s2 = sigma2_d.get(ccddd, sigma2_bar)
            Z = n_d / (n_d + s2 / tau2)
            pred_formula = math.exp(m)
            pred_cred = math.exp(m + Z * offset)
            actual = cost
            records.append({
                "ccddd": ccddd, "year": sy, "Z": Z, "offset": offset, "n": n_d,
                "actual": actual,
                "ape_formula": abs(pred_formula - actual) / actual,
                "ape_cred": abs(pred_cred - actual) / actual,
            })
    return records, tau2, sigma2_bar


def pct(arr, q):
    return float(np.percentile(arr, q)) * 100


def report(records, tau2, sigma2_bar, rows):
    se_names = {}
    import csv
    with open("out_stars/stars_operations_allocation.csv") as f:
        for r in csv.DictReader(f):
            se_names[r["ccddd"]] = r["district"]

    print(f"\nBuhlmann hyperparameters:  tau^2 (between)={tau2:.4f}  "
          f"sigma^2 (within, panel)={sigma2_bar:.4f}  -> k=sigma^2/tau^2={sigma2_bar/tau2:.2f}")
    print(f"Implied credibility Z for a steady district: "
          f"n=2 -> {2/(2+sigma2_bar/tau2):.2f}, n=3 -> {3/(3+sigma2_bar/tau2):.2f}, "
          f"n=4 -> {4/(4+sigma2_bar/tau2):.2f}")
    print(f"Evaluated {len(records)} district-years (non-COVID targets, "
          f">= min-prior years of history).")

    def block(title, recs):
        if not recs:
            return
        f = np.array([r["ape_formula"] for r in recs])
        c = np.array([r["ape_cred"] for r in recs])
        win = np.mean(c < f) * 100
        print(f"\n{title}  (n={len(recs)})")
        print(f"  {'':16s} {'median APE':>11s} {'mean APE':>10s} {'90th pct':>10s} {'95th pct':>10s}")
        print(f"  {'formula only':16s} {np.median(f)*100:10.1f}% {np.mean(f)*100:9.1f}% "
              f"{pct(f,90):9.1f}% {pct(f,95):9.1f}%")
        print(f"  {'credibility':16s} {np.median(c)*100:10.1f}% {np.mean(c)*100:9.1f}% "
              f"{pct(c,90):9.1f}% {pct(c,95):9.1f}%")
        print(f"  credibility beats formula on {win:.0f}% of district-years")

    block("ALL evaluated district-years", records)

    # fat end: top 15 by mean actual cost among evaluated districts
    size = defaultdict(list)
    for r in records:
        size[r["ccddd"]].append(r["actual"])
    meansize = {c: np.mean(v) for c, v in size.items()}
    top = set(sorted(meansize, key=meansize.get, reverse=True)[:15])
    block("FAT END (top 15 districts by mean cost)",
          [r for r in records if r["ccddd"] in top])

    # SPS detail
    sps = [r for r in records if r["ccddd"] == "17001"]
    if sps:
        print("\nSeattle Public Schools (17001) per target year:")
        print(f"  {'year':10s} {'n':>2s} {'Z':>5s} {'offset':>7s} "
              f"{'formula APE':>12s} {'credibility APE':>16s}")
        for r in sorted(sps, key=lambda r: r["year"]):
            print(f"  {r['year']:10s} {r['n']:>2d} {r['Z']:5.2f} {r['offset']:+7.3f} "
                  f"{r['ape_formula']*100:11.1f}% {r['ape_cred']*100:15.1f}%")

    # which fat-end districts gain the most
    print("\nLargest fat-end corrections (mean APE: formula -> credibility):")
    by_d = defaultdict(list)
    for r in records:
        if r["ccddd"] in top:
            by_d[r["ccddd"]].append(r)
    rowsout = []
    for c, rs in by_d.items():
        mf = np.mean([r["ape_formula"] for r in rs]) * 100
        mc = np.mean([r["ape_cred"] for r in rs]) * 100
        rowsout.append((mf - mc, c, mf, mc, np.mean([r["Z"] for r in rs])))
    for gain, c, mf, mc, z in sorted(rowsout, reverse=True):
        print(f"  {se_names.get(c, c)[:32]:32s} Z={z:.2f}  {mf:5.1f}% -> {mc:5.1f}%  "
              f"(-{gain:.1f}pt)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--cost-csv", default="transit-expenditures.csv")
    ap.add_argument("--prior-strength", type=float, default=3.0,
                    help="pseudo-obs pulling per-district sigma^2 toward the panel mean")
    ap.add_argument("--min-prior", type=int, default=2,
                    help="minimum prior years of history required to evaluate a district")
    args = ap.parse_args()

    se = _se()
    rows, _pub, _raw = se.load(args.csv)
    if not os.path.exists(args.cost_csv):
        raise SystemExit(f"needs {args.cost_csv}")
    totals, _k, _d = se.load_costs(args.cost_csv)
    n = se.attach_costs(rows, totals, lag=0)
    print(f"Attached F-196 cost (ex obj 0/1/9) to {n} district-years.")

    records, tau2, sigma2_bar = backtest(se, rows, args.prior_strength, args.min_prior)
    report(records, tau2, sigma2_bar, rows)


if __name__ == "__main__":
    main()
