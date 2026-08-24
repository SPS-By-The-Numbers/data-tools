#!python3
"""How much of each S-275 duty title is covered by the state's basic
education allocation.

Two halves:

  1. S-275 (BigQuery) -- per duty title, summed total_final_salary,
     assignment_salary and FTE for one district/year.
  2. Apportionment (PDF) -- pages 1-7 of the district's 1191F "Final
     Apportionment Summary", which derive the Guaranteed Entitlement from
     state-funded staff units.  Those pages are NOT in
     `ospi_fiscal.fiscal_apportionment_final` (that table is headline-only
     by design), so they are re-parsed here via `parse_bea_pages`.

The state funds three staff classes -- CIS (certificated instructional),
CAS (certificated administrative), CLS (classified) -- each at a flat
per-FTE salary rate, plus insurance and payroll-tax/benefit pots.  Every
duty title maps to exactly one class, which is the join key.

Two attributions are reported per duty title, because they answer
different questions:

  rate-based  = class per-FTE rate * the duty title's actual S-275 FTE.
                "At state rates, what would these people cost?"  Sums to
                more or less than the state pot depending on whether SPS
                staffs above or below the state's model.
  share-based = class allocation pot * (duty FTE / district actual FTE in
                that class).  "Spread the state's actual dollars over the
                people actually doing the work."  Sums exactly to the pot.

Usage:
    python3 -m tools.duty_funding.build_duty_funding \\
        --pdf "data/fiscal/apportionment/2024-2025/district/17001_seattle_public_schools/Final Apportionment Summary.pdf" \\
        -o out.csv
"""

import argparse
import csv
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from .funding_sources import (
    DUTY_CLASS, SEGMENT_KEYS, SEGMENT_LABEL, StaffShares, attribute,
    attribute_staff_units, revenue_lines, staff_units,
)
from .model_roles import FIELDS as ROLE_FIELDS, role_rows
from .parse_bea_pages import pages_for, parse

Q = Decimal("0.01")

# `DUTY_CLASS` (funding_sources) maps duty root -> cis/cas/cls; the columns
# here spell the class in caps.
CLASS_UPPER = {"cis": "CIS", "cas": "CAS", "cls": "CLS"}

SQL = Path(__file__).with_name("s275_by_duty.sql")
PROGRAM_SQL = Path(__file__).with_name("s275_by_duty_program.sql")
BENEFITS_SQL = Path(__file__).with_name("f196_benefits.sql")
REVENUE_SQL = Path(__file__).with_name("f196_revenues.sql")
PROGRAM_OBJECT_SQL = Path(__file__).with_name("f196_program_objects.sql")

OUT_FIELDS = [
    "duty_root_code", "duty_title", "duty_category", "state_staff_class",
    "employees", "assignments",
    "total_final_salary", "assignment_salary", "assignment_fte",
    "state_model_fte_for_class", "actual_fte_for_class",
    "state_salary_rate_per_fte", "state_benefit_rate_per_fte",
    "rate_state_salary", "rate_state_benefits", "rate_state_total_comp",
    "share_of_class_fte",
    "share_state_salary", "share_state_benefits", "share_state_total_comp",
    "pct_salary_state_funded_rate", "pct_salary_state_funded_share",
] + [f"rev_{k}" for k in SEGMENT_KEYS] + [
    "staff_revenue_all_sources", "pct_salary_all_sources",
    "benefits_paid", "total_compensation", "pct_comp_all_sources",
]


def run_query(sql: Path, ccddd: int, school_year: str, project: str):
    # bq defaults to 100 rows; the duty x program query returns more
    out = subprocess.run(
        ["bq", "query", f"--project_id={project}", "--use_legacy_sql=false",
         "--format=csv", "--quiet", "--max_rows=100000",
         f"--parameter=ccddd:INT64:{ccddd}",
         f"--parameter=school_year:STRING:{school_year}"],
        stdin=sql.open(), check=True, capture_output=True, text=True,
    ).stdout
    return list(csv.DictReader(out.splitlines()))


