"""Stage 4: acs_population — ACS + TIGER block-group data for SPS territory.

Pulls two ACS 5-year (2023) tables for King County (FIPS 53033):
  B01001  Sex by Age     — total school-age children by 5-yr band (block group)
  B14003  School Enrollment by Type of School by Age  (tract level —
          this detailed cross-tabulation is suppressed at block-group resolution
          in most ACS years; we pull it at tract level and apply the public-
          school fraction to block groups within each tract)

Downloads TIGER/Line 2023 block-group geometries for WA, filters to King County,
and clips them to the SPS service territory (union of all parse_shapes layers).

Writes two kinds of output:
  gitignored raw cache  data/census/
  tracked intermediates analysis/montecarlo/census_seattle/

Raw cache layout:
  data/census/acs5_B01001_king_bg.csv   (B01001 block-group pull)
  data/census/acs5_B14003_king_tract.csv (B14003 tract pull)
  data/census/tl_2023_53_bg.zip         (TIGER/Line WA block groups)

Tracked outputs (census_seattle/):
  block_groups.csv    — GEOID, geoid_tract, area_sqft, sps_area_sqft, sps_frac,
                        centroid_lat, centroid_lon, geometry_wkt (EPSG:2926)
  acs_age.csv         — GEOID, age_5_9, age_10_14, age_15_17, age_5_17
  acs_enrollment.csv  — GEOID, geoid_tract, pub_5_9, priv_5_9, pub_10_14,
                        priv_10_14, pub_15_17, priv_15_17 (tract totals joined
                        to each block group), pub_frac_5_9, pub_frac_10_14,
                        pub_frac_15_17

Requires CENSUS_API_KEY env var (free key from api.census.gov/signup.html).

Build:   python3 -m analysis.montecarlo.acs_population [--build] [--force]
Summary: python3 -m analysis.montecarlo.acs_population

Loaders (no untracked data needed after --build):
  load_block_groups()    → GeoDataFrame (EPSG:2926, geometry=intersection polygon)
  load_acs_age()         → DataFrame
  load_acs_enrollment()  → DataFrame
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from analysis.montecarlo import parse_shapes

_REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = _REPO_ROOT / "data" / "census"
OUT_DIR = Path(__file__).resolve().parent / "census_seattle"

_ACS_YEAR = 2023
_STATE_FIPS = "53"        # Washington
_COUNTY_FIPS = "033"      # King County
_TIGER_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/BG/tl_2023_53_bg.zip"
)

ANALYSIS_CRS = parse_shapes.ANALYSIS_CRS   # EPSG:2926 (WA State Plane N, US feet)

# B01001 Sex by Age — male school-age bands (004=5-9, 005=10-14, 006=15-17)
# + female counterparts (028, 029, 030). Available at block-group level.
_B01001_VARS = [
    "B01001_004E",   # male 5-9
    "B01001_005E",   # male 10-14
    "B01001_006E",   # male 15-17
    "B01001_028E",   # female 5-9
    "B01001_029E",   # female 10-14
    "B01001_030E",   # female 15-17
]

# B14003 School Enrollment by Type by Age. This detailed cross-tabulation is
# suppressed at block-group resolution; we pull at tract level.
# Public school enrolled:  male 005/006/007 (5-9/10-14/15-17)
#                          female 033/034/035
# Private school enrolled: male 014/015/016
#                          female 042/043/044
_B14003_VARS = [
    "B14003_005E", "B14003_006E", "B14003_007E",   # male public 5-9, 10-14, 15-17
    "B14003_014E", "B14003_015E", "B14003_016E",   # male private 5-9, 10-14, 15-17
    "B14003_033E", "B14003_034E", "B14003_035E",   # female public 5-9, 10-14, 15-17
    "B14003_042E", "B14003_043E", "B14003_044E",   # female private 5-9, 10-14, 15-17
]


# ---------------------------------------------------------------------------
# Census API helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    key = os.environ.get("CENSUS_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "CENSUS_API_KEY not set. Get a free key at "
            "https://api.census.gov/data/key_signup.html"
        )
    return key


def _fetch_acs(
    variables: list[str],
    geo_for: str,
    geo_in: str,
    dest: Path,
    label: str,
    force: bool,
) -> pd.DataFrame:
    """Generic ACS 5-year pull; cache result as CSV at dest."""
    if dest.exists() and not force:
        return pd.read_csv(dest, dtype=str)
    key = _api_key()
    var_str = ",".join(["NAME"] + variables)
    url = (
        f"https://api.census.gov/data/{_ACS_YEAR}/acs/acs5"
        f"?get={var_str}"
        f"&for={geo_for}"
        f"&in={geo_in}"
        f"&key={key}"
    )
    with urllib.request.urlopen(url) as r:
        rows = json.load(r)
    header, *data = rows
    df = pd.DataFrame(data, columns=header)
    df = df.drop(columns=["NAME"])
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    print(f"  fetched {label}: {len(df)} rows → {dest.name}")
    return df


# ---------------------------------------------------------------------------
# TIGER geometry
# ---------------------------------------------------------------------------

def _load_tiger(force: bool) -> gpd.GeoDataFrame:
    """Download TIGER/Line WA block groups; cache zip in data/census/."""
    zip_path = RAW_DIR / "tl_2023_53_bg.zip"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not zip_path.exists() or force:
        print(f"  downloading TIGER block groups from {_TIGER_URL} …")
        urllib.request.urlretrieve(_TIGER_URL, zip_path)
        print(f"    → {zip_path} ({zip_path.stat().st_size // 1024} KB)")

    with zipfile.ZipFile(zip_path) as z:
        shp_name = next(n for n in z.namelist() if n.endswith(".shp"))
        members = {Path(n).name: z.read(n) for n in z.namelist()}

    tmp_dir = RAW_DIR / "_tiger_extracted"
    tmp_dir.mkdir(exist_ok=True)
    for name, data in members.items():
        (tmp_dir / name).write_bytes(data)

    gdf = gpd.read_file(tmp_dir / Path(shp_name).name)
    gdf = gdf[gdf["COUNTYFP"] == _COUNTY_FIPS].copy()
    gdf["GEOID"] = gdf["GEOID"].str.strip()
    return gdf.to_crs(ANALYSIS_CRS)


# ---------------------------------------------------------------------------
# SPS territory boundary
# ---------------------------------------------------------------------------

def _sps_boundary():
    """Union of all parse_shapes layers → single SPS territory polygon."""
    shapes = parse_shapes.load_all()
    parts = []
    for layer in ["attendance_es", "attendance_ms", "attendance_hs",
                  "option_esk8", "option_hs"]:
        gdf = getattr(shapes, layer)
        parts.append(gdf.geometry.to_crs(ANALYSIS_CRS))
    combined = pd.concat(parts, ignore_index=True)
    return unary_union(combined)


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def _build_age(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate B01001 male+female → age bands."""
    df = df_raw[["GEOID"]].copy()
    for col in _B01001_VARS:
        df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0)
    df["age_5_9"]   = df_raw["B01001_004E"] + df_raw["B01001_028E"]
    df["age_10_14"] = df_raw["B01001_005E"] + df_raw["B01001_029E"]
    df["age_15_17"] = df_raw["B01001_006E"] + df_raw["B01001_030E"]
    df["age_5_17"]  = df["age_5_9"] + df["age_10_14"] + df["age_15_17"]
    return df.astype({c: int for c in df.columns if c != "GEOID"})


