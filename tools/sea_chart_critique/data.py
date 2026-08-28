"""Numbers behind the SEA chart critique. All 2024-25 unless stated.

Two sources:
  * S-275 final, SPS 2024-25 -- via s275_by_duty_2425.sql (cached CSV).
  * The 1191F prototypical-school drivers + 1191EDF model roles, already
    parsed by tools/duty_funding/ into output/duty_funding/.
"""
import csv
import os
import subprocess
from decimal import Decimal as D

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "output", "sea_chart_critique")
DUTY_FUNDING = os.path.join(ROOT, "output", "duty_funding")
SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "s275_by_duty_2425.sql")
DUTY_CSV = os.path.join(OUT, "s275_by_duty_2425.csv")

# ---------------------------------------------------------------- 1191F rates
# Per-1.0-staff-unit salary allocations, SPS 2024-25, regionalization 1.180
# included. Derived in load_1191f() from the parsed drivers so they stay tied
# to the PDF rather than being typed in.
IPD_2526 = D("1.025")          # 2025-26 salary inflator; confirmed below
REGIONALIZATION = D("1.180")


def load_1191f():
    """CIS/CAS/CLS salary rate per 1.0 staff unit, plus the PLD add-on."""
    vals = {}
    with open(os.path.join(DUTY_FUNDING, "sps_2024-25_1191f_drivers.csv")) as f:
        for r in csv.DictReader(f):
            vals.setdefault(r["name"], set()).add(r["value"])

    def one(name):
        v = vals[name]
        assert len(v) == 1, (name, v)
        return D(next(iter(v)))

    cis_fte = one("School Generated CIS FTE")
    cas_fte = one("School Generated CAS FTE")
    reg = one("Regionalization")
    assert reg == REGIONALIZATION

    # CIS and CLS print their salary-increase-level rate directly.
    cis = one("CIS Sal Inc") * reg
    cls = one("CLS - Salary Inc") * reg
    # CAS prints only the maintenance rate; recover the full rate from the
    # two subtotals it feeds (maint + increase) over school-generated CAS FTE.
    cas = (D("18051105.89") + D("1360584.03")) / cas_fte
    pld = one("School CIS PD Salary") / cis_fte   # professional learning days
    return {
        "cis": cis, "cas": cas, "cls": cls, "pld_per_cis_fte": pld,
        "cis_fte": cis_fte, "cas_fte": cas_fte,
        "cls_fte": one("School Generated CLS FTE"),
        "district_cas_fte": one("District Total CAS FTE"),
        "district_cls_fte": one("District Total CLS FTE"),
        "central_cas_fte": one("Central Admin CAS FTE"),
        "enrollment_aafte": one("Enroll Total w/ Run Start"),
        "cas_allocation": D("18051105.89") + D("1360584.03"),
    }


# ------------------------------------------------------------------- S-275
def load_duties():
    if not os.path.exists(DUTY_CSV):
        os.makedirs(OUT, exist_ok=True)
        with open(SQL) as fin, open(DUTY_CSV, "w") as fout:
            subprocess.run(
                ["bq", "--project_id=sps-btn-data", "query",
                 "--use_legacy_sql=false", "--max_rows=500", "--format=csv"],
                stdin=fin, stdout=fout, check=True)
    with open(DUTY_CSV) as f:
        return {r["duty_root"]: r for r in csv.DictReader(f)}


# S-275 duty roots -> the staff class the state's model would put them in.
CAS_ROOTS = ["11", "12", "13", "21", "22", "23", "24", "25"]
CIS_ROOTS = ["31", "32", "33", "34", "39", "40", "41", "42", "43", "44",
             "45", "46", "47", "48", "51", "52", "61"]
CLS_ROOTS = ["90", "91", "92", "93", "94", "95", "96", "97", "98", "99"]

# The five SEA buckets, mapped to duty roots that anyone can re-run.
GROUPS = [
    ("Teachers",                      ["31", "32", "33", "34"],        "cis"),
    ("Instructional aides (paras)",   ["91"],                          "cls"),
    ("Classified professionals",      ["96"],                          "cls"),
    ("Directors & supervisors",       ["99"],                          "cls"),
    ("Principals & vice principals",  ["21", "22", "23", "24", "25"],  "cas"),
    ("Office & clerical",             ["94"],                          "cls"),
    ("Cabinet & district admin",      ["12", "13"],                    "cas"),
    ("Superintendent",                ["11"],                          "cas"),
]


