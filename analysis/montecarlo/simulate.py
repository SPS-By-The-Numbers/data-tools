"""Stage 10: simulate — the Monte Carlo driver (paired baseline/scenario draws).

For each draw i the loop samples one coherent uncertain world and evaluates
the BASELINE and the SCENARIO inside it with identical inputs (paired design —
the delta CIs are tight because draw-level noise cancels in the difference):

    θ_i   = sample_params(rng)      # ride-propensity shape around the fit
    pop_i = sample_synth_pop(rng)   # Dirichlet grade-band split per block group
    baseline: assignment(pop_i) → cells → expected_riders(θ_i)   [solve scale]
    scenario: assignment(pop_i) → cells → expected_riders(θ_i)   [reuse scale]

CALIBRATION IS PER-DRAW (decision, s9): the propensity scale s, the covariate
centering means, and the gifted propensity are re-solved on each draw's own
BASELINE cells, then reused verbatim for that draw's scenario run. Rationale:
the district targets (10,008 basic / 1,316 gifted) are observed facts, not
uncertain inputs — every sampled world must reproduce them at baseline, and
the paired scenario run measures the delta under that same coherent
calibration. (Fixed expected-value calibration would let the baseline district
total drift with the draw, adding variance that is calibration error, not
parameter uncertainty.) Consequence: baseline district totals are degenerate
across draws BY CONSTRUCTION; the distributions live in the per-school split
and in every scenario delta.

What is sampled (θ distributions — decision, s9; NOTES "What the MC loop
samples"):
  decay_mi          lognormal around the fitted value, σ_log = 0.2 (≈ ±20%)
  beta_*            normal around the fitted value, sd = max(0.2·|β̂|, 0.05)
  rho               FIXED at the fitted 1.0 — the fit pinned it at the pure-
                    decay boundary; sampling below adds a flat floor the fit
                    firmly rejected (NOTES s7)
  p_max             fixed (structural cap, not a fitted quantity)
  gifted_propensity solved per draw on the baseline (see calibration above)
  population        sample_synth_pop(rng) — Dirichlet α from Stage 5
Scenario worlds are built ONCE from the expected-value baseline — geometry,
flow edits and walk zones do not depend on θ or the population draw. (The one
approximation: a moved option school's column is re-derived with the
expected-value population inside apply(); the per-draw IPF then reconciles it.)

Per-world invariants are computed once, outside the draw loop: the mutated
World itself, its walk fractions (geometry only), and the shared residence
weights. One paired draw ≈ 0.25 s (the 30-60 s/evaluate estimate in older
notes predates this caching), so hundreds of draws are routine.

Outputs (tracked under analysis/montecarlo/simulate/<scenario>/):
  district_draws.csv — draw × program: base/scen riders + rider-weighted
                       distance stats (basic only)
  school_draws.csv   — draw × school × program: base/scen riders + eligible
  theta_draws.csv    — draw: sampled θ + solved scale / gifted propensity
  meta.json          — scenario spec, n_draws, seed, flags, runtime

Run:   python3 -m analysis.montecarlo.simulate --scenario close_sacajawea \
           [--n-draws 200] [--seed 20260610] [--no-theta] [--no-pop]
       python3 -m analysis.montecarlo.simulate           # list saved runs

API (Stage 11 entry points):
  run_mc(scenario, n_draws, seed, ...) → dict of the three DataFrames (+ saves)
  load_run(name) → dict(district, school, theta, meta)
  sample_params(rng, base) → RidershipParams draw
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.montecarlo import ridership as rid
from analysis.montecarlo import scenarios as scn
from analysis.montecarlo.assignment import build_matrix
from analysis.montecarlo.eligibility import walk_fractions
from analysis.montecarlo.synth_population import load_synth_pop, sample_synth_pop

_HERE = Path(__file__).resolve().parent
OUT_DIR = _HERE / "simulate"

DEFAULT_N_DRAWS = 200
DEFAULT_SEED = 20260610

# θ sampling spec (see module docstring + NOTES s9 decision log).
_DECAY_SIGMA_LOG = 0.2
_BETA_SD_FRAC = 0.2
_BETA_SD_FLOOR = 0.05
_BETAS = ("beta_ms", "beta_low_income", "beta_swd", "beta_absent")


def sample_params(rng: np.random.Generator,
                  base: rid.RidershipParams | None = None) -> rid.RidershipParams:
    """One θ draw around the fitted RidershipParams.

    gifted_propensity is forced to None — the draw loop solves it on the
    draw's baseline (per-draw calibration) and reuses it for the scenario.
    """
    if base is None:
        base = rid.load_params()
    kw = {"decay_mi": float(base.decay_mi * np.exp(rng.normal(0.0, _DECAY_SIGMA_LOG))),
          "gifted_propensity": None}
    for name in _BETAS:
        b = getattr(base, name)
        kw[name] = float(rng.normal(b, max(_BETA_SD_FRAC * abs(b), _BETA_SD_FLOOR)))
    # HS-vs-MS discounts (USER assumption, s10) — both uncertain, sampled
    # independently; only move results when a scenario adds HS basic service:
    # all-HS loss to independent transit travel, and the additional gr 11-12
    # (age 16+) car discount.
    kw["hs_indep_factor"] = float(np.clip(rng.normal(base.hs_indep_factor, 0.1), 0.05, 1.0))
    kw["hs_car_factor"] = float(np.clip(rng.normal(base.hs_car_factor, 0.2), 0.05, 1.0))
    return replace(base, **kw)


# ---------------------------------------------------------------------------
# One arm (world) evaluation — per-world invariants precomputed by the caller
# ---------------------------------------------------------------------------

def _eval_arm(world: scn.World, walk: pd.DataFrame, pop: pd.DataFrame,
              params: rid.RidershipParams,
              fixed_scale: float | None = None,
              covar_means: dict | None = None) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Stages 6-8 for one world and one draw. Returns (riders, info, cells)."""
    assignment = build_matrix(pop=pop, weights=world.weights, flows=world.flows,
                              col_marg=world.col_marg)
    cells = rid.basic_cells(assignment, walk, points=world.points,
                            basic_ids=world.basic_ids, covar_means=covar_means,
                            bands=tuple(sorted(world.bus_bands)))
    gifted = scn.scenario_gifted_pool(world, assignment, walk, pop)
    riders, info = rid.expected_riders(params=params, cells=cells, gifted=gifted,
                                       fixed_scale=fixed_scale, return_info=True)
    return riders, info, cells


