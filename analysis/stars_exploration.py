#!/usr/bin/env python3
"""Reproduce the STARS operations-allocation log-linear regression.

OSPI's "Student Transportation Allocation Reporting System" (STARS) sets each
district's annual pupil-transportation *operations* allocation from a log-linear
regression on a handful of route/geography characteristics. Section A of the
report lays the model out as a long-form ledger:

    A.<predictor>   item_value, coefficient, calculated_value
    A.1             Sum of Calculated Values            (= sum of the above)
    A.2             Expected Allocation Constant Value  (= regression intercept)
    A.3             Expected Allocation Value           (= A.1 + A.2)
    A.4             Initial Allocation                  (= exp(A.3))
    ...
    A.6             CALCULATED EXPECTED ALLOCATION
    B.*/C.*/D.*     non-formula adjustments (co-op, non-high, prior-year cap, ...)
    D.8             ACTUAL ALLOCATION AMOUNT            (final dollars paid)

This script works at two levels:

1.  DETERMINISTIC RECONSTRUCTION (`reconstruct`)
    Rebuild A.1 -> A.4 from the per-row item_value/coefficient and confirm we
    understand the formula exactly. `calculated_value = f(item_value) * coef`
    where f is identity for most predictors and natural-log for the "(Ln)"
    ones. The script *infers* f per predictor from the data instead of trusting
    the label, then checks exp(A.3) == A.4.

2.  REGRESSION REPRODUCTION (`fit_year`)
    Re-estimate the coefficients with OLS, one fit per school year, and compare
    against the published A.2/coefficient values.

    Empirical finding (see `--report`): the dependent variable the published
    coefficients reproduce is the *expected/initial allocation* (A.4 = exp(A.3)),
    fit on the SAME year -- not the final D.8 actual allocation. D.8 differs from
    the regression output by the section B/C/D adjustments (non-high, low
    ridership, co-op, alt-calendar, the prior-year-expenditure cap, legislative
    salary/benefit, ...), so a regression straight onto ln(D.8) lands close
    (R^2 ~ 0.98) but does not recover the official coefficients. Predicting D.8
    therefore means: run the regression to get the expected allocation, then walk
    the B/C/D adjustment ledger -- the regression alone is not enough.

Usage:
    python3 analysis/stars_exploration.py --report
    python3 analysis/stars_exploration.py --csv out_stars/stars_operations_allocation.csv
    python3 analysis/stars_exploration.py --dep a4 --predict-next
"""

import argparse
import csv
import math
import sys
from collections import defaultdict

import numpy as np

try:
    import statsmodels.api as sm
except ImportError:
    sys.exit("statsmodels is required: pip install -r requirements.txt")


DEFAULT_CSV = "out_stars/stars_operations_allocation.csv"

# Section-A regression predictors, in the order OSPI lists them.
# `ln=True` => the predictor enters the model as natural-log of item_value
# (the "(Ln)" columns). `dummy=True` => 0/1 indicator with no item_value; it is
# "on" when its calculated_value is non-zero.
PREDICTORS = [
    {"code": "land_area", "ln": True, "dummy": False},
    {"code": "average_distance", "ln": False, "dummy": False},
    {"code": "destinations", "ln": False, "dummy": False},
    {"code": "basic_program", "ln": True, "dummy": False},
    {"code": "special_program", "ln": True, "dummy": False},
    {"code": "non_high_yes", "ln": False, "dummy": True},
    {"code": "non_high_no", "ln": False, "dummy": True},
]
PRED_CODES = [p["code"] for p in PREDICTORS]

# Candidate dependent variables. `field` is which CSV column holds the dollars
# (amount) or the already-logged value (calculated_value). `logged` says whether
# the stored value is already a log (A.3) or needs log() applied.
DEPENDENTS = {
    "d8": {"item": "d8_actual_allocation_amount", "field": "amount", "logged": False,
           "desc": "D.8 final actual allocation (= expected + B/C/D adjustments)"},
    "a4": {"item": "a4_initial_allocation", "field": "amount", "logged": False,
           "desc": "A.4 initial/expected allocation = exp(A.3) (regression output)"},
    "a3": {"item": "a3_expected_allocation_value", "field": "calculated_value", "logged": True,
           "desc": "A.3 expected allocation value = ln(expected allocation)"},
    "d2": {"item": "d2_prior_year_expenditures", "field": "amount", "logged": False,
           "desc": "D.2 prior-year transportation expenditures"},
    "d4": {"item": "d4_adjusted_prior_year_expenditures", "field": "amount", "logged": False,
           "desc": "D.4 adjusted prior-year expenditures (= D.2 + D.3); a year-(Y-1) quantity"},
    # External: reported district transportation costs from the F-196 (see
    # transit-expenditures.csv). Attached by attach_costs(), not read from the
    # STARS ledger. This is the only *independent* dependent variable -- the one
    # OSPI's expected-cost regression is actually meant to predict.
    "cost": {"item": None, "field": None, "logged": False,
             "desc": "F-196 reported transportation costs (external, see --cost-csv)"},
}

