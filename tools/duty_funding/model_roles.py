#!python3
"""The prototypical school model's own staffing roles, and the S-275 duty
titles that fill them.

Report 1191EDF -- "Student Full Time Enrollment and Calculated Staff Unit
Report" -- derives the district's funded staffing one role at a time:
principals, classroom teachers, librarians, counselors, nurses, social
workers, psychologists, teaching assistance, office support, custodians,
security, family involvement, technology, facilities, warehouse and central
administration. Those roles sum exactly to the three class totals the 1191F
uses, so the decomposition is the state's own, not an invention here:

    CIS  2,645.197   CAS  188.451   CLS  812.965

Each role is matched to the S-275 duty roots that do that work. Roles the
basic education allocation does not fund at all -- therapists, speech
pathologists, behaviour analysts, substitutes -- have no staff unit, and are
collected in a final row per class so the comparison stays honest about what
the model leaves out.
"""

from decimal import Decimal

# label, staff class, 1191EDF line labels to sum, S-275 duty roots
ROLES = [
    ("Classroom teachers", "CIS", ["Classroom Teachers"], {31, 32, 33, 34}),
    ("Guidance counselors", "CIS", ["Guidance Counselors"], {42}),
    ("School nurses", "CIS", ["School Nurses"], {47}),
    ("Teacher librarians", "CIS", ["Teacher Librarians"], {41}),
    ("Social workers", "CIS", ["Social Workers"], {44}),
    ("Psychologists", "CIS", ["Psychologists"], {46}),

    ("Principals and vice principals", "CAS", ["Principals"], {21, 22, 23, 24}),
    ("Central administration", "CAS", ["Certificated Administrators"],
     {11, 12, 13, 25}),

    # Teaching assistance and family involvement are separate lines in the
    # report but a single S-275 duty root; likewise custodians and security.
    ("Office support", "CLS", ["Office Support"], {94}),
    ("Custodians and security", "CLS",
     ["Custodians", "Student & Staff Safety"], {97}),
    ("Central administration", "CLS", ["Classified Staff"], {96, 99}),
    ("Teaching assistance and family involvement", "CLS",
     ["Teaching Assistance", "Family Involvement Coordinators"], {91}),
    ("Facilities, warehouse, maintenance", "CLS",
     ["Facilities, Maintenance, Grounds", "Warehouse, Laborers, Mechanics"],
     {92, 93, 95}),
    ("Technology", "CLS", ["Technology"], {98}),
]

# Everything the model funds, so leftover duty roots can be found by subtraction.
MAPPED_ROOTS = {r for _l, _c, _k, roots in ROLES for r in roots}
UNFUNDED_LABEL = "Roles with no basic education staff unit"


def model_units(items):
    """{1191EDF line label: FTE} from the parsed report.

    Only section III is read -- I is enrolment and II is salary bases. The
    small-district and remote-and-necessary adjustments in III.C are all zero
    for a district this size and would collide on label, so they are skipped.
    """
    out = {}
    for row in items:
        if row["section"] != "III" or row["subsection"] == "C":
            continue
        label = row["label"]
        if label.startswith("Total") or label.startswith("Central Administration"):
            continue
        out.setdefault(label, Decimal(row["amount"]))
    return out


FIELDS = ["role", "staff_class", "model_fte", "actual_fte",
          "model_dollars", "actual_pay"]


def role_rows(items, duty_rows, duty_class, class_pots):
    """One row per model role, reconciled in both units.

    Dollars follow FTE because that is how the model works: a class is
    funded at one flat rate per staff unit, so a role's share of its class's
    money is its share of the class's units. Summed per class the dollars
    come back to the class pot, and over all roles to the whole staff-unit
    half of the guaranteed entitlement.
    """
    units = model_units(items)
    fte_by_root, pay_by_root = {}, {}
    for r in duty_rows:
        root = int(r["duty_root_code"])
        fte_by_root[root] = fte_by_root.get(root, Decimal(0)) + Decimal(
            r["assignment_fte"] or "0")
        pay_by_root[root] = pay_by_root.get(root, Decimal(0)) + Decimal(
            r["total_compensation"] or "0")

    model_class_fte = {}
    for _label, cls, keys, _roots in ROLES:
        model_class_fte[cls] = model_class_fte.get(cls, Decimal(0)) + sum(
            units[k] for k in keys)

    rows = []
    for label, cls, keys, roots in ROLES:
        model = sum(units[k] for k in keys)
        rows.append((label, cls, model,
                     sum(fte_by_root.get(r, Decimal(0)) for r in roots),
                     class_pots[cls.lower()] * model / model_class_fte[cls],
                     sum(pay_by_root.get(r, Decimal(0)) for r in roots)))

    for cls in ("CIS", "CAS", "CLS"):
        roots = [r for r in fte_by_root
                 if r not in MAPPED_ROOTS and duty_class.get(r) == cls.lower()]
        if not roots:
            continue
        rows.append((UNFUNDED_LABEL, cls, Decimal(0),
                     sum(fte_by_root[r] for r in roots), Decimal(0),
                     sum(pay_by_root.get(r, Decimal(0)) for r in roots)))
    return rows
