"""Per-school assumption + delta breakdown for one scenario.

``compute(name)`` returns the structured breakdown (resolved assumptions —
e.g. closure receivers with kids-received shares — plus a per-school table
of enrollment / bus-eligible / EV rides deltas with the MC delta + 95% CI
from the saved run). The CLI renders it to simulate/<scenario>/breakdown.md;
findings_html.py renders the same data as expandable HTML sections.

Run:  python3 -m analysis.montecarlo.breakdown <scenario>
"""

from __future__ import annotations

import argparse
import datetime
import io

from analysis.montecarlo import report as rpt
from analysis.montecarlo import ridership as rid
from analysis.montecarlo import scenarios as scn
from analysis.montecarlo import simulate as sim
from analysis.montecarlo.school_directory import load_schools

_EVAL_CACHE: dict = {}


def _baseline_eval(params):
    if "base" not in _EVAL_CACHE:
        _EVAL_CACHE["base"] = scn.evaluate(scn.baseline_world(), params=params)
    return _EVAL_CACHE["base"]


def _exal_terms(run: dict) -> dict:
    """Per-term EXAL decomposition at the mean-draw inputs.

    Each formula term contributes a multiplicative factor exp(coef·Δterm);
    the factors multiply exactly to scenario/baseline EXAL at the mean
    inputs. The MC mean Δrevenue is reported alongside (it differs
    slightly because EXAL is nonlinear in the draws).
    """
    import numpy as np
    fs = rpt.funding_summary(run)
    B, C = rpt.EXAL_BASE, rpt.EXAL_COEF
    d = {k: float(fs[f"d_{k}"].mean())
         for k in ("basic", "special", "dest", "avgdist")}
    terms = []
    for label, key, coef, logged in (
            ("BasicRiders", "basic", "b_basic", True),
            ("SpecialRiders", "special", "b_special", True),
            ("Destinations", "dest", "b_dest", False),
            ("AvgDistance (mi)", "avgdist", "b_avgdist", False)):
        b, s = B[key], B[key] + d[key]
        dterm = (C[coef] * (np.log(s + 1) - np.log(b + 1)) if logged
                 else C[coef] * (s - b))
        terms.append({"label": label, "base": b, "scen": s, "logged": logged,
                      "factor": float(np.exp(dterm))})
    base_rev = float(fs["base_revenue"].mean())
    prod = float(np.prod([t["factor"] for t in terms]))
    return {"terms": terms, "base_rev": base_rev,
            "scen_rev": base_rev * prod,
            "d_mc": (float(fs["d_revenue"].mean()),
                     float(fs["d_revenue"].quantile(0.025)),
                     float(fs["d_revenue"].quantile(0.975)))}