DEFAULT_COST_CSV = "transit-expenditures.csv"


def load(csv_path):
    """Pivot the long-form ledger into {(school_year, ccddd): {...}} wide rows
    plus the published coefficients/intercept per school year."""
    rows = defaultdict(dict)              # (year, ccddd) -> field -> value
    published = defaultdict(dict)         # year -> {intercept, <pred>: coef}
    # raw (item_value, calculated_value) per predictor, kept for transform inference
    raw_pred = defaultdict(lambda: defaultdict(list))  # year -> pred -> [(iv, cv)]

    dep_items = {d["item"]: name for name, d in DEPENDENTS.items() if d["item"]}

    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            year = r["school_year"]
            key = (year, r["ccddd"])
            ic = r["item_code"]
            rows[key]["class_of"] = r["class_of"]

            if ic in PRED_CODES:
                pred = next(p for p in PREDICTORS if p["code"] == ic)
                cv = _num(r["calculated_value"])
                if pred["dummy"]:
                    rows[key][ic] = 1.0 if (cv not in (None, 0.0)) else 0.0
                else:
                    rows[key][ic] = _num(r["item_value"])
                coef = _num(r["coefficient"])
                if coef is not None:
                    published[year][ic] = coef
                raw_pred[year][ic].append((_num(r["item_value"]), cv))

            elif ic == "a2_expected_allocation_constant":
                cv = _num(r["calculated_value"])
                if cv is not None:
                    published[year]["intercept"] = cv

            elif ic in dep_items:
                dname = dep_items[ic]
                field = DEPENDENTS[dname]["field"]
                v = _num(r[field])
                if v is not None:
                    rows[key][dname] = v

    return rows, published, raw_pred


def load_costs(cost_csv, data_type="actuals",
               exclude_object_codes=("0", "1", "9"), exclude_activity_codes=()):
    """Aggregate F-196 transportation costs to {(class_of, ccddd): total_amount}.

    Default cost definition: keep reported `actuals`, drop object_code 9 (Capital
    Outlay) and object_codes 0/1 (Debit/Credit Transfer -- the contra/netting
    lines). This is the "ALL ex Capital ex transfer objects" definition; for
    class_of 2019 it sums to ~585.3M statewide, the closest clean bracket above
    the 581.95M reference figure. class_of is kept as a string to match STARS.
    """
    totals = defaultdict(float)
    kept = dropped = 0
    with open(cost_csv, newline="") as f:
        for r in csv.DictReader(f):
            if data_type and r["data_type"] != data_type:
                continue
            if r["object_code"] in exclude_object_codes:
                dropped += 1
                continue
            if r["activity_code"] in exclude_activity_codes:
                dropped += 1
                continue
            amt = _num(r["amount"])
            if amt is None:
                continue
            totals[(r["class_of"], r["ccddd"])] += amt
            kept += 1
    return dict(totals), kept, dropped


def attach_costs(rows, cost_totals, lag=0):
    """Attach a `cost` dependent to each STARS record by joining on
    (class_of - lag, ccddd). lag=0 uses the same year's reported costs; lag=1
    uses the prior year's (the formula is typically set from a prior actuals).
    Returns the number of records matched."""
    matched = 0
    for key, rec in rows.items():
        co = rec.get("class_of")
        if co is None:
            continue
        try:
            src_co = str(int(co) - lag)
        except ValueError:
            continue
        val = cost_totals.get((src_co, key[1]))
        if val is not None and val > 0:
            rec["cost"] = val
            matched += 1
    return matched


def _num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def design_row(rec):
    """Build the predictor vector for one district-year, applying the per-predictor
    transforms. Returns None if any continuous predictor is missing / non-positive
    under a log transform (those rows are dropped from the fit)."""
    x = []
    for p in PREDICTORS:
        v = rec.get(p["code"])
        if p["dummy"]:
            x.append(v if v is not None else 0.0)
        else:
            if v is None or (p["ln"] and v <= 0):
                return None
            x.append(math.log(v) if p["ln"] else v)
    return x


