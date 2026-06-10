"""Stage 2: school_directory — canonical school list with classification and name maps.

Maps messy source names (STARS destination_name, Section 4 school/area names) to
canonical school_ids from parse_shapes locations, classifies every school, and
attaches program flags from STARS routes.

Outputs (tracked under analysis/montecarlo/school_directory/):
  schools.csv           — 98-row canonical school directory
  stars_name_map.csv    — STARS destination_name → school_id
  section4_name_map.csv — Section 4 school/residence_area names → school_id

Run:  python3 -m analysis.montecarlo.school_directory [--build]

Loaders (pure-functional, for downstream stages):
  load_schools()           → DataFrame, 98 rows
  load_stars_name_map()    → Series(destination_name → school_id, Int64)
  load_section4_name_map() → Series(name → school_id, Int64)
"""

from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

import pandas as pd

from analysis.montecarlo.parse_shapes import load_locations

_HERE = Path(__file__).resolve().parent
_DIR = _HERE / "school_directory"

# ---------------------------------------------------------------------------
# Hard-coded overrides: applied before any normalization / fuzzy logic.
# Keys are the raw source strings exactly as they appear in the source data.
# Values are school_id (int) or None for non-SPS / service / closed sites.
# ---------------------------------------------------------------------------

_STARS_OVERRIDES: dict[str, int | None] = {
    # Typos
    "Clevland H.S.": 12,
    "Thorton Creek Elementary": 977,
    "Broadview-Thompson K-8 School": 208,     # Thompson vs Thomson
    # "First-name" prefixes dropped in canonical
    "Bailey Gatzert Elementary": 226,
    "Daniel Bagley Elementary": 204,
    "Frantz Coe Elementary": 211,
    "James Baldwin Elementary School": 257,
    "John Hay Elementary": 234,
    "John Muir Elementary": 256,
    "John Rogers Elementary": 266,
    "John Rogers Elementary TEMP CONST": 266,
    "John Stanford International": 241,
    "John Stanford International Elementary (Latona)": 241,
    # Program-at-location (@) names — use the school, not the host site
    "K-5 Stem @ Boren": 972,
    "Hazel Wolf K-8 @ Pinehurst Site": 292,
    # Old / renamed schools
    "Denny M.S.": 103,
    "Denny International Middle School": 103,
    "Madrona Elementary": 249,
    "Garfield High School": 14,
    # Temp / construction variants → same school_id as the permanent school
    "Alki Elementary TEMP CONST": 202,
    "Emerson Elementary TEMPORARY": 221,
    "Kimball Elementary-temp loc (21-": 288,
    "Kimball Elementary-temp loc (21-22, 22-23)": 288,
    "Loyal Heights Elememtary (Temp Location)": 246,
    "Mercer M.S. TEMP CONST": 110,
    "Montlake Elementary TEMP CONST": 255,
    "Queen Anne Elementary (Temp": 974,
    "Queen Anne Elementary (Temp Location)": 974,
    "West Seattle Elementary-temp loc": 236,
    "West Seattle Elementary-temp loc 2021-22": 236,
    "West Woodland Elementary-Temp": 281,
    "Viewlands Elementary-temp loc (21-": 276,
    "Viewlands Elementary-temp loc (21-22, 22-23)": 276,
    # Roxhill Building: the Roxhill ES building used for other programs
    "Roxhill Building": 267,
    # Multi-suffix names resolved by override (iterative strip would get "west seattle"
    # which matches the Elementary; must pin the HS explicitly)
    "West Seattle H.S.": 19,
    "Catharine Blaine K-8 School": 289,
    "The Center School": 24,
    # Closed / out-of-SPS schools
    "Northgate Elementary": None,
    "Van Asselt Elementary": None,
    "Brier Elementary": None,
    "Edmonds Woodway H.S.": None,
    "Highland Terrace Elementary": None,
    "Cascade View Elementary": None,
    "Kenmore Elementary": None,
    "Lake Forest Park Elementary": None,
    "Lynnwood H.S.": None,
    "Ridgecrest Elementary": None,
    "Tukwila Elementary": None,
    # Non-school / service / contract / out-of-district sites
    "415 BUILDING": None,
    "Alderwood Early Childhood Center": None,
    "BRIDGES @ Providence Mount St.": None,
    "Bridges @ Magnuson Bldg": None,
    "Brightmont Academy - Seattle": None,
    "Community Care Center - Contract Site": None,
    "Early Learning Center @ Old Van Asselt Bldg.": None,
    "Experimental Ed Unit": None,
    "Experimental Education Unit": None,
    "Happy Zone Alternative Learning Center": None,
    "John Stanford Center - Shuttle": None,
    "Listen & Talk": None,
    "Middle College": None,
    "Miller Community Center": None,
    "Mount St. Vincent": None,
    "North Seattle Food Bank": None,
    "Northwest School for the Hearing": None,
    "Northwest School for the Hearing Impaired": None,
    "Playful Reading": None,
    "Playful Learning": None,
    "Roxbury Lanes": None,
    "Seattle Hearing, Speech, &": None,
    "Seattle Hearing, Speech, & Deafness Center": None,
    "Seattle World School": None,
    "South Seattle Community College": None,
    "Wallingford Boys & Girls Club": None,
}