def compute(name: str) -> dict:
    """Structured per-school breakdown for one scenario (EV + saved MC)."""
    scenario = scn.load_scenario(name)
    base_w = scn.baseline_world()
    scen_w = scn.apply(scenario, base_w)
    params = rid.load_params()
    base = _baseline_eval(params)
    scen = scn.evaluate(scen_w, params=params)
    names = load_schools().set_index("school_id")["name"]

    cm_b = base_w.col_marg.groupby("school_id")["target"].sum()
    cm_s = scen_w.col_marg.groupby("school_id")["target"].sum()
    el_b = base["cells"].groupby("school_id")["n_eligible"].sum()
    el_s = scen["cells"].groupby("school_id")["n_eligible"].sum()

    def riders(res, program):
        r = res["riders"]
        return r[r.program == program].set_index("school_id")["riders"]

    rb, rs = riders(base, "basic"), riders(scen, "basic")
    gb, gs = riders(base, "gifted"), riders(scen, "gifted")

    mc, exal = None, None
    try:
        run = sim.load_run(name)
    except FileNotFoundError:
        run = None
    if run is not None:
        mc = rpt.school_summary(run)
        mc = mc[mc.program == "basic"].set_index("school_id")
        exal = _exal_terms(run)

    closed = {op["school_id"] for op in scenario.ops if op["op"] == "close_school"}
    converted = {op["school_id"] for op in scenario.ops
                 if op["op"] == "convert_option_to_neighborhood"}
    d_enroll = cm_s.sub(cm_b, fill_value=0.0)
    d_rides = rs.sub(rb, fill_value=0.0)
    d_gift = gs.sub(gb, fill_value=0.0)
    affected = sorted(set(d_enroll[d_enroll.abs() > 0.5].index)
                      | set(d_rides[d_rides.abs() > 0.5].index) | closed,
                      key=lambda s: d_rides.get(s, 0.0))

    def role(sid):
        if sid in closed:
            return "closed"
        if sid in converted:
            return "converted"
        if d_enroll.get(sid, 0) > 0.5:
            return "receiver"
        if d_enroll.get(sid, 0) < -0.5:
            return "donor"
        if rb.get(sid, 0.0) < 0.5 < rs.get(sid, 0.0):
            return "new service"
        return "affected"

    rows = []
    for sid in affected:
        row = {"sid": int(sid), "name": str(names.get(sid, sid)),
               "role": role(sid),
               "enroll_b": float(cm_b.get(sid, 0.0)), "enroll_s": float(cm_s.get(sid, 0.0)),
               "elig_b": float(el_b.get(sid, 0.0)), "elig_s": float(el_s.get(sid, 0.0)),
               "ev_b": float(rb.get(sid, 0.0)), "ev_s": float(rs.get(sid, 0.0)),
               "mc": None}
        # propensity = rides/day per eligible student; marginal = the rate
        # at which the CHANGE in the eligible pool converts to rides
        row["prop_b"] = row["ev_b"] / row["elig_b"] if row["elig_b"] > 1 else None
        row["prop_s"] = row["ev_s"] / row["elig_s"] if row["elig_s"] > 1 else None
        d_el = row["elig_s"] - row["elig_b"]
        row["marg"] = ((row["ev_s"] - row["ev_b"]) / d_el
                       if abs(d_el) > 1 else None)
        if mc is not None and sid in mc.index:
            m = mc.loc[sid]
            row["mc"] = (float(m["d_mean"]), float(m["d_lo"]), float(m["d_hi"]))
        rows.append(row)

    ops = []
    for op in scenario.ops:
        entry = {"kind": op["op"],
                 "params": {k: v for k, v in op.items()
                            if k not in ("op", "comment")}}
        if op["op"] == "close_school":
            sid = op["school_id"]
            entry["school"] = str(names.get(sid, sid))
            entry["sid"] = sid
            entry["kids_out"] = float(-d_enroll.get(sid, 0.0))
            entry["named_receivers"] = bool(op.get("receivers"))
        ops.append(entry)
    # receiver shares are scenario-wide (sum of all closures' displacements)
    recv = d_enroll[d_enroll > 0.5].sort_values(ascending=False)
    receivers = [{"sid": int(s), "name": str(names.get(s, s)),
                  "kids": float(k), "share": float(k / recv.sum())}
                 for s, k in recv.items()] if len(recv) else []

    gifted_rows = [{"sid": int(s), "name": str(names.get(s, s)),
                    "ev_b": float(gb.get(s, 0.0)), "ev_s": float(gs.get(s, 0.0))}
                   for s in d_gift[d_gift.abs() > 0.5].sort_values().index]

    return {"name": name, "description": scenario.description, "ops": ops,
            "receivers": receivers, "rows": rows, "gifted_rows": gifted_rows,
            "district": (float(rb.sum()), float(rs.sum())),
            "has_mc": mc is not None, "exal": exal}


INVARIANTS = (
    "Evaluation invariants (all scenarios): district enrollment is conserved "
    "per grade band (kids change schools, never leave); walk zones change "
    "only where an op touches them; the ride-propensity model keeps the "
    "baseline-calibrated scale and covariate centering, so changes in rides "
    "come only from the re-assignment (who is bus-eligible, and at what "
    "distance and school demographics); the gifted program moves only when "
    "an HCC pathway site is touched.")

COLUMN_NOTES = (
    ("enrolled", "students assigned to the school (IPF column marginal, all "
     "grade bands); a receiver's gain is its share of a closed/converted "
     "school's students."),
    ("bus-eligible", "assigned students living outside the school's walk "
     "zone; the gap between Δenrolled and Δeligible is the (approximate) "
     "count landing inside the walk zone."),
    ("EV rides/day", "expected rides at the baseline-calibrated propensity; "
     "“affected” rows move because the propensity tilt re-centers "
     "as the eligible pool shifts."),
    ("propensity", "rides/day per bus-eligible student (school level, "
     "base → scen); the parenthesized marginal rate is Δrides ÷ Δeligible — "
     "the expected uptake of the NEWLY eligible (or newly ineligible) "
     "students at this school. A both-ways rider counts 2, so 0.60 ≈ "
     "between 30% riding both ways and 60% riding one way; the theoretical "
     "max is 2."),
    ("MC Δ", "mean and 95% interval over the paired Monte Carlo draws "
     "(population + behavioral-parameter uncertainty)."),
)


def _prop_txt(r: dict) -> str:
    """'0.65 → 0.66 (marg 0.72)' — rides/day per eligible student."""
    fmt = lambda v: "—" if v is None else f"{v:.2f}"
    marg = "" if r["marg"] is None else f" (marg {r['marg']:.2f})"
    return f"{fmt(r['prop_b'])} → {fmt(r['prop_s'])}{marg}"


