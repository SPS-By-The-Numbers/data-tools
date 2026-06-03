#!/usr/bin/env python3
"""Add a rural/urban indicator to the STARS model and test input interactions.

Rather than asking whether ruralness adds a little signal (it didn't, as a single
density term), this asks the structural question: do rural and urban districts
have DIFFERENT cost structures? We split districts into rural vs urban, add the
dummy as a main effect, and interact it with each continuous input so every
slope (elasticity) is free to differ between the two groups:

    ln(cost) = [7 base STARS predictors]
             + rural
             + rural * ln(land_area)
             + rural * average_distance
             + rural * destinations
             + rural * ln(basic_program)
             + rural * ln(special_program)

The key statistic is a joint F-test of the whole added block (dummy + 5
interactions) against the base model, per year: if it's significant, the
rural/urban distinction genuinely reshapes how inputs map to cost.

Rural/urban split (data-driven, no external locale codes available):
  density = basic_program / land_area (students per sq mi). Within each year,
  districts below the chosen quantile of density are 'rural' (low density). The
  split is per-year so it stays balanced as the panel changes. Threshold is
  configurable; --split inverse uses land_area/basic_program instead.

Dependent: F-196 reported cost (default; the real target). dep=a4 is a negative
control -- the formula output has no rural structure, so the block should be ~0.

Usage:
    python3 analysis/stars_rural_interaction.py
    python3 analysis/stars_rural_interaction.py --quantile 0.33 --dep cost
    python3 analysis/stars_rural_interaction.py --dep a4         # negative control
"""

import argparse
import importlib.util
import math
import os

import numpy as np
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
COVID = {"2020-2021", "2021-2022"}
# continuous inputs whose slope we let vary by rural/urban (transformed as in base)
INTERACT = ["land_area", "average_distance", "destinations",
            "basic_program", "special_program"]


def _se():
    spec = importlib.util.spec_from_file_location(
        "stars_exploration", os.path.join(HERE, "stars_exploration.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def density(rec, split):
    area = rec.get("land_area")
    basic = rec.get("basic_program")
    if area is None or area <= 0 or basic is None or basic <= 0:
        return None
    return area / basic if split == "inverse" else basic / area


def year_design(se, rows, sy, dep, quantile, split):
    """Build base X, extended X (with rural dummy + interactions), y, and the
    transformed-feature index map for one year. Returns None if too few rows."""
    # collect usable records and their density
    recs = []
    for k in [k for k in rows if k[0] == sy]:
        rec = rows[k]
        base = se.design_row(rec)
        d = density(rec, split)
        yv = rec.get(dep)
        if base is None or d is None or yv is None or yv <= 0:
            continue
        recs.append((base, d, math.log(yv)))
    if len(recs) < 30:
        return None
    dens = np.array([r[1] for r in recs])
    cut = np.quantile(dens, quantile)
    # 'rural' = low density (for inverse split, high value = rural, so flip)
    if split == "inverse":
        cut = np.quantile(dens, 1 - quantile)
        rural = (dens >= cut).astype(float)
    else:
        rural = (dens < cut).astype(float)

    idx = {c: i for i, c in enumerate(se.PRED_CODES)}
    Xb, Xe = [], []
    for (base, _d, _y), R in zip(recs, rural):
        Xb.append(base)
        inter = [R * base[idx[c]] for c in INTERACT]
        Xe.append(base + [R] + inter)
    y = np.array([r[2] for r in recs])
    return np.array(Xb), np.array(Xe), y, int(rural.sum()), len(recs)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="out_stars/stars_operations_allocation.csv")
    ap.add_argument("--cost-csv", default="transit-expenditures.csv")
    ap.add_argument("--dep", default="cost", choices=["cost", "a4", "d8", "d4"])
    ap.add_argument("--quantile", type=float, default=0.5,
                    help="density quantile cut for rural (default 0.5 = median split)")
    ap.add_argument("--split", default="density", choices=["density", "inverse"])
    ap.add_argument("--detail-year", default="2018-2019",
                    help="year to print the full interaction breakdown for")
    args = ap.parse_args()

    se = _se()
    rows, _pub, _raw = se.load(args.csv)
    if args.dep == "cost":
        if not os.path.exists(args.cost_csv):
            raise SystemExit(f"--dep cost needs {args.cost_csv}")
        totals, _k, _d = se.load_costs(args.cost_csv)
        n = se.attach_costs(rows, totals, lag=0)
        print(f"Attached F-196 cost (ex obj 0/1/9) to {n} district-years.")

    print(f"\nRural = bottom {args.quantile:.0%} by density "
          f"({'land_area/basic' if args.split=='inverse' else 'basic/land_area'}), "
          f"per-year split. dep={args.dep}.")
    print("Joint F-test: rural dummy + 5 slope interactions vs base model.\n")
    print(f"{'year':10s} {'n':>4s} {'rural':>5s} {'R2 base':>8s} {'R2 ext':>8s} "
          f"{'dR2':>7s} {'F(6)':>7s} {'p':>8s} {'sig':>4s}")
    years = sorted({k[0] for k in rows})
    sig = tested = 0
    for sy in years:
        if sy in COVID:
            continue
        built = year_design(se, rows, sy, args.dep, args.quantile, args.split)
        if built is None:
            continue
        Xb, Xe, y, nr, n = built
        rb = sm.OLS(y, sm.add_constant(Xb)).fit()
        re = sm.OLS(y, sm.add_constant(Xe)).fit()
        F, p, _df = re.compare_f_test(rb)
        tested += 1
        s = "***" if p < 0.01 else ("**" if p < 0.05 else ("*" if p < 0.10 else ""))
        if p < 0.05:
            sig += 1
        print(f"{sy:10s} {n:4d} {nr:5d} {rb.rsquared:8.4f} {re.rsquared:8.4f} "
              f"{re.rsquared-rb.rsquared:7.4f} {F:7.2f} {p:8.4f} {s:>4s}")
    print(f"\n  interaction block jointly significant (p<0.05): {sig}/{tested} years")

    # full breakdown for one representative year
    built = year_design(se, rows, args.detail_year, args.dep, args.quantile, args.split)
    if built is not None:
        Xb, Xe, y, nr, n = built
        re = sm.OLS(y, sm.add_constant(Xe)).fit()
        names = (["const"] + se.PRED_CODES + ["rural"]
                 + [f"rural*{c}" for c in INTERACT])
        print(f"\nFull extended model, {args.detail_year} (n={n}, rural={nr}, "
              f"R2={re.rsquared:.4f}):")
        print(f"{'term':22s} {'coef':>11s} {'t':>7s} {'p':>7s}")
        for nm, b, t, p in zip(names, re.params, re.tvalues, re.pvalues):
            star = "*" if p < 0.05 else " "
            print(f"{nm:22s} {b:11.4f} {t:7.2f} {p:7.3f}{star}")


if __name__ == "__main__":
    main()