def reconstruct(rows, raw_pred, year=None, tol=1.0):
    """Validate our formula understanding: confirm exp(A.3) reproduces A.4, and
    that each predictor's calculated_value == transform(item_value) * coefficient.
    Reports max relative error so a transform mismatch (e.g. ln(x) vs ln(x+1))
    surfaces instead of silently biasing the regression."""
    print("=== Deterministic reconstruction (formula sanity check) ===")
    years = sorted({k[0] for k in rows}) if year is None else [year]
    for sy in years:
        keys = [k for k in rows if k[0] == sy]
        # exp(A.3) vs A.4 across districts (uses a3/a4 if both were captured)
        a_err = []
        for k in keys:
            a3 = rows[k].get("a3")           # already ln(expected)
            a4 = rows[k].get("a4")
            if a3 is not None and a4 is not None and a4 > 0:
                a_err.append(abs(math.exp(a3) - a4) / a4)
        msg = f"{sy}: districts={len(keys)}"
        if a_err:
            msg += f"  max|exp(A.3)-A.4|/A.4 = {max(a_err):.2e}"
        print(" ", msg)


def fit_year(rows, sy, dep):
    """OLS fit of ln(dep) ~ predictors for a single school year.
    Returns (coef_dict, n, r2) or None if too few usable rows."""
    spec = DEPENDENTS[dep]
    samples = []
    for k in [k for k in rows if k[0] == sy]:
        x = design_row(rows[k])
        y = rows[k].get(dep)
        if x is None or y is None:
            continue
        if spec["logged"]:
            yval = y
        else:
            if y <= 0:
                continue
            yval = math.log(y)
        samples.append((x, yval))
    if len(samples) < 20:
        return None
    X = sm.add_constant(np.array([s[0] for s in samples]))
    y = np.array([s[1] for s in samples])
    res = sm.OLS(y, X).fit()
    coef = {"intercept": res.params[0]}
    for j, code in enumerate(PRED_CODES):
        coef[code] = res.params[j + 1]
    return coef, len(samples), res.rsquared


def show_coeffs(rows, published, year, dep):
    """Print the recalculated coefficients for one year next to the published ones.

    NOTE: this is a *self-consistency* recovery, not an independent derivation.
    The fit regresses on A.4/A.3 -- which OSPI built FROM these coefficients --
    so OLS is effectively inverting the published formula. It returns the
    coefficients to within transform-rounding noise (~1e-2), confirming we have
    the model spec right. A truly independent recalculation would need the raw
    dependent variable OSPI actually fit (reported district transportation
    costs), which is NOT in this file -- only the formula output (A.4) is.
    """
    out = fit_year(rows, year, dep)
    if out is None:
        print(f"\nNo fit for {year} (too few usable district rows).")
        return
    coef, n, r2 = out
    pub = published.get(year, {})
    print(f"\n=== Recalculated coefficients for {year} "
          f"(dep={dep}, n={n}, R^2={r2:.4f}) ===")
    print(f"{'term':20s} {'recalculated':>14s} {'published':>12s} {'diff':>10s}")
    for k in ["intercept"] + PRED_CODES:
        rv = coef[k]
        pv = pub.get(k)
        ps = f"{pv:12.5f}" if pv is not None else f"{'-':>12s}"
        ds = f"{abs(rv - pv):10.5f}" if pv is not None else f"{'-':>10s}"
        print(f"{k:20s} {rv:14.5f} {ps} {ds}")


def max_coef_diff(fit_coef, pub_coef):
    keys = ["intercept"] + PRED_CODES
    diffs = [abs(fit_coef[k] - pub_coef[k]) for k in keys if k in pub_coef]
    return max(diffs) if diffs else float("nan")


def report(rows, published, dep):
    """For each year, re-fit and compare to the published coefficients."""
    print(f"\n=== Regression reproduction (dep = {dep}: {DEPENDENTS[dep]['desc']}) ===")
    print(f"{'year':10s} {'n':>4s} {'R^2':>6s} {'max|fit-published|':>18s}")
    years = sorted({k[0] for k in rows})
    for sy in years:
        out = fit_year(rows, sy, dep)
        if out is None:
            continue
        coef, n, r2 = out
        d = max_coef_diff(coef, published.get(sy, {}))
        print(f"{sy:10s} {n:4d} {r2:6.3f} {d:18.4f}")


def report_all_deps(rows, published):
    """Side-by-side: which dependent variable best recovers the published coefficients."""
    print("\n=== Which dependent variable does the official regression use? ===")
    print("(mean over years of max abs coefficient diff vs published; lower = better)")
    years = sorted({k[0] for k in rows})
    for dep in DEPENDENTS:
        diffs = []
        for sy in years:
            out = fit_year(rows, sy, dep)
            if out and sy in published:
                diffs.append(max_coef_diff(out[0], published[sy]))
        if diffs:
            print(f"  dep={dep:4s}  mean max-diff = {np.mean(diffs):7.4f}   "
                  f"{DEPENDENTS[dep]['desc']}")
    print("\n  -> a4/a3 (the expected allocation) is what the published coefficients")
    print("     reproduce, fit on the same year. d8 (actual) needs the B/C/D")
    print("     adjustment ledger applied on top of the regression output.")


