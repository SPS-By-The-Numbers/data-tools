#!python3
"""Every dollar of General Fund revenue a district receives, reduced to the
part that actually pays people, and attributed to S-275 staff.

Two F-196 tables do the work:

  * `general_fund_revenues` -- one row per revenue code, each carrying the
    OSPI program its money is restricted to. That makes attribution
    mechanical: a line restricted to program 21 spreads across the duty
    titles holding special education FTE.
  * `general_fund_expenditures` -- program x object, which says what share
    of each program's spending is people (objects 2 and 3 salaries, 4
    benefits) rather than contracted services, supplies or capital.

The second is what keeps the answer honest. Pupil transportation is the
clearest case: SPS contracts its yellow bus service, so program 99 spends
$63.5M of which only 7.4% is staff pay -- $56.9M is object 7, purchased
services. Charging the whole transportation revenue stream against the 28
FTE coded to program 99 would overstate them roughly thirteenfold. Every
revenue line is therefore scaled by its program's staff share before being
attributed, and the remainder is reported as revenue that buys something
other than people.
"""

from decimal import Decimal

# Programs the basic education allocation pays for.
BEA_PROGRAMS = {1, 2, 3, 9, 31, 34, 45, 97}

# Account 3100 and the 3121 special-education transfer are both inside the
# 1191F guaranteed entitlement, so their F-196 revenue lines are dropped --
# the CIS/CAS/CLS staff units below stand in their place. Counting either
# again would double-count the same money.
ENTITLEMENT_REVENUES = {3100, 3121}
SPED_REVENUES = {4121, 4321}

# Duty root -> the state's staff class, per the S-275 reporting manual.
DUTY_CLASS = {
    **{r: "cas" for r in (11, 12, 13, 21, 22, 23, 24, 25)},
    **{r: "cis" for r in (31, 32, 33, 34, 39, 40, 41, 42, 43, 44, 45, 46,
                          47, 48, 49, 51, 52, 61, 63, 64)},
    **{r: "cls" for r in (90, 91, 92, 93, 94, 95, 96, 97, 98, 99)},
}

# key, label, colour slot, on by default.
# Every General Fund dollar lands in exactly one segment, so the chart can
# show any combination. The six state apportionment streams (revenue codes
# 3xxx and 4xxx) start checked; federal and local money starts off.
# CIS, CAS and CLS share one colour and one segment: a duty title belongs to
# exactly one staff class, so the three never appear in the same bar, and the
# chart is already faceted by class. Splitting them would spend two colours
# saying what the section heading already says.
SEGMENTS = [
    ("apportionment", "State apportionment — CIS, CAS and CLS staff units", 1),
    ("sped", "Special education — state", 2),
]
STAFF_UNIT_KEYS = ["cis", "cas", "cls"]
SEGMENT_KEYS = [s[0] for s in SEGMENTS]
SEGMENT_LABEL = {s[0]: s[1] for s in SEGMENTS}
SEGMENT_SLOT = {s[0]: s[2] for s in SEGMENTS}


def segment_of(revenue_code, program_code):
    """Which display segment a revenue line belongs to, or None.

    None covers two different cases, both reported rather than hidden:
    Account 3100 and the 3121 transfer, already represented by the 1191F
    staff units; and every source this chart does not cover -- LAP,
    bilingual, highly capable, transportation, food service, Title I, other
    federal, the local levy, private gifts and transfers.
    """
    if revenue_code in ENTITLEMENT_REVENUES:
        return None
    if revenue_code in SPED_REVENUES:
        return "sped"
    return None


def staff_units(params):
    """{cis, cas, cls} dollars from pages 1-7 of the 1191F.

    This is what "state apportionment" means in the prototypical school
    model: a funded number of certificated instructional, certificated
    administrative and classified staff units, each with a salary rate and
    its benefits. Salary, insurance, payroll benefits, substitutes and
    professional learning days, summed per class. Insurance is a headcount
    pot shared by CIS and CAS so it splits by FTE; payroll benefits are a
    percentage of salary so they split by salary; substitutes and
    professional learning days are instructional, so both are CIS.
    """
    p = {k: Decimal(v) for k, v in params.items()}
    cis_fte, cas_fte = p["School Generated CIS FTE"], p["District Total CAS FTE"]
    cis_sal = p["School CIS Salary Maint Total"] + p["School CIS Salary Inc Total"]
    cas_sal = p["Total CAS Salary Maint"] + p["Total CAS Salary Inc"]
    cls_sal = p["Total CLS Salary Maint"] + p["Total CLS Salary Inc"]
    cert_ins = p["CIS/CAS Insurance Maint Total"] + p["CIS/CAS Insurance Inc Total"]
    cert_ben = p["CIS/CAS Benefits Maint Total"] + p["CIS/CAS Benefits Inc Total"]
    cls_ins = p["CLS Insurance Maint Total"] + p["CLS Insurance Inc Total"]
    cls_ben = p["CLS Benefits Maint Total"] + p["CLS Benefits Inc Total"]
    cert_fte, cert_sal = cis_fte + cas_fte, cis_sal + cas_sal
    return {
        "cis": (cis_sal + cert_ins * cis_fte / cert_fte
                + cert_ben * cis_sal / cert_sal
                + p["Substitutes"] + p["Total Program 01 PD"]),
        "cas": (cas_sal + cert_ins * cas_fte / cert_fte
                + cert_ben * cas_sal / cert_sal),
        "cls": cls_sal + cls_ins + cls_ben,
    }


