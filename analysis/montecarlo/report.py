"""Stage 11: report — summarize a saved MC run into deltas with CIs + equity cuts.

Consumes the tables Stage 10 (simulate.py) saves under simulate/<scenario>/ and
produces the human-facing summary:

  * district rider + estimated-route deltas per program, with 95% CIs
    (percentile intervals over the paired draws);
  * rider-weighted distance-to-school distribution (basic program):
    mean / p50 / p90 baseline vs scenario, CI on the deltas;
  * per-school movers: mean rider delta + CI, est-route delta, school names;
  * equity cuts (basic program): per-draw rider-delta sums grouped by
      - school low-income share (RC 2024-25 enrollment), terciles over the
        schools in the run;
      - ES attendance-area poverty (the `poverty` attribute on
        parse_shapes.load_attendance_es), terciles — neighborhood ES schools
        only (option/K-8 sites have no attendance area → "no ES area" group).

Routes are derived from riders via the district riders-per-route by program
(Stage 8 convention), so route deltas inherit the rider CIs.

Run:   python3 -m analysis.montecarlo.report <scenario> [--save] [--top N]
       python3 -m analysis.montecarlo.report              # list saved runs

--save writes the same text to simulate/<scenario>/report.txt.

API:
  report(name, top=..., save=...) → str (the report text)
  district_summary(run) / school_summary(run) / equity_cuts(run) → DataFrames
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.montecarlo import parse_shapes
from analysis.montecarlo import ridership as rid
from analysis.montecarlo import simulate as sim
from analysis.montecarlo.school_directory import load_schools

CI_LO, CI_HI = 0.025, 0.975


def _ci(s: pd.Series) -> tuple[float, float]:
    return float(s.quantile(CI_LO)), float(s.quantile(CI_HI))


def _fmt_ci(s: pd.Series, fmt: str = "+.1f") -> str:
    lo, hi = _ci(s)
    return f"{s.mean():{fmt}} [{lo:{fmt}}, {hi:{fmt}}]"


# ---------------------------------------------------------------------------
# Summary tables
# ---------------------------------------------------------------------------

def district_summary(run: dict) -> pd.DataFrame:
    """Per program: mean base/scen riders + delta stats and route deltas."""
    tgt = rid.district_targets()
    rpr = {"basic": tgt["on_bus"] / tgt["routes_basic"],
           "gifted": tgt["gifted"] / tgt["routes_gifted"]}
    rows = []
    for prog, d in run["district"].groupby("program"):
        lo, hi = _ci(d["d_riders"])
        rows.append({
            "program": prog,
            "base_riders": d["base_riders"].mean(),
            "scen_riders": d["scen_riders"].mean(),
            "d_riders_mean": d["d_riders"].mean(),
            "d_riders_lo": lo, "d_riders_hi": hi,
            "d_routes_mean": d["d_riders"].mean() / rpr[prog],
            "d_routes_lo": lo / rpr[prog], "d_routes_hi": hi / rpr[prog],
        })
    return pd.DataFrame(rows)


def school_summary(run: dict) -> pd.DataFrame:
    """Per school × program: mean rider delta + CI, sorted by delta."""
    sc = run["school"].copy()
    sc["d_riders"] = sc["scen_riders"] - sc["base_riders"]
    g = sc.groupby(["school_id", "program"])
    out = g.agg(base_riders=("base_riders", "mean"),
                scen_riders=("scen_riders", "mean"),
                d_mean=("d_riders", "mean"),
                d_lo=("d_riders", lambda s: s.quantile(CI_LO)),
                d_hi=("d_riders", lambda s: s.quantile(CI_HI))).reset_index()
    tgt = rid.district_targets()
    rpr = {"basic": tgt["on_bus"] / tgt["routes_basic"],
           "gifted": tgt["gifted"] / tgt["routes_gifted"]}
    out["d_routes_mean"] = out["d_mean"] / out["program"].map(rpr)
    names = load_schools().set_index("school_id")["name"]
    out["name"] = out["school_id"].map(names).fillna("?")
    return out.sort_values("d_mean")


def _school_groups() -> pd.DataFrame:
    """Per school: low-income tercile + ES-area poverty tercile labels."""
    cov = rid.school_covariates()[["low_income_frac"]].copy()

    def terciles(s: pd.Series, unit: str) -> pd.Series:
        edges = s.quantile([0, 1 / 3, 2 / 3, 1]).to_numpy()
        labels = [f"low (≤{edges[1]:{unit}})",
                  f"mid ({edges[1]:{unit}}–{edges[2]:{unit}})",
                  f"high (>{edges[2]:{unit}})"]
        return pd.cut(s, bins=edges, labels=labels, include_lowest=True)

    cov["li_group"] = terciles(cov["low_income_frac"], ".0%")
    att = parse_shapes.load_attendance_es()
    pov = att.set_index(att.school_id.astype(int))["poverty"]
    cov["es_poverty"] = pov.reindex(cov.index)
    has = cov["es_poverty"].notna()
    cov.loc[has, "pov_group"] = terciles(cov.loc[has, "es_poverty"], ".0f").astype(str)
    cov["pov_group"] = cov["pov_group"].fillna("(no ES area)")
    return cov


def equity_cuts(run: dict) -> dict[str, pd.DataFrame]:
    """Basic-program rider deltas summed per group per draw → mean + CI.

    Returns {'low_income': df, 'es_poverty': df}; each df has one row per
    group with n_schools, base_riders, d_mean, d_lo, d_hi.
    """
    sc = run["school"].copy()
    sc = sc[sc.program == "basic"]
    sc["d_riders"] = sc["scen_riders"] - sc["base_riders"]
    groups = _school_groups()
    sc = sc.merge(groups, left_on="school_id", right_index=True, how="left")

    out = {}
    for key, col in (("low_income", "li_group"), ("es_poverty", "pov_group")):
        sc[col] = sc[col].astype(str).replace("nan", "(no data)")
        per_draw = sc.groupby(["draw", col], observed=True).agg(
            d=("d_riders", "sum"), base=("base_riders", "sum")).reset_index()
        g = per_draw.groupby(col, observed=True)
        df = g.agg(base_riders=("base", "mean"),
                   d_mean=("d", "mean"),
                   d_lo=("d", lambda s: s.quantile(CI_LO)),
                   d_hi=("d", lambda s: s.quantile(CI_HI))).reset_index()
        df["n_schools"] = df[col].map(
            sc.groupby(col, observed=True)["school_id"].nunique())
        df = df.rename(columns={col: "group"})
        order = {"low": 0, "mid": 1, "hig": 2}
        df = df.sort_values("group", key=lambda s: s.str[:3].map(order).fillna(9))
        out[key] = df.reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def report(name: str, top: int = 10, save: bool = False) -> str:
    run = sim.load_run(name)
    meta = run["meta"]
    buf = io.StringIO()
    w = buf.write

    w(f"=== MC report: {meta['scenario']} "
      f"({meta['n_draws']} draws, seed {meta['seed']}) ===\n")
    if meta.get("description"):
        w(f"  {meta['description']}\n")
    flags = []
    if not meta.get("sample_theta", True):
        flags.append("θ FIXED")
    if not meta.get("sample_pop", True):
        flags.append("population FIXED")
    if flags:
        w(f"  [{', '.join(flags)}]\n")

    w("\nDistrict (riders are means over draws; deltas show 95% CI):\n")
    for _, r in district_summary(run).iterrows():
        w(f"  {r['program']:6s}: riders {r['base_riders']:9,.1f} → "
          f"{r['scen_riders']:9,.1f}   Δ {r['d_riders_mean']:+7.1f} "
          f"[{r['d_riders_lo']:+.1f}, {r['d_riders_hi']:+.1f}]"
          f"   est routes Δ {r['d_routes_mean']:+5.2f} "
          f"[{r['d_routes_lo']:+.2f}, {r['d_routes_hi']:+.2f}]\n")

    d = run["district"]
    db = d[d.program == "basic"]
    if "base_dist_mean" in db.columns and db["base_dist_mean"].notna().any():
        w("\nRider-weighted distance to school (basic, miles):\n")
        for stat in ("dist_mean", "dist_p50", "dist_p90"):
            delta = db[f"scen_{stat}"] - db[f"base_{stat}"]
            w(f"  {stat[5:]:>5s}: {db[f'base_{stat}'].mean():5.2f} → "
              f"{db[f'scen_{stat}'].mean():5.2f}   Δ {_fmt_ci(delta, '+.3f')}\n")

    ss = school_summary(run)
    movers = ss[ss["d_mean"].abs() > 0.5]
    w(f"\nPer-school movers (|mean Δriders| > 0.5): {len(movers)}\n")
    shown = pd.concat([movers.head(top), movers.tail(top)]).drop_duplicates("school_id")
    for _, r in shown.iterrows():
        w(f"  {r['name']:24.24s} {r['program']:6s} "
          f"{r['base_riders']:7.1f} → {r['scen_riders']:7.1f}   "
          f"Δ {r['d_mean']:+7.1f} [{r['d_lo']:+.1f}, {r['d_hi']:+.1f}]"
          f"   routes Δ {r['d_routes_mean']:+5.2f}\n")

    cuts = equity_cuts(run)
    w("\nEquity cuts (basic program; Δriders summed per group per draw):\n")
    w("  by school low-income share (RC 2024-25 terciles):\n")
    for _, r in cuts["low_income"].iterrows():
        w(f"    {r['group']:22s} ({int(r['n_schools']):3d} schools, "
          f"{r['base_riders']:7,.0f} base riders)  "
          f"Δ {r['d_mean']:+7.1f} [{r['d_lo']:+.1f}, {r['d_hi']:+.1f}]\n")
    w("  by ES attendance-area poverty %% (terciles; neighborhood ES only):\n"
      .replace("%%", "%"))
    for _, r in cuts["es_poverty"].iterrows():
        w(f"    {r['group']:22s} ({int(r['n_schools']):3d} schools, "
          f"{r['base_riders']:7,.0f} base riders)  "
          f"Δ {r['d_mean']:+7.1f} [{r['d_lo']:+.1f}, {r['d_hi']:+.1f}]\n")

    text = buf.getvalue()
    if save:
        out = sim.OUT_DIR / name / "report.txt"
        out.write_text(text)
        text += f"\nWrote {out}\n"
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 11: MC run report")
    parser.add_argument("scenario", nargs="?", help="saved run name (simulate/<name>/)")
    parser.add_argument("--top", type=int, default=10,
                        help="movers shown from each end (default 10)")
    parser.add_argument("--save", action="store_true",
                        help="also write simulate/<name>/report.txt")
    args = parser.parse_args()
    if args.scenario:
        print(report(args.scenario, top=args.top, save=args.save), end="")
    else:
        sim._summary()