def group_rows(duties, rates):
    out = []
    for name, roots, cls in GROUPS:
        roots = [r for r in roots if r in duties]
        emp = sum(int(duties[r]["employees"]) for r in roots)
        fte = sum(D(duties[r]["fte"]) for r in roots)
        sal = sum(D(duties[r]["total_final_salary"]) for r in roots)
        rate = rates[cls]
        out.append({
            "name": name, "class": cls.upper(), "roots": roots,
            "employees": emp, "fte": fte, "salary": sal,
            "per_fte": sal / fte, "rate": rate,
            "gap_per_fte": sal / fte - rate,
            "gap_total": sal - rate * fte,
        })
    return out


def class_totals(duties, rates):
    out = {}
    for cls, roots in (("cis", CIS_ROOTS), ("cas", CAS_ROOTS), ("cls", CLS_ROOTS)):
        roots = [r for r in roots if r in duties]
        out[cls] = {
            "employees": sum(int(duties[r]["employees"]) for r in roots),
            "fte": sum(D(duties[r]["fte"]) for r in roots),
            "salary": sum(D(duties[r]["total_final_salary"]) for r in roots),
            "rate": rates[cls],
        }
        out[cls]["gap_total"] = out[cls]["salary"] - rates[cls] * out[cls]["fte"]
    return out


def model_roles():
    rows = []
    with open(os.path.join(DUTY_FUNDING, "sps_2024-25_model_roles.csv")) as f:
        for r in csv.DictReader(f):
            if r["role"].startswith("Roles with no basic"):
                continue
            role = " ".join(r["role"].split())
            if role.startswith("Facilities"):
                role = "Facilities, warehouse, maintenance"
            rows.append({
                "role": role,
                "class": r["staff_class"],
                "model_fte": D(r["model_fte"]),
                "actual_fte": D(r["actual_fte"]),
                "model_dollars": D(r["model_dollars"]),
                "actual_pay": D(r["actual_pay"]),
            })
    # Two rows are named "Central administration"; disambiguate by class.
    for r in rows:
        if r["role"] == "Central administration":
            r["role"] = "Central administration (%s)" % r["class"]
    return rows


# --------------------------------------------------------------- SEA buckets
# SEA's job categories are not S-275 categories and it published no
# definitions. S-275 carries no names, so the buckets are reconstructed by
# salary tier and checked against headcounts from the SPS leadership pages as
# they stood during 2024-25 (Wayback captures 2025-03-22 and 2025-03-26):
#
#   Superintendent                  1   Dr. Brent Jones
#   Superintendent Senior Cabinet  10   Redmond, Narver, Podesta, Pritchett,
#                                       Howard, Campbell, Torres, Starosky,
#                                       Buttleman, Del Valle
#   Regional Exec. Directors        5   Carter, Moynihan, Hunt, McCarthy, Mercer
#
# The cabinet tier lands on exactly ten people paid $275,613 or more (excluding
# the superintendent), which is the check that makes the match credible.
ADMIN_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "s275_admin_employees_2425.sql")
ADMIN_CSV = os.path.join(OUT, "s275_admin_employees_2425.csv")

CABINET_FLOOR = D("275000")   # the gap below this tier is $21,047 wide
N_CABINET = 10                # from the 2024-25 leadership page
N_EXEC_DIRECTORS = 5          # from the 2024-25 directors-of-schools page


def load_admin_employees():
    if not os.path.exists(ADMIN_CSV):
        os.makedirs(OUT, exist_ok=True)
        with open(ADMIN_SQL) as fin, open(ADMIN_CSV, "w") as fout:
            subprocess.run(
                ["bq", "--project_id=sps-btn-data", "query",
                 "--use_legacy_sql=false", "--max_rows=1000", "--format=csv"],
                stdin=fin, stdout=fout, check=True)
    with open(ADMIN_CSV) as f:
        rows = [r for r in csv.DictReader(f)]
    for r in rows:
        r["salary"] = D(r["salary"])
        r["fte"] = D(r["fte"])
        r["is_cas"] = r["duty_root"] in ("11", "12", "13")
    return rows