def _weighted_quantile(v: np.ndarray, w: np.ndarray, qs: tuple) -> list[float]:
    order = np.argsort(v)
    v, w = v[order], w[order]
    cum = np.cumsum(w)
    if cum[-1] <= 0:
        return [float("nan")] * len(qs)
    cum = cum / cum[-1]
    return [float(np.interp(q, cum, v)) for q in qs]


def _cell_riders(cells: pd.DataFrame, params: rid.RidershipParams,
                 scale: float) -> np.ndarray:
    """Expected riders per basic cell (same propensity math as expected_riders)."""
    shape = rid._cell_shape(cells, params)
    p = np.minimum(scale * shape, params.p_max) if np.isfinite(scale) \
        else np.full_like(shape, params.p_max)
    return cells["n_eligible"].to_numpy() * p


def _dist_stats(cells: pd.DataFrame, w: np.ndarray) -> dict:
    """District rider-weighted stop→school distance stats (basic program)."""
    d = cells["dist_mi"].to_numpy()
    p50, p90 = _weighted_quantile(d, w, (0.5, 0.9))
    return {"dist_mean": float(np.average(d, weights=w)) if w.sum() > 0 else float("nan"),
            "dist_p50": p50, "dist_p90": p90}


def _school_dist(cells: pd.DataFrame, w: np.ndarray) -> pd.Series:
    """Per-school rider-weighted mean stop→school distance, miles."""
    df = pd.DataFrame({"school_id": cells["school_id"].to_numpy(),
                       "wd": w * cells["dist_mi"].to_numpy(), "w": w})
    g = df.groupby("school_id").sum()
    return g["wd"] / g["w"].where(g["w"] > 0)