_S4_OVERRIDES: dict[str, int | None] = {
    # Punctuation variants that normalization misses
    "B.F. Day": 218,
    "Bailey Gatzert": 226,
    "Catharine Blaine": 289,
    "Catharine Blaine K-8": 289,
    "Daniel Bagley": 204,
    "David T. Denny Int'l": 103,
    "David T. Denny Intl": 103,
    "Eagle Staff": 113,           # Robert Eagle Staff (abbreviated)
    "Frantz Coe": 211,
    "Franz Coe": 211,
    "J. Stanford Intl.": 241,
    "James Baldwin": 257,
    "Jane Addams MS": 106,
    "John Hay": 234,
    "John Muir": 256,
    "John Rogers": 266,
    "John Stanford Int'l": 241,
    "John Stanford Intl": 241,
    "John Stanford Intl.": 241,
    "K-5 STEM at Boren": 972,
    "K-5 STEM at Boren             N/A": 972,
    "Martin Luther King": 207,
    "McClure Other": 118,         # "Other" = open-enrollment / non-resident rows
    "Ocra": 939,                  # Orca typo
    "Pinehurst": 292,             # Hazel Wolf @ Pinehurst site
    "Sandpoint": 269,             # Sand Point
    "Sealth": 18,                 # Chief Sealth
    "South Shore PK-8": 291,
    "STEM K-8": 972,              # K-5 STEM at Boren (ES + MS draw)
    "T. Marshall": 212,           # Thurgood Marshall
    "The Center School": 24,
    "Washington Other": 117,
    "West Seattle": 19,           # HS context only in all Section 4 years
    "West Seattle ES": 236,
    "West Seattle Elem.": 236,
    "West Seattle Elementar": 236,
    "West Seattle HS": 19,
    "Whitman Other": 115,
    # Historical program name
    "APP at Lincoln": 15,         # APP/HCC at Lincoln HS building
    "AS #1": 935,                 # TOPS, formerly Alternative School #1
    "Cleveland STEM": 12,
    # Closed schools (present in older years only)
    "Northgate": None,
    "Schmitz Park": None,
    "Van Asselt": None,
    # Non-school entries
    "Alan T. Sugiyama": None,
    "Bridges": None,
    "Bridges Transition Program": None,
    "Cascade PP Prog*": None,
    "Cascade PP Prog**": None,
    "Cascade Parent": None,
    "Cascade Parent Part'ship": None,
    "Cascade Parent Partner.": None,
    "Cascade Parent Partnersh": None,
    "Cascade Parent Partnershi": None,
    "Cascade Parent Partnership": None,
    "Cascade Parent Partnership Pro": None,
    "Cascade Parent Partnership Program": None,
    "Cascade Virtual Option": None,
    "Cascade Virtual Option K-12": None,
    "Ed. Serv. Center": None,
    "Education Service Centers": None,
    "Education Service Ctrs": None,
    "Exp. Ed. Unit": None,
    "Home School": None,
    "Home School Resource": None,
    "Hutch School": None,
    "In Tandem": None,
    "InterAgency": None,
    "Interagency": None,
    "Middle College": None,
    "Non Public Agencies": None,
    "Non-Res": None,
    "Out of District/Unknow": None,
    "Out of District/Unknown": None,
    "Partnership": None,
    "Partnership Program": None,
    "Priv/Parach Sped": None,
    "Priv/Paroch Sped": None,
    "Private Sp. Ed. Srvcs.": None,
    "Program": None,
    "Res Consortium": None,
    "Secondary BOC": None,
    "Seattle World School": None,
    "South Lake": None,
    "SpEd Consortium": None,
    "Sugiyama High School": None,
    "World School": None,
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_STRIP_SUFFIXES = [
    "elementary school", "middle school", "high school",
    "k 8 school", "k8 school", "k 8", "k8",
    "elementary", "international", "intl", "school",
    "m s", "h s", "e s", "ms", "hs", "es",
]


def _normalize(name: str) -> str:
    """Reduce a school name to a short token for comparison."""
    s = name.lower().strip().rstrip("*").strip()
    # Strip parentheticals like "(Temp ...)" or "(21-22, ...)"
    s = re.sub(r"\s*\([^)]*\)", "", s)
    # Strip "@ location" suffixes (keep the program part before @)
    s = re.sub(r"\s+@\s+.*$", "", s)
    # Strip temp/construction trailing phrases
    s = re.sub(r"[-\s]+temp\b.*$", "", s)
    s = re.sub(r"\s+temporary\b.*$", "", s)
    # Normalize punctuation: apostrophes, dots, commas → remove; hyphens → space
    s = s.replace("'", "").replace(".", "").replace(",", "").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Strip trailing school-type tokens iteratively (longest first each pass)
    while True:
        stripped = False
        for suf in _STRIP_SUFFIXES:
            if s.endswith(" " + suf):
                s = s[: -len(suf) - 1].strip()
                stripped = True
                break
        if not stripped:
            break
    return s.strip()


# ---------------------------------------------------------------------------
# Name-map builder
# ---------------------------------------------------------------------------

def _build_name_map(
    source_names: list[str],
    norm_to_id: dict[str, int],
    overrides: dict[str, int | None],
    fuzzy_cutoff: float = 0.82,
) -> pd.DataFrame:
    """Map a list of raw names to school_ids.

    Returns a DataFrame with columns:
      name, school_id, match_type
    match_type is one of: manual | exact | fuzzy | unmatched | non_school
    """
    rows = []
    canonical_norms = list(norm_to_id.keys())

    for raw in source_names:
        if raw in overrides:
            sid = overrides[raw]
            mtype = "non_school" if sid is None else "manual"
            rows.append({"name": raw, "school_id": sid, "match_type": mtype})
            continue

        norm = _normalize(raw)

        # Exact normalized match
        if norm in norm_to_id:
            rows.append({"name": raw, "school_id": norm_to_id[norm], "match_type": "exact"})
            continue

        # Fuzzy match
        matches = difflib.get_close_matches(norm, canonical_norms, n=1, cutoff=fuzzy_cutoff)
        if matches:
            rows.append({
                "name": raw,
                "school_id": norm_to_id[matches[0]],
                "match_type": "fuzzy",
            })
            continue

        rows.append({"name": raw, "school_id": None, "match_type": "unmatched"})

    df = pd.DataFrame(rows)
    df["school_id"] = df["school_id"].astype("Int64")
    return df


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_HCC_PATHWAY_SITES = {
    "current":    {"Cascadia", "Decatur", "Thurgood Marshall"},
    "proposed":   {"Cascadia", "Decatur", "Thurgood Marshall", "Alki", "Rainier View"},
    "historical": {"Cascadia", "Decatur", "Thurgood Marshall", "Fairmount Park"},
}


def _classify_schools(locs: pd.DataFrame) -> pd.DataFrame:
    """Add classification and HCC-site flags to the locations DataFrame."""
    def _cls(status: str) -> str:
        if status == "HC":
            return "hcc_pathway"
        if "Option" in status:
            return "option"
        if status == "Service School":
            return "service"
        return "neighborhood"

    df = locs[["school_id", "school_code", "name", "level", "status"]].copy()
    df["classification"] = df["status"].apply(_cls)

    for era, sites in _HCC_PATHWAY_SITES.items():
        df[f"is_hcc_site_{era}"] = df["name"].isin(sites)

    return df.drop(columns=["status"])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build() -> None:
    """Generate and write all school_directory CSVs."""
    _DIR.mkdir(exist_ok=True)

    locs = load_locations()
    norm_to_id: dict[str, int] = {
        _normalize(row["name"]): int(row["school_id"])
        for _, row in locs.iterrows()
        if pd.notna(row["school_id"])
    }

    # --- schools.csv --------------------------------------------------------
    schools = _classify_schools(locs)

    # Program flags from STARS routes (requires stars_name_map to already be built,
    # so we do a two-pass: first build stars_map, then add flags).
    stars_dests_path = _HERE / "stars_seattle" / "destinations.csv"
    stars_dests = pd.read_csv(stars_dests_path)["destination_name"].dropna().tolist()
    stars_map_df = _build_name_map(stars_dests, norm_to_id, _STARS_OVERRIDES)

    routes_path = _HERE / "stars_seattle" / "routes.csv"
    routes = pd.read_csv(routes_path)
    # Join destination_name → school_id via the map
    name_to_sid = stars_map_df.set_index("name")["school_id"]
    routes = routes.copy()
    routes["school_id"] = routes["destination_name"].map(name_to_sid)

    flag_programs = {
        "has_gifted":   "gifted",
        "has_bilingual": "bilingual",
        "has_early_ed":  "early_ed",
    }
    for flag, prog in flag_programs.items():
        flagged_ids = set(
            routes.loc[routes["program"] == prog, "school_id"].dropna().astype(int)
        )
        schools[flag] = schools["school_id"].isin(flagged_ids)

    schools.to_csv(_DIR / "schools.csv", index=False)
    print(f"schools.csv: {len(schools)} rows")

    # --- stars_name_map.csv -------------------------------------------------
    stars_map_df.to_csv(_DIR / "stars_name_map.csv", index=False)
    matched = stars_map_df["match_type"].isin(["manual", "exact", "fuzzy"]).sum()
    unmatched = (stars_map_df["match_type"] == "unmatched").sum()
    print(
        f"stars_name_map.csv: {len(stars_map_df)} names, "
        f"{matched} matched, {unmatched} unmatched"
    )
    if unmatched:
        print("  UNMATCHED STARS names:")
        for nm in stars_map_df.loc[stars_map_df["match_type"] == "unmatched", "name"]:
            print(f"    {nm!r}")

    # Update destinations.csv with filled school_id
    dests = pd.read_csv(stars_dests_path)
    sid_lookup = stars_map_df.set_index("name")["school_id"]
    dests["school_id"] = dests["destination_name"].map(sid_lookup)
    dests.to_csv(stars_dests_path, index=False)
    print(f"destinations.csv updated with school_id")

    # --- section4_name_map.csv ----------------------------------------------
    s4_names: set[str] = set()
    for fname in [
        "out_enrollment/section4_od.csv",
        "out_enrollment/section4_attendees.csv",
        "out_enrollment/section4_option_draw.csv",
    ]:
        df = pd.read_csv(_HERE.parents[1] / fname)
        for col in ("school", "residence_area"):
            if col in df.columns:
                s4_names.update(df[col].dropna().unique())

    s4_map_df = _build_name_map(sorted(s4_names), norm_to_id, _S4_OVERRIDES)
    s4_map_df.to_csv(_DIR / "section4_name_map.csv", index=False)
    matched = s4_map_df["match_type"].isin(["manual", "exact", "fuzzy"]).sum()
    unmatched_s4 = s4_map_df[s4_map_df["match_type"] == "unmatched"]
    print(
        f"section4_name_map.csv: {len(s4_map_df)} names, "
        f"{matched} matched, {unmatched_s4.shape[0]} unmatched"
    )
    if len(unmatched_s4):
        print("  UNMATCHED Section4 names:")
        for nm in unmatched_s4["name"]:
            print(f"    {nm!r}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_schools() -> pd.DataFrame:
    """Return the 98-row canonical school directory with classification + flags."""
    return pd.read_csv(_DIR / "schools.csv")


def load_stars_name_map() -> pd.Series:
    """Return a Series mapping STARS destination_name → school_id (Int64)."""
    df = pd.read_csv(_DIR / "stars_name_map.csv")
    return df.set_index("name")["school_id"].astype("Int64")


def load_section4_name_map() -> pd.Series:
    """Return a Series mapping Section 4 school/area name → school_id (Int64)."""
    df = pd.read_csv(_DIR / "section4_name_map.csv")
    return df.set_index("name")["school_id"].astype("Int64")


# ---------------------------------------------------------------------------
# Summary (__main__)
# ---------------------------------------------------------------------------

def _summary() -> None:
    schools = load_schools()
    stars_map = pd.read_csv(_DIR / "stars_name_map.csv")
    s4_map = pd.read_csv(_DIR / "section4_name_map.csv")

    print("=== schools.csv ===")
    print(f"  {len(schools)} schools")
    print(f"  classification: {schools['classification'].value_counts().to_dict()}")
    for era in ("current", "proposed", "historical"):
        n = schools[f"is_hcc_site_{era}"].sum()
        names = schools.loc[schools[f"is_hcc_site_{era}"], "name"].tolist()
        print(f"  is_hcc_site_{era}: {n} — {names}")
    for flag in ("has_gifted", "has_bilingual", "has_early_ed"):
        n = schools[flag].sum()
        names = schools.loc[schools[flag], "name"].tolist()
        print(f"  {flag}: {n} — {names}")

    print("\n=== stars_name_map.csv ===")
    print(f"  {len(stars_map)} names")
    print(f"  by match_type: {stars_map['match_type'].value_counts().to_dict()}")
    fuzzy = stars_map[stars_map["match_type"] == "fuzzy"]
    if len(fuzzy):
        print(f"  fuzzy matches (review for correctness):")
        school_lookup = load_schools().set_index("school_id")["name"]
        for _, r in fuzzy.iterrows():
            sid = r["school_id"]
            cname = school_lookup.get(sid, "?") if pd.notna(sid) else "?"
            print(f"    {r['name']!r:55s} → {sid} ({cname})")

    print("\n=== section4_name_map.csv ===")
    print(f"  {len(s4_map)} names")
    print(f"  by match_type: {s4_map['match_type'].value_counts().to_dict()}")
    s4_fuzzy = s4_map[s4_map["match_type"] == "fuzzy"]
    if len(s4_fuzzy):
        print(f"  fuzzy matches (review for correctness):")
        school_lookup = load_schools().set_index("school_id")["name"]
        for _, r in s4_fuzzy.iterrows():
            sid = r["school_id"]
            cname = school_lookup.get(sid, "?") if pd.notna(sid) else "?"
            print(f"    {r['name']!r:55s} → {sid} ({cname})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.build:
        _build()
    _summary()
