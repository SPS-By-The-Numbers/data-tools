"""Stage 6: assignment — P(school | block group, grade band) via OD-anchored IPF.

Produces the baseline assignment matrix: for every block group and grade band
(es = K-5, ms = 6-8, hs = 9-12), the probability distribution over the 98 SPS
schools that the children living there attend. The baseline is **anchored to
the observed Section 4 origin-destination flows** (2024-25): the OD matrix
gives P(school | attendance area, band); block groups inherit their area's
distribution area-weighted; IPF then reconciles the result against
census-based row marginals (synth_pop kids per BG) and enrollment-based
column marginals (RC per-grade counts per school).

Pipeline:
  1. ``bg_area_weights``  — area-weighted overlay of block groups with the
     ES/MS/HS attendance-area layers → w(BG, area) per band.
  2. ``observed_flows``   — Section 4 od.csv → P(school | area, band), names
     resolved to school_id via school_directory; non-school destinations
     (Interagency, Private SpEd, ...) dropped and renormalized.
  3. ``column_marginals`` — RC per-grade enrollment (2024) → school × band.
  4. ``build_matrix``     — prior = kids × W @ F, then IPF per band.

Draw kernels (for SCENARIO generalization, not the baseline): the module also
provides ``kernel_bg_weights`` implementing the three kernel families
(neighborhood = attendance-area membership, option = exponential distance
decay, hcc_pathway = pathway-area union from hcc_pathways_es.csv), and
``fit_option_decay`` which fits the option decay length against the observed
OD option columns → ``assignment/kernel_params.csv``.

Outputs (tracked under analysis/montecarlo/assignment/):
  assignment_matrix.csv — GEOID × school_id × grade_band: n_expected, p
  kernel_params.csv     — fitted option-kernel decay length per band

Run:   python3 -m analysis.montecarlo.assignment [--build]

Loaders (pure-functional, for downstream stages):
  load_assignment()     → DataFrame
  load_kernel_params()  → DataFrame

MC hook (Stage 10): ``build_matrix(pop=sample_synth_pop(rng))`` recomputes the
matrix for one sampled population without touching the tracked files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

from analysis.montecarlo import parse_shapes
from analysis.montecarlo import section4_seattle as s4
from analysis.montecarlo.acs_population import load_block_groups
from analysis.montecarlo.rc_seattle import load_enrollment
from analysis.montecarlo.school_directory import load_schools, load_section4_name_map
from analysis.montecarlo.synth_population import load_synth_pop

_HERE = Path(__file__).resolve().parent
OUT_DIR = _HERE / "assignment"

BASE_YEAR = 2024  # fall year of the 2024-25 baseline

BANDS = ("es", "ms", "hs")
_BAND_GRADES = {
    "es": ["K", "Half-day Kindergarten", "1", "2", "3", "4", "5"],
    "ms": ["6", "7", "8"],
    "hs": ["9", "10", "11", "12"],
}
# synth_pop / sample_synth_pop column for each band (either naming accepted).
_POP_COLS = {"es": ("n_pub_es", "n_es"), "ms": ("n_pub_ms", "n_ms"), "hs": ("n_pub_hs", "n_hs")}

# Expected-count floor below which matrix cells are dropped from the output.
_CELL_FLOOR = 1e-4

FEET_PER_MILE = parse_shapes.FEET_PER_MILE


# ---------------------------------------------------------------------------
# 1. Block group → attendance-area weights
# ---------------------------------------------------------------------------

def bg_area_weights(shapes: parse_shapes.Shapes | None = None,
                    block_groups: gpd.GeoDataFrame | None = None) -> pd.DataFrame:
    """Area-weighted membership of each block group in each attendance area.

    Returns long DataFrame: GEOID, grade_band, area_id (school_id of the
    attendance-area school), w. Within (GEOID, grade_band), w sums to 1.
    """
    if shapes is None:
        shapes = parse_shapes.load_all()
    if block_groups is None:
        block_groups = load_block_groups()
    layers = {"es": shapes.attendance_es, "ms": shapes.attendance_ms, "hs": shapes.attendance_hs}

    out = []
    for band, layer in layers.items():
        inter = gpd.overlay(
            block_groups[["GEOID", "geometry"]],
            layer[["school_id", "geometry"]],
            how="intersection", keep_geom_type=False,
        )
        inter["a"] = inter.geometry.area
        w = inter.groupby(["GEOID", "school_id"], as_index=False)["a"].sum()
        w["w"] = w["a"] / w.groupby("GEOID")["a"].transform("sum")
        w["grade_band"] = band
        out.append(w.rename(columns={"school_id": "area_id"})[["GEOID", "grade_band", "area_id", "w"]])
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------------------
# 2. Observed Section 4 flows → P(school | area, band)
# ---------------------------------------------------------------------------

def observed_flows() -> pd.DataFrame:
    """Section 4 OD flows with names resolved to school_ids.

    Returns long DataFrame: grade_band, area_id, school_id, n, p where
    p = P(school | area, band). Band mapping: ES rows (grade_band NaN or K-5,
    the latter being the K-8 attendance schools' K-5 blocks) → es; MS → ms;
    HS → hs. ES '6-8' rows are EXCLUDED — those students live in some MS
    attendance area and are already counted in the MS OD tables.
    Non-school destinations (Interagency, Private SpEd, ...) are dropped and
    the per-area distribution renormalized over real schools.
    """
    od = s4.load_od()
    nm = load_section4_name_map()

    es = od[(od.level == "ES") & (od.grade_band.isna() | (od.grade_band == "K-5"))].copy()
    ms = od[od.level == "MS"].copy()
    hs = od[od.level == "HS"].copy()
    parts = []
    for band, df in (("es", es), ("ms", ms), ("hs", hs)):
        df = df.copy()
        df["grade_band"] = band
        parts.append(df)
    flows = pd.concat(parts, ignore_index=True)

    flows["area_id"] = flows["residence_area"].map(nm)
    flows["school_id"] = flows["school"].map(nm)
    if flows["area_id"].isna().any():
        bad = flows.loc[flows.area_id.isna(), "residence_area"].unique()
        raise ValueError(f"unmapped residence areas: {bad}")
    flows = flows[flows["school_id"].notna()].copy()  # drop non-school destinations
    flows["area_id"] = flows["area_id"].astype(int)
    flows["school_id"] = flows["school_id"].astype(int)

    flows = flows.groupby(["grade_band", "area_id", "school_id"], as_index=False)["n"].sum()
    flows["p"] = flows["n"] / flows.groupby(["grade_band", "area_id"])["n"].transform("sum")
    return flows


# ---------------------------------------------------------------------------
# 3. Column marginals — school × band enrollment (RC per-grade)
# ---------------------------------------------------------------------------

def column_marginals(year: int = BASE_YEAR) -> pd.DataFrame:
    """Per school × band enrollment from RC per-grade counts.

    Returns DataFrame: school_id, grade_band, target. PK is excluded (not
    transported as basic program; not in the synthetic population either).
    """
    enr = load_enrollment()
    enr = enr[(enr["year"] == year) & (~enr["is_district_total"])]
    schools = load_schools()
    sc_to_id = schools.set_index("school_code")["school_id"]

    rows = []
    for band, grades in _BAND_GRADES.items():
        sub = enr[enr["grade"].isin(grades)].copy()
        sub["school_id"] = sub["school_code"].map(sc_to_id)
        sub = sub[sub["school_id"].notna()]
        agg = sub.groupby(sub["school_id"].astype(int))["all_students"].sum()
        for sid, n in agg.items():
            if n > 0:
                rows.append({"school_id": sid, "grade_band": band, "target": float(n)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. IPF
# ---------------------------------------------------------------------------

def ipf(prior: np.ndarray, row_targets: np.ndarray, col_targets: np.ndarray,
        max_iter: int = 500, tol: float = 1e-8) -> tuple[np.ndarray, float, int]:
    """Iterative proportional fitting. Returns (matrix, row_resid, n_iter).

    Ends on a column scaling, so column sums match col_targets exactly;
    row_resid is the largest remaining relative row-sum deviation (rows are
    the soft, census-estimated margin).
    """
    m = prior.astype(float).copy()
    rt = row_targets.astype(float)
    ct = col_targets.astype(float)
    resid = np.inf
    for it in range(1, max_iter + 1):
        rs = m.sum(axis=1)
        m *= np.divide(rt, rs, out=np.zeros_like(rs), where=rs > 0)[:, None]
        cs = m.sum(axis=0)
        m *= np.divide(ct, cs, out=np.zeros_like(cs), where=cs > 0)[None, :]
        rs = m.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            rel = np.abs(rs - rt) / np.where(rt > 0, rt, 1.0)
        new_resid = float(rel.max()) if len(rel) else 0.0
        if abs(resid - new_resid) < tol:
            resid = new_resid
            break
        resid = new_resid
    return m, resid, it


# ---------------------------------------------------------------------------
# 5. Build the matrix
# ---------------------------------------------------------------------------

def _pop_column(pop: pd.DataFrame, band: str) -> pd.Series:
    for col in _POP_COLS[band]:
        if col in pop.columns:
            return pop.set_index("GEOID")[col]
    raise KeyError(f"population frame lacks a {band} column (tried {_POP_COLS[band]})")


def build_matrix(pop: pd.DataFrame | None = None,
                 weights: pd.DataFrame | None = None,
                 flows: pd.DataFrame | None = None,
                 col_marg: pd.DataFrame | None = None,
                 verbose: bool = False) -> pd.DataFrame:
    """Compute the assignment matrix (long form) for one population draw.

    pop defaults to the expected-value synth_pop; pass ``sample_synth_pop(rng)``
    output for an MC draw. Returns DataFrame: GEOID, school_id, grade_band,
    n_expected, p (= P(school | BG, band)).
    """
    if pop is None:
        pop = load_synth_pop()
    if weights is None:
        weights = bg_area_weights()
    if flows is None:
        flows = observed_flows()
    if col_marg is None:
        col_marg = column_marginals()

    out = []
    for band in BANDS:
        w = weights[weights.grade_band == band]
        f = flows[flows.grade_band == band]
        cm = col_marg[col_marg.grade_band == band]

        # Schools with enrollment but no observed flow can't be filled by IPF
        # (structural zero column). Report and drop.
        flow_schools = sorted(f.school_id.unique())
        no_flow = cm[~cm.school_id.isin(flow_schools)]
        if len(no_flow) and verbose:
            print(f"  [{band}] {len(no_flow)} schools have enrollment but no OD flow "
                  f"(dropped from marginals): {no_flow.school_id.tolist()} "
                  f"({no_flow.target.sum():.0f} students)")
        cm = cm[cm.school_id.isin(flow_schools)]

        geoids = sorted(w.GEOID.unique())
        schools = sorted(set(flow_schools) & set(cm.school_id))
        gi = {g: i for i, g in enumerate(geoids)}
        si = {s: j for j, s in enumerate(schools)}

        # W: BG × area weights; F: area × school flow probabilities
        areas = sorted(f.area_id.unique())
        ai = {a: k for k, a in enumerate(areas)}
        W = np.zeros((len(geoids), len(areas)))
        for r in w.itertuples():
            if r.area_id in ai:
                W[gi[r.GEOID], ai[r.area_id]] = r.w
        F = np.zeros((len(areas), len(schools)))
        for r in f.itertuples():
            if r.school_id in si:
                F[ai[r.area_id], si[r.school_id]] = r.p

        kids = _pop_column(pop, band).reindex(geoids).fillna(0.0).to_numpy()
        col_targets = cm.set_index("school_id")["target"].reindex(schools).to_numpy()

        # Scale the census-based rows to the enrollment total for this band.
        scale = col_targets.sum() / kids.sum() if kids.sum() > 0 else 1.0
        row_targets = kids * scale

        prior = row_targets[:, None] * (W @ F)
        m, resid, n_iter = ipf(prior, row_targets, col_targets)
        if verbose:
            print(f"  [{band}] {len(geoids)} BGs × {len(schools)} schools; "
                  f"row scale {scale:.3f}; IPF {n_iter} iters, "
                  f"max row residual {resid:.1%}")

        rows_sum = m.sum(axis=1)
        ii, jj = np.nonzero(m > _CELL_FLOOR)
        out.append(pd.DataFrame({
            "GEOID": np.asarray(geoids)[ii],
            "school_id": np.asarray(schools)[jj],
            "grade_band": band,
            "n_expected": m[ii, jj],
            "p": m[ii, jj] / rows_sum[ii],
        }))
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------------------
# Draw kernels (scenario generalization)
# ---------------------------------------------------------------------------

def _school_points() -> pd.Series:
    """school_id → shapely Point (EPSG:2926)."""
    locs = parse_shapes.load_locations()
    return locs.dropna(subset=["school_id"]).set_index(
        locs.dropna(subset=["school_id"]).school_id.astype(int)
    )["geometry"]

def _bg_centroids(block_groups: gpd.GeoDataFrame | None = None) -> gpd.GeoSeries:
    if block_groups is None:
        block_groups = load_block_groups()
    return block_groups.set_index("GEOID").geometry.centroid


def kernel_bg_weights(school_id: int, kind: str, band: str,
                      pop: pd.DataFrame | None = None,
                      weights: pd.DataFrame | None = None,
                      decay_ft: float | None = None,
                      hcc_era: str = "pathway_2023_2025") -> pd.Series:
    """P(BG | school) under a synthetic draw kernel (for scenario worlds).

    kind: 'neighborhood' | 'option' | 'hcc_pathway'. Returns a Series indexed
    by GEOID summing to 1: where this school's students live if its draw is
    governed by the kernel rather than the observed OD column.

      neighborhood — kids weighted by area-membership of the school's
                     attendance area (uniform per kid within the area).
      option       — kids weighted by exp(-d/decay_ft) from the school point
                     (decay fitted by fit_option_decay; district-wide tail).
      hcc_pathway  — kids weighted uniformly over the union of attendance
                     areas mapped to this site in hcc_pathways_<band>.csv
                     (es and ms maps exist; no HS pathways post-2019).
    """
    if pop is None:
        pop = load_synth_pop()
    kids = _pop_column(pop, band)

    if kind == "neighborhood":
        if weights is None:
            weights = bg_area_weights()
        w = weights[(weights.grade_band == band) & (weights.area_id == school_id)]
        raw = w.set_index("GEOID")["w"] * kids.reindex(w.GEOID.values).values
    elif kind == "option":
        if decay_ft is None:
            kp = load_kernel_params()
            row = kp[kp.grade_band == band]
            decay_ft = float(row.decay_ft.iloc[0]) if len(row) else 1.5 * FEET_PER_MILE
        pts = _school_points()
        d = _bg_centroids().distance(pts.loc[school_id])
        raw = kids * np.exp(-d.reindex(kids.index) / decay_ft)
    elif kind == "hcc_pathway":
        if band not in ("es", "ms"):
            raise ValueError(f"no HCC pathway map for band {band!r} (es/ms only)")
        pathways = pd.read_csv(_HERE / f"hcc_pathways_{band}.csv")
        schools = load_schools()
        site_name = schools.set_index("school_id").loc[school_id, "name"]
        member_areas = pathways.loc[pathways[hcc_era] == site_name, f"{band}_name"]
        att = (parse_shapes.load_attendance_es() if band == "es"
               else parse_shapes.load_attendance_ms())
        area_ids = att[att.name.isin(member_areas)].school_id.astype(int)
        if weights is None:
            weights = bg_area_weights()
        w = weights[(weights.grade_band == band) & (weights.area_id.isin(area_ids))]
        ww = w.groupby("GEOID")["w"].sum()
        raw = ww * kids.reindex(ww.index)
    else:
        raise ValueError(f"unknown kernel kind: {kind}")

    raw = raw.dropna()
    total = raw.sum()
    if not total > 0:
        raise ValueError(
            f"empty {kind} kernel for school {school_id} ({band}) — wrong "
            "school_id for this kernel kind (e.g. not an HCC site / no "
            "attendance area)?")
    return raw / total


def fit_option_decay(flows: pd.DataFrame | None = None,
                     weights: pd.DataFrame | None = None,
                     pop: pd.DataFrame | None = None,
                     verbose: bool = False) -> pd.DataFrame:
    """Fit the option-kernel decay length per band against the observed OD.

    For each option school, the observed quantity is its draw's distribution
    over residence areas, P(area | school). The kernel model predicts it as
    kids(BG) × exp(-d/L) aggregated BG→area. L is grid-searched per band to
    minimize the mean total-variation distance across that band's option
    schools; TV under a no-decay (uniform per kid) kernel is reported as the
    baseline the decay has to beat.
    """
    if flows is None:
        flows = observed_flows()
    if weights is None:
        weights = bg_area_weights()
    if pop is None:
        pop = load_synth_pop()
    schools = load_schools()
    option_ids = set(schools[schools.classification == "option"].school_id)
    pts = _school_points()
    cents = _bg_centroids()

    grid_mi = np.concatenate([np.arange(0.25, 3.01, 0.25), np.arange(3.5, 8.01, 0.5)])
    rows = []
    for band in BANDS:
        f = flows[flows.grade_band == band]
        w = weights[weights.grade_band == band]
        kids = _pop_column(pop, band)
        targets = {}
        for sid in sorted(option_ids & set(f.school_id)):
            col = f[f.school_id == sid]
            if col.n.sum() < 50 or sid not in pts.index:
                continue  # too small to constrain a fit
            targets[sid] = col.set_index("area_id")["n"] / col.n.sum()
        if not targets:
            continue

        areas = sorted(f.area_id.unique())
        # BG membership matrix per area for aggregating model weights BG→area
        wp = w.pivot_table(index="GEOID", columns="area_id", values="w", fill_value=0.0)
        wp = wp.reindex(columns=areas, fill_value=0.0)
        kid_vec = kids.reindex(wp.index).fillna(0.0)

        def mean_tv(decay_ft: float | None) -> float:
            tvs = []
            for sid, obs in targets.items():
                if decay_ft is None:
                    bgw = kid_vec
                else:
                    d = cents.reindex(wp.index).distance(pts.loc[sid])
                    bgw = kid_vec * np.exp(-d / decay_ft)
                model = pd.Series(bgw.to_numpy() @ wp.to_numpy(), index=areas)
                model = model / model.sum()
                obs_full = obs.reindex(areas).fillna(0.0)
                tvs.append(0.5 * float((model - obs_full).abs().sum()))
            return float(np.mean(tvs))

        tv_uniform = mean_tv(None)
        tv_by_L = {L: mean_tv(L * FEET_PER_MILE) for L in grid_mi}
        best_L = min(tv_by_L, key=tv_by_L.get)
        rows.append({
            "grade_band": band,
            "n_schools": len(targets),
            "decay_mi": float(best_L),
            "decay_ft": float(best_L * FEET_PER_MILE),
            "mean_tv": tv_by_L[best_L],
            "mean_tv_uniform": tv_uniform,
        })
        if verbose:
            print(f"  [{band}] option kernel: {len(targets)} schools, "
                  f"best decay {best_L:.2f} mi "
                  f"(TV {tv_by_L[best_L]:.3f} vs uniform {tv_uniform:.3f})")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Build / loaders / summary
# ---------------------------------------------------------------------------

def build(verbose: bool = True) -> pd.DataFrame:
    OUT_DIR.mkdir(exist_ok=True)
    if verbose:
        print("Building BG-area weights, flows, marginals...")
    weights = bg_area_weights()
    flows = observed_flows()
    col_marg = column_marginals()
    pop = load_synth_pop()

    if verbose:
        print("Assignment matrix (OD-anchored prior + IPF):")
    matrix = build_matrix(pop=pop, weights=weights, flows=flows,
                          col_marg=col_marg, verbose=verbose)
    matrix = matrix.sort_values(["grade_band", "GEOID", "school_id"])
    matrix["n_expected"] = matrix["n_expected"].round(4)
    matrix["p"] = matrix["p"].round(6)
    matrix.to_csv(OUT_DIR / "assignment_matrix.csv", index=False)
    if verbose:
        print(f"assignment_matrix.csv: {len(matrix)} cells, "
              f"{matrix.GEOID.nunique()} BGs, {matrix.school_id.nunique()} schools")

    if verbose:
        print("Fitting option draw-kernel decay lengths:")
    kp = fit_option_decay(flows=flows, weights=weights, pop=pop, verbose=verbose)
    kp.to_csv(OUT_DIR / "kernel_params.csv", index=False)
    if verbose:
        print(f"kernel_params.csv: {len(kp)} rows")
        print(f"\nWrote {OUT_DIR}")
    return matrix


def load_assignment() -> pd.DataFrame:
    """Baseline assignment matrix: GEOID, school_id, grade_band, n_expected, p."""
    path = OUT_DIR / "assignment_matrix.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 -m analysis.montecarlo.assignment --build")
    return pd.read_csv(path)


def load_kernel_params() -> pd.DataFrame:
    """Fitted option-kernel decay per band: grade_band, decay_mi/ft, mean_tv."""
    path = OUT_DIR / "kernel_params.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: python3 -m analysis.montecarlo.assignment --build")
    return pd.read_csv(path)


def _summary() -> None:
    m = load_assignment()
    schools = load_schools().set_index("school_id")
    print("=== assignment_matrix.csv ===")
    print(f"  {len(m)} cells; {m.GEOID.nunique()} block groups; "
          f"{m.school_id.nunique()} schools")
    for band in BANDS:
        sub = m[m.grade_band == band]
        tot = sub.n_expected.sum()
        print(f"  {band}: {len(sub):6d} cells, {tot:9,.0f} students, "
              f"{sub.school_id.nunique()} schools, "
              f"median {sub.groupby('GEOID').size().median():.0f} schools/BG")
    # P(school|BG) sanity: per BG-band, p sums to 1
    psum = m.groupby(["GEOID", "grade_band"])["p"].sum()
    print(f"  p sums per (BG, band): min {psum.min():.4f}, max {psum.max():.4f}")
    top = (m.groupby("school_id").n_expected.sum().nlargest(5))
    print("  top 5 schools by expected students:")
    for sid, n in top.items():
        print(f"    {schools.loc[sid, 'name']:30s} {n:8,.0f}")
    print("\n=== kernel_params.csv ===")
    print(load_kernel_params().round(3).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 6: OD-anchored IPF assignment")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        build()
    else:
        _summary()
