"""Stage 8: ridership — P(ride | bus-eligible, distance, grade band, demographics).

Turns the Stage 6×7 bus-eligible pool into expected yellow-bus riders. The M4
baseline is a single global propensity (10,008 / 15,229 = 0.657) that hits the
district target by construction; this stage models the SHAPE — how propensity
varies with distance to school, grade band, and school demographics — while
still hitting the district totals exactly (hard re-normalization).

Model (per assignment-matrix cell, ES+MS bands at basic-route schools):

    p(cell) = clip( s · f(d) · exp(β·x), 0, p_max )
    f(d)    = (1−ρ) + ρ·exp(−d / decay_mi)    d = BG centroid → school point
              ρ=0 flat, ρ=1 pure exponential decay, ρ<0 rising with distance
    x       = centered covariates: is_ms, low_income_frac, swd_frac,
              chronic absent_rate (school-level, eligible-weighted centering)
    s       = solved so Σ eligible·p = the STARS district target (10,008)

θ = (ρ, decay_mi, β…) is fit by grid search + refinement against the SOFT
target: per-school route-implied riders (STARS basic routes × riders/route).
The gifted program gets its own pool — HC enrollment at the gifted-route
sites, spread via the HCC pathway kernel (ES sites) or the school's
assignment column (MS sites; open question 4b) — and a single propensity
solved against the gifted rider target (1,316 in 2024-25).

Riders map to route/bus-ish outputs via district riders-per-route by program.

Outputs (tracked under analysis/montecarlo/ridership/):
  school_ridership.csv — per school × program: eligible, propensity, riders,
                         actual routes, estimated routes
  params.csv           — fitted θ + solved scales + fit metrics

Run:   python3 -m analysis.montecarlo.ridership [--build]

Loaders / API (pure-functional core for Stage 10):
  load_ridership()                          → DataFrame
  load_params()                             → RidershipParams (fitted)
  basic_cells(assignment, walk)             → per-cell eligible pool
  expected_riders(assignment, walk, params) → school × program table
  sample_riders(rng, ...)                   → Poisson count draw (MC wrapper;
                                              Stage 10 samples θ itself)
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass, fields, replace
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from analysis.montecarlo import parse_shapes
from analysis.montecarlo.assignment import (
    _bg_centroids,
    _school_points,
    bg_area_weights,
    kernel_bg_weights,
    load_assignment,
)
from analysis.montecarlo.baseline_ridership import (
    load_district_targets,
    load_school_enrollment,
    load_school_routes,
)
from analysis.montecarlo.eligibility import load_walker_fractions
from analysis.montecarlo.rc_seattle import load_attendance_all_students
from analysis.montecarlo.school_directory import load_schools

_HERE = Path(__file__).resolve().parent
OUT_DIR = _HERE / "ridership"

BASE_YEAR = 2024
_BUS_BANDS = ("es", "ms")  # no HS basic yellow-bus routes (STARS 2024-25)
FEET_PER_MILE = parse_shapes.FEET_PER_MILE

# Covariate columns; x_<name> are the centered versions used by the tilt.
_COVARS = ("is_ms", "low_income_frac", "swd_frac", "absent_rate")


@dataclass(frozen=True)
class RidershipParams:
    """θ for the ride-propensity model. Stage 10 samples/perturbs these.

    The overall propensity LEVEL is not a parameter: ``expected_riders``
    re-solves the scale s against the district on-bus target every call, so θ
    only controls the relative shape across cells.
    """
    rho: float = 0.0           # decay-component weight: f = (1−ρ) + ρ·exp(−d/decay);
                               # ρ∈[−1,1]: 0 flat, 1 pure decay, <0 rising w/ distance
    decay_mi: float = 1.0      # distance scale of the decay component
    beta_ms: float = 0.0       # grade-band tilt (MS vs ES)
    beta_low_income: float = 0.0
    beta_swd: float = 0.0
    beta_absent: float = 0.0
    p_max: float = 0.95        # per-cell propensity cap
    gifted_propensity: float | None = None  # None → solve vs the gifted target


# ---------------------------------------------------------------------------
# Targets / covariates
# ---------------------------------------------------------------------------

def district_targets(year: int = BASE_YEAR) -> dict:
    """The STARS district calibration numbers for one year."""
    t = load_district_targets()
    row = t[t.year == year].iloc[0]
    return {
        "on_bus": float(row["basic_students_on_buses"]),
        "gifted": float(row["special_students_gifted"]),
        "routes_basic": float(row["routes_basic"]),
        "routes_gifted": float(row["routes_gifted"]),
    }


def school_covariates(year: int = BASE_YEAR) -> pd.DataFrame:
    """Per-school shape covariates, indexed by school_id.

    low_income_frac / swd_frac from RC enrollment (baseline year);
    absent_rate = chronic absenteeism, school-level All Grades, latest
    unsuppressed year ≤ baseline (RC attendance ends 2023-24).
    """
    se = load_school_enrollment()
    se = se[se.year == year].set_index("school_id")
    cov = pd.DataFrame(index=se.index)
    cov["low_income_frac"] = se["low_income"] / se["enrollment"]
    cov["swd_frac"] = se["students_with_disabilities"] / se["enrollment"]

    att = load_attendance_all_students()
    sl = att[(att.grade_level == "All Grades") & (~att.suppressed) & (att.year <= year)]
    sl = sl.sort_values("year").groupby("school_code").tail(1)
    code_to_id = load_schools().set_index("school_code")["school_id"]
    sl = sl.assign(school_id=sl["school_code"].map(code_to_id)).dropna(subset=["school_id"])
    cov["absent_rate"] = sl.set_index(sl["school_id"].astype(int))["chronic_absent_rate"]
    return cov


# ---------------------------------------------------------------------------
# Basic-program cell pool
# ---------------------------------------------------------------------------

def basic_cells(assignment: pd.DataFrame | None = None,
                walk: pd.DataFrame | None = None,
                year: int = BASE_YEAR) -> pd.DataFrame:
    """Per-cell bus-eligible pool for the basic program.

    One row per (GEOID, school, band) cell of the assignment matrix, ES+MS
    bands at the schools that actually run basic routes in ``year``. Columns:
    n_eligible (= n_expected × (1 − walk_frac)), dist_mi (BG centroid →
    school point), raw covariates, and centered x_* covariates (centering
    weighted by n_eligible, so β=0 means a flat tilt over the pool).
    """
    if assignment is None:
        assignment = load_assignment()
    if walk is None:
        walk = load_walker_fractions()
    routes = load_school_routes()
    basic_ids = set(routes[(routes.year == year) & (routes.program == "basic")].school_id)

    df = assignment[
        assignment.grade_band.isin(_BUS_BANDS) & assignment.school_id.isin(basic_ids)
    ].merge(walk, on=["GEOID", "school_id"], how="left")
    df["walk_frac"] = df["walk_frac"].fillna(0.0)
    df["n_eligible"] = df["n_expected"] * (1.0 - df["walk_frac"])
    df = df[df["n_eligible"] > 0].copy()

    cents = _bg_centroids()
    pts = _school_points()
    df["dist_mi"] = shapely.distance(
        cents.reindex(df["GEOID"]).to_numpy(),
        pts.reindex(df["school_id"]).to_numpy(),
    ) / FEET_PER_MILE

    df["is_ms"] = (df["grade_band"] == "ms").astype(float)
    cov = school_covariates(year)
    df = df.merge(cov, left_on="school_id", right_index=True, how="left")
    w = df["n_eligible"].to_numpy()
    for c in _COVARS:
        v = df[c].to_numpy(dtype=float)
        ok = ~np.isnan(v)
        mean = float(np.average(v[ok], weights=w[ok]))
        df[f"x_{c}"] = np.where(ok, v - mean, 0.0)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Propensity model
# ---------------------------------------------------------------------------

def _cell_shape(cells: pd.DataFrame, params: RidershipParams) -> np.ndarray:
    """Unscaled relative propensity per cell (the model's SHAPE term)."""
    f = (1.0 - params.rho) + params.rho * np.exp(
        -cells["dist_mi"].to_numpy() / params.decay_mi)
    tilt = (params.beta_ms * cells["x_is_ms"].to_numpy()
            + params.beta_low_income * cells["x_low_income_frac"].to_numpy()
            + params.beta_swd * cells["x_swd_frac"].to_numpy()
            + params.beta_absent * cells["x_absent_rate"].to_numpy())
    return np.maximum(f, 0.0) * np.exp(tilt)


def _solve_scale(e: np.ndarray, shape: np.ndarray, target: float,
                 p_max: float) -> float:
    """s such that Σ e·min(s·shape, p_max) = target.

    Active-set iteration starting from the uncapped solution; the capped set
    only grows as s rises, so this terminates in a handful of passes.
    """
    if float((e * p_max).sum()) <= target:
        return np.inf  # target unreachable even at the cap
    s = target / float(e @ shape)
    for _ in range(100):
        capped = s * shape >= p_max
        cap_riders = float(e[capped].sum()) * p_max
        denom = float(e[~capped] @ shape[~capped])
        if denom <= 0:
            break
        s_new = (target - cap_riders) / denom
        if abs(s_new - s) <= 1e-12 * max(s, 1.0):
            s = s_new
            break
        s = s_new
    return s


def _cell_propensity(cells: pd.DataFrame, params: RidershipParams,
                     target: float) -> tuple[np.ndarray, float]:
    """Per-cell ride probability, re-normalized to the district target."""
    shape = _cell_shape(cells, params)
    e = cells["n_eligible"].to_numpy()
    s = _solve_scale(e, shape, target, params.p_max)
    if not np.isfinite(s):
        return np.full_like(shape, params.p_max), s
    return np.minimum(s * shape, params.p_max), s


# ---------------------------------------------------------------------------
# Gifted program pool
# ---------------------------------------------------------------------------

def gifted_pool(assignment: pd.DataFrame | None = None,
                walk: pd.DataFrame | None = None,
                year: int = BASE_YEAR,
                weights: pd.DataFrame | None = None) -> pd.DataFrame:
    """Bus-eligible HC pool per gifted-route site.

    HC enrollment (RC ``highly_capable``) at each school with gifted routes,
    spread over block groups by:
      ES sites (Cascadia, Decatur, Thurgood Marshall) — the HCC pathway
        kernel (exact union of feeder attendance areas, era 2023-2025);
      MS sites — the school's own assignment column, i.e. HC kids assumed
        spatially distributed like the rest of the school's draw. This
        UNDERSTATES their bus eligibility (HC kids skew distant) — open
        question 4b (MS pathway map) would fix it.
    Walk-zone exclusion applied per block group as for basic.
    """
    if assignment is None:
        assignment = load_assignment()
    if walk is None:
        walk = load_walker_fractions()
    if weights is None:
        weights = bg_area_weights()
    routes = load_school_routes()
    g = routes[(routes.year == year) & (routes.program == "gifted")]
    schools = load_schools().set_index("school_id")
    se = load_school_enrollment()
    hc = se[se.year == year].set_index("school_id")["highly_capable"]

    rows = []
    for sid in sorted(g.school_id):
        level = schools.loc[sid, "level"]
        n_hc = float(hc.get(sid, 0) or 0)
        wsub = walk[walk.school_id == sid].set_index("GEOID")["walk_frac"]
        if level == "ES":
            pbg = kernel_bg_weights(sid, "hcc_pathway", "es", weights=weights)
            band = "es"
        else:
            col = assignment[(assignment.school_id == sid) & (assignment.grade_band == "ms")]
            pbg = col.set_index("GEOID")["n_expected"]
            pbg = pbg / pbg.sum()
            band = "ms"
        elig_frac = float((pbg * (1.0 - wsub.reindex(pbg.index).fillna(0.0))).sum())
        rows.append({"school_id": sid, "grade_band": band, "kernel": "hcc_pathway"
                     if level == "ES" else "od_column", "n_hc": n_hc,
                     "n_bus_eligible": n_hc * elig_frac})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Expected riders (pure core)
# ---------------------------------------------------------------------------

def expected_riders(assignment: pd.DataFrame | None = None,
                    walk: pd.DataFrame | None = None,
                    params: RidershipParams | None = None,
                    year: int = BASE_YEAR,
                    cells: pd.DataFrame | None = None,
                    gifted: pd.DataFrame | None = None,
                    return_info: bool = False):
    """Expected riders per school × program (the Stage 10 entry point).

    Pure function of (assignment, walk_fractions, θ): pass a sampled
    assignment matrix / scenario walk fractions / sampled θ to re-run the
    model; tracked files are only read for the defaults. ``cells`` /
    ``gifted`` short-circuit the pool construction when the caller already
    has them (e.g. the fit loop). Basic bands are aggregated per school;
    grade_band is informational. est_routes = riders / district
    riders-per-route for the program.
    """
    if params is None:
        params = load_params()
    if cells is None:
        cells = basic_cells(assignment, walk, year)
    if gifted is None:
        gifted = gifted_pool(assignment, walk, year)
    tgt = district_targets(year)

    p, scale = _cell_propensity(cells, params, tgt["on_bus"])
    riders = cells["n_eligible"].to_numpy() * p
    per_band = cells.assign(riders=riders).groupby(
        ["school_id", "grade_band"], as_index=False
    ).agg(n_bus_eligible=("n_eligible", "sum"), riders=("riders", "sum"))
    basic = per_band.groupby("school_id", as_index=False).agg(
        n_bus_eligible=("n_bus_eligible", "sum"), riders=("riders", "sum"))
    bands = per_band.groupby("school_id")["grade_band"].apply(
        lambda s: "+".join(sorted(s)))
    basic["grade_band"] = basic["school_id"].map(bands)
    basic["program"] = "basic"

    gprop = params.gifted_propensity
    if gprop is None:
        gprop = tgt["gifted"] / gifted["n_bus_eligible"].sum()
    gout = gifted[["school_id", "grade_band", "n_bus_eligible"]].copy()
    gout["riders"] = gout["n_bus_eligible"] * gprop
    gout["program"] = "gifted"

    out = pd.concat([basic, gout], ignore_index=True)
    out["propensity"] = out["riders"] / out["n_bus_eligible"]
    rpr = {"basic": tgt["on_bus"] / tgt["routes_basic"],
           "gifted": tgt["gifted"] / tgt["routes_gifted"]}
    out["est_routes"] = out["riders"] / out["program"].map(rpr)
    out = out[["school_id", "program", "grade_band", "n_bus_eligible",
               "propensity", "riders", "est_routes"]]
    if return_info:
        return out, {"scale": scale, "gifted_propensity": gprop,
                     "riders_per_route_basic": rpr["basic"],
                     "riders_per_route_gifted": rpr["gifted"]}
    return out


def sample_riders(rng: np.random.Generator,
                  assignment: pd.DataFrame | None = None,
                  walk: pd.DataFrame | None = None,
                  params: RidershipParams | None = None,
                  year: int = BASE_YEAR) -> pd.DataFrame:
    """MC wrapper: Poisson count draw around the expected riders.

    This adds count noise only; Stage 10 supplies parameter uncertainty by
    sampling θ (and the population, via ``assignment=build_matrix(pop=...)``).
    """
    df = expected_riders(assignment, walk, params, year)
    tgt = district_targets(year)
    df = df.copy()
    df["riders"] = rng.poisson(df["riders"].to_numpy()).astype(float)
    rpr = {"basic": tgt["on_bus"] / tgt["routes_basic"],
           "gifted": tgt["gifted"] / tgt["routes_gifted"]}
    df["est_routes"] = df["riders"] / df["program"].map(rpr)
    return df


# ---------------------------------------------------------------------------
# Fitting θ against the per-school route soft target
# ---------------------------------------------------------------------------

def _route_targets(cells: pd.DataFrame, year: int, on_bus: float):
    """Per-school route-implied rider targets, aligned to the cell pool.

    Returns (school_ids, n_routes, rider_target, school_index_per_cell).
    rider_target = n_routes × on_bus/Σn_routes so targets and (renormalized)
    predictions have the same district total.
    """
    routes = load_school_routes()
    r = routes[(routes.year == year) & (routes.program == "basic")]
    nr = r.groupby("school_id")["n_routes"].sum()
    sids = np.sort(cells["school_id"].unique())
    nr = nr.reindex(sids).fillna(0.0)
    target = nr / nr.sum() * on_bus
    idx = np.searchsorted(sids, cells["school_id"].to_numpy())
    return sids, nr.to_numpy(dtype=float), target.to_numpy(dtype=float), idx


def fit_params(cells: pd.DataFrame | None = None, year: int = BASE_YEAR,
               verbose: bool = False) -> tuple[RidershipParams, dict]:
    """Grid search + refinement for θ on the basic program.

    Objective: SSE between per-school predicted riders (after district
    renormalization) and route-implied riders. Reports Pearson r of predicted
    riders vs STARS basic route counts before (flat propensity = M4 baseline)
    and after shaping.
    """
    if cells is None:
        cells = basic_cells(year=year)
    tgt = district_targets(year)
    on_bus = tgt["on_bus"]
    sids, n_routes, target, idx = _route_targets(cells, year, on_bus)
    e = cells["n_eligible"].to_numpy()

    def school_riders(params: RidershipParams) -> np.ndarray:
        p, _ = _cell_propensity(cells, params, on_bus)
        return np.bincount(idx, weights=e * p, minlength=len(sids))

    def sse(params: RidershipParams) -> float:
        return float(((school_riders(params) - target) ** 2).sum())

    flat = RidershipParams()
    riders_flat = school_riders(flat)
    sse_before = float(((riders_flat - target) ** 2).sum())
    r_before = float(np.corrcoef(riders_flat, n_routes)[0, 1])

    grid = {
        "rho": (-0.5, 0.0, 0.5, 0.75, 0.9, 1.0),
        "decay_mi": (0.5, 1.0, 2.0, 4.0),
        "beta_ms": (-1.0, -0.5, 0.0, 0.5, 1.0),
        "beta_low_income": (-2.0, -1.0, 0.0, 1.0, 2.0),
        "beta_swd": (-4.0, -2.0, 0.0, 2.0, 4.0),
        "beta_absent": (-2.0, -1.0, 0.0, 1.0, 2.0),
    }
    names = list(grid)
    best, best_sse = flat, sse_before
    for combo in itertools.product(*grid.values()):
        cand = replace(flat, **dict(zip(names, combo)))
        v = sse(cand)
        if v < best_sse:
            best, best_sse = cand, v
    if verbose:
        print(f"  coarse grid best: {best_sse:,.0f} SSE  {_fmt_params(best)}")

    # Coordinate refinement around the coarse optimum: repeat full passes at
    # each step size until no improvement, then halve the steps. Walks freely
    # past the coarse-grid edges instead of pinning at them.
    steps = {"rho": 0.2, "decay_mi": None, "beta_ms": 0.5,
             "beta_low_income": 0.5, "beta_swd": 1.0, "beta_absent": 0.5}
    for _ in range(4):
        improved = True
        while improved:
            improved = False
            for name in names:
                cur = getattr(best, name)
                if steps[name] is None:  # decay: multiplicative neighborhood
                    cands = (cur * 0.75, cur * 1.25)
                else:
                    cands = (cur - steps[name], cur + steps[name])
                for c in cands:
                    if name == "rho" and not (-1.0 <= c <= 1.0):
                        continue
                    if name == "decay_mi" and c <= 0.05:
                        continue
                    cand = replace(best, **{name: c})
                    v = sse(cand)
                    if v < best_sse - 1e-9:
                        best, best_sse, improved = cand, v, True
        steps = {k: (v / 2 if v else None) for k, v in steps.items()}
    if verbose:
        print(f"  refined best:     {best_sse:,.0f} SSE  {_fmt_params(best)}")

    riders_after = school_riders(best)
    r_after = float(np.corrcoef(riders_after, n_routes)[0, 1])
    metrics = {
        "n_schools": len(sids),
        "sse_before": sse_before, "sse_after": best_sse,
        "pearson_routes_before": r_before, "pearson_routes_after": r_after,
    }
    return best, metrics


def _fmt_params(p: RidershipParams) -> str:
    return (f"ρ={p.rho:.2f} decay={p.decay_mi:.2f}mi β_ms={p.beta_ms:+.2f} "
            f"β_li={p.beta_low_income:+.2f} β_swd={p.beta_swd:+.2f} "
            f"β_abs={p.beta_absent:+.2f}")


# ---------------------------------------------------------------------------
# Build / loaders
# ---------------------------------------------------------------------------

def build(verbose: bool = True) -> pd.DataFrame:
    OUT_DIR.mkdir(exist_ok=True)
    cells = basic_cells()
    if verbose:
        print(f"basic pool: {len(cells)} cells, "
              f"{cells.school_id.nunique()} schools, "
              f"{cells.n_eligible.sum():,.0f} eligible")
        print("Fitting θ against route-implied per-school riders:")
    params, metrics = fit_params(cells=cells, verbose=verbose)

    gifted = gifted_pool()
    table, info = expected_riders(params=params, cells=cells, gifted=gifted,
                                  return_info=True)
    schools = load_schools()
    table = table.merge(schools[["school_id", "name", "level"]], on="school_id", how="left")
    routes = load_school_routes()
    r24 = routes[routes.year == BASE_YEAR].groupby(["school_id", "program"])["n_routes"].sum()
    table["n_routes_actual"] = [
        r24.get((sid, prog), 0) for sid, prog in zip(table.school_id, table.program)]
    table = table[["school_id", "name", "level", "program", "grade_band",
                   "n_bus_eligible", "propensity", "riders",
                   "n_routes_actual", "est_routes"]]
    table = table.sort_values(["program", "school_id"])
    for c in ("n_bus_eligible", "riders", "est_routes"):
        table[c] = table[c].round(2)
    table["propensity"] = table["propensity"].round(4)
    table.to_csv(OUT_DIR / "school_ridership.csv", index=False)

    prow = {f.name: getattr(params, f.name) for f in fields(params)}
    prow["gifted_propensity"] = info["gifted_propensity"]
    prow.update({k: v for k, v in info.items() if k != "gifted_propensity"})
    prow.update(metrics)
    pd.DataFrame([prow]).to_csv(OUT_DIR / "params.csv", index=False)

    if verbose:
        print(f"school_ridership.csv: {len(table)} rows "
              f"({(table.program == 'basic').sum()} basic schools, "
              f"{(table.program == 'gifted').sum()} gifted sites)")
        print(f"params.csv: {_fmt_params(params)}; "
              f"gifted propensity {info['gifted_propensity']:.3f}")
        print(f"route correlation r: {metrics['pearson_routes_before']:.3f} → "
              f"{metrics['pearson_routes_after']:.3f}")
        print(f"Wrote {OUT_DIR}")
    return table


def load_ridership() -> pd.DataFrame:
    """Per school × program: eligible, propensity, riders, routes."""
    path = OUT_DIR / "school_ridership.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 -m analysis.montecarlo.ridership --build")
    return pd.read_csv(path)


