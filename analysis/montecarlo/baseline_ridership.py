"""Stage 3: baseline_ridership — per-school calibration table.

Joins STARS route data (routes, distance, stops per school × program × year)
with RC enrollment (per school × year) and district-level rider counts from
quarterly_metrics. Also validates the draw-kernel hypothesis (gifted routes
are longer and have more stops than basic routes).

Sources (all tracked intermediates — no untracked data needed):
  analysis/montecarlo/stars_seattle/     (routes_by_school_year, quarterly_metrics)
  analysis/montecarlo/rc_seattle/        (enrollment)
  analysis/montecarlo/school_directory/  (stars_name_map, schools)

Outputs (tracked under analysis/montecarlo/baseline_ridership/):
  school_routes.csv       — per school_id × program × year: routes/distance/stops
  school_enrollment.csv   — per school_id × year: enrollment + demographics
  district_targets.csv    — per year: district-level riders/routes/buses by program
  kernel_check.csv        — per school × year: basic vs gifted distance comparison

Run:   python3 -m analysis.montecarlo.baseline_ridership [--build]

Loaders (pure-functional, for downstream stages):
  load_school_routes()     → DataFrame
  load_school_enrollment() → DataFrame
  load_district_targets()  → DataFrame
  load_kernel_check()      → DataFrame
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from analysis.montecarlo.stars_seattle import (
    load_quarterly_metrics,
    load_routes_by_school_year,
)
from analysis.montecarlo.rc_seattle import load_enrollment
from analysis.montecarlo.school_directory import load_schools, load_stars_name_map

_HERE = Path(__file__).resolve().parent
_DIR = _HERE / "baseline_ridership"

# School years dominated by COVID zero-ridership; excluded from district target means.
_COVID_YEARS = {"2020-2021"}  # 2021-22 is partial return — keep, but flag

# District-level metric codes to include in district_targets.csv
_TARGET_METRICS = [
    "basic_students_on_buses",
    "basic_students_in_walk_areas",
    "basic_students_transit_buses",
    "basic_students_total",
    "special_students_gifted",
    "special_students_early_ed",
    "special_students_bilingual",
    "special_students_homeless",
    "special_students_special_ed",
    "routes_basic",
    "routes_gifted",
    "routes_bilingual",
    "routes_early_ed",
    "routes_homeless",
    "buses_basic",
    "buses_gifted",
]


def _school_year_to_int(sy: str) -> int:
    """'2024-2025' → 2024 (fall year)."""
    return int(sy.split("-")[0])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build() -> None:
    _DIR.mkdir(exist_ok=True)

    schools = load_schools()
    stars_map = load_stars_name_map()

    # -----------------------------------------------------------------------
    # 1. school_routes.csv — per school_id × program × year
    # -----------------------------------------------------------------------
    rby = load_routes_by_school_year()
    rby = rby.copy()
    rby["school_id"] = rby["destination_name"].map(stars_map).astype("Int64")
    rby["year"] = rby["school_year"].apply(_school_year_to_int)

    # Drop non-SPS destinations (out-of-district / service sites)
    rby = rby[rby["school_id"].notna()].copy()

    # avg_stops_per_route: total_stops / n_route_rows (each route×quarter is one row)
    rby["avg_stops"] = rby["total_stops"] / rby["n_route_rows"]

    school_routes = rby[[
        "school_id", "school_year", "year", "program",
        "n_routes", "avg_distance_mean", "avg_stops",
    ]].rename(columns={"avg_distance_mean": "avg_distance_mi"})

    school_routes.to_csv(_DIR / "school_routes.csv", index=False)
    print(f"school_routes.csv:   {len(school_routes):5d} rows "
          f"({school_routes['school_id'].nunique()} schools, "
          f"{school_routes['year'].nunique()} years, "
          f"{school_routes['program'].nunique()} programs)")

    # -----------------------------------------------------------------------
    # 2. school_enrollment.csv — per school_id × year
    # -----------------------------------------------------------------------
    enr = load_enrollment()

    # "All Grades" rows give the school-level total; exclude district-total rows
    enr_school = enr[
        (enr["grade"] == "All Grades") & (~enr["is_district_total"])
    ].copy()

    # Join school_code → school_id via school_directory
    sc_to_id = schools.set_index("school_code")["school_id"]
    enr_school["school_id"] = enr_school["school_code"].map(sc_to_id).astype("Int64")
    enr_school = enr_school[enr_school["school_id"].notna()].copy()

    demo_cols = [
        "all_students", "low_income", "homeless", "highly_capable",
        "students_with_disabilities", "english_language_learners",
    ]
    school_enr = enr_school[["school_id", "year"] + demo_cols].rename(
        columns={"all_students": "enrollment"}
    )

    school_enr.to_csv(_DIR / "school_enrollment.csv", index=False)
    print(f"school_enrollment.csv: {len(school_enr):4d} rows "
          f"({school_enr['school_id'].nunique()} schools, "
          f"{school_enr['year'].nunique()} years)")

    # -----------------------------------------------------------------------
    # 3. district_targets.csv — per year × metric, averaged across quarters
    # -----------------------------------------------------------------------
    qm = load_quarterly_metrics()
    qm = qm[qm["metric_code"].isin(_TARGET_METRICS)].copy()
    qm["year"] = qm["school_year"].apply(_school_year_to_int)
    qm["is_covid"] = qm["school_year"].isin(_COVID_YEARS)

    # Mean across quarters per year (NaN-safe; COVID year kept but flagged)
    targets_long = qm.groupby(["year", "school_year", "is_covid", "metric_code"])[
        "value"
    ].mean().reset_index()
    targets = targets_long.pivot_table(
        index=["year", "school_year", "is_covid"],
        columns="metric_code",
        values="value",
    ).reset_index()
    targets.columns.name = None

    # Ensure all requested columns are present (some metrics absent in early years)
    for col in _TARGET_METRICS:
        if col not in targets.columns:
            targets[col] = float("nan")

    col_order = ["year", "school_year", "is_covid"] + _TARGET_METRICS
    targets = targets[col_order].sort_values("year")

    targets.to_csv(_DIR / "district_targets.csv", index=False)
    print(f"district_targets.csv:  {len(targets):3d} rows ({targets['year'].nunique()} years)")

    # -----------------------------------------------------------------------
    # 4. kernel_check.csv — gifted vs basic distance per school × year
    # -----------------------------------------------------------------------
    basic = school_routes[school_routes["program"] == "basic"][
        ["school_id", "year", "n_routes", "avg_distance_mi", "avg_stops"]
    ].rename(columns={
        "n_routes": "basic_n_routes",
        "avg_distance_mi": "basic_avg_dist_mi",
        "avg_stops": "basic_avg_stops",
    })

    gifted = school_routes[school_routes["program"] == "gifted"][
        ["school_id", "year", "n_routes", "avg_distance_mi", "avg_stops"]
    ].rename(columns={
        "n_routes": "gifted_n_routes",
        "avg_distance_mi": "gifted_avg_dist_mi",
        "avg_stops": "gifted_avg_stops",
    })

    kernel = basic.merge(gifted, on=["school_id", "year"], how="inner")
    kernel["gifted_dist_ratio"] = kernel["gifted_avg_dist_mi"] / kernel["basic_avg_dist_mi"]
    kernel["gifted_longer"] = kernel["gifted_avg_dist_mi"] > kernel["basic_avg_dist_mi"]

    # Add school metadata
    school_meta = schools[["school_id", "name", "classification", "is_hcc_site_current"]].copy()
    kernel = kernel.merge(school_meta, on="school_id", how="left")
    col_order = [
        "school_id", "name", "classification", "is_hcc_site_current", "year",
        "basic_n_routes", "basic_avg_dist_mi", "basic_avg_stops",
        "gifted_n_routes", "gifted_avg_dist_mi", "gifted_avg_stops",
        "gifted_dist_ratio", "gifted_longer",
    ]
    kernel = kernel[col_order].sort_values(["year", "school_id"])

    kernel.to_csv(_DIR / "kernel_check.csv", index=False)
    n_valid = kernel["gifted_longer"].sum()
    n_total = len(kernel)
    print(f"kernel_check.csv:    {n_total:4d} rows "
          f"({kernel['school_id'].nunique()} schools, "
          f"{n_valid}/{n_total} rows where gifted > basic distance)")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_school_routes() -> pd.DataFrame:
    """Per school_id × program × year: n_routes, avg_distance_mi, avg_stops."""
    return pd.read_csv(_DIR / "school_routes.csv")


def load_school_enrollment() -> pd.DataFrame:
    """Per school_id × year: enrollment + demographic counts."""
    return pd.read_csv(_DIR / "school_enrollment.csv")


def load_district_targets() -> pd.DataFrame:
    """Per year: district-level riders/routes/buses by program."""
    return pd.read_csv(_DIR / "district_targets.csv")


def load_kernel_check() -> pd.DataFrame:
    """Per school × year: basic vs gifted distance comparison."""
    return pd.read_csv(_DIR / "kernel_check.csv")


# ---------------------------------------------------------------------------
# Summary (__main__)
# ---------------------------------------------------------------------------

def _summary() -> None:
    sr = load_school_routes()
    se = load_school_enrollment()
    dt = load_district_targets()
    kc = load_kernel_check()

    print("=== school_routes.csv ===")
    yr = 2024
    sr24 = sr[sr["year"] == yr]
    print(f"  2024-25: {sr24['school_id'].nunique()} schools, "
          f"{sr24['program'].nunique()} programs")
    prog_stats = sr24.groupby("program")[["n_routes", "avg_distance_mi", "avg_stops"]].mean()
    print("  Per-program averages (2024-25):")
    print(prog_stats.round(2).to_string())

    print("\n=== school_enrollment.csv ===")
    se24 = se[se["year"] == yr]
    print(f"  2024-25: {len(se24)} schools, total enrolled: {se24['enrollment'].sum():,}")

    print("\n=== district_targets.csv ===")
    print("  Yellow-bus riders (basic_students_on_buses) by year:")
    for _, row in dt.sort_values("year").iterrows():
        flag = " [COVID]" if row["is_covid"] else ""
        print(f"    {row['school_year']}: "
              f"{row['basic_students_on_buses']:6,.0f} basic on-bus  "
              f"{row['special_students_gifted']:5,.0f} gifted{flag}")

    print("\n=== kernel_check.csv ===")
    kc24 = kc[kc["year"] == yr]
    n = len(kc24)
    n_ok = kc24["gifted_longer"].sum()
    print(f"  2024-25: {n} schools with both basic+gifted routes; "
          f"{n_ok}/{n} have gifted > basic distance")
    if n:
        print(f"  Basic  avg: {kc24['basic_avg_dist_mi'].mean():.2f} mi, "
              f"{kc24['basic_avg_stops'].mean():.1f} stops")
        print(f"  Gifted avg: {kc24['gifted_avg_dist_mi'].mean():.2f} mi, "
              f"{kc24['gifted_avg_stops'].mean():.1f} stops")
        print(f"  Mean gifted/basic dist ratio: {kc24['gifted_dist_ratio'].mean():.2f}")
        print("  Schools with gifted routes (2024-25):")
        for _, r in kc24.sort_values("gifted_avg_dist_mi", ascending=False).iterrows():
            flag = " *HCC*" if r["is_hcc_site_current"] else ""
            print(f"    {r['name']:30s} "
                  f"basic={r['basic_avg_dist_mi']:.2f}mi  "
                  f"gifted={r['gifted_avg_dist_mi']:.2f}mi  "
                  f"ratio={r['gifted_dist_ratio']:.2f}{flag}")

    # Kernel hypothesis check across all years (excluding COVID)
    kc_nc = kc[kc["year"] != 2020]
    pct = kc_nc["gifted_longer"].mean() * 100
    print(f"\n  Kernel hypothesis (all non-COVID years): "
          f"{pct:.1f}% of school×year rows have gifted > basic dist")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        _build()
    _summary()
