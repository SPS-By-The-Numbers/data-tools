"""Stage 5: synth_population — estimated public school children per block group.

Combines Stage 4 outputs (ACS age + enrollment + block-group geometries) to
produce a per-block-group × grade-band table of estimated public school children.
This is the *row marginals* input for the IPF assignment stage (Stage 6).

Grade bands match SPS school levels:
  es   kindergarten + grades 1-5  (roughly ages 5-10)
  ms   grades 6-8                 (roughly ages 11-13)
  hs   grades 9-12                (roughly ages 14-17)

ACS age bands (B01001) do not align perfectly with grade bands, so we use a
deterministic fractional split:

  ACS 5-9 years   → 100% ES     (ages 5-9 = kindergarten through grade 4)
  ACS 10-14 years → 20% ES      (age 10 = grade 5)
                    60% MS      (ages 11-13 = grades 6-8)
                    20% HS      (age 14 = grade 9)
  ACS 15-17 years → 100% HS    (ages 15-17 = grades 10-12)

These fractions are exact-integer-grade algebra, not statistical estimates.
The MC layer samples from Dirichlet distributions seeded from the cell counts
(α = n_expected + 0.5 as a weakly-informative prior).

Public-school fraction comes from B14003 at tract level (too suppressed at BG
level); each block group inherits its parent tract's fraction per age band.
Block groups entirely outside SPS territory (sps_frac == 0) are excluded.
Block groups partially overlapping the SPS boundary are area-weighted: the
expected children count is multiplied by sps_frac before the public-school
and grade-band adjustments.

Sources:   census_seattle/ (all tracked — no network needed)
Outputs:   census_seattle/synth_pop.csv

Columns in synth_pop.csv:
  GEOID           12-digit block-group GEOID
  geoid_tract     11-digit tract GEOID
  sps_frac        fraction of block-group area within SPS territory
  n_age_5_9       ACS children 5-9  (raw, before sps_frac weighting)
  n_age_10_14     ACS children 10-14 (raw)
  n_age_15_17     ACS children 15-17 (raw)
  n_pub_es        expected public ES children (sps_frac × age × grade split × pub_frac)
  n_pub_ms        expected public MS children
  n_pub_hs        expected public HS children
  n_pub_total     n_pub_es + n_pub_ms + n_pub_hs
  alpha_es        Dirichlet concentration parameter for ES (n_pub_es + 0.5)
  alpha_ms        Dirichlet concentration parameter for MS
  alpha_hs        Dirichlet concentration parameter for HS

Run:
  python3 -m analysis.montecarlo.synth_population [--build]

Loaders:
  load_synth_pop()  → DataFrame

Sampling one MC draw (expected by Stage 10 simulate.py):
  from analysis.montecarlo.synth_population import sample_synth_pop
  pop = sample_synth_pop(rng)   → DataFrame with n_es, n_ms, n_hs columns
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.montecarlo import acs_population as acs

OUT_DIR = Path(__file__).resolve().parent / "census_seattle"

# Age-to-grade-band fractional split: keys are ACS band names.
# ES = K-5 (ages 5-10): 5-9 fully ES, age 10 (1/5 of 10-14 band) goes ES.
# MS = 6-8 (ages 11-13): 3/5 of 10-14 band.
# HS = 9-12 (ages 14-17): 1/5 of 10-14 band (age 14 = grade 9) + all 15-17.
_GRADE_SPLIT = {
    "es": {"age_5_9": 1.0, "age_10_14": 0.2, "age_15_17": 0.0},
    "ms": {"age_5_9": 0.0, "age_10_14": 0.6, "age_15_17": 0.0},
    "hs": {"age_5_9": 0.0, "age_10_14": 0.2, "age_15_17": 1.0},
}

# Mapping: ACS age band → which B14003 public fraction column to use.
_PUB_FRAC_COL = {
    "age_5_9": "pub_frac_5_9",
    "age_10_14": "pub_frac_10_14",
    "age_15_17": "pub_frac_15_17",
}

# Dirichlet prior concentration added to each cell (half-count = weakly informative).
_DIRICHLET_PRIOR = 0.5


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(verbose: bool = True) -> pd.DataFrame:
    """Compute synth_pop.csv from census_seattle/ intermediates."""
    bg = acs.load_block_groups()[["GEOID", "geoid_tract", "sps_frac"]].copy()
    age = acs.load_acs_age()
    enr = acs.load_acs_enrollment()

    # Merge on GEOID
    df = bg.merge(age, on="GEOID", how="left")
    df = df.merge(
        enr[["GEOID", "pub_frac_5_9", "pub_frac_10_14", "pub_frac_15_17"]],
        on="GEOID", how="left",
    )

    # Fill missing public fractions with district-wide means (rare edge case)
    for col in ["pub_frac_5_9", "pub_frac_10_14", "pub_frac_15_17"]:
        mean_frac = df[col].mean(skipna=True)
        df[col] = df[col].fillna(mean_frac)

    # Area-weight age counts by sps_frac for partial-overlap block groups
    for band in ["age_5_9", "age_10_14", "age_15_17"]:
        df[f"n_{band}"] = df[band] * df["sps_frac"]

    # Expected public children per grade band:
    # sum over age bands of (age_count × grade_split_frac × pub_frac)
    for grade in ["es", "ms", "hs"]:
        total = pd.Series(0.0, index=df.index)
        for age_band, split_frac in _GRADE_SPLIT[grade].items():
            if split_frac == 0.0:
                continue
            pub_frac_col = _PUB_FRAC_COL[age_band]
            total += df[f"n_{age_band}"] * split_frac * df[pub_frac_col]
        df[f"n_pub_{grade}"] = total

    df["n_pub_total"] = df["n_pub_es"] + df["n_pub_ms"] + df["n_pub_hs"]

    # Dirichlet concentration parameters (α = n + prior)
    for grade in ["es", "ms", "hs"]:
        df[f"alpha_{grade}"] = df[f"n_pub_{grade}"] + _DIRICHLET_PRIOR

    out_cols = [
        "GEOID", "geoid_tract", "sps_frac",
        "n_age_5_9", "n_age_10_14", "n_age_15_17",
        "n_pub_es", "n_pub_ms", "n_pub_hs", "n_pub_total",
        "alpha_es", "alpha_ms", "alpha_hs",
    ]
    # Rename raw age columns
    df = df.rename(columns={
        "n_age_5_9": "n_age_5_9",
        "n_age_10_14": "n_age_10_14",
        "n_age_15_17": "n_age_15_17",
    })

    result = df[out_cols].sort_values("GEOID").reset_index(drop=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / "synth_pop.csv", index=False)

    if verbose:
        n = len(result)
        n_pub_es = result["n_pub_es"].sum()
        n_pub_ms = result["n_pub_ms"].sum()
        n_pub_hs = result["n_pub_hs"].sum()
        n_pub_total = result["n_pub_total"].sum()
        print(f"synth_pop.csv: {n} block groups")
        print(f"  Expected public school children in SPS territory:")
        print(f"    ES (K-5):  {n_pub_es:7,.0f}")
        print(f"    MS (6-8):  {n_pub_ms:7,.0f}")
        print(f"    HS (9-12): {n_pub_hs:7,.0f}")
        print(f"    Total:     {n_pub_total:7,.0f}  (SPS 2024-25 enrollment: 49,765)")
        ratio = n_pub_total / 49765 if n_pub_total else float("nan")
        print(f"  ACS/enrollment ratio: {ratio:.2f}x  "
              f"({'over' if ratio > 1 else 'under'}-count)")
        print(f"\nWrote {OUT_DIR / 'synth_pop.csv'}")

    return result


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_synth_pop() -> pd.DataFrame:
    """Per block-group expected public school children by grade band."""
    path = OUT_DIR / "synth_pop.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run: "
            "python3 -m analysis.montecarlo.synth_population --build"
        )
    return pd.read_csv(path)


def sample_synth_pop(rng: np.random.Generator) -> pd.DataFrame:
    """Draw one MC sample of public school children by grade band.

    For each block group, samples a (n_es, n_ms, n_hs) triplet from a
    Dirichlet distribution parameterized by (alpha_es, alpha_ms, alpha_hs),
    then scales by n_pub_total to get expected counts. Returns a DataFrame
    with the same index as load_synth_pop() plus columns n_es, n_ms, n_hs.

    The paired design (Stage 10) calls this once per MC iteration and uses
    the SAME sample for both baseline and scenario runs, so deltas are tight.
    """
    pop = load_synth_pop()
    alpha = pop[["alpha_es", "alpha_ms", "alpha_hs"]].to_numpy()
    # Sample grade-band fractions per block group from Dirichlet
    fracs = rng.dirichlet(alpha, size=None) if alpha.shape[0] == 1 else _dirichlet_rows(rng, alpha)
    totals = pop["n_pub_total"].to_numpy()
    result = pop[["GEOID", "geoid_tract", "sps_frac", "n_pub_total"]].copy()
    result["n_es"] = fracs[:, 0] * totals
    result["n_ms"] = fracs[:, 1] * totals
    result["n_hs"] = fracs[:, 2] * totals
    return result


def _dirichlet_rows(rng: np.random.Generator, alpha: np.ndarray) -> np.ndarray:
    """Sample one Dirichlet draw per row of alpha."""
    out = np.empty_like(alpha, dtype=float)
    for i in range(len(alpha)):
        out[i] = rng.dirichlet(alpha[i])
    return out


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary() -> None:
    pop = load_synth_pop()
    print("=== synth_pop.csv ===")
    print(f"  {len(pop)} block groups")
    tot = pop["n_pub_total"].sum()
    es = pop["n_pub_es"].sum()
    ms = pop["n_pub_ms"].sum()
    hs = pop["n_pub_hs"].sum()
    print(f"  Expected public school children (sps_frac-weighted):")
    print(f"    ES:    {es:7,.0f}  ({es/tot:.1%})")
    print(f"    MS:    {ms:7,.0f}  ({ms/tot:.1%})")
    print(f"    HS:    {hs:7,.0f}  ({hs/tot:.1%})")
    print(f"    Total: {tot:7,.0f}")
    print(f"  SPS 2024-25 enrollment: 49,765  (ACS over-count: {tot/49765:.2f}x)")
    print(f"  Block groups with >0 public ES: {(pop['n_pub_es'] > 0).sum()}")
    print(f"  Block groups with >0 public HS: {(pop['n_pub_hs'] > 0).sum()}")
    # Top 10 by total
    top = pop.nlargest(5, "n_pub_total")[["GEOID", "n_pub_es", "n_pub_ms", "n_pub_hs", "n_pub_total"]]
    print(f"\n  Top 5 block groups by total:")
    print(top.round(1).to_string(index=False))

    # Quick MC sanity check (3 draws)
    rng = np.random.default_rng(42)
    draws = [sample_synth_pop(rng)["n_pub_total"].sum() for _ in range(3)]
    print(f"\n  MC sanity (3 draws of district total): "
          f"{[f'{d:.0f}' for d in draws]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stage 5: synthetic population by grade band")
    parser.add_argument("--build", action="store_true",
                        help="Compute synth_pop.csv from census_seattle/ intermediates")
    args = parser.parse_args()

    if args.build:
        build()
    else:
        _summary()
