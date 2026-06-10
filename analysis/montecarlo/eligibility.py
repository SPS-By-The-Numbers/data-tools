"""Stage 7: eligibility — walk-zone membership → walker vs bus-eligible fractions.

For every (block group, school) pair, computes ``walk_frac``: the fraction of
the block group's SPS-territory area that lies inside that school's official
walk zone. A child assigned to school S from block group G is a *walker*
(not bus-eligible) with probability walk_frac(G, S); the remainder are
bus-eligible for yellow-bus service.

BASELINE eligibility is pure geometry against the official walk-zone polygons
from parse_shapes — no fitting. (The calibrated-buffer approach in NOTES.md is
only for SCENARIO thresholds: pass scenario polygons to ``walk_fractions``.)

WARNING (NOTES.md s5 correction): STARS ``basic_students_in_walk_areas`` is
~96-324/yr — a reporting adjustment, NOT a count of children living in walk
zones. There is no independent district-level walker target; the end-to-end
validation below runs against ``basic_students_on_buses`` = 10,008 (2024-25).

Outputs (tracked under analysis/montecarlo/eligibility/):
  walker_fractions.csv — GEOID × school_id → walk_frac (nonzero rows only)

Run:   python3 -m analysis.montecarlo.eligibility [--build]
       (no --build: prints summary + the M4 combined-pipeline validation)

Loaders / API:
  load_walker_fractions()             → DataFrame
  walk_fractions(walkzones=...)       → recompute for scenario polygons
  bus_eligible(assignment, walk)      → per school × band eligible counts
  validate_pipeline()                 → M4 calibration check vs STARS
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

from analysis.montecarlo import parse_shapes
from analysis.montecarlo.acs_population import load_block_groups
from analysis.montecarlo.assignment import load_assignment
from analysis.montecarlo.baseline_ridership import (
    load_district_targets,
    load_school_routes,
)
from analysis.montecarlo.school_directory import load_schools

_HERE = Path(__file__).resolve().parent
OUT_DIR = _HERE / "eligibility"

BASE_YEAR = 2024

# Grade bands with basic-program yellow-bus service. STARS 2024-25 shows basic
# routes only at ES and MS destinations (HS students get no basic yellow bus).
_BUS_BANDS = ("es", "ms")


# ---------------------------------------------------------------------------
# Core geometry
# ---------------------------------------------------------------------------

def walk_fractions(walkzones: gpd.GeoDataFrame | None = None,
                   block_groups: gpd.GeoDataFrame | None = None) -> pd.DataFrame:
    """Fraction of each block group's SPS-territory area inside each walk zone.

    walkzones defaults to the official polygons (parse_shapes.load_walkzones);
    a scenario can pass any GeoDataFrame with ``school_id`` and ``geometry``
    (EPSG:2926). Returns DataFrame: GEOID, school_id, walk_frac — nonzero
    pairs only; absent pairs mean walk_frac = 0 (fully bus-eligible).

    The denominator is the block group's area *within SPS territory*
    (sps_area_sqft), matching how synth_pop weights children by sps_frac.
    """
    if walkzones is None:
        walkzones = parse_shapes.load_walkzones()
    if block_groups is None:
        block_groups = load_block_groups()

    inter = gpd.overlay(
        block_groups[["GEOID", "sps_area_sqft", "geometry"]],
        walkzones[["school_id", "geometry"]],
        how="intersection", keep_geom_type=False,
    )
    inter["a"] = inter.geometry.area
    wf = inter.groupby(["GEOID", "school_id"], as_index=False)["a"].sum()
    wf = wf.merge(block_groups[["GEOID", "sps_area_sqft"]], on="GEOID")
    wf["walk_frac"] = (wf["a"] / wf["sps_area_sqft"]).clip(upper=1.0)
    wf = wf[wf["walk_frac"] > 1e-6]
    return wf[["GEOID", "school_id", "walk_frac"]].sort_values(["school_id", "GEOID"])


# ---------------------------------------------------------------------------
# Combining with the assignment matrix
# ---------------------------------------------------------------------------

def bus_eligible(assignment: pd.DataFrame | None = None,
                 walk: pd.DataFrame | None = None) -> pd.DataFrame:
    """Expected walker / bus-eligible counts per school × grade band.

    Joins the Stage 6 assignment matrix with walk fractions:
      n_walk(G,S)     = n_expected × walk_frac
      n_eligible(G,S) = n_expected × (1 − walk_frac)
    Returns per school_id × grade_band: n_assigned, n_walk, n_bus_eligible.
    """
    if assignment is None:
        assignment = load_assignment()
    if walk is None:
        walk = load_walker_fractions()
    df = assignment.merge(walk, on=["GEOID", "school_id"], how="left")
    df["walk_frac"] = df["walk_frac"].fillna(0.0)
    df["n_walk"] = df["n_expected"] * df["walk_frac"]
    df["n_bus_eligible"] = df["n_expected"] - df["n_walk"]
    out = df.groupby(["school_id", "grade_band"], as_index=False).agg(
        n_assigned=("n_expected", "sum"),
        n_walk=("n_walk", "sum"),
        n_bus_eligible=("n_bus_eligible", "sum"),
    )
    return out


# ---------------------------------------------------------------------------
# Build / loaders
# ---------------------------------------------------------------------------

def build(verbose: bool = True) -> pd.DataFrame:
    OUT_DIR.mkdir(exist_ok=True)
    wf = walk_fractions()
    wf = wf.copy()
    wf["walk_frac"] = wf["walk_frac"].round(6)
    wf.to_csv(OUT_DIR / "walker_fractions.csv", index=False)
    if verbose:
        print(f"walker_fractions.csv: {len(wf)} nonzero (BG, school) pairs, "
              f"{wf.school_id.nunique()} schools, {wf.GEOID.nunique()} BGs")
        print(f"Wrote {OUT_DIR}")
    return wf


def load_walker_fractions() -> pd.DataFrame:
    """GEOID × school_id → walk_frac (nonzero pairs; missing = 0)."""
    path = OUT_DIR / "walker_fractions.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 -m analysis.montecarlo.eligibility --build")
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# M4 combined-pipeline validation
# ---------------------------------------------------------------------------

def validate_pipeline() -> dict:
    """Validate assignment × eligibility against the 2024-25 STARS targets.

    The on-bus propensity (Stage 8) is the free parameter, so the district
    total cannot be predicted independently yet. This check establishes:
      1. the basic bus-eligible pool is large enough (implied propensity < 1)
         and not absurdly large (implied propensity not << typical opt-in);
      2. per-school bus-eligible counts correlate with STARS basic route
         counts — the spatial shape is right even before propensity modeling.
    """
    elig = bus_eligible()
    schools = load_schools()
    routes = load_school_routes()
    targets = load_district_targets()
    t24 = targets[targets.year == BASE_YEAR].iloc[0]
    on_bus = float(t24["basic_students_on_buses"])
    gifted_riders = float(t24["special_students_gifted"])

    basic24 = routes[(routes.year == BASE_YEAR) & (routes.program == "basic")]
    basic_ids = set(basic24.school_id)

    # Basic program: ES+MS bands at schools that actually run basic routes.
    pool = elig[elig.grade_band.isin(_BUS_BANDS)]
    pool_basic = pool[pool.school_id.isin(basic_ids)]
    eligible_total = pool_basic.n_bus_eligible.sum()
    implied_propensity = on_bus / eligible_total

    # Per-school shape check: bus-eligible kids vs basic route counts.
    per_school = pool_basic.groupby("school_id").n_bus_eligible.sum().rename("eligible")
    cmp = pd.concat([per_school, basic24.groupby("school_id").n_routes.sum()], axis=1).dropna()
    pearson = cmp["eligible"].corr(cmp["n_routes"])
    spearman = cmp["eligible"].corr(cmp["n_routes"], method="spearman")

    # Gifted reference: pure HCC pathway sites (no basic routes by design).
    hcc_ids = set(schools[schools.is_hcc_site_current].school_id) - basic_ids
    hcc_pool = elig[(elig.school_id.isin(hcc_ids)) & (elig.grade_band == "es")]
    hcc_eligible = hcc_pool.n_bus_eligible.sum()

    walkers_at_basic = pool_basic.n_walk.sum()
    res = {
        "eligible_total": eligible_total,
        "on_bus_target": on_bus,
        "implied_propensity": implied_propensity,
        "walkers_at_basic_schools": walkers_at_basic,
        "pearson_routes": pearson,
        "spearman_routes": spearman,
        "n_basic_schools": len(cmp),
        "hcc_es_eligible": hcc_eligible,
        "gifted_riders_target": gifted_riders,
    }

    print("=== M4 combined-pipeline validation (2024-25) ===")
    print(f"  basic-route schools (STARS): {len(cmp)}  "
          f"[ES+MS bands only — no HS basic routes exist]")
    print(f"  assigned to them (ES+MS):       {pool_basic.n_assigned.sum():9,.0f}")
    print(f"  living in their walk zones:     {walkers_at_basic:9,.0f}")
    print(f"  bus-eligible pool:              {eligible_total:9,.0f}")
    print(f"  STARS basic on-bus target:      {on_bus:9,.0f}")
    print(f"  implied on-bus propensity:      {implied_propensity:9.3f}  "
          "(Stage 8 fits this; sane range ~0.25-0.75)")
    print(f"  per-school eligible vs basic routes: "
          f"Pearson r={pearson:.3f}, Spearman ρ={spearman:.3f}")
    print(f"  pure-HCC ES sites bus-eligible: {hcc_eligible:9,.0f}  "
          f"(gifted riders target {gifted_riders:,.0f})")
    ok = (0.2 <= implied_propensity <= 0.9) and pearson > 0.5
    print(f"  STRUCTURAL CHECK: {'PASS' if ok else 'FAIL'} "
          "(propensity in [0.2, 0.9] and Pearson > 0.5)")
    return res


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary() -> None:
    wf = load_walker_fractions()
    schools = load_schools().set_index("school_id")
    print("=== walker_fractions.csv ===")
    print(f"  {len(wf)} nonzero (BG, school) pairs; "
          f"{wf.school_id.nunique()} schools with walk-zone overlap")
    in_dir = wf[wf.school_id.isin(schools.index)]
    per_school = in_dir.groupby("school_id").walk_frac.sum()
    print(f"  schools absent from locations (closed/leased, kept): "
          f"{sorted(set(wf.school_id) - set(schools.index))}")
    top = per_school.nlargest(5)
    print("  largest walk-zone footprints (sum of BG fractions ~ BG-equivalents):")
    for sid, v in top.items():
        print(f"    {schools.loc[sid, 'name']:30s} {v:6.1f}")
    print()
    validate_pipeline()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 7: walk-zone eligibility")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        _summary()