# ---------------------------------------------------------------------------
# The MC loop
# ---------------------------------------------------------------------------

def run_mc(scenario: scn.Scenario | str,
           n_draws: int = DEFAULT_N_DRAWS,
           seed: int = DEFAULT_SEED,
           sample_theta: bool = True,
           sample_pop: bool = True,
           save: bool = True,
           verbose: bool = True) -> dict:
    """Paired Monte Carlo over one scenario; returns + optionally saves tables."""
    if isinstance(scenario, str):
        scenario = scn.load_scenario(scenario)
    t0 = time.time()
    rng = np.random.default_rng(seed)
    base_params = rid.load_params()

    # Per-world invariants (computed once, not per draw).
    world_b = scn.baseline_world()
    world_s = scn.apply(scenario, world_b)
    walk_b = walk_fractions(walkzones=world_b.walkzones)
    walk_s = walk_fractions(walkzones=world_s.walkzones)
    pop_ev = load_synth_pop()

    district_rows, school_rows, theta_rows = [], [], []
    for i in range(n_draws):
        theta = sample_params(rng, base_params) if sample_theta \
            else replace(base_params, gifted_propensity=None)
        pop = sample_synth_pop(rng) if sample_pop else pop_ev

        # Baseline arm: per-draw calibration (solve scale + gifted propensity,
        # center covariates on this draw's own eligible pool).
        riders_b, info_b, cells_b = _eval_arm(world_b, walk_b, pop, theta)
        cal_means = cells_b.attrs["covar_means"]
        scale = info_b["scale"]
        theta_s = replace(theta, gifted_propensity=info_b["gifted_propensity"])

        # Scenario arm: identical draw, baseline-solved calibration.
        riders_s, _, cells_s = _eval_arm(world_s, walk_s, pop, theta_s,
                                         fixed_scale=scale, covar_means=cal_means)

        b = riders_b.set_index(["school_id", "program"])[["n_bus_eligible", "riders"]]
        s = riders_s.set_index(["school_id", "program"])[["n_bus_eligible", "riders"]]
        j = b.join(s, how="outer", lsuffix="_base", rsuffix="_scen").fillna(0.0)
        j = j.rename(columns={"n_bus_eligible_base": "base_eligible",
                              "riders_base": "base_riders",
                              "n_bus_eligible_scen": "scen_eligible",
                              "riders_scen": "scen_riders"})

        # rider-weighted stop→school distances (basic program)
        w_b = _cell_riders(cells_b, theta, scale)
        w_s = _cell_riders(cells_s, theta, scale)
        sd_b, sd_s = _school_dist(cells_b, w_b), _school_dist(cells_s, w_s)
        jr = j.reset_index()
        is_basic = jr["program"] == "basic"
        jr["base_dist_mean"] = np.where(is_basic, jr["school_id"].map(sd_b), np.nan)
        jr["scen_dist_mean"] = np.where(is_basic, jr["school_id"].map(sd_s), np.nan)
        school_rows.append(jr.assign(draw=i))

        dd = j.groupby(level="program").sum()
        ds_b = _dist_stats(cells_b, w_b)
        ds_s = _dist_stats(cells_s, w_s)
        for prog, r in dd.iterrows():
            row = {"draw": i, "program": prog,
                   "base_riders": float(r["base_riders"]),
                   "scen_riders": float(r["scen_riders"]),
                   "d_riders": float(r["scen_riders"] - r["base_riders"])}
            if prog == "basic":
                row.update({f"base_{k}": v for k, v in ds_b.items()})
                row.update({f"scen_{k}": v for k, v in ds_s.items()})
            district_rows.append(row)

        trow = {"draw": i, **asdict(theta)}
        trow["gifted_propensity"] = info_b["gifted_propensity"]
        trow["scale"] = scale
        theta_rows.append(trow)
        if verbose and (i + 1) % 25 == 0:
            print(f"  draw {i + 1}/{n_draws}  ({time.time() - t0:.1f}s)")

    district = pd.DataFrame(district_rows)
    school = pd.concat(school_rows, ignore_index=True)[
        ["draw", "school_id", "program", "base_eligible", "base_riders",
         "scen_eligible", "scen_riders", "base_dist_mean", "scen_dist_mean"]]
    theta_df = pd.DataFrame(theta_rows)
    runtime = time.time() - t0

    meta = {"scenario": scenario.name, "description": scenario.description,
            "ops": list(scenario.ops), "n_draws": n_draws, "seed": seed,
            "sample_theta": sample_theta, "sample_pop": sample_pop,
            "runtime_s": round(runtime, 1)}
    out = {"district": district, "school": school, "theta": theta_df, "meta": meta}

    if save:
        run_dir = OUT_DIR / scenario.name
        run_dir.mkdir(parents=True, exist_ok=True)
        d = district.copy()
        for c in d.columns:
            if d[c].dtype == float:
                d[c] = d[c].round(4)
        d.to_csv(run_dir / "district_draws.csv", index=False)
        sc = school.copy()
        for c in ("base_eligible", "base_riders", "scen_eligible", "scen_riders",
                  "base_dist_mean", "scen_dist_mean"):
            sc[c] = sc[c].round(3)
        sc.to_csv(run_dir / "school_draws.csv", index=False)
        theta_df.to_csv(run_dir / "theta_draws.csv", index=False)
        with open(run_dir / "meta.json", "w") as fh:
            json.dump(meta, fh, indent=2)
        if verbose:
            print(f"Wrote {run_dir}")

    if verbose:
        bd = district[district.program == "basic"]["d_riders"]
        gd = district[district.program == "gifted"]["d_riders"]
        print(f"{scenario.name}: {n_draws} draws in {runtime:.1f}s "
              f"({runtime / n_draws:.2f}s/draw)")
        print(f"  district Δ basic riders:  mean {bd.mean():+8.1f}  "
              f"95% CI [{bd.quantile(0.025):+.1f}, {bd.quantile(0.975):+.1f}]")
        print(f"  district Δ gifted riders: mean {gd.mean():+8.1f}  "
              f"95% CI [{gd.quantile(0.025):+.1f}, {gd.quantile(0.975):+.1f}]")
    return out


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_run(name: str) -> dict:
    """Load a saved MC run: dict(district, school, theta, meta)."""
    run_dir = OUT_DIR / name
    if not (run_dir / "meta.json").exists():
        raise FileNotFoundError(
            f"no MC run at {run_dir}. Run: python3 -m analysis.montecarlo.simulate "
            f"--scenario {name}")
    with open(run_dir / "meta.json") as fh:
        meta = json.load(fh)
    return {"district": pd.read_csv(run_dir / "district_draws.csv"),
            "school": pd.read_csv(run_dir / "school_draws.csv"),
            "theta": pd.read_csv(run_dir / "theta_draws.csv"),
            "meta": meta}