def attribute_staff_units(units, duty_rows, basis="assignment_fte"):
    """{duty title: {"apportionment": dollars}}.

    Divided by FTE, not payroll -- and deliberately unlike the revenue
    segments. The prototypical model allocates per staff unit at a flat rate
    per class: CIS FTE times the CIS salary rate. Spreading the pot by FTE
    reproduces that, so a title paid above its class's flat rate covers less
    than the class average and one paid below covers more. Spreading it by
    payroll instead would hand every title in a class the identical share
    and hide the very difference the model creates.

    No program codes involved: the model funds staff classes, and the S-275
    duty root says which class a title belongs to.
    """
    by_class = {}
    for r in duty_rows:
        key = DUTY_CLASS.get(int(r["duty_root_code"]))
        amount = Decimal(r[basis] or "0")
        if key is None or amount <= 0:
            continue
        by_class.setdefault(key, {})[r["duty_title"]] = amount
    out = {}
    for key, pot in units.items():
        shares = by_class.get(key, {})
        denom = sum(shares.values())
        if not denom:
            continue
        for duty, amount in shares.items():
            bucket = out.setdefault(duty, {})
            bucket["apportionment"] = (bucket.get("apportionment", Decimal(0))
                                       + pot * amount / denom)
    return out


class StaffShares:
    """What fraction of a program's spending goes to people."""

    def __init__(self, program_object_rows):
        self.by_program, staff, total = {}, Decimal(0), Decimal(0)
        bea_staff = bea_total = Decimal(0)
        for r in program_object_rows:
            spend = Decimal(r["total"] or "0")
            if spend <= 0:
                continue
            people = Decimal(r["salary"] or "0") + Decimal(r["benefits"] or "0")
            code = int(r["program_code"])
            self.by_program[code] = people / spend
            staff += people
            total += spend
            if code in BEA_PROGRAMS:
                bea_staff += people
                bea_total += spend
        # districtwide default, for unrestricted money and for programs with
        # revenue but no expenditure of their own
        self.default = staff / total if total else Decimal(1)
        self.bea = bea_staff / bea_total if bea_total else self.default

    def of(self, program, is_bea=False):
        if is_bea:
            return self.bea
        if program in self.by_program:
            return self.by_program[program]
        return self.default


def revenue_lines(rows, shares):
    """(lines, non-staff residual, revenue outside the sources shown).

    Each line is split two ways: the part its program actually spends on
    people, and the part that buys contracted services, supplies, food or
    capital. Only the first is attributable to a duty title.
    """
    lines, residual, off_chart = [], Decimal(0), Decimal(0)
    for r in rows:
        amount = Decimal(r["amount"] or "0")
        if not amount:
            continue
        code = int(r["revenue_code"] or 0)
        program = int(r["program_code"] or 0) or None
        key = segment_of(code, program or 0)
        if key is None:
            if code not in ENTITLEMENT_REVENUES:
                off_chart += amount
            continue
        share = shares.of(program)
        lines.append((key, program, amount * share))
        residual += amount * (1 - share)
    return lines, residual, off_chart


def attribute(lines, duty_program_rows, basis="total_final_salary"):
    """{duty title: {segment key: dollars}}.

    Each line is spread across duty titles by their share of the *payroll*
    in its program, not by headcount. Payroll money follows salary: a
    teacher and an instructional aide in the same program are not each owed
    the same slice of it. Distributing by FTE instead over-credits the
    cheaper title and under-credits the dearer one -- with a two-to-one
    spread in pay between duty titles, that is not a rounding difference.

    Unrestricted lines, and lines whose program employs no S-275 staff,
    spread across all staff so no dollar is lost.
    """
    by_program, total = {}, Decimal(0)
    for r in duty_program_rows:
        amount = Decimal(r[basis] or "0")
        if amount <= 0:
            continue
        code = int(r["program_code"])
        bucket = by_program.setdefault(code, {})
        bucket[r["duty_title"]] = bucket.get(r["duty_title"], Decimal(0)) + amount
        total += amount

    all_staff = {}
    for shares in by_program.values():
        for duty, amount in shares.items():
            all_staff[duty] = all_staff.get(duty, Decimal(0)) + amount

    # Account 3100 is restricted to the basic education programs even though
    # its revenue line is coded unrestricted.
    bea, bea_total = {}, Decimal(0)
    for code in BEA_PROGRAMS & by_program.keys():
        for duty, amount in by_program[code].items():
            bea[duty] = bea.get(duty, Decimal(0)) + amount
            bea_total += amount

    out = {}
    for key, program, amount in lines:
        if program in by_program:
            shares, denom = by_program[program], sum(by_program[program].values())
        else:
            shares, denom = all_staff, total
        if not denom:
            continue
        for duty, duty_fte in shares.items():
            bucket = out.setdefault(duty, {})
            bucket[key] = bucket.get(key, Decimal(0)) + amount * duty_fte / denom
    return out
