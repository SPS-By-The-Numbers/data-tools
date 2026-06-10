"""Ingest the OSPI Report Card enrollment + SQSS (attendance) data for Seattle.

Two sources, both Seattle (ccddd 17001), both gitignored locally, so this module
filters/cleans them into **tracked** intermediate CSVs under
`analysis/montecarlo/rc_seattle/`:

  1. ``data/enrollment/rc_enrollment_17001.csv`` -- OSPI Report Card enrollment,
     per school x grade x year, with demographic counts (low_income, SWD, ELL,
     highly_capable, race, gender, homeless, foster, ...). Already Seattle-only.

  2. ``safs_prod/sqss/rc_sqss.avro`` -- the SQSS Report Card for ALL districts
     (5.4M rows). We keep the **Regular Attendance** measure for Seattle. OSPI's
     "Regular Attendance" = share of students absent <10% of enrolled days;
     its complement is **chronic absenteeism** (absent >=10%). So:

         regular_attendance_rate = numerator / denominator
         chronic_absent_rate     = 1 - regular_attendance_rate
         chronic_absent_count    = denominator - numerator

Why: together these let us relate per-school enrollment (and its demographic mix
+ chronic absenteeism) to bus ridership, so the Monte Carlo can distribute total
riders across the district non-uniformly instead of assuming every school pulls
riders at the same rate.

Notes / gotchas baked in here:
  * The avro's ``percent`` column is unpopulated in this dump (always 0). We
    compute rates from numerator/denominator, NOT percent.
  * Suppressed/missing cells use the SAFS null sentinel -931415926; we map those
    to NaN. ``dat`` carries the suppression reason ("Suppressed: N<10", etc.).
  * ``student_group_type`` uses two different vocabularies across source years
    (e.g. "AllStudents" vs "All Students", "SWD" vs "Student With Disabilities
    Status"). We normalize to a single canonical set (see ``_GROUP_TYPE``).

Build (reads the gitignored sources, writes rc_seattle/):

    $ python3 -m analysis.montecarlo.rc_seattle --build

Then:

    from analysis.montecarlo import rc_seattle as rc
    enr  = rc.load_enrollment()
    saa  = rc.load_attendance_all_students()    # AllStudents, all grade bands
    grp  = rc.load_attendance_by_group()        # every subgroup, school-level
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
ENROLLMENT_SRC = _REPO_ROOT / "data" / "enrollment" / "rc_enrollment_17001.csv"
SQSS_SRC = _REPO_ROOT / "safs_prod" / "sqss" / "rc_sqss.avro"
OUT_DIR = Path(__file__).resolve().parent / "rc_seattle"

SEATTLE_CCDDD = 17001
ATTENDANCE_MEASURE = "Regular Attendance"
NULL_SENTINEL = -931415926  # SAFS _NULL_NUMBER

# Enrollment columns that are integer counts (everything else is id/label/text).
_ENROLL_INT = [
    "all_students", "military_parent", "migrant", "low_income", "homeless",
    "foster_care", "mobile", "section_504", "highly_capable",
    "english_language_learners", "students_with_disabilities", "female", "male",
    "gender_x", "white", "black_african_american", "native_hawaiian_other_pacific",
    "hispanic_latino_of_any_race", "american_indian_alaskan_native", "asian",
    "two_or_more_races",
]

# Canonicalize the two source vocabularies for student_group_type.
_GROUP_TYPE = {
    "AllStudents": "all", "All Students": "all",
    "Income": "low_income", "Low Income Status": "low_income",
    "SWD": "swd", "Student With Disabilities Status": "swd",
    "EnglishLearner": "english_learner", "English Learner Status": "english_learner",
    "Homeless": "homeless", "Homeless Status": "homeless",
    "Foster": "foster", "Foster Care Status": "foster",
    "HiCAP": "highly_capable", "Highly Capable Status": "highly_capable",
    "Migrant": "migrant", "Migrant Status": "migrant",
    "MilitaryFamily": "military", "Military Parent Status": "military",
    "Section504": "section_504", "Section 504 Status": "section_504",
    "Mobile Status": "mobile",
    "Gender": "gender",
    "FederalRaceEthnicity": "race_ethnicity", "Federal Race Ethnicity": "race_ethnicity",
}


# --- enrollment ---------------------------------------------------------------

def build_enrollment(verbose: bool = True) -> pd.DataFrame:
    df = pd.read_csv(ENROLLMENT_SRC, dtype=str)
    for col in _ENROLL_INT:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["is_district_total"] = df["school_name"].eq("District Total")
    # Normalized fall-start year: works across all three source formats
    # ("2014-15", "2014-2015", "2017-2018") for joins between sources.
    df.insert(1, "year", df["school_year"].str[:4].astype(int))
    # ccddd is constant (17001); keep it dropped-implicit like the STARS slice.
    df = df.drop(columns=[c for c in ["ccddd"] if c in df.columns])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "enrollment.csv", index=False)
    if verbose:
        print(f"  enrollment              {len(df):>6} rows -> enrollment.csv "
              f"({df.school_code.nunique()} schools, "
              f"{df.school_year.nunique()} years)")
    return df


# --- attendance (SQSS Regular Attendance -> chronic absenteeism) ---------------

def _clean_num(v):
    if v is None:
        return None
    f = float(v)
    return None if f == NULL_SENTINEL else f


def build_attendance(verbose: bool = True) -> pd.DataFrame:
    import fastavro

    keep_cols = ["school_year", "class_of", "school_code", "student_group_type",
                 "student_group", "grade_level", "dat"]
    records = []
    with open(SQSS_SRC, "rb") as f:
        for rec in fastavro.reader(f):
            if rec.get("ccddd") != SEATTLE_CCDDD or rec.get("measure") != ATTENDANCE_MEASURE:
                continue
            row = {k: rec.get(k) for k in keep_cols}
            row["numerator"] = _clean_num(rec.get("numerator"))
            row["denominator"] = _clean_num(rec.get("denominator"))
            records.append(row)

    df = pd.DataFrame.from_records(records)
    df["group_type"] = df["student_group_type"].map(_GROUP_TYPE).fillna(df["student_group_type"])

    # Rates computed from counts (the `percent` column is unusable in this dump).
    # "Suppressed" must key off whether a rate is actually computable, NOT the
    # `dat` string: in 2022-23+ OSPI changed `dat` to "Top/Bottom Range: ..."
    # / blank even on rows that carry real counts, so the old dat-based flag
    # wrongly nuked every recent year. `dat` is kept only as an annotation.
    den = df["denominator"]
    valid = den.notna() & (den > 0) & df["numerator"].notna()
    df["suppressed"] = ~valid
    df["regular_attendance_rate"] = (df["numerator"] / den).where(valid)
    df["chronic_absent_rate"] = (1 - df["regular_attendance_rate"]).where(valid)
    df["chronic_absent_count"] = (den - df["numerator"]).where(valid)
    df = df.rename(columns={"denominator": "n_students", "numerator": "n_regular"})

    df["year"] = df["school_year"].str[:4].astype(int)
    cols = ["school_year", "year", "class_of", "school_code", "group_type", "student_group",
            "grade_level", "n_students", "n_regular", "regular_attendance_rate",
            "chronic_absent_rate", "chronic_absent_count", "suppressed", "dat"]
    df = df[cols].sort_values(["school_year", "school_code", "group_type", "grade_level"])

    # We don't persist the full 169k-row per-grade x per-subgroup table (it's
    # ~15MB and finer than the ridership work needs). Instead two lean slices:
    #   * AllStudents across ALL grade bands  (per-school per-grade signal)
    #   * every subgroup at the school level  (grade_level == "All Grades")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saa = df[df["group_type"] == "all"]
    by_group = df[df["grade_level"] == "All Grades"]
    saa.to_csv(OUT_DIR / "attendance_all_students.csv", index=False)
    by_group.to_csv(OUT_DIR / "attendance_by_group.csv", index=False)

    if verbose:
        print(f"  attendance_all_students {len(saa):>6} rows -> attendance_all_students.csv")
        print(f"  attendance_by_group     {len(by_group):>6} rows -> attendance_by_group.csv")
    return df


def build(verbose: bool = True) -> None:
    if not ENROLLMENT_SRC.exists():
        raise FileNotFoundError(f"missing {ENROLLMENT_SRC}")
    if not SQSS_SRC.exists():
        raise FileNotFoundError(f"missing {SQSS_SRC}")
    build_enrollment(verbose=verbose)
    build_attendance(verbose=verbose)
    if verbose:
        print(f"\nWrote Seattle Report Card intermediates to {OUT_DIR}")


# --- loaders ------------------------------------------------------------------

def _load(name: str) -> pd.DataFrame:
    path = OUT_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python3 -m analysis.montecarlo.rc_seattle "
            "--build` (requires the gitignored sources)."
        )
    return pd.read_csv(path)


def load_enrollment() -> pd.DataFrame:
    return _load("enrollment")


def load_attendance_all_students() -> pd.DataFrame:
    return _load("attendance_all_students")


def load_attendance_by_group() -> pd.DataFrame:
    return _load("attendance_by_group")


def _summary() -> None:
    print(f"Seattle Report Card intermediates in {OUT_DIR}\n")
    enr = load_enrollment()
    schools = enr[~enr.is_district_total]
    ag = schools[schools.grade == "All Grades"]
    print(f"Enrollment: {len(enr)} rows, {schools.school_code.nunique()} schools, "
          f"years {enr.school_year.min()}..{enr.school_year.max()}")
    tot = ag.groupby("school_year").all_students.sum()
    print("  district all-grades enrollment by year:")
    print(tot.to_string())

    att = load_attendance_all_students()
    ag2 = att[(att.grade_level == "All Grades") & (~att.suppressed)]
    byyr = ag2.groupby("school_year").agg(
        schools=("school_code", "nunique"),
        chronic_absent_rate=("chronic_absent_rate", "mean"),
    )
    print(f"\nChronic absenteeism (AllStudents, All Grades, unsuppressed): "
          f"{len(att)} all-student rows total")
    print("  mean per-school chronic-absent rate by year:")
    print((byyr.assign(chronic_absent_rate=(byyr.chronic_absent_rate * 100).round(1))).to_string())


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv:
        build()
    else:
        _summary()