def list_runs() -> list[str]:
    if not OUT_DIR.exists():
        return []
    return sorted(p.parent.name for p in OUT_DIR.glob("*/meta.json"))


def _summary() -> None:
    runs = list_runs()
    print(f"simulate dir: {OUT_DIR}")
    if not runs:
        print("  (no saved MC runs — use --scenario <name>)")
        return
    for name in runs:
        r = load_run(name)
        m = r["meta"]
        bd = r["district"][r["district"].program == "basic"]["d_riders"]
        print(f"  {name:28s} {m['n_draws']:4d} draws (seed {m['seed']})  "
              f"Δbasic mean {bd.mean():+8.1f}  "
              f"CI [{bd.quantile(0.025):+.1f}, {bd.quantile(0.975):+.1f}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 10: MC driver")
    parser.add_argument("--scenario", help="scenario name (scenarios/<name>.json) or path")
    parser.add_argument("--n-draws", type=int, default=DEFAULT_N_DRAWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--no-theta", action="store_true",
                        help="hold θ at the fitted values (population only)")
    parser.add_argument("--no-pop", action="store_true",
                        help="hold the population at expected values (θ only)")
    args = parser.parse_args()
    if args.scenario:
        run_mc(args.scenario, n_draws=args.n_draws, seed=args.seed,
               sample_theta=not args.no_theta, sample_pop=not args.no_pop)
    else:
        _summary()