def _build_enrollment_tract(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate B14003 male+female → public/private by age band at tract level.

    Returns a DataFrame keyed by 11-digit geoid_tract with:
      pub_5_9, priv_5_9, pub_10_14, priv_10_14, pub_15_17, priv_15_17,
      pub_frac_5_9, pub_frac_10_14, pub_frac_15_17
    """
    # Build tract GEOID (state+county+tract = 11 digits)
    df_raw["geoid_tract"] = df_raw["state"] + df_raw["county"] + df_raw["tract"]
    df = df_raw[["geoid_tract"]].copy()
    for col in _B14003_VARS:
        df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0)
    df["pub_5_9"]    = df_raw["B14003_005E"] + df_raw["B14003_033E"]
    df["pub_10_14"]  = df_raw["B14003_006E"] + df_raw["B14003_034E"]
    df["pub_15_17"]  = df_raw["B14003_007E"] + df_raw["B14003_035E"]
    df["priv_5_9"]   = df_raw["B14003_014E"] + df_raw["B14003_042E"]
    df["priv_10_14"] = df_raw["B14003_015E"] + df_raw["B14003_043E"]
    df["priv_15_17"] = df_raw["B14003_016E"] + df_raw["B14003_044E"]
    for band in ["5_9", "10_14", "15_17"]:
        total = df[f"pub_{band}"] + df[f"priv_{band}"]
        df[f"pub_frac_{band}"] = (df[f"pub_{band}"] / total).where(total > 0)
    int_cols = [c for c in df.columns
                if c.startswith(("pub_", "priv_")) and "frac" not in c]
    return df.astype({c: int for c in int_cols})


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(force: bool = False, verbose: bool = True) -> None:
    """Fetch ACS + TIGER, clip to SPS, write census_seattle/ intermediates."""
    # 1. Fetch ACS tables
    df_b01001 = _fetch_acs(
        _B01001_VARS,
        geo_for="block%20group:*",
        geo_in=f"state:{_STATE_FIPS}%20county:{_COUNTY_FIPS}%20tract:*",
        dest=RAW_DIR / "acs5_B01001_king_bg.csv",
        label="B01001 (block group)",
        force=force,
    )
    df_b14003 = _fetch_acs(
        _B14003_VARS,
        geo_for="tract:*",
        geo_in=f"state:{_STATE_FIPS}%20county:{_COUNTY_FIPS}",
        dest=RAW_DIR / "acs5_B14003_king_tract.csv",
        label="B14003 (tract)",
        force=force,
    )

    # 2. Build per-block-group GEOID for B01001
    df_b01001["GEOID"] = (
        df_b01001["state"] + df_b01001["county"]
        + df_b01001["tract"] + df_b01001["block group"]
    )

    # 3. TIGER geometries → King County block groups (EPSG:2926)
    if verbose:
        print("  loading TIGER block-group geometries …")
    tiger = _load_tiger(force)

    # 4. SPS territory boundary
    if verbose:
        print("  computing SPS territory boundary …")
    sps_boundary = _sps_boundary()

    # 5. Clip block groups to SPS territory
    tiger["area_sqft"] = tiger.geometry.area
    tiger_sps = tiger.copy()
    tiger_sps["geometry"] = tiger.geometry.intersection(sps_boundary)
    tiger_sps["sps_area_sqft"] = tiger_sps.geometry.area
    tiger_sps["sps_frac"] = tiger_sps["sps_area_sqft"] / tiger_sps["area_sqft"]
    tiger_sps = tiger_sps[tiger_sps["sps_frac"] > 0].copy()

    centroids = tiger_sps.geometry.centroid.to_crs(4326)
    tiger_sps["centroid_lon"] = centroids.x
    tiger_sps["centroid_lat"] = centroids.y
    tiger_sps["geoid_tract"] = tiger_sps["GEOID"].str[:11]

    bg = tiger_sps[["GEOID", "geoid_tract", "area_sqft", "sps_area_sqft",
                     "sps_frac", "centroid_lat", "centroid_lon"]].copy()
    bg["geometry_wkt"] = tiger_sps.geometry.apply(lambda g: g.wkt)
    bg = bg.sort_values("GEOID").reset_index(drop=True)
    sps_geoids = set(bg["GEOID"])
    sps_tract_geoids = set(bg["geoid_tract"])

    # 6. Build age table (block-group level)
    age = _build_age(df_b01001)
    age_sps = age[age["GEOID"].isin(sps_geoids)].reset_index(drop=True)

    # 7. Build enrollment table (tract level) and join to block groups
    tract_enr = _build_enrollment_tract(df_b14003)
    tract_enr_sps = tract_enr[tract_enr["geoid_tract"].isin(sps_tract_geoids)].copy()

    # Join tract fractions to each block group (one bg row per tract row × bg rows in tract)
    enr_sps = bg[["GEOID", "geoid_tract"]].merge(
        tract_enr_sps, on="geoid_tract", how="left"
    ).sort_values("GEOID").reset_index(drop=True)

    # 8. Write outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bg.to_csv(OUT_DIR / "block_groups.csv", index=False)
    age_sps.to_csv(OUT_DIR / "acs_age.csv", index=False)
    enr_sps.to_csv(OUT_DIR / "acs_enrollment.csv", index=False)

    if verbose:
        n_bg = len(bg)
        n_king = len(tiger)
        pub_tot = enr_sps[["pub_5_9","pub_10_14","pub_15_17"]].sum().sum()
        priv_tot = enr_sps[["priv_5_9","priv_10_14","priv_15_17"]].sum().sum()
        print(f"\nSPS territory: {n_bg}/{n_king} King County block groups with overlap")
        print(f"  block_groups.csv:    {n_bg} rows")
        print(f"  acs_age.csv:         {len(age_sps)} rows  "
              f"(total 5-17 in SPS territory: {age_sps['age_5_17'].sum():,})")
        print(f"  acs_enrollment.csv:  {len(enr_sps)} rows  "
              f"(tract-level: pub={pub_tot/len(tract_enr_sps):.0f} avg per tract, "
              f"{pub_tot/(pub_tot+priv_tot):.1%} public)")
        print(f"\nWrote census intermediates to {OUT_DIR}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load(name: str) -> pd.DataFrame:
    path = OUT_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: "
            "python3 -m analysis.montecarlo.acs_population --build"
        )
    return pd.read_csv(path)


def load_block_groups() -> gpd.GeoDataFrame:
    """Block groups clipped to SPS territory (EPSG:2926 geometry)."""
    from shapely import wkt
    df = _load("block_groups")
    geoms = df["geometry_wkt"].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(df.drop(columns=["geometry_wkt"]), geometry=geoms, crs=ANALYSIS_CRS)
    return gdf


def load_acs_age() -> pd.DataFrame:
    """School-age population by band (5-9, 10-14, 15-17) per block group."""
    return _load("acs_age")


def load_acs_enrollment() -> pd.DataFrame:
    """Public/private enrollment by age band (tract level, joined to block groups)."""
    return _load("acs_enrollment")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary() -> None:
    bg = load_block_groups()
    age = load_acs_age()
    enr = load_acs_enrollment()

    print("=== block_groups.csv ===")
    print(f"  {len(bg)} block groups with SPS overlap")
    full = bg[bg["sps_frac"] > 0.99]
    print(f"  {len(full)} fully inside SPS territory (sps_frac > 99%)")
    print(f"  {len(bg) - len(full)} partially overlapping")
    print(f"  Total SPS area: {bg['sps_area_sqft'].sum() / 5280**2:.1f} sq miles")

    print("\n=== acs_age.csv ===")
    print(f"  {len(age)} block groups")
    print(f"  Total school-age children (5-17): {age['age_5_17'].sum():,}")
    print(f"  By band: 5-9={age['age_5_9'].sum():,}  "
          f"10-14={age['age_10_14'].sum():,}  "
          f"15-17={age['age_15_17'].sum():,}")

    print("\n=== acs_enrollment.csv ===")
    pub = enr[["pub_5_9","pub_10_14","pub_15_17"]].sum().sum()
    priv = enr[["priv_5_9","priv_10_14","priv_15_17"]].sum().sum()
    print(f"  (tract-level counts, one copy per block group in tract)")
    if pub + priv > 0:
        print(f"  Overall public fraction (sum across tracts): {pub/(pub+priv):.1%}")
    for band, label in [("5_9","5-9 (ES)"),("10_14","10-14 (MS)"),("15_17","15-17 (HS)")]:
        frac = enr[f"pub_frac_{band}"].mean()
        print(f"  {label}: avg tract public fraction = {frac:.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 4: ACS + TIGER population data")
    parser.add_argument("--build", action="store_true",
                        help="Fetch ACS + TIGER, clip to SPS, write census_seattle/")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if cached files exist")
    args = parser.parse_args()

    if args.build:
        build(force=args.force)
    else:
        _summary()