def class_pots(params):
    """Collapse the recovered 1191F drivers into per-staff-class pots."""
    p = {k: Decimal(v) for k, v in params.items()}

    cis_fte = p["School Generated CIS FTE"]
    cas_fte = p["District Total CAS FTE"]
    cls_fte = p["District Total CLS FTE"]

    cis_salary = p["School CIS Salary Maint Total"] + p["School CIS Salary Inc Total"]
    cas_salary = p["Total CAS Salary Maint"] + p["Total CAS Salary Inc"]
    cls_salary = p["Total CLS Salary Maint"] + p["Total CLS Salary Inc"]

    # Insurance is a headcount pot shared by CIS and CAS; payroll tax and
    # mandatory benefits are a percentage of salary, so they split by salary.
    cert_insurance = p["CIS/CAS Insurance Maint Total"] + p["CIS/CAS Insurance Inc Total"]
    cert_benefits = p["CIS/CAS Benefits Maint Total"] + p["CIS/CAS Benefits Inc Total"]
    cls_insurance = p["CLS Insurance Maint Total"] + p["CLS Insurance Inc Total"]
    cls_benefits = p["CLS Benefits Maint Total"] + p["CLS Benefits Inc Total"]

    cert_fte = cis_fte + cas_fte
    cert_salary = cis_salary + cas_salary

    return {
        "CIS": {
            "fte": cis_fte,
            "salary": cis_salary,
            "benefits": cert_insurance * cis_fte / cert_fte
                        + cert_benefits * cis_salary / cert_salary,
        },
        "CAS": {
            "fte": cas_fte,
            "salary": cas_salary,
            "benefits": cert_insurance * cas_fte / cert_fte
                        + cert_benefits * cas_salary / cert_salary,
        },
        "CLS": {
            "fte": cls_fte,
            "salary": cls_salary,
            "benefits": cls_insurance + cls_benefits,
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, required=True,
                    help="the district's Final Apportionment Summary.pdf")
    ap.add_argument("--ccddd", type=int, default=17001)
    ap.add_argument("--school-year", default="2024-2025")
    ap.add_argument("--project", default="sps-btn-data")
    ap.add_argument("-o", "--out", type=Path, help="output CSV (default stdout)")
    ap.add_argument("--items-out", type=Path,
                    help="also write the parsed pages 1-7 line items here")
    ap.add_argument("--revenue-out", type=Path,
                    help="also write the revenue-source summary here")
    ap.add_argument("--roles-out", type=Path,
                    help="also write the 1191EDF staffing roles here")
    args = ap.parse_args()

    items, raw_params = parse(args.pdf)
    if args.items_out:
        from .parse_bea_pages import ITEM_FIELDS
        with args.items_out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=ITEM_FIELDS)
            w.writeheader()
            w.writerows(items)

    params = {}
    for row in raw_params:
        params.setdefault(row["name"], row["value"])
    pots = class_pots(params)

    duties = run_query(SQL, args.ccddd, args.school_year, args.project)

    # F-196 benefits, as a ratio of the salaries they sit on top of. The S-275
    # reports salary only, so this is what lifts it to total compensation.
    objects = {int(r["object_code"]): Decimal(r["amount"])
               for r in run_query(BENEFITS_SQL, args.ccddd, args.school_year, args.project)}
    benefit_ratio = objects[4] / (objects[2] + objects[3])

    # every General Fund revenue dollar, scaled down to the part its program
    # actually spends on people, then attributed to duty titles
    by_program = run_query(PROGRAM_SQL, args.ccddd, args.school_year, args.project)
    revenues = run_query(REVENUE_SQL, args.ccddd, args.school_year, args.project)
    shares = StaffShares(run_query(PROGRAM_OBJECT_SQL, args.ccddd,
                                   args.school_year, args.project))
    lines, non_staff_revenue, off_chart_revenue = revenue_lines(revenues, shares)
    seg_by_duty = attribute(lines, by_program)
    units = staff_units(params)
    if args.revenue_out:
        staff_by_segment = {k: Decimal(0) for k in SEGMENT_KEYS}
        for key, _program, amount in lines:
            staff_by_segment[key] += amount
        staff_by_segment["apportionment"] = sum(units.values())
        gross = sum(Decimal(r["amount"] or "0") for r in revenues)
        with args.revenue_out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["segment", "label", "staff_revenue", "share_of_staff_revenue"])
            staff_total = sum(staff_by_segment.values())
            for key in SEGMENT_KEYS:
                w.writerow([key, SEGMENT_LABEL[key],
                            staff_by_segment[key].quantize(Q),
                            round(staff_by_segment[key] / staff_total * 100, 2)])
            w.writerow(["_staff_total", "Revenue that pays people",
                        staff_total.quantize(Q), "100.00"])
            w.writerow(["_non_staff",
                        "Not attributed: these sources buy things, not people",
                        non_staff_revenue.quantize(Q), ""])
            w.writerow(["_off_chart",
                        "Not shown: LAP, bilingual, highly capable, "
                        "transportation, food service, Title I, other federal, "
                        "local levy, private gifts and transfers",
                        off_chart_revenue.quantize(Q), ""])

            w.writerow(["_gross", "All General Fund revenue",
                        gross.quantize(Q), ""])
            w.writerow(["_staff_spend", "F-196 spending on objects 2, 3 and 4",
                        (objects[2] + objects[3] + objects[4]).quantize(Q), ""])
            w.writerow(["_model_benefits",
                        "Insurance and payroll benefits inside the staff units",
                        (Decimal(params["TOTAL Benefits"])).quantize(Q), ""])
            w.writerow(["_sped_staff_share",
                        "Share of program 21 spending that is salaries and benefits",
                        round(shares.of(21) * 100, 2), ""])

    # Collapse contract types: one row per duty title.
    rolled = {}
    for d in duties:
        root = int(d["duty_root_code"])
        r = rolled.setdefault(root, {
            "duty_root_code": root,
            "duty_title": d["duty_title"],
            "duty_category": d["duty_category"],
            "state_staff_class": CLASS_UPPER.get(DUTY_CLASS.get(root), "unmapped"),
            "employees": 0, "assignments": 0,
            "total_final_salary": Decimal(0),
            "assignment_salary": Decimal(0),
            "assignment_fte": Decimal(0),
        })
        # employees is a distinct count per contract type; the base-contract
        # row is the one that covers everybody, so take the max rather than
        # summing (which would double-count staff holding a supplemental).
        r["employees"] = max(r["employees"], int(d["employees"]))
        r["assignments"] += int(d["assignments"])
        for k in ("total_final_salary", "assignment_salary", "assignment_fte"):
            r[k] += Decimal(d[k] or "0")

    # the 1191F staff units, attributed by staff class rather than program
    unit_rows = [{"duty_root_code": r["duty_root_code"],
                  "duty_title": r["duty_title"],
                  "assignment_fte": r["assignment_fte"]}
                 for r in rolled.values()]
    for duty, by_key in attribute_staff_units(units, unit_rows).items():
        seg_by_duty.setdefault(duty, {}).update(by_key)

    actual_fte = {}
    for r in rolled.values():
        actual_fte[r["state_staff_class"]] = (
            actual_fte.get(r["state_staff_class"], Decimal(0)) + r["assignment_fte"])

    rows = []
    for r in sorted(rolled.values(), key=lambda x: -x["total_final_salary"]):
        cls = r["state_staff_class"]
        pot = pots.get(cls)
        fte = r["assignment_fte"]
        out = dict(r)

        if pot and pot["fte"]:
            sal_rate = pot["salary"] / pot["fte"]
            ben_rate = pot["benefits"] / pot["fte"]
            share = (fte / actual_fte[cls]) if actual_fte.get(cls) else Decimal(0)
            out.update({
                "state_model_fte_for_class": pot["fte"],
                "actual_fte_for_class": actual_fte[cls],
                "state_salary_rate_per_fte": sal_rate.quantize(Q),
                "state_benefit_rate_per_fte": ben_rate.quantize(Q),
                "rate_state_salary": (sal_rate * fte).quantize(Q),
                "rate_state_benefits": (ben_rate * fte).quantize(Q),
                "rate_state_total_comp": ((sal_rate + ben_rate) * fte).quantize(Q),
                "share_of_class_fte": round(share, 6),
                "share_state_salary": (pot["salary"] * share).quantize(Q),
                "share_state_benefits": (pot["benefits"] * share).quantize(Q),
                "share_state_total_comp": ((pot["salary"] + pot["benefits"]) * share).quantize(Q),
            })
            if r["total_final_salary"]:
                out["pct_salary_state_funded_rate"] = round(
                    (sal_rate * fte) / r["total_final_salary"] * 100, 2)
                out["pct_salary_state_funded_share"] = round(
                    (pot["salary"] * share) / r["total_final_salary"] * 100, 2)

        benefits = r["total_final_salary"] * benefit_ratio
        comp = r["total_final_salary"] + benefits
        out["benefits_paid"] = benefits.quantize(Q)
        out["total_compensation"] = comp.quantize(Q)

        segs = seg_by_duty.get(r["duty_title"], {})
        for key in SEGMENT_KEYS:
            out[f"rev_{key}"] = segs.get(key, Decimal(0)).quantize(Q)
        all_sources = sum(segs.values(), Decimal(0))
        out["staff_revenue_all_sources"] = all_sources.quantize(Q)
        if r["total_final_salary"]:
            out["pct_salary_all_sources"] = round(
                all_sources / r["total_final_salary"] * 100, 2)
            out["pct_comp_all_sources"] = round(all_sources / comp * 100, 2)

        out["total_final_salary"] = r["total_final_salary"].quantize(Q)
        out["assignment_salary"] = r["assignment_salary"].quantize(Q)
        rows.append({k: out.get(k, "") for k in OUT_FIELDS})

    if args.roles_out:
        # 1191EDF derives the funded staffing one role at a time; its page
        # range moves between districts, so it is located by banner
        first, last = pages_for(args.pdf, "1191EDF")
        edf_items, _ = parse(args.pdf, first, last)
        with args.roles_out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(ROLE_FIELDS)
            for role in role_rows(edf_items, rows, DUTY_CLASS, units):
                # FTE keeps the report's three decimals; rounding it to cents
                # made the class totals drift by a hundredth of an FTE
                w.writerow([role[0], role[1],
                            role[2].quantize(Decimal("0.001")),
                            role[3].quantize(Decimal("0.001")),
                            role[4].quantize(Q), role[5].quantize(Q)])

    handle = args.out.open("w", newline="") if args.out else sys.stdout
    try:
        w = csv.DictWriter(handle, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.out:
            handle.close()


if __name__ == "__main__":
    main()
