"""Stage 9: scenarios — machine-readable scenario spec + the 5 ops → mutated world.

A *scenario* is an ordered list of composable operations applied to a copy of
the baseline world (geography + school directory + draw kernels). ``apply``
produces a :class:`World` whose pieces feed the existing stage hooks
unchanged:

    world.flows / world.col_marg / world.weights → assignment.build_matrix(...)
    world.walkzones                              → eligibility.walk_fractions(...)
    world.points / world.basic_ids               → ridership.basic_cells(...)
    world.gifted                                 → scenario_gifted_pool(...)
    everything                                   → ridership.expected_riders(...)

Operations (see NOTES.md "Architecture (LOCKED)"):

  set_walk_threshold             {level: ES|MS|HS, miles}
  scale_walkzone                 {school_id, factor | miles}
  close_school                   {school_id, receivers?: [ids], hcc_receiver?: id}
  convert_option_to_neighborhood {school_id, stay_rate?: float}
  move_school                    {school_id, new_location: [x_ft, y_ft] (EPSG:2926)
                                  | {lat, lon}, move_geozone?: bool}

Key modeling choices:

  * The residence-area partition (block-group → attendance-area weights) is
    FIXED across scenarios — areas are geographic strata of where kids live;
    ops only edit the DESTINATION side (flow columns, enrollment marginals,
    walk zones, school points). This keeps the OD anchoring intact.
  * Walk-zone resizing uses CALIBRATED BUFFERS (NOTES.md): per school, fit the
    crow-flies multiplier m so a circle of radius m·T·5280ft around the school
    point reproduces the official polygon's area at the current threshold T
    (ES 1 mi, MS/HS 2 mi); scenario thresholds reuse m. The empty scenario
    keeps the official polygons (buffers only replace zones an op touches).
  * Closure: the closed school's flow column moves to receiving schools —
    kids stay where they live, only their destination changes. Attendance
    kids → receiving neighborhood school(s) (default: 3 nearest open
    same-level neighborhood schools, split per residence area in proportion
    to the receivers' existing draw from that area, nearest receiver as
    fallback); option kids → next option site (default: nearest open
    same-level option school); HCC pathway relocates INTACT to hcc_receiver
    (default: nearest other gifted site of the same band) — its member
    feeder areas and HC enrollment move with it (user default, NOTES open
    question 3). Caveat: a mixed site (e.g. Thurgood Marshall) moves its HC
    enrollment via the gifted table but its full basic flow column via the
    neighborhood rule.
  * Conversion (option → neighborhood): the school's draw becomes
    attendance-style — residents of its geozone attend it at the band's
    observed stay-rate; its previous (distance-decay) enrollees return to
    their areas' other destinations pro-rata. STEADY-STATE semantics (no
    grandfathering of current distant enrollees — NOTES open question 2).
  * Move: the walk zone recenters as a calibrated buffer at the new point;
    an option school's flow column is re-derived from the fitted exponential
    decay kernel at the new point (column total preserved); a neighborhood
    school keeps its flows (attendance area unchanged) — only distances and
    the walk zone change. ``move_geozone`` translates the geozone polygon for
    any LATER convert op (the fitted option kernel itself has no geozone
    term, per NOTES s6).
  * Enrollment marginals follow the flows: after each op, each school×band
    RC target is rescaled by its flow-total ratio and the band total is
    re-normalized to the baseline band total (closures/conversions move kids
    between schools, never out of the district).
  * Scenario evaluation uses the BASELINE-solved propensity scale and
    baseline covariate centering (``fixed_scale`` / ``covar_means`` in
    ridership.py) — re-solving would renormalize every scenario back to the
    10,008 district target and all deltas would vanish.

Outputs: none tracked — scenarios are inputs (scenarios/*.json) + an in-memory
evaluation. ``run_scenario`` returns baseline/scenario rider tables + deltas.

Run:   python3 -m analysis.montecarlo.scenarios                # list + spec check
       python3 -m analysis.montecarlo.scenarios --validate     # empty == baseline
       python3 -m analysis.montecarlo.scenarios --run <name|path> [--quiet]

API (Stage 10 entry points):
  baseline_world()              → World (cached, copy-on-apply)
  load_scenario(path)           → Scenario
  apply(scenario, world=None)   → mutated World copy
  evaluate(world, params=None, pop=None) → dict(assignment, walk, cells,
                                                gifted, riders, info)
  run_scenario(scenario, ...)   → dict(baseline, scenario, deltas, district)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely import affinity

from analysis.montecarlo import parse_shapes
from analysis.montecarlo import ridership as rid
from analysis.montecarlo.assignment import (
    _bg_centroids,
    _pop_column,
    _school_points,
    bg_area_weights,
    build_matrix,
    column_marginals,
    load_kernel_params,
    observed_flows,
)
from analysis.montecarlo.baseline_ridership import (
    load_school_enrollment,
    load_school_routes,
)
from analysis.montecarlo.eligibility import walk_fractions
from analysis.montecarlo.school_directory import load_schools
from analysis.montecarlo.synth_population import load_synth_pop

_HERE = Path(__file__).resolve().parent
SCENARIO_DIR = _HERE / "scenarios"

BASE_YEAR = 2024
FEET_PER_MILE = parse_shapes.FEET_PER_MILE

# SPS walk thresholds by school level, miles (NOTES.md — open question 4 asks
# to verify the exact rule; these are the working values).
WALK_THRESHOLD_MI = {"ES": 1.0, "MS": 2.0, "HS": 2.0}

# Default HCC era for pathway-membership lookups (matches ridership.gifted_pool).
HCC_ERA = "pathway_2023_2025"

_OPS = ("set_walk_threshold", "scale_walkzone", "close_school",
        "convert_option_to_neighborhood", "move_school")


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------

@dataclass
class World:
    """A copy of the baseline world that scenario ops mutate in place.

    ``weights`` (block-group × residence-area membership) is shared, never
    mutated — the residence strata are fixed. Everything else is deep-copied
    by :meth:`copy`.
    """
    points: pd.Series              # school_id → Point (EPSG:2926)
    walkzones: gpd.GeoDataFrame    # school_id, geometry
    schools: pd.DataFrame          # canonical directory (classification mutable)
    flows: pd.DataFrame            # grade_band, area_id, school_id, n, p
    col_marg: pd.DataFrame         # school_id, grade_band, target
    weights: pd.DataFrame          # bg_area_weights — FIXED residence strata
    att_layers: dict               # band → attendance-area GeoDataFrame (FIXED)
    geozones: gpd.GeoDataFrame     # option geozones: school_id, level, geometry
    basic_ids: set                 # schools with basic yellow-bus service
    gifted: pd.DataFrame           # school_id, grade_band, kernel, n_hc, member_area_ids
    walk_mult: pd.Series           # school_id → calibrated buffer multiplier
    stay_rates: dict               # band → observed stay-rate
    band_targets: dict             # band → baseline enrollment total (conserved)
    closed: set = field(default_factory=set)
    pop: pd.DataFrame | None = None

    def copy(self) -> "World":
        return World(
            points=self.points.copy(),
            walkzones=self.walkzones.copy(),
            schools=self.schools.copy(),
            flows=self.flows.copy(),
            col_marg=self.col_marg.copy(),
            weights=self.weights,            # shared, never mutated
            att_layers=self.att_layers,      # shared, never mutated
            geozones=self.geozones.copy(),
            basic_ids=set(self.basic_ids),
            gifted=self.gifted.copy(deep=True),
            walk_mult=self.walk_mult.copy(),
            stay_rates=dict(self.stay_rates),
            band_targets=dict(self.band_targets),
            closed=set(self.closed),
            pop=self.pop,
        )

    def level(self, school_id: int) -> str:
        return self.schools.set_index("school_id").loc[school_id, "level"]


_BASELINE: World | None = None


def _hcc_member_area_ids(site_name: str, era: str = HCC_ERA) -> list[int]:
    """ES attendance-area school_ids feeding an HCC pathway site (exact
    replica of the lookup in assignment.kernel_bg_weights)."""
    pathways = pd.read_csv(_HERE / "hcc_pathways_es.csv")
    member_areas = pathways.loc[pathways[era] == site_name, "es_name"]
    att = parse_shapes.load_attendance_es()
    return att[att.name.isin(member_areas)].school_id.astype(int).tolist()


def _baseline_gifted(schools: pd.DataFrame, year: int = BASE_YEAR) -> pd.DataFrame:
    """Gifted-route sites with kernel kind, HC enrollment, ES member areas."""
    routes = load_school_routes()
    g = routes[(routes.year == year) & (routes.program == "gifted")]
    sn = schools.set_index("school_id")
    se = load_school_enrollment()
    hc = se[se.year == year].set_index("school_id")["highly_capable"]
    rows = []
    for sid in sorted(g.school_id.unique()):
        level = sn.loc[sid, "level"]
        if level == "ES":
            kernel, band = "hcc_pathway", "es"
            members = _hcc_member_area_ids(sn.loc[sid, "name"])
        else:
            kernel, band = "od_column", "ms"
            members = []
        rows.append({"school_id": int(sid), "grade_band": band, "kernel": kernel,
                     "n_hc": float(hc.get(sid, 0) or 0), "member_area_ids": members})
    return pd.DataFrame(rows)


def _baseline_walk_mult(walkzones: gpd.GeoDataFrame, points: pd.Series,
                        schools: pd.DataFrame) -> pd.Series:
    """Calibrated buffer multiplier per school.

    m = r_equiv / (T·5280) where r_equiv = sqrt(area/π) of the official
    polygon and T is the current threshold for the school's level. Schools
    without an official zone get their level's median m.
    """
    sn = schools.set_index("school_id")
    mult = {}
    for r in walkzones.itertuples():
        sid = int(r.school_id)
        if sid not in sn.index:
            continue  # closed/leased sites kept in the layer but not modeled
        T_ft = WALK_THRESHOLD_MI[sn.loc[sid, "level"]] * FEET_PER_MILE
        mult[sid] = float(np.sqrt(r.geometry.area / np.pi) / T_ft)
    s = pd.Series(mult, name="walk_mult")
    level_median = {lvl: s[s.index.isin(sn[sn.level == lvl].index)].median()
                    for lvl in ("ES", "MS", "HS")}
    for sid in sn.index.difference(s.index):
        s.loc[int(sid)] = level_median[sn.loc[sid, "level"]]
    return s.sort_index()


def baseline_world(rebuild: bool = False) -> World:
    """The cached baseline world. Callers get copies via ``apply``."""
    global _BASELINE
    if _BASELINE is not None and not rebuild:
        return _BASELINE

    schools = load_schools()
    points = _school_points()
    walkzones = parse_shapes.load_walkzones()[["school_id", "geometry"]].copy()
    walkzones["school_id"] = walkzones["school_id"].astype(int)
    flows = observed_flows()
    flows["n"] = flows["n"].astype(float)  # ops scale columns fractionally
    col_marg = column_marginals()
    weights = bg_area_weights()
    att_layers = {"es": parse_shapes.load_attendance_es(),
                  "ms": parse_shapes.load_attendance_ms(),
                  "hs": parse_shapes.load_attendance_hs()}
    geozones = gpd.GeoDataFrame(
        pd.concat([parse_shapes.load_option_esk8(), parse_shapes.load_option_hs()],
                  ignore_index=True),
        crs=walkzones.crs)[["school_id", "level", "geometry"]]
    geozones["school_id"] = geozones["school_id"].astype(int)
    routes = load_school_routes()
    basic_ids = set(int(s) for s in routes[
        (routes.year == BASE_YEAR) & (routes.program == "basic")].school_id)

    stay = {}
    for band, f in flows.groupby("grade_band"):
        stay[band] = float(f.loc[f.area_id == f.school_id, "n"].sum() / f.n.sum())
    band_targets = col_marg.groupby("grade_band")["target"].sum().to_dict()

    _BASELINE = World(
        points=points, walkzones=walkzones, schools=schools, flows=flows,
        col_marg=col_marg, weights=weights, att_layers=att_layers,
        geozones=geozones, basic_ids=basic_ids,
        gifted=_baseline_gifted(schools),
        walk_mult=_baseline_walk_mult(walkzones, points, schools),
        stay_rates=stay, band_targets=band_targets,
    )
    return _BASELINE


# ---------------------------------------------------------------------------
# Shared op helpers
# ---------------------------------------------------------------------------

def _recompute_p(flows: pd.DataFrame) -> pd.DataFrame:
    flows = flows[flows.n > 0].copy()
    flows["p"] = flows["n"] / flows.groupby(["grade_band", "area_id"])["n"].transform("sum")
    return flows.reset_index(drop=True)


def _rescale_col_marg(world: World, flows_before: pd.DataFrame) -> None:
    """Make enrollment marginals track the flow edits.

    Each school×band target is scaled by its flow-total ratio (new columns
    get the band's average target-per-flow); each band is then re-normalized
    to its baseline total — ops move kids between schools, never out of the
    district.
    """
    before = flows_before.groupby(["grade_band", "school_id"])["n"].sum()
    after = world.flows.groupby(["grade_band", "school_id"])["n"].sum()
    cm = world.col_marg.set_index(["grade_band", "school_id"])["target"]

    new = {}
    for (band, sid), n_after in after.items():
        n_before = before.get((band, sid), 0.0)
        t_before = cm.get((band, sid), np.nan)
        if n_before > 0 and not np.isnan(t_before):
            new[(band, sid)] = t_before * n_after / n_before
        else:
            # new column: estimate target from the band's target-per-flow rate
            rate = world.band_targets[band] / before[before.index.get_level_values(0) == band].sum()
            new[(band, sid)] = n_after * rate
    out = pd.Series(new, name="target")
    out.index.names = ["grade_band", "school_id"]
    # conserve the band totals exactly
    bt = out.groupby(level="grade_band").sum()
    fac = np.array([world.band_targets[b] / bt[b]
                    for b in out.index.get_level_values("grade_band")])
    out = pd.Series(out.to_numpy() * fac, index=out.index, name="target")
    world.col_marg = out.reset_index()[["school_id", "grade_band", "target"]]


def _buffer_zone(world: World, school_id: int, radius_ft: float) -> None:
    """Replace one school's walk zone with a circular buffer."""
    geom = world.points.loc[school_id].buffer(radius_ft)
    wz = world.walkzones
    if (wz.school_id == school_id).any():
        wz.loc[wz.school_id == school_id, "geometry"] = geom
    else:
        world.walkzones = pd.concat(
            [wz, gpd.GeoDataFrame({"school_id": [school_id]}, geometry=[geom], crs=wz.crs)],
            ignore_index=True)


def _nearest(world: World, school_id: int, candidates: list[int], k: int = 1) -> list[int]:
    """k nearest candidate schools to ``school_id`` by point distance."""
    p = world.points.loc[school_id]
    d = {c: p.distance(world.points.loc[c]) for c in candidates if c != school_id}
    return [c for c, _ in sorted(d.items(), key=lambda kv: kv[1])[:k]]


def _open_ids(world: World, classification: str | None = None,
              level: str | None = None) -> list[int]:
    s = world.schools
    m = ~s.school_id.isin(world.closed)
    if classification:
        m &= s.classification == classification
    if level:
        m &= s.level == level
    return [int(x) for x in s.loc[m, "school_id"]]


# ---------------------------------------------------------------------------
# The 5 ops
# ---------------------------------------------------------------------------

def op_set_walk_threshold(world: World, level: str, miles: float) -> None:
    """Regenerate every open school's walk zone at a new threshold (one level)."""
    for sid in _open_ids(world, level=level):
        _buffer_zone(world, sid, world.walk_mult.loc[sid] * miles * FEET_PER_MILE)


def op_scale_walkzone(world: World, school_id: int,
                      factor: float | None = None,
                      miles: float | None = None) -> None:
    """Resize one school's walk zone via its calibrated buffer."""
    if (factor is None) == (miles is None):
        raise ValueError("scale_walkzone: give exactly one of factor / miles")
    base_mi = WALK_THRESHOLD_MI[world.level(school_id)]
    eff_mi = miles if miles is not None else factor * base_mi
    _buffer_zone(world, school_id, world.walk_mult.loc[school_id] * eff_mi * FEET_PER_MILE)


def _move_flow_column(world: World, school_id: int, receivers: list[int]) -> None:
    """Reassign every (band, area) flow of ``school_id`` to the receivers.

    Per residence area, split in proportion to the receivers' existing draw
    from that area; nearest receiver takes everything if none of them draws
    from it. Kids stay where they live.
    """
    flows = world.flows
    moved = flows[flows.school_id == school_id]
    keep = flows[flows.school_id != school_id].copy()
    add = []
    for band, mb in moved.groupby("grade_band"):
        existing = keep[(keep.grade_band == band) & keep.school_id.isin(receivers)]
        draw = existing.set_index(["area_id", "school_id"])["n"]
        for r in mb.itertuples():
            w = np.array([draw.get((r.area_id, rec), 0.0) for rec in receivers])
            if w.sum() <= 0:
                near = _nearest(world, int(r.area_id) if int(r.area_id) in world.points.index
                                else school_id, receivers, k=1)[0]
                w = np.array([1.0 if rec == near else 0.0 for rec in receivers])
            w = w / w.sum()
            for rec, frac in zip(receivers, w):
                if frac > 0:
                    add.append({"grade_band": band, "area_id": r.area_id,
                                "school_id": rec, "n": r.n * frac, "p": 0.0})
    out = pd.concat([keep, pd.DataFrame(add)], ignore_index=True)
    out = out.groupby(["grade_band", "area_id", "school_id"], as_index=False)["n"].sum()
    world.flows = _recompute_p(out)


def op_close_school(world: World, school_id: int,
                    receivers: list[int] | None = None,
                    hcc_receiver: int | None = None) -> None:
    """Close a school; redistribute its draw by the fallback rules."""
    if school_id in world.closed:
        raise ValueError(f"school {school_id} already closed")
    cls = world.schools.set_index("school_id").loc[school_id, "classification"]
    level = world.level(school_id)
    flows_before = world.flows

    # --- gifted pathway relocates intact (user default, open question 3)
    gif = world.gifted
    if (gif.school_id == school_id).any():
        row = gif[gif.school_id == school_id].iloc[0]
        if hcc_receiver is None:
            cands = [int(s) for s in gif.school_id
                     if s != school_id and
                     gif.set_index("school_id").loc[s, "grade_band"] == row["grade_band"]]
            if not cands:
                raise ValueError(f"close_school({school_id}): no default gifted "
                                 "receiver of the same band; pass hcc_receiver")
            hcc_receiver = _nearest(world, school_id, cands, k=1)[0]
        gif = gif[gif.school_id != school_id].copy()
        if (gif.school_id == hcc_receiver).any():
            i = gif.index[gif.school_id == hcc_receiver][0]
            gif.loc[i, "n_hc"] += row["n_hc"]
            merged = list(gif.loc[i, "member_area_ids"]) + list(row["member_area_ids"])
            gif.at[i, "member_area_ids"] = sorted(set(merged))
        else:
            rec_level = world.level(hcc_receiver)
            gif = pd.concat([gif, pd.DataFrame([{
                "school_id": hcc_receiver,
                "grade_band": "es" if rec_level == "ES" else "ms",
                "kernel": "hcc_pathway" if rec_level == "ES" else "od_column",
                "n_hc": row["n_hc"],
                "member_area_ids": list(row["member_area_ids"]),
            }])], ignore_index=True)
        world.gifted = gif

    # --- the flow column moves to the receivers
    if receivers is None:
        if cls == "option":
            cands = _open_ids(world, "option", level)
            receivers = _nearest(world, school_id, cands, k=1)
        elif cls == "hcc_pathway":
            receivers = [hcc_receiver]
        else:
            cands = _open_ids(world, "neighborhood", level)
            receivers = _nearest(world, school_id, cands, k=3)
    if not receivers or any(r is None for r in receivers):
        raise ValueError(f"close_school({school_id}): no receivers resolved")
    _move_flow_column(world, school_id, [int(r) for r in receivers])
    _rescale_col_marg(world, flows_before)

    world.walkzones = world.walkzones[world.walkzones.school_id != school_id]
    was_basic = school_id in world.basic_ids
    world.basic_ids.discard(school_id)
    if was_basic:
        # service follows the kids: receivers of a basic-served school get service
        world.basic_ids |= {int(r) for r in receivers
                            if world.level(int(r)) in ("ES", "MS")}
    world.closed.add(school_id)


def op_convert_option_to_neighborhood(world: World, school_id: int,
                                      stay_rate: float | None = None) -> None:
    """Swap an option school's draw kernel for an attendance-area draw.

    The new attendance area is the school's geozone; residents attend at the
    band's observed stay-rate; the school's previous enrollees return to their
    areas' other destinations pro-rata (steady state, no grandfathering).
    """
    cls = world.schools.set_index("school_id").loc[school_id, "classification"]
    if cls != "option":
        raise ValueError(f"convert: school {school_id} is {cls}, not option")
    gz = world.geozones[world.geozones.school_id == school_id]
    if gz.empty:
        raise ValueError(f"convert: school {school_id} has no geozone polygon")
    geo = gz.geometry.union_all()
    flows_before = world.flows

    flows = world.flows.copy()
    for band in sorted(flows.loc[flows.school_id == school_id, "grade_band"].unique()):
        f = flows[flows.grade_band == band]
        stay = stay_rate if stay_rate is not None else world.stay_rates[band]
        att = world.att_layers[band]
        gfrac = {int(r.school_id): r.geometry.intersection(geo).area / r.geometry.area
                 for r in att.itertuples()}
        N = f.groupby("area_id")["n"].sum()
        old = f[f.school_id == school_id].set_index("area_id")["n"]
        for a in N.index:
            new_n = N[a] * gfrac.get(int(a), 0.0) * stay
            old_n = float(old.get(a, 0.0))
            other = N[a] - old_n
            fac = (N[a] - new_n) / other if other > 0 else 0.0
            sel = (flows.grade_band == band) & (flows.area_id == a)
            flows.loc[sel & (flows.school_id != school_id), "n"] *= fac
            flows = flows[~(sel & (flows.school_id == school_id))]
            if new_n > 0:
                flows = pd.concat([flows, pd.DataFrame([{
                    "grade_band": band, "area_id": a, "school_id": school_id,
                    "n": new_n, "p": 0.0}])], ignore_index=True)
    world.flows = _recompute_p(flows)
    _rescale_col_marg(world, flows_before)

    world.schools.loc[world.schools.school_id == school_id, "classification"] = "neighborhood"
    if world.level(school_id) in ("ES", "MS"):
        world.basic_ids.add(school_id)


def op_move_school(world: World, school_id: int, new_location,
                   move_geozone: bool = False) -> None:
    """Relocate a school building; walk zone recenters, option draw refits."""
    if isinstance(new_location, dict):
        pt = gpd.GeoSeries([shapely.Point(new_location["lon"], new_location["lat"])],
                           crs=4326).to_crs(parse_shapes.ANALYSIS_CRS).iloc[0]
    else:
        pt = shapely.Point(float(new_location[0]), float(new_location[1]))
    old_pt = world.points.loc[school_id]
    world.points.loc[school_id] = pt

    # walk zone recenters as a calibrated buffer at the current threshold
    base_mi = WALK_THRESHOLD_MI[world.level(school_id)]
    _buffer_zone(world, school_id, world.walk_mult.loc[school_id] * base_mi * FEET_PER_MILE)

    if move_geozone:
        gz = world.geozones
        sel = gz.school_id == school_id
        gz.loc[sel, "geometry"] = gz.loc[sel, "geometry"].apply(
            lambda g: affinity.translate(g, xoff=pt.x - old_pt.x, yoff=pt.y - old_pt.y))

    cls = world.schools.set_index("school_id").loc[school_id, "classification"]
    if cls == "option":
        # re-derive the draw column from the fitted decay kernel at the new point
        flows_before = world.flows
        kp = load_kernel_params().set_index("grade_band")["decay_ft"]
        pop = world.pop if world.pop is not None else load_synth_pop()
        cents = _bg_centroids()
        flows = world.flows.copy()
        for band in sorted(flows.loc[flows.school_id == school_id, "grade_band"].unique()):
            decay_ft = float(kp.get(band, 1.5 * FEET_PER_MILE))
            kids = _pop_column(pop, band)
            raw = kids * np.exp(-cents.reindex(kids.index).distance(pt) / decay_ft)
            w = world.weights[world.weights.grade_band == band]
            wp = w.pivot_table(index="GEOID", columns="area_id", values="w", fill_value=0.0)
            model = pd.Series(
                raw.reindex(wp.index).fillna(0.0).to_numpy() @ wp.to_numpy(),
                index=wp.columns)
            model = model / model.sum()
            col = flows[(flows.grade_band == band) & (flows.school_id == school_id)]
            total = col.n.sum()
            flows = flows[~((flows.grade_band == band) & (flows.school_id == school_id))]
            add = pd.DataFrame({"grade_band": band, "area_id": model.index,
                                "school_id": school_id, "n": total * model.values,
                                "p": 0.0})
            flows = pd.concat([flows, add[add.n > 1e-9]], ignore_index=True)
        world.flows = _recompute_p(flows)
        _rescale_col_marg(world, flows_before)


_OP_FNS = {
    "set_walk_threshold": op_set_walk_threshold,
    "scale_walkzone": op_scale_walkzone,
    "close_school": op_close_school,
    "convert_option_to_neighborhood": op_convert_option_to_neighborhood,
    "move_school": op_move_school,
}


# ---------------------------------------------------------------------------
# Scenario spec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    ops: tuple

    @classmethod
    def from_dict(cls, d: dict, name: str | None = None) -> "Scenario":
        return cls(name=d.get("name", name or "unnamed"),
                   description=d.get("description", ""),
                   ops=tuple(d.get("ops", [])))


def load_scenario(path_or_name: str | Path) -> Scenario:
    """Load scenarios/<name>.json (or any path to a scenario JSON)."""
    p = Path(path_or_name)
    if not p.exists():
        p = SCENARIO_DIR / f"{path_or_name}.json"
    with open(p) as fh:
        return Scenario.from_dict(json.load(fh), name=p.stem)


_REQUIRED = {
    "set_walk_threshold": {"level", "miles"},
    "scale_walkzone": {"school_id"},
    "close_school": {"school_id"},
    "convert_option_to_neighborhood": {"school_id"},
    "move_school": {"school_id", "new_location"},
}


def validate_scenario(scenario: Scenario, world: World | None = None) -> list[str]:
    """Static validation; returns a list of problems (empty = valid).

    Checks op names + required params, school_ids against parse_shapes
    locations, sequential closure consistency, level / geometry parameter
    sanity, and that conversion targets are option schools with geozones.
    """
    if world is None:
        world = baseline_world()
    known = set(world.schools.school_id.astype(int))
    option_ids = set(world.schools.loc[world.schools.classification == "option",
                                       "school_id"].astype(int))
    geozone_ids = set(world.geozones.school_id.astype(int))
    closed: set = set()
    probs = []
    for i, op in enumerate(scenario.ops):
        tag = f"op[{i}]"
        kind = op.get("op")
        if kind not in _OPS:
            probs.append(f"{tag}: unknown op {kind!r}")
            continue
        missing = _REQUIRED[kind] - set(op)
        if missing:
            probs.append(f"{tag} {kind}: missing params {sorted(missing)}")
            continue
        sid = op.get("school_id")
        if sid is not None:
            if sid not in known:
                probs.append(f"{tag} {kind}: unknown school_id {sid}")
                continue
            if sid in closed:
                probs.append(f"{tag} {kind}: school {sid} closed earlier in this scenario")
        if kind == "set_walk_threshold":
            if op["level"] not in WALK_THRESHOLD_MI:
                probs.append(f"{tag}: level must be one of {sorted(WALK_THRESHOLD_MI)}")
            if not op["miles"] > 0:
                probs.append(f"{tag}: miles must be > 0")
        elif kind == "scale_walkzone":
            if ("factor" in op) == ("miles" in op):
                probs.append(f"{tag}: give exactly one of factor / miles")
        elif kind == "close_school":
            for rec in (op.get("receivers") or []):
                if rec not in known or rec in closed or rec == sid:
                    probs.append(f"{tag}: bad receiver {rec}")
            hr = op.get("hcc_receiver")
            if hr is not None and (hr not in known or hr in closed):
                probs.append(f"{tag}: bad hcc_receiver {hr}")
            closed.add(sid)
        elif kind == "convert_option_to_neighborhood":
            if sid not in option_ids:
                probs.append(f"{tag}: school {sid} is not an option school")
            elif sid not in geozone_ids:
                probs.append(f"{tag}: option school {sid} has no geozone")
        elif kind == "move_school":
            loc = op["new_location"]
            ok = (isinstance(loc, dict) and {"lat", "lon"} <= set(loc)) or \
                 (isinstance(loc, (list, tuple)) and len(loc) == 2)
            if not ok:
                probs.append(f"{tag}: new_location must be [x_ft, y_ft] or {{lat, lon}}")
    return probs


def apply(scenario: Scenario, world: World | None = None) -> World:
    """Apply a scenario's ops, in order, to a copy of the (baseline) world."""
    if world is None:
        world = baseline_world()
    probs = validate_scenario(scenario, world)
    if probs:
        raise ValueError(f"invalid scenario {scenario.name!r}: " + "; ".join(probs))
    out = world.copy()
    for op in scenario.ops:
        kw = {k: v for k, v in op.items() if k not in ("op", "comment")}
        _OP_FNS[op["op"]](out, **kw)
    return out


# ---------------------------------------------------------------------------
# Evaluation — feed the world through the stage 6/7/8 hooks
# ---------------------------------------------------------------------------

def scenario_gifted_pool(world: World, assignment: pd.DataFrame,
                         walk: pd.DataFrame,
                         pop: pd.DataFrame | None = None) -> pd.DataFrame:
    """World-aware replica of ridership.gifted_pool.

    Identical math, but the site list / HC enrollment / pathway member areas
    come from ``world.gifted`` so closures and relocations flow through.
    """
    if pop is None:
        pop = world.pop if world.pop is not None else load_synth_pop()
    rows = []
    for r in world.gifted.itertuples():
        sid = int(r.school_id)
        wsub = walk[walk.school_id == sid].set_index("GEOID")["walk_frac"]
        if r.kernel == "hcc_pathway":
            kids = _pop_column(pop, "es")
            w = world.weights[(world.weights.grade_band == "es")
                              & world.weights.area_id.isin(r.member_area_ids)]
            ww = w.groupby("GEOID")["w"].sum()
            raw = (ww * kids.reindex(ww.index)).dropna()
            pbg = raw / raw.sum()
        else:
            col = assignment[(assignment.school_id == sid)
                             & (assignment.grade_band == "ms")]
            pbg = col.set_index("GEOID")["n_expected"]
            pbg = pbg / pbg.sum()
        elig_frac = float((pbg * (1.0 - wsub.reindex(pbg.index).fillna(0.0))).sum())
        rows.append({"school_id": sid, "grade_band": r.grade_band,
                     "kernel": r.kernel, "n_hc": r.n_hc,
                     "n_bus_eligible": r.n_hc * elig_frac})
    return pd.DataFrame(rows)


_BASELINE_CAL: dict | None = None


def _baseline_calibration(params: rid.RidershipParams) -> dict:
    """Baseline-solved propensity scale + covariate means (computed once).

    Solved on the same recomputed path scenarios use, so the empty scenario
    reproduces the baseline exactly.
    """
    global _BASELINE_CAL
    if _BASELINE_CAL is not None:
        return _BASELINE_CAL
    world = baseline_world()
    pop = load_synth_pop()
    assignment = build_matrix(pop=pop, weights=world.weights, flows=world.flows,
                              col_marg=world.col_marg)
    walk = walk_fractions(walkzones=world.walkzones)
    cells = rid.basic_cells(assignment, walk, points=world.points,
                            basic_ids=world.basic_ids)
    gifted = scenario_gifted_pool(world, assignment, walk, pop)
    _, info = rid.expected_riders(params=params, cells=cells, gifted=gifted,
                                  return_info=True)
    _BASELINE_CAL = {"scale": info["scale"],
                     "covar_means": cells.attrs["covar_means"]}
    return _BASELINE_CAL


def evaluate(world: World, params: rid.RidershipParams | None = None,
             pop: pd.DataFrame | None = None, verbose: bool = False) -> dict:
    """Run stages 6-8 on a (possibly mutated) world with baseline calibration.

    Returns dict with assignment, walk, cells, gifted, riders (per school ×
    program) and info (scale used etc.). Pass ``pop=sample_synth_pop(rng)``
    for an MC draw (use the SAME draw for baseline and scenario — paired
    design).
    """
    if params is None:
        params = rid.load_params()
    if pop is None:
        pop = world.pop if world.pop is not None else load_synth_pop()
    cal = _baseline_calibration(params)

    assignment = build_matrix(pop=pop, weights=world.weights, flows=world.flows,
                              col_marg=world.col_marg, verbose=verbose)
    walk = walk_fractions(walkzones=world.walkzones)
    cells = rid.basic_cells(assignment, walk, points=world.points,
                            basic_ids=world.basic_ids,
                            covar_means=cal["covar_means"])
    gifted = scenario_gifted_pool(world, assignment, walk, pop)
    riders, info = rid.expected_riders(params=params, cells=cells, gifted=gifted,
                                       fixed_scale=cal["scale"], return_info=True)
    return {"assignment": assignment, "walk": walk, "cells": cells,
            "gifted": gifted, "riders": riders, "info": info}


def run_scenario(scenario: Scenario,
                 params: rid.RidershipParams | None = None,
                 pop: pd.DataFrame | None = None,
                 verbose: bool = True) -> dict:
    """Evaluate baseline and scenario with shared calibration; return deltas."""
    if params is None:
        params = rid.load_params()
    base_w = baseline_world()
    scen_w = apply(scenario, base_w)
    base = evaluate(base_w, params=params, pop=pop)
    scen = evaluate(scen_w, params=params, pop=pop)

    def per_school(res):
        r = res["riders"]
        return r.set_index(["school_id", "program"])[
            ["n_bus_eligible", "riders", "est_routes"]]

    b, s = per_school(base), per_school(scen)
    delta = s.sub(b, fill_value=0.0).rename(columns=lambda c: f"d_{c}")
    delta = delta.join(b.add_prefix("base_"), how="outer").fillna(0.0)
    delta = delta.sort_values("d_riders")

    district = {}
    for prog in ("basic", "gifted"):
        bb = b.xs(prog, level="program") if prog in b.index.get_level_values(1) else pd.DataFrame()
        ss = s.xs(prog, level="program") if prog in s.index.get_level_values(1) else pd.DataFrame()
        district[prog] = {
            "base_riders": float(bb["riders"].sum()) if len(bb) else 0.0,
            "scen_riders": float(ss["riders"].sum()) if len(ss) else 0.0,
            "base_routes": float(bb["est_routes"].sum()) if len(bb) else 0.0,
            "scen_routes": float(ss["est_routes"].sum()) if len(ss) else 0.0,
        }
        district[prog]["d_riders"] = district[prog]["scen_riders"] - district[prog]["base_riders"]
        district[prog]["d_routes"] = district[prog]["scen_routes"] - district[prog]["base_routes"]

    if verbose:
        _print_report(scenario, delta, district)
    return {"baseline": base, "scenario": scen, "deltas": delta, "district": district}


def _print_report(scenario: Scenario, delta: pd.DataFrame, district: dict) -> None:
    names = load_schools().set_index("school_id")["name"]
    print(f"=== scenario {scenario.name!r} ===")
    if scenario.description:
        print(f"  {scenario.description}")
    for prog, d in district.items():
        print(f"  {prog:6s}: riders {d['base_riders']:8,.1f} → {d['scen_riders']:8,.1f}  "
              f"(Δ {d['d_riders']:+8,.1f});  est routes {d['base_routes']:6.1f} → "
              f"{d['scen_routes']:6.1f} (Δ {d['d_routes']:+5.1f})")
    movers = delta[delta.d_riders.abs() > 0.5]
    print(f"  per-school movers (|Δriders| > 0.5): {len(movers)}")
    shown = pd.concat([movers.head(8), movers.tail(8)])
    shown = shown[~shown.index.duplicated()]
    for (sid, prog), r in shown.iterrows():
        print(f"    {names.get(sid, sid):24.24s} {prog:6s} riders "
              f"{r.base_riders:7.1f} → {r.base_riders + r.d_riders:7.1f} "
              f"(Δ {r.d_riders:+7.1f})")


# ---------------------------------------------------------------------------
# Baseline-equivalence validation (the M6 acceptance check)
# ---------------------------------------------------------------------------

def validate_baseline(verbose: bool = True) -> bool:
    """The empty scenario must reproduce the tracked baseline exactly.

    'Exactly' = within the rounding applied when the tracked CSVs were
    written (assignment n_expected 4 dp, walk_frac 6 dp, riders 2 dp).
    """
    from analysis.montecarlo.assignment import load_assignment
    from analysis.montecarlo.eligibility import load_walker_fractions

    empty = Scenario(name="empty", description="", ops=())
    world = apply(empty)
    res = evaluate(world)

    ok = True

    m = res["assignment"].merge(
        load_assignment(), on=["GEOID", "school_id", "grade_band"],
        how="outer", suffixes=("", "_t"), indicator=True)
    unmatched = (m._merge != "both").sum()
    dmax = float((m.loc[m._merge == "both", "n_expected"]
                  - m.loc[m._merge == "both", "n_expected_t"]).abs().max())
    cells_ok = unmatched == 0 and dmax <= 1e-3
    ok &= cells_ok
    if verbose:
        print(f"  assignment matrix: {len(m)} cells, unmatched {unmatched}, "
              f"max |Δn_expected| {dmax:.2e}  {'OK' if cells_ok else 'FAIL'}")

    w = res["walk"].merge(load_walker_fractions(), on=["GEOID", "school_id"],
                          how="outer", suffixes=("", "_t"), indicator=True)
    wun = (w._merge != "both").sum()
    wmax = float((w.loc[w._merge == "both", "walk_frac"]
                  - w.loc[w._merge == "both", "walk_frac_t"]).abs().max())
    walk_ok = wun == 0 and wmax <= 1e-5
    ok &= walk_ok
    if verbose:
        print(f"  walk fractions:    {len(w)} pairs, unmatched {wun}, "
              f"max |Δwalk_frac| {wmax:.2e}  {'OK' if walk_ok else 'FAIL'}")

    rt = rid.load_ridership().set_index(["school_id", "program"])
    rr = res["riders"].set_index(["school_id", "program"])
    j = rr.join(rt, how="outer", lsuffix="", rsuffix="_t")
    run_ = j["riders"].isna().sum() + j["riders_t"].isna().sum()
    rmax = float((j["riders"] - j["riders_t"]).abs().max())
    eligmax = float((j["n_bus_eligible"] - j["n_bus_eligible_t"]).abs().max())
    riders_ok = run_ == 0 and rmax <= 0.05 and eligmax <= 0.05
    ok &= riders_ok
    if verbose:
        print(f"  riders:            {len(j)} school×program rows, unmatched {run_}, "
              f"max |Δriders| {rmax:.3f}, max |Δeligible| {eligmax:.3f}  "
              f"{'OK' if riders_ok else 'FAIL'}")
        bsum = float(rr.xs('basic', level='program')["riders"].sum())
        gsum = float(rr.xs('gifted', level='program')["riders"].sum())
        print(f"  district riders: basic {bsum:,.1f}, gifted {gsum:,.1f}")
        print(f"  EMPTY-SCENARIO BASELINE CHECK: {'PASS' if ok else 'FAIL'}")
    return bool(ok)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _list_scenarios() -> None:
    print(f"scenario dir: {SCENARIO_DIR}")
    paths = sorted(SCENARIO_DIR.glob("*.json")) if SCENARIO_DIR.exists() else []
    if not paths:
        print("  (no scenario files)")
    for p in paths:
        sc = load_scenario(p)
        probs = validate_scenario(sc)
        status = "OK" if not probs else f"INVALID: {'; '.join(probs)}"
        print(f"  {sc.name:28s} {len(sc.ops)} ops  [{status}]")
        if sc.description:
            print(f"    {sc.description}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 9: scenario engine")
    parser.add_argument("--validate", action="store_true",
                        help="check the empty scenario reproduces the baseline")
    parser.add_argument("--run", metavar="NAME_OR_PATH",
                        help="apply + evaluate one scenario, print rider deltas")
    args = parser.parse_args()
    if args.validate:
        validate_baseline()
    elif args.run:
        run_scenario(load_scenario(args.run))
    else:
        _list_scenarios()
