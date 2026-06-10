"""Parse the Seattle Public Schools transportation shapefiles.

This is the geographic foundation for the ridership Monte Carlo simulation. It
reads the seven shapefiles shipped under ``data/transit/shapes/Transpo Files``
and normalizes them into a small set of GeoDataFrames that share a common CRS,
a common join key (``school_id``), and consistent column names.

The source layers are:

  * ``Jan2025Upd_SPS_Locations``      -- 98 school point locations (EPSG:3857)
  * ``SchoolWalkZones_Albert``        -- per-school walk-zone polygons
  * ``sps_attendance_area_ES_Albert`` -- elementary attendance areas (+ poverty)
  * ``sps_attendance_area_MS_Albert`` -- middle-school attendance areas
  * ``sps_attendance_area_HS_Albert`` -- high-school attendance areas
  * ``sps_geozone_option_ESK8_Albert``-- option/choice ES+K8 eligibility zones
  * ``sps_geozone_option_HS_Albert``  -- option/choice HS eligibility zones

Everything is reprojected to EPSG:2926 (NAD83(HARN) / Washington North, US
survey feet) so that distances and areas come out in feet -- convenient for
walk-distance thresholds (SPS uses 1 mile for ES, 2 miles for MS/HS).

Run as a module for a summary:

    $ python3 -m analysis.montecarlo.parse_shapes
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd

# NAD83(HARN) / Washington North (ftUS). The walk-zone and attendance-area
# layers are already in this CRS; the school-location points are in Web
# Mercator and get reprojected into it. Feet are the natural unit for the
# 1-mile / 2-mile walk thresholds the district uses.
ANALYSIS_CRS = 2926

FEET_PER_MILE = 5280.0

# data/transit/shapes/Transpo Files, resolved relative to the repo root so the
# module works regardless of the current working directory.
SHAPES_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "transit" / "shapes" / "Transpo Files"
)

_LAYERS = {
    "locations": "Jan2025Upd_SPS_Locations",
    "walkzones": "SchoolWalkZones_Albert",
    "attendance_es": "sps_attendance_area_ES_Albert",
    "attendance_ms": "sps_attendance_area_MS_Albert",
    "attendance_hs": "sps_attendance_area_HS_Albert",
    "option_esk8": "sps_geozone_option_ESK8_Albert",
    "option_hs": "sps_geozone_option_HS_Albert",
}


@dataclass
class Shapes:
    """All normalized SPS geographic layers, sharing CRS and ``school_id``.

    ``regions`` is a single long-form GeoDataFrame stacking every attendance
    area and option geozone (columns: ``school_id, name, level, kind``, plus
    ``ms_sch``/``ms_zone``/``poverty`` for the ES rows). It is the convenient
    table for "which polygon does a residence fall in" point-in-polygon work.
    """

    locations: gpd.GeoDataFrame
    walkzones: gpd.GeoDataFrame
    attendance_es: gpd.GeoDataFrame
    attendance_ms: gpd.GeoDataFrame
    attendance_hs: gpd.GeoDataFrame
    option_esk8: gpd.GeoDataFrame
    option_hs: gpd.GeoDataFrame
    regions: gpd.GeoDataFrame


def _read(layer_key: str) -> gpd.GeoDataFrame:
    path = SHAPES_DIR / f"{_LAYERS[layer_key]}.shp"
    if not path.exists():
        raise FileNotFoundError(f"missing shapefile: {path}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gdf = gpd.read_file(path)
    return gdf.to_crs(ANALYSIS_CRS)


def _as_int_id(series) -> "gpd.pd.Series":
    """Coerce a float/int id column to a nullable integer."""
    return series.astype("float64").round().astype("Int64")


def load_locations() -> gpd.GeoDataFrame:
    """School point locations, reprojected to the analysis CRS.

    Columns: ``school_id, school_code, name, map_label, status, level,
    grades, geometry``.
    """
    g = _read("locations").rename(
        columns={
            "school_ID": "school_id",
            "SchoolCode": "school_code",
            "SchoolName": "name",
            "mapLabel": "map_label",
            "esmshs": "level",
        }
    )
    g["school_id"] = _as_int_id(g["school_id"])
    g["school_code"] = _as_int_id(g["school_code"])
    cols = ["school_id", "school_code", "name", "map_label", "status", "level", "grades", "geometry"]
    return g[cols]


def load_walkzones(drop_unidentified: bool = True) -> gpd.GeoDataFrame:
    """Walk-zone polygons, one (multi)polygon per school.

    The raw layer stores disjoint walk-zone pieces for some schools as separate
    rows; those are dissolved so each ``school_id`` has a single geometry.
    Rows with ``school_id == 0`` are unidentified program sites (e.g. "Svi 1418
    Prog") with no walk-zone name and are dropped by default.

    Columns: ``school_id, school_code, name, walkzone, grades, status, region,
    source, geometry``.
    """
    g = _read("walkzones").rename(
        columns={
            "SchoolID": "school_id",
            "SCHOOL_COD": "school_code",
            "SCHOOL_NAM": "name",
            "WalkZone": "walkzone",
            "Grades": "grades",
            "Geographic": "region",
        }
    )
    g["school_id"] = _as_int_id(g["school_id"])
    if drop_unidentified:
        g = g[g["school_id"] != 0]

    # Dissolve disjoint pieces of the same school into one geometry. Attribute
    # columns are taken from the first piece (they are identical per school).
    attrs = ["school_code", "name", "walkzone", "grades", "status", "region", "source"]
    g = g.dissolve(by="school_id", aggfunc="first")[attrs + ["geometry"]].reset_index()
    return g


def _load_region(layer_key: str, id_col: str, name_col: str, level: str, kind: str) -> gpd.GeoDataFrame:
    g = _read(layer_key).rename(columns={id_col: "school_id", name_col: "name"})
    g["school_id"] = _as_int_id(g["school_id"])
    g["level"] = level
    g["kind"] = kind
    keep = ["school_id", "name", "level", "kind"]
    # Preserve the elementary poverty + feeder-middle-school attributes.
    for extra in ("ms_sch", "ms_zone", "Poverty"):
        if extra in g.columns:
            out = "poverty" if extra == "Poverty" else extra
            g = g.rename(columns={extra: out})
            keep.append(out)
    return g[keep + ["geometry"]]


def load_attendance_es() -> gpd.GeoDataFrame:
    return _load_region("attendance_es", "es_sch", "es_zone", "ES", "attendance")


def load_attendance_ms() -> gpd.GeoDataFrame:
    return _load_region("attendance_ms", "ms_sch", "ms_zone", "MS", "attendance")


def load_attendance_hs() -> gpd.GeoDataFrame:
    return _load_region("attendance_hs", "HS_SCH", "HS_ZONE", "HS", "attendance")


def load_option_esk8() -> gpd.GeoDataFrame:
    return _load_region("option_esk8", "GEO_ID", "GEOZONE", "ESK8", "option")


def load_option_hs() -> gpd.GeoDataFrame:
    return _load_region("option_hs", "GEO_ID", "GEOZONE", "HS", "option")


def load_all() -> Shapes:
    """Load and normalize every layer into a :class:`Shapes` bundle."""
    locations = load_locations()
    walkzones = load_walkzones()
    att_es, att_ms, att_hs = load_attendance_es(), load_attendance_ms(), load_attendance_hs()
    opt_es, opt_hs = load_option_esk8(), load_option_hs()

    regions = gpd.GeoDataFrame(
        gpd.pd.concat([att_es, att_ms, att_hs, opt_es, opt_hs], ignore_index=True),
        crs=f"EPSG:{ANALYSIS_CRS}",
    )
    return Shapes(
        locations=locations,
        walkzones=walkzones,
        attendance_es=att_es,
        attendance_ms=att_ms,
        attendance_hs=att_hs,
        option_esk8=opt_es,
        option_hs=opt_hs,
        regions=regions,
    )


def _summary() -> None:
    s = load_all()
    print(f"CRS = EPSG:{ANALYSIS_CRS} (units: US feet); source = {SHAPES_DIR}")
    print()
    layers = [
        ("locations (points)", s.locations),
        ("walkzones", s.walkzones),
        ("attendance_es", s.attendance_es),
        ("attendance_ms", s.attendance_ms),
        ("attendance_hs", s.attendance_hs),
        ("option_esk8", s.option_esk8),
        ("option_hs", s.option_hs),
    ]
    for name, g in layers:
        geom = sorted(g.geom_type.unique().tolist())
        print(f"  {name:22} n={len(g):3}  {geom}")
    print()
    print(f"  regions (stacked attendance+option): n={len(s.regions)}")
    print(f"    by level: {s.regions.level.value_counts().to_dict()}")
    print(f"    by kind:  {s.regions.kind.value_counts().to_dict()}")
    # Sanity: every region/walkzone school_id should resolve to a location.
    loc_ids = set(s.locations.school_id.dropna().astype(int))
    for name, g in [("walkzones", s.walkzones), ("regions", s.regions)]:
        ids = set(g.school_id.dropna().astype(int))
        missing = sorted(ids - loc_ids)
        print(f"  {name} school_ids absent from locations: {missing}")


if __name__ == "__main__":
    _summary()
