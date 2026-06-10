"""Stage 11: report — summarize a saved MC run into deltas with CIs + equity cuts.

UNITS (USER CORRECTION, s10): every 'riders' figure here and throughout the
pipeline is STARS **rides per day** — AM and PM boardings each count once, so
a student riding both ways counts as 2. Unique students are between rides/2
and rides (long-route students disproportionately ride mornings only). The
calibration targets (10,008.5 basic / 1,315.5 gifted) and all deltas share
this unit; riders-per-route (49.5) is rides/day per route, ≈ 25 students on
a one-way run.

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
(Stage 8 convention), so route deltas inherit the rider CIs. Buses + annual
cost (s10): fleet = the busier of the two bell shifts (ES vs MS/HS) since a
bus serves one route per shift; cost = Δbuses × $148.9k/bus-year (SY2024-25
all-in vendor cost — constants + sources at the top of this module).

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

# --- Bus fleet + cost model (user-ingested facts, s10) -----------------------
# SPS fully outsources transportation. SY2024-25 purchased-transportation
# spend: $56.89M / 382 buses ≈ $148.9k per bus-year — the ALL-IN vendor cost
# (contracted base daily rate ~$580-650/bus/day plus excess hours,
# attendants, field trips, McKinney-Vento, KPI adjustments; ≈ $820/bus/day
# over ~181 service days). SY2023-24 nearly identical ($56.56M/381 ≈
# $148.4k). Adding district-side supervision/crossing guards (~$4.7M/yr)
# ≈ +$12k → ~$161k total. Pre-COVID ≈ $106k (SY2018-19: $37.5M/355);
# SY2022-23 (~$169k) was the one-time Zūm-failure outlier — excluded.
COST_PER_BUS_YEAR = 148_900  # all-in vendor cost, SY2024-25

# A bus serves one route per bell shift; SPS runs 2 shifts (ES at a
# different bell time from MS/HS), so the fleet size is the MAX of
# simultaneously active routes: max(ES-shift routes, MS/HS-shift routes),
# pooled across the modeled programs (basic + gifted — a bus can pair an
# ES gifted run with an MS basic run). K-8s ride the ES shift (one bell
# time, level "ES"). Validation vs STARS 2024-25: the rule gives
# max(144+27, 47+13) = 171 buses vs the actual basic+gifted 162 (+5.6%).
_SHIFT = {"ES": "es", "MS": "ms_hs", "HS": "ms_hs"}

# --- STARS pupil-transportation reimbursement (EXAL = Expected Allocation),
# user-ingested s10 -----------------------------------------------------------
# 2025-26 formula. Allocation = min(EXAL, D2 prior-year cap $59.8M) +
# LegSalaryAdj ($1,048,782). Per user instruction we assume the cap is never
# hit and coefficients are stable year-to-year, so the salary adj and cap
# drop out of every delta. Rider inputs are AM+PM boarding counts (rides/day,
# same unit as this pipeline). At the SY2024-25 inputs EXAL = exp(17.41780)
# ≈ $36.68M, and the marginal value of one basic boarding is
# 0.66498·EXAL/(BasicRiders+1) ≈ $2,653.
EXAL_COEF = {
    "b_basic": 0.66498,     # · ln(BasicRiders + 1)
    "b_special": 0.11000,   # · ln(SpecialRiders + 1)
    "b_dest": 0.01523,      # · Destinations (linear)
    "b_avgdist": 0.04231,   # · AvgDistance (linear, miles)
    "b_landarea": 0.02839,  # · ln(LandArea sq mi)
    "b_nonhigh": -0.29176,  # · NonHighDist (0 for SPS)
    "constant": 8.60130,
}
EXAL_BASE = {               # official SY2024-25 SPS inputs
    "basic": 9194.75,       # NOTE: a different STARS count than the model's
    "special": 4256.25,     # 10,008.5 quarterly-metrics baseline — scenario
    "dest": 105.75,         # DELTAS are applied on top of these inputs.
    "avgdist": 2.16,        # Gifted deltas feed SpecialRiders (gifted is a
    "landarea": 85.50,      # "special" program in STARS; 4,256 ≈ gifted
    "nonhigh": 0.0,         # 1,316 + special_ed 2,506 + early_ed/etc.)
}


def _exal(basic: np.ndarray, special: np.ndarray, dest: np.ndarray,
          avgdist: np.ndarray) -> np.ndarray:
    c = EXAL_COEF
    return np.exp(c["b_basic"] * np.log(basic + 1)
                  + c["b_special"] * np.log(special + 1)
                  + c["b_dest"] * dest
                  + c["b_avgdist"] * avgdist
                  + c["b_landarea"] * np.log(EXAL_BASE["landarea"])
                  + c["b_nonhigh"] * EXAL_BASE["nonhigh"]
                  + c["constant"])


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


def bus_cost_summary(run: dict) -> pd.DataFrame:
    """Per draw: bell-shift fleet size baseline vs scenario + annual cost delta.

    Routes per school from riders via riders-per-route; buses per draw =
    max over the 2 bell shifts of the shift's route total (see _SHIFT note);
    cost delta = Δbuses × COST_PER_BUS_YEAR.
    """
    tgt = rid.district_targets()
    rpr = {"basic": tgt["on_bus"] / tgt["routes_basic"],
           "gifted": tgt["gifted"] / tgt["routes_gifted"]}
    sc = run["school"].copy()
    levels = load_schools().set_index("school_id")["level"]
    sc["shift"] = sc["school_id"].map(levels).map(_SHIFT)
    for arm in ("base", "scen"):
        sc[f"{arm}_routes"] = sc[f"{arm}_riders"] / sc["program"].map(rpr)
    per_shift = sc.groupby(["draw", "shift"])[["base_routes", "scen_routes"]].sum()
    out = per_shift.groupby(level="draw").max()  # fleet = the busier shift
    out = out.rename(columns={"base_routes": "base_buses", "scen_routes": "scen_buses"})
    out["d_buses"] = out["scen_buses"] - out["base_buses"]
    out["d_cost"] = out["d_buses"] * COST_PER_BUS_YEAR
    return out.reset_index()


def funding_summary(run: dict) -> pd.DataFrame:
    """Per draw: EXAL reimbursement delta from the scenario's input changes.

    Scenario deltas (basic rides → BasicRiders, gifted rides → SpecialRiders,
    served-school count → Destinations, rider-weighted basic avg distance →
    AvgDistance) are applied on top of the official EXAL_BASE inputs;
    d_revenue = EXAL(scen inputs) − EXAL(base inputs) per draw.
    """
    d = run["district"]
    db = d[d.program == "basic"].set_index("draw")
    dg = d[d.program == "gifted"].set_index("draw")
    d_basic = db["d_riders"]
    d_gift = dg["d_riders"].reindex(d_basic.index).fillna(0.0)
    if "base_dist_mean" in db.columns and db["base_dist_mean"].notna().any():
        d_dist = (db["scen_dist_mean"] - db["base_dist_mean"]).fillna(0.0)
    else:
        d_dist = pd.Series(0.0, index=d_basic.index)

    sc = run["school"]
    served = sc.groupby(["draw", "school_id"])[["base_riders", "scen_riders"]].sum()
    n_base = served.groupby(level="draw").agg(n=("base_riders", lambda s: (s > 0.5).sum()))["n"]
    n_scen = served.groupby(level="draw").agg(n=("scen_riders", lambda s: (s > 0.5).sum()))["n"]
    d_dest = (n_scen - n_base).reindex(d_basic.index).fillna(0.0)

    B = EXAL_BASE
    base_rev = _exal(np.full(len(d_basic), B["basic"]), np.full(len(d_basic), B["special"]),
                     np.full(len(d_basic), B["dest"]), np.full(len(d_basic), B["avgdist"]))
    scen_rev = _exal(B["basic"] + d_basic.to_numpy(), B["special"] + d_gift.to_numpy(),
                     B["dest"] + d_dest.to_numpy(), B["avgdist"] + d_dist.to_numpy())
    return pd.DataFrame({
        "draw": d_basic.index, "d_basic": d_basic.to_numpy(),
        "d_special": d_gift.to_numpy(), "d_dest": d_dest.to_numpy(),
        "d_avgdist": d_dist.to_numpy(), "base_revenue": base_rev,
        "scen_revenue": scen_rev, "d_revenue": scen_rev - base_rev,
    })


def school_summary(run: dict) -> pd.DataFrame:
    """Per school × program: mean rider delta + CI, sorted by delta."""
    sc = run["school"].copy()
    for c in ("base_dist_mean", "scen_dist_mean"):  # absent in pre-s9 runs
        if c not in sc.columns:
            sc[c] = np.nan
    sc["d_riders"] = sc["scen_riders"] - sc["base_riders"]
    g = sc.groupby(["school_id", "program"])
    out = g.agg(base_riders=("base_riders", "mean"),
                scen_riders=("scen_riders", "mean"),
                d_mean=("d_riders", "mean"),
                d_lo=("d_riders", lambda s: s.quantile(CI_LO)),
                d_hi=("d_riders", lambda s: s.quantile(CI_HI)),
                base_dist=("base_dist_mean", "mean"),
                scen_dist=("scen_dist_mean", "mean")).reset_index()
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

    w("\nDistrict (means over draws; deltas show 95% CI). NOTE: 'riders' = "
      "STARS rides/day —\n  AM and PM boardings each count, so a both-ways "
      "student counts as 2; unique\n  students are between half and all of "
      "the figure (long-route kids often ride AM only):\n")
    for _, r in district_summary(run).iterrows():
        w(f"  {r['program']:6s}: riders {r['base_riders']:9,.1f} → "
          f"{r['scen_riders']:9,.1f}   Δ {r['d_riders_mean']:+7.1f} "
          f"[{r['d_riders_lo']:+.1f}, {r['d_riders_hi']:+.1f}]"
          f"   est routes Δ {r['d_routes_mean']:+5.2f} "
          f"[{r['d_routes_lo']:+.2f}, {r['d_routes_hi']:+.2f}]\n")

    bc = bus_cost_summary(run)
    w("\nBus fleet + annual cost (2 bell shifts: fleet = busier of ES vs "
      "MS/HS shift;\n"
      f"  ${COST_PER_BUS_YEAR/1000:.1f}k per bus-year, SY2024-25 all-in "
      "vendor cost — see report.py constants):\n")
    w(f"  buses: {bc['base_buses'].mean():6.1f} → {bc['scen_buses'].mean():6.1f}"
      f"   Δ {_fmt_ci(bc['d_buses'], '+.1f')}\n")
    w(f"  annual cost Δ: {_fmt_ci(bc['d_cost'] / 1e6, '+,.2f')} $M/yr\n")

    fs = funding_summary(run)
    w("\nState funding (STARS EXAL reimbursement, 2025-26 formula; baseline "
      f"${fs['base_revenue'].mean()/1e6:.2f}M,\n"
      "  assumed below cap; Δinputs: basic/gifted ride deltas, served-school "
      "count, avg distance):\n")
    w(f"  Δ inputs (means): BasicRiders {fs['d_basic'].mean():+,.0f}, "
      f"SpecialRiders {fs['d_special'].mean():+,.0f}, "
      f"Destinations {fs['d_dest'].mean():+,.1f}, "
      f"AvgDistance {fs['d_avgdist'].mean():+.3f} mi\n")
    w(f"  revenue Δ: {_fmt_ci(fs['d_revenue'] / 1e6, '+,.2f')} $M/yr\n")
    net = (fs.set_index("draw")["d_revenue"] - bc.set_index("draw")["d_cost"]) / 1e6
    w(f"  NET fiscal Δ (revenue − bus cost): {_fmt_ci(net, '+,.2f')} $M/yr\n")

    d = run["district"]
    db = d[d.program == "basic"]
    if "base_dist_mean" in db.columns and db["base_dist_mean"].notna().any():
        w("\nAvg stop→school distance, rider-weighted (basic, miles; STARS "
          "calls this 'average_distance'):\n")
        for stat in ("dist_mean", "dist_p50", "dist_p90"):
            delta = db[f"scen_{stat}"] - db[f"base_{stat}"]
            w(f"  {stat[5:]:>5s}: {db[f'base_{stat}'].mean():5.2f} → "
              f"{db[f'scen_{stat}'].mean():5.2f}   Δ {_fmt_ci(delta, '+.3f')}\n")

    ss = school_summary(run)
    movers = ss[ss["d_mean"].abs() > 0.5]
    w(f"\nPer-school movers (|mean Δriders| > 0.5): {len(movers)}\n")
    shown = pd.concat([movers.head(top), movers.tail(top)]).drop_duplicates("school_id")
    has_dist = "base_dist" in shown.columns
    for _, r in shown.iterrows():
        dist = ""
        if has_dist and pd.notna(r.get("base_dist")) and pd.notna(r.get("scen_dist")):
            dist = f"   dist {r['base_dist']:4.2f}→{r['scen_dist']:4.2f}mi"
        w(f"  {r['name']:24.24s} {r['program']:6s} "
          f"{r['base_riders']:7.1f} → {r['scen_riders']:7.1f}   "
          f"Δ {r['d_mean']:+7.1f} [{r['d_lo']:+.1f}, {r['d_hi']:+.1f}]"
          f"   routes Δ {r['d_routes_mean']:+5.2f}{dist}\n")

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
