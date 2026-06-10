"""Extract the Seattle Public Schools (ccddd 17001) slice of the STARS data.

STARS = OSPI's Student Transportation Allocation Reporting System. The repo's
`out_stars/` directory holds the fully-parsed multi-district STARS tables (see
the STARS reconstruction work under `analysis/stars_*`). That directory is
gitignored working data, so this module filters it down to Seattle and writes
small, **tracked** intermediate CSVs under `analysis/montecarlo/stars_seattle/`.
Future sessions can then load the Seattle slice instantly without re-touching
(or even having) the big `out_stars/` files.

Seattle = county-district code **17001** = "Seattle Public Schools". Coverage is
school years 2017-2018 .. 2025-2026.

What's here (the ridership ground truth for calibrating the Monte Carlo):
  * routes              -- per-route detail: destination (school), program,
                           stop counts, average_distance, by year+quarter.
  * quarterly_metrics   -- district student/route/bus counts by program and
                           quarter (long form: year, quarter, metric_code, val).
  * efficiency / cohort -- annual buses, basic/special riders, avg distance,
                           destinations, relative efficiency rating.
  * kpi                 -- riders/bus and cost/rider KPIs by year.
  * operations_allocation -- the STARS funding-formula line items by year.
  * destinations        -- distinct route destination names (to be mapped to
                           parse_shapes `school_id` in a later stage).
  * routes_by_school_year -- routes/stops/avg-distance rolled up per
                           destination x program x year.
  * d_*                 -- the dimension/lookup tables, copied verbatim so the
                           metric/section/program codes are decodable in place.

Build the intermediates (reads out_stars/, writes stars_seattle/):

    $ python3 -m analysis.montecarlo.stars_seattle --build

Then in code:

    from analysis.montecarlo import stars_seattle as ss
    routes = ss.load_routes()        # reads the intermediate CSV
    eff    = ss.load_efficiency()
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

SEATTLE_CCDDD = "17001"

_REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = _REPO_ROOT / "out_stars"
OUT_DIR = Path(__file__).resolve().parent / "stars_seattle"

# Source fact tables -> intermediate basename, with columns to coerce numeric.
# Columns absent in a given file are silently skipped.
_NUMERIC = {
    "stop_count", "total_stops", "average_distance", "value", "weight_pct",
    "prior_year_expenditures", "buses", "basic_riders", "special_riders",
    "avg_distance", "num_destinations", "land_area", "k_rte",
    "road_miles_per_sq_mile", "students_per_road_mile",
    "target_prior_year_expenditures", "target_buses",
    "relative_efficiency_rating", "item_value", "coefficient",
    "calculated_value", "amount", "running_total",
}

# (source filename, intermediate name). These are the per-district fact tables.
_FACT_TABLES = [
    ("stars_quarterly_district_route.csv", "routes"),
    ("stars_quarterly_district.csv", "quarterly_metrics"),
    ("stars_efficiency.csv", "efficiency"),
    ("stars_efficiency_cohort.csv", "efficiency_cohort"),
    ("stars_kpi.csv", "kpi"),
    ("stars_operations_allocation.csv", "operations_allocation"),
]

# Dimension tables copied verbatim (no district column to filter on).
_DIM_TABLES = [
    "d_stars_quarterly_metric.csv",
    "d_stars_kpi_metric.csv",
    "d_stars_route_program.csv",
    "d_stars_ops_allocation_section.csv",
    "d_stars_ops_allocation_item.csv",
    "d_stars_quarter.csv",
]

# Columns that carry no Seattle-specific signal once we've filtered to 17001.
_DROP_CONSTANT = ["ccddd", "county", "district"]


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if col in _NUMERIC:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _filter_seattle(src: Path) -> pd.DataFrame:
    df = pd.read_csv(src, dtype=str)
    df = df[df["ccddd"] == SEATTLE_CCDDD].copy()
    df = _coerce_numeric(df)
    drop = [c for c in _DROP_CONSTANT if c in df.columns]
    return df.drop(columns=drop)


def build(verbose: bool = True) -> None:
    """Filter out_stars/ to Seattle and write the intermediate CSVs."""
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(
            f"{SOURCE_DIR} not found. The Seattle intermediates in {OUT_DIR} are "
            "tracked and may already be sufficient; only --build needs out_stars/."
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pd.DataFrame] = {}
    for src_name, out_name in _FACT_TABLES:
        df = _filter_seattle(SOURCE_DIR / src_name)
        frames[out_name] = df
        df.to_csv(OUT_DIR / f"{out_name}.csv", index=False)
        if verbose:
            print(f"  {out_name:24} {len(df):>6} rows -> {out_name}.csv")

    for dim in _DIM_TABLES:
        shutil.copyfile(SOURCE_DIR / dim, OUT_DIR / dim)
    if verbose:
        print(f"  copied {len(_DIM_TABLES)} dimension tables (d_*.csv)")

    _build_derived(frames["routes"], verbose=verbose)
    if verbose:
        print(f"\nWrote Seattle STARS intermediates to {OUT_DIR}")


def _build_derived(routes: pd.DataFrame, verbose: bool = True) -> None:
    """Derived convenience tables built from the route detail."""
    # Distinct destinations (route targets) — seeds the school_id mapping later.
    dest = (
        routes.groupby("destination_name")
        .agg(
            n_route_rows=("route_number", "size"),
            n_years=("school_year", "nunique"),
            first_year=("school_year", "min"),
            last_year=("school_year", "max"),
        )
        .reset_index()
        .sort_values("destination_name")
    )
    # school_id is filled in a later stage (fuzzy-match to parse_shapes names).
    dest.insert(1, "school_id", pd.NA)
    dest.to_csv(OUT_DIR / "destinations.csv", index=False)

    # routes/stops/distance rolled up per destination x program x year.
    agg = (
        routes.groupby(["school_year", "destination_name", "program"])
        .agg(
            n_routes=("route_number", "nunique"),
            n_route_rows=("route_number", "size"),
            total_stops=("stop_count", "sum"),
            avg_distance_mean=("average_distance", "mean"),
            avg_distance_min=("average_distance", "min"),
            avg_distance_max=("average_distance", "max"),
        )
        .reset_index()
        .sort_values(["school_year", "destination_name", "program"])
    )
    agg.to_csv(OUT_DIR / "routes_by_school_year.csv", index=False)
    if verbose:
        print(f"  destinations             {len(dest):>6} rows -> destinations.csv")
        print(f"  routes_by_school_year    {len(agg):>6} rows -> routes_by_school_year.csv")


# --- loaders: read the tracked intermediates (preferred over out_stars) -------

def _load(name: str) -> pd.DataFrame:
    path = OUT_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python3 -m analysis.montecarlo.stars_seattle "
            "--build` (requires out_stars/)."
        )
    return pd.read_csv(path)


def load_routes() -> pd.DataFrame:
    return _load("routes")


def load_quarterly_metrics() -> pd.DataFrame:
    return _load("quarterly_metrics")


def load_efficiency() -> pd.DataFrame:
    return _load("efficiency")


def load_efficiency_cohort() -> pd.DataFrame:
    return _load("efficiency_cohort")


def load_kpi() -> pd.DataFrame:
    return _load("kpi")


def load_operations_allocation() -> pd.DataFrame:
    return _load("operations_allocation")


def load_destinations() -> pd.DataFrame:
    return _load("destinations")


def load_routes_by_school_year() -> pd.DataFrame:
    return _load("routes_by_school_year")


def _summary() -> None:
    print(f"Seattle STARS intermediates in {OUT_DIR}\n")
    if not OUT_DIR.exists():
        print("  (not built yet — run with --build)")
        return
    eff = load_efficiency().sort_values("school_year")
    print("Annual ridership / efficiency (from efficiency.csv):")
    cols = ["school_year", "buses", "basic_riders", "special_riders",
            "avg_distance", "num_destinations", "relative_efficiency_rating"]
    print(eff[cols].to_string(index=False))
    routes = load_routes()
    print(f"\nRoute detail: {len(routes)} rows, "
          f"{routes.destination_name.nunique()} distinct destinations, "
          f"years {routes.school_year.min()}..{routes.school_year.max()}")
    print(f"  by program: {routes.program.value_counts().to_dict()}")


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv:
        build()
    else:
        _summary()