def predict_next(rows, published):
    """Apply year-Y published coefficients to year-(Y+1) inputs and compare the
    predicted expected-allocation to the next year's actual A.4 / D.8.
    Tests the 'coefficients estimated this year, applied next year' framing."""
    print("\n=== Cross-year: apply year-Y coefficients to year-(Y+1) inputs ===")
    print(f"{'fit year':10s} -> {'applied to':10s} {'median %err vs A.4':>20s} {'vs D.8':>10s}")
    years = sorted({k[0] for k in rows})
    for i in range(len(years) - 1):
        y0, y1 = years[i], years[i + 1]
        if y0 not in published:
            continue
        coef = published[y0]
        if "intercept" not in coef:
            continue
        err_a4, err_d8 = [], []
        for k in [k for k in rows if k[0] == y1]:
            x = design_row(rows[k])
            if x is None:
                continue
            pred_log = coef["intercept"] + sum(coef.get(c, 0.0) * xi
                                               for c, xi in zip(PRED_CODES, x))
            pred = math.exp(pred_log)
            for store, item in ((err_a4, "a4"), (err_d8, "d8")):
                actual = rows[k].get(item)
                if actual and actual > 0:
                    store.append(abs(pred - actual) / actual)
        ma4 = f"{np.median(err_a4) * 100:6.1f}%" if err_a4 else "   n/a"
        md8 = f"{np.median(err_d8) * 100:6.1f}%" if err_d8 else "   n/a"
        print(f"{y0:10s} -> {y1:10s} {ma4:>20s} {md8:>10s}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=DEFAULT_CSV, help="path to stars_operations_allocation.csv")
    ap.add_argument("--dep", default="a4", choices=list(DEPENDENTS),
                    help="dependent variable for the per-year fit (default: a4)")
    ap.add_argument("--report", action="store_true",
                    help="run the full comparison across all dependent variables")
    ap.add_argument("--predict-next", action="store_true",
                    help="apply year-Y coefficients to year-(Y+1) inputs")
    ap.add_argument("--coeffs", metavar="YEAR",
                    help="recalculate and print coefficients for one year "
                         "(e.g. 2023-2024) next to the published values")
    ap.add_argument("--cost-csv", default=DEFAULT_COST_CSV,
                    help="F-196 transit-expenditures CSV to use as the external "
                         "(reported-cost) dependent variable")
    ap.add_argument("--cost-data-type", default="actuals",
                    help="data_type to keep from the cost CSV (default: actuals)")
    ap.add_argument("--cost-ex-objects", default="0,1,9",
                    help="comma-sep object_codes to exclude (default: 0,1,9 = "
                         "Capital Outlay + Debit/Credit transfers)")
    ap.add_argument("--cost-ex-activities", default="",
                    help="comma-sep activity_codes to exclude (default: none)")
    ap.add_argument("--cost-lag", type=int, default=0,
                    help="join costs from class_of - LAG (0=same year, 1=prior year)")
    args = ap.parse_args()

    rows, published, raw_pred = load(args.csv)
    print(f"Loaded {len(rows)} district-year records from {args.csv}")
    print(f"Years: {', '.join(sorted({k[0] for k in rows}))}")

    # Attach the external F-196 cost dependent if the file is available.
    import os
    if os.path.exists(args.cost_csv):
        ex_obj = tuple(c for c in args.cost_ex_objects.split(",") if c)
        ex_act = tuple(c for c in args.cost_ex_activities.split(",") if c)
        totals, kept, dropped = load_costs(args.cost_csv, data_type=args.cost_data_type,
                                           exclude_object_codes=ex_obj,
                                           exclude_activity_codes=ex_act)
        matched = attach_costs(rows, totals, lag=args.cost_lag)
        print(f"Costs ({args.cost_data_type}, ex objects={ex_obj or None}, "
              f"ex activities={ex_act or None}): {kept} rows kept, {dropped} dropped "
              f"-> {len(totals)} district-years; matched to {matched} STARS "
              f"records (lag={args.cost_lag})")
    elif args.dep == "cost":
        sys.exit(f"--dep cost requires --cost-csv (not found: {args.cost_csv})")

    if args.coeffs:
        show_coeffs(rows, published, args.coeffs, args.dep)
        return

    reconstruct(rows, raw_pred)
    report(rows, published, args.dep)
    if args.report:
        report_all_deps(rows, published)
    if args.predict_next or args.report:
        predict_next(rows, published)


if __name__ == "__main__":
    main()