def sea_buckets(duties, rates):
    """SEA's five job categories, rebuilt with the right membership.

    Administrators are counted in POSITIONS. Since the s275 assignment dedup
    was fixed they file at 1.0 FTE apiece, so positions and FTE agree for them
    and the basis no longer changes any number -- it is kept because headcount
    is what the leadership roster gives, and it is what the buckets are matched
    against. Teachers and paras divide by FTE, which for them is real
    part-time work.
    """
    emp = load_admin_employees()
    supt = [r for r in emp if r["duty_root"] == "11"]
    cabinet = sorted((r for r in emp
                      if r["duty_root"] != "11" and r["salary"] >= CABINET_FLOOR),
                     key=lambda r: -r["salary"])
    assert len(cabinet) == N_CABINET, (len(cabinet), N_CABINET)
    taken = {r["emp"] for r in cabinet}
    rest13 = sorted((r for r in emp
                     if r["duty_root"] == "13" and r["emp"] not in taken),
                    key=lambda r: -r["salary"])
    execdirs = rest13[:N_EXEC_DIRECTORS]
    taken |= {r["emp"] for r in execdirs}
    progdirs = [r for r in emp
                if r["duty_root"] in ("13", "99") and r["emp"] not in taken]

    def by_person(name, rows, note):
        n = len(rows)
        n_cas = sum(1 for r in rows if r["is_cas"])
        rate = (n_cas * rates["cas"] + (n - n_cas) * rates["cls"]) / n
        sal = sum(r["salary"] for r in rows)
        reported_fte = sum(r["fte"] for r in rows)
        return {
            "name": name, "note": note, "basis": "positions",
            "positions": D(n), "headcount": n, "n_cas": n_cas,
            "n_cls": n - n_cas, "salary": sal, "per": sal / n, "rate": rate,
            "sea_per": sal / reported_fte, "reported_fte": reported_fte,
        }

    def by_fte(name, roots, cls, note):
        roots = [r for r in roots if r in duties]
        n = sum(int(duties[r]["employees"]) for r in roots)
        fte = sum(D(duties[r]["fte"]) for r in roots)
        sal = sum(D(duties[r]["total_final_salary"]) for r in roots)
        return {
            "name": name, "note": note, "basis": "FTE", "positions": fte,
            "headcount": n, "n_cas": 0, "n_cls": 0, "salary": sal,
            "per": sal / fte, "rate": rates[cls], "sea_per": sal / fte,
            "reported_fte": fte,
        }

    return [
        by_person("Superintendent", supt, "duty 11"),
        by_person("Executive cabinet", cabinet,
                  "10 senior cabinet, 2024-25 roster"),
        by_person("Regional exec. directors", execdirs,
                  "5 regional EDs, 2024-25 roster"),
        by_person("Program directors", progdirs,
                  "all remaining duty 13 + 99"),
        by_fte("Teachers", ["31", "32", "33", "34"], "cis", "duty 31-34"),
        by_fte("Paras & office staff", ["91", "94"], "cls", "duty 91, 94"),
    ]


# ------------------------------------------------- funded units per skyline group
# The 1191EDF roles do not line up one-to-one with the eight job groups: two
# roles each cover two groups, so their units are split by the groups' actual
# FTE. Duty 25 ("Other School Administrator", one person) sits under the model's
# central-administration role but under principals here; at one position it
# does not move anything.
GROUP_ROLES = {
    "Teachers": (["Classroom teachers"], ["31", "32", "33", "34"]),
    "Instructional aides (paras)": (
        ["Teaching assistance and family involvement"], ["91"]),
    "Office & clerical": (["Office support"], ["94"]),
    "Principals & vice principals": (
        ["Principals and vice principals"], ["21", "22", "23", "24", "25"]),
    "Cabinet & district admin": (["Central administration (CAS)"], ["12", "13"]),
    "Superintendent": (["Central administration (CAS)"], ["11"]),
    "Classified professionals": (["Central administration (CLS)"], ["96"]),
    "Directors & supervisors": (["Central administration (CLS)"], ["99"]),
}


def funded_units_by_group(duties):
    """Staff units the model generates for each of the eight job groups."""
    roles = {r["role"]: r for r in model_roles()}
    share = {}
    for name, (rns, codes) in GROUP_ROLES.items():
        share[name] = sum(D(duties[c]["fte"]) for c in codes if c in duties)
    out = {}
    for name, (rns, _) in GROUP_ROLES.items():
        units = D(0)
        for rn in rns:
            peers = [n for n, (r2, _) in GROUP_ROLES.items() if rn in r2]
            denom = sum(share[n] for n in peers)
            units += roles[rn]["model_fte"] * (share[name] / denom)
        out[name] = units
    return out
