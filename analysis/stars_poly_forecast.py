#!/usr/bin/env python3
"""Per-district polynomial forecast of the transportation allocation, benchmarked
against the existing STARS cross-sectional formula.

Question: instead of OSPI's formula -- which each year regresses every district's
allocation on freshly-collected route/geography characteristics (land area,
ridership, programs, ...) -- could you predict a district's next-year allocation
just by extrapolating its OWN recent allocation history with a low-order
polynomial in time? And is that more or less accurate than STARS?

Setup for a target year Y and a window of k prior years:
  * POLYNOMIAL method: fit a degree-d polynomial to (year, D.8) over the k years
    Y-k .. Y-1 for that district, then evaluate it at Y. Uses ONLY that
    district's own allocation history -- no route data, no cross-district info.
        d = 1            -> linear trend (robust)
        d = min(k-1, 2)  -> "poly": quadratic once >= 3 points are available
  * STARS method: A.4 "initial/expected allocation" for year Y, i.e. the formula
    output already in the ledger. (Uses year-Y route characteristics + the
    regression coefficients.)
  * GROUND TRUTH: D.8 actual allocation amount for year Y.

Both are scored by absolute percentage error vs the same D.8 actual, on the SAME
set of district-years, so "more/less accurate" is a paired comparison. The
sample necessarily shrinks as k grows (need k prior years of history).

Usage:
    python3 analysis/stars_poly_forecast.py
    python3 analysis/stars_poly_forecast.py --target d8 --log
    python3 analysis/stars_poly_forecast.py --windows 2,3,4,5 --max-degree 2
"""

import argparse
import importlib.util
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
COVID_TARGET_YEARS = {2021, 2022}  # school years 2020-21, 2021-22


def load_series(stars_csv):
    """Return {ccddd: {class_of_int: {'d8':.., 'a4':..}}} via the exploration loader."""
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)
    rows, _published, _raw = se.load(stars_csv)
    series = defaultdict(dict)
    for (_sy, ccddd), rec in rows.items():
        co = rec.get("class_of")
        if co is None:
            continue
        series[ccddd][int(co)] = {"d8": rec.get("d8"), "a4": rec.get("a4")}
    return series


def poly_forecast(years, values, target_year, degree, log_space):
    """Fit a degree-`degree` polynomial through (years, values) and extrapolate to
    target_year. Years are centered for numerical stability. In log_space the fit
    is on ln(values) and the result is exponentiated."""
    x = np.array(years, dtype=float) - years[0]
    y = np.array(values, dtype=float)
    if log_space:
        if np.any(y <= 0):
            return None
        y = np.log(y)
    deg = min(degree, len(years) - 1)
    coeffs = np.polyfit(x, y, deg)
    pred = np.polyval(coeffs, target_year - years[0])
    if log_space:
        pred = np.exp(pred)
    return float(pred)


def ape(pred, actual):
    if pred is None or actual is None or actual <= 0:
        return None
    return abs(pred - actual) / actual


def evaluate(series, window, degree, target, log_space):
    """Collect paired (poly_ape, stars_ape) over every predictable district-year
    for the given window. Returns a list of dict records."""
    recs = []
    for ccddd, yrs in series.items():
        for Y in yrs:
            hist_years = list(range(Y - window, Y))
            if not all(h in yrs and yrs[h][target] is not None for h in hist_years):
                continue
            actual = yrs[Y]["d8"]
            stars_pred = yrs[Y]["a4"]
            if actual is None or stars_pred is None:
                continue
            hist_vals = [yrs[h][target] for h in hist_years]
            poly_pred = poly_forecast(hist_years, hist_vals, Y, degree, log_space)
            pa, sa = ape(poly_pred, actual), ape(stars_pred, actual)
            if pa is None or sa is None:
                continue
            recs.append({"ccddd": ccddd, "year": Y, "poly_ape": pa, "stars_ape": sa})
    return recs


def summarize(recs, drop_covid):
    if drop_covid:
        recs = [r for r in recs if r["year"] not in COVID_TARGET_YEARS]
    n = len(recs)
    if n == 0:
        return None
    poly = np.array([r["poly_ape"] for r in recs])
    stars = np.array([r["stars_ape"] for r in recs])
    win = np.mean(poly < stars)
    return {
        "n": n,
        "poly_med": np.median(poly) * 100,
        "poly_mean": np.mean(poly) * 100,
        "stars_med": np.median(stars) * 100,
        "stars_mean": np.mean(stars) * 100,
        "win_rate": win * 100,
    }


def run(series, windows, max_degree, target, log_space, drop_covid):
    label = "excluding COVID target years (2021,2022)" if drop_covid else "all target years"
    space = "log-space" if log_space else "level"
    print(f"\n=== Polynomial forecast vs STARS  [target={target.upper()}, "
          f"{space} fit, {label}] ===")
    print("APE = absolute % error vs D.8 actual. Win = % of district-years where "
          "polynomial beats STARS.\n")
    hdr = (f"{'window':>6} {'degree':>6} {'n':>5} "
           f"{'POLY medAPE':>12} {'POLY meanAPE':>13} "
           f"{'STARS medAPE':>13} {'STARS meanAPE':>14} {'POLY win%':>10}")
    print(hdr)
    print("-" * len(hdr))
    for k in windows:
        for deg in sorted({1, min(k - 1, max_degree)}):
            recs = evaluate(series, k, deg, target, log_space)
            s = summarize(recs, drop_covid)
            if s is None:
                continue
            tag = "linear" if deg == 1 else f"deg{deg}"
            print(f"{k:>6} {tag:>6} {s['n']:>5} "
                  f"{s['poly_med']:>11.1f}% {s['poly_mean']:>12.1f}% "
                  f"{s['stars_med']:>12.1f}% {s['stars_mean']:>13.1f}% "
                  f"{s['win_rate']:>9.1f}%")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stars-csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--windows", default="2,3,4,5",
                    help="comma-sep prior-year window sizes (default 2,3,4,5)")
    ap.add_argument("--max-degree", type=int, default=2,
                    help="cap polynomial degree (default 2 = quadratic)")
    ap.add_argument("--target", default="d8", choices=["d8", "a4"],
                    help="history series to extrapolate (default d8 actual allocation)")
    ap.add_argument("--log", action="store_true",
                    help="fit in log space (multiplicative trend)")
    args = ap.parse_args()

    series = load_series(args.stars_csv)
    windows = [int(w) for w in args.windows.split(",") if w]
    print(f"Loaded {len(series)} districts, "
          f"{sum(len(v) for v in series.values())} district-years.")

    # Report both with and without the COVID-distorted target years.
    for drop in (False, True):
        run(series, windows, args.max_degree, args.target, args.log, drop)


if __name__ == "__main__":
    main()