def load_params() -> RidershipParams:
    """The fitted θ (gifted_propensity solved, not None)."""
    path = OUT_DIR / "params.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 -m analysis.montecarlo.ridership --build")
    row = pd.read_csv(path).iloc[0]
    return RidershipParams(**{f.name: row[f.name] for f in fields(RidershipParams)})


# ---------------------------------------------------------------------------
# Summary / validation
# ---------------------------------------------------------------------------

def _summary() -> None:
    df = load_ridership()
    praw = pd.read_csv(OUT_DIR / "params.csv").iloc[0]
    params = load_params()
    tgt = district_targets()

    print("=== Stage 8 ridership (2024-25 baseline) ===")
    basic = df[df.program == "basic"]
    gifted = df[df.program == "gifted"]
    print(f"  basic:  {len(basic)} schools, riders {basic.riders.sum():9,.1f} "
          f"(target {tgt['on_bus']:,.0f})")
    print(f"  gifted: {len(gifted)} sites,  riders {gifted.riders.sum():9,.1f} "
          f"(target {tgt['gifted']:,.0f})")
    print(f"  θ: {_fmt_params(params)}  p_max={params.p_max}")
    print(f"  gifted propensity: {params.gifted_propensity:.3f}")
    print(f"  basic propensity range over schools: "
          f"{basic.propensity.min():.3f} – {basic.propensity.max():.3f} "
          f"(flat M4 baseline: 0.657)")
    print(f"  per-school riders vs STARS basic routes: "
          f"r {praw['pearson_routes_before']:.3f} (flat) → "
          f"{praw['pearson_routes_after']:.3f} (shaped)  "
          f"[{int(praw['n_schools'])} schools]")
    print(f"  route SSE: {praw['sse_before']:,.0f} → {praw['sse_after']:,.0f}")
    print(f"  riders/route: basic {praw['riders_per_route_basic']:.1f}, "
          f"gifted {praw['riders_per_route_gifted']:.1f}")
    print(f"  est routes: basic {basic.est_routes.sum():.0f} "
          f"(actual {basic.n_routes_actual.sum():.0f} mapped / "
          f"{tgt['routes_basic']:.0f} district), "
          f"gifted {gifted.est_routes.sum():.0f} "
          f"(actual {gifted.n_routes_actual.sum():.0f})")
    print("\n  gifted sites:")
    for _, r in gifted.sort_values("riders", ascending=False).iterrows():
        print(f"    {r['name']:22s} {r.grade_band}  eligible {r.n_bus_eligible:6.1f}  "
              f"riders {r.riders:6.1f}  routes {r.n_routes_actual:.0f} "
              f"(est {r.est_routes:.1f})")
    print("\n  largest basic-rider schools:")
    for _, r in basic.nlargest(8, "riders").iterrows():
        print(f"    {r['name']:22s} {r.grade_band:5s}  eligible {r.n_bus_eligible:7.1f}  "
              f"p {r.propensity:.3f}  riders {r.riders:6.1f}  "
              f"routes {r.n_routes_actual:.0f} (est {r.est_routes:.1f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 8: ride propensity → riders")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        _summary()