def render_md(d: dict) -> str:
    out = io.StringIO()
    w = out.write
    w(f"# Scenario breakdown: `{d['name']}`\n\n{d['description']}\n\n")
    w(f"*Generated {datetime.date.today().isoformat()} from the 2024-25 "
      "baseline. All rider figures are rides/day (AM+PM boardings). "
      "Expected-value (EV) columns are the deterministic model; the MC "
      "column is the mean Δ and 95% interval over the saved paired draws.*\n\n")
    w("## Resolved assumptions\n\n")
    for i, op in enumerate(d["ops"]):
        if op["kind"] == "close_school":
            w(f"**op[{i}] `close_school`** — close **{op['school']}** "
              f"({op['sid']}); its {op['kids_out']:.0f} assigned students "
              "stay where they live and re-assign to "
              + ("receivers **named in the spec**." if op["named_receivers"]
                 else "the **engine-default receivers** (3 nearest open "
                      "same-level neighborhood schools, split per residence "
                      "area in proportion to existing draw).") + "\n\n")
        else:
            w(f"**op[{i}] `{op['kind']}`** — `{op['params']}`\n\n")
    if d["receivers"]:
        w("Receiving schools (all displacements combined):\n\n"
          "| receiver | kids received | share |\n|---|---|---|\n")
        for r in d["receivers"]:
            w(f"| {r['name']} ({r['sid']}) | {r['kids']:.1f} | {r['share']:.0%} |\n")
        w("\n")
    w(INVARIANTS + "\n\n")

    w("## Per-school deltas (basic program)\n\n")
    w("| school | role | enrolled base→scen (Δ) | bus-eligible base→scen (Δ) "
      "| EV rides/day base→scen (Δ) | propensity base→scen (marginal) "
      "| MC Δ rides [95% CI] |\n")
    w("|---|---|---|---|---|---|---|\n")
    for r in d["rows"]:
        mc_txt = "—" if r["mc"] is None else \
            f"{r['mc'][0]:+.1f} [{r['mc'][1]:+.1f}, {r['mc'][2]:+.1f}]"
        w(f"| {r['name']} ({r['sid']}) | {r['role']} "
          f"| {r['enroll_b']:,.0f} → {r['enroll_s']:,.0f} "
          f"({r['enroll_s'] - r['enroll_b']:+,.0f}) "
          f"| {r['elig_b']:,.0f} → {r['elig_s']:,.0f} "
          f"({r['elig_s'] - r['elig_b']:+,.0f}) "
          f"| {r['ev_b']:,.1f} → {r['ev_s']:,.1f} "
          f"({r['ev_s'] - r['ev_b']:+,.1f}) | {_prop_txt(r)} | {mc_txt} |\n")
    b, s = d["district"]
    w(f"| **district total** | | | | **{b:,.1f} → {s:,.1f} ({s - b:+,.1f})** | | |\n\n")

    if d["gifted_rows"]:
        w("## Per-school deltas (gifted program)\n\n"
          "| school | EV rides/day base→scen (Δ) |\n|---|---|\n")
        for r in d["gifted_rows"]:
            w(f"| {r['name']} ({r['sid']}) | {r['ev_b']:,.1f} → "
              f"{r['ev_s']:,.1f} ({r['ev_s'] - r['ev_b']:+,.1f}) |\n")
        w("\n")
    else:
        w("Gifted program: unchanged (no HCC pathway site is touched).\n\n")

    if d["exal"]:
        e = d["exal"]
        w("## State funding (EXAL) change\n\n")
        w("Each term of the STARS Expected Allocation formula contributes a "
          "multiplicative factor; the factors multiply exactly to the "
          "scenario reimbursement at the mean-draw inputs.\n\n")
        w("| term | input base → scen | factor on EXAL |\n|---|---|---|\n")
        for t in e["terms"]:
            fmt = ",.2f" if not t["logged"] else ",.0f"
            w(f"| {t['label']} | {t['base']:{fmt}} → {t['scen']:{fmt}} "
              f"| ×{t['factor']:.4f} |\n")
        w(f"| **EXAL** | **${e['base_rev']/1e6:,.2f}M → "
          f"${e['scen_rev']/1e6:,.2f}M** | **×{e['scen_rev']/e['base_rev']:.4f}** |\n\n")
        w(f"MC mean Δ revenue: {e['d_mc'][0]/1e6:+,.2f} "
          f"[{e['d_mc'][1]/1e6:+,.2f}, {e['d_mc'][2]/1e6:+,.2f}] $M/yr "
          "(differs slightly from the factor product — EXAL is nonlinear "
          "across draws). Destinations deltas are vs the any-program served "
          "set: only never-served schools count as additions; closures count "
          "even if the model carried no rides there.\n\n")

    w("## Reading the table\n\n")
    for term, note in COLUMN_NOTES:
        w(f"- **{term}** — {note}\n")
    return out.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scenario")
    args = ap.parse_args()
    out = sim.OUT_DIR / args.scenario / "breakdown.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_md(compute(args.scenario)))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
