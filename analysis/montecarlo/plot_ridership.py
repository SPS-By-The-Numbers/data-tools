"""Plot Seattle basic-program ridership split into yellow-bus vs transit-pass.

The STARS efficiency table's ``basic_riders`` conflates two very different
things: students riding district **yellow buses** (``basic_students_on_buses``)
and students given **public-transit passes** (``basic_students_transit_buses``,
i.e. ORCA). Much of the headline decline in "basic riders" is actually the
transit-pass program going to zero from 2022-2023 onward -- NOT a collapse in
yellow-bus ridership. For the ridership Monte Carlo, **yellow-bus on_bus is the
quantity to model/calibrate**, kept separate from transit pass.

Accounting identity (verified in the data):
    basic_students_total = on_buses + transit_buses - in_walk_areas

Annual values are the mean across the quarters that actually reported service
(quarters with ``basic_students_total == 0`` -- e.g. fully-remote COVID terms --
are dropped so they don't drag the average down).

    $ python3 -m analysis.montecarlo.plot_ridership            # writes PNG
    $ python3 -m analysis.montecarlo.plot_ridership --show
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from analysis.montecarlo import stars_seattle as ss  # noqa: E402

OUT_PNG = Path(__file__).resolve().parent / "ridership_bus_vs_transit.png"

_BASIC = {
    "basic_students_on_buses": "on_bus",
    "basic_students_transit_buses": "transit_pass",
    "basic_students_in_walk_areas": "walk_area",
    "basic_students_total": "total",
}


def annual_basic_ridership() -> "ss.pd.DataFrame":
    """Annual basic-program ridership components (mean of reporting quarters).

    Returns a DataFrame indexed by ``school_year`` with columns ``on_bus``,
    ``transit_pass``, ``walk_area``, ``total``, and ``n_quarters`` (how many
    quarters were averaged).
    """
    q = ss.load_quarterly_metrics()
    q = q[q.metric_code.isin(_BASIC)].copy()
    q["component"] = q.metric_code.map(_BASIC)
    wide = q.pivot_table(
        index=["school_year", "quarter"], columns="component", values="value", aggfunc="first"
    ).reset_index()
    # Drop quarters with no reported service (e.g. remote COVID terms).
    reporting = wide[wide["total"].fillna(0) > 0]
    annual = reporting.groupby("school_year").agg(
        on_bus=("on_bus", "mean"),
        transit_pass=("transit_pass", "mean"),
        walk_area=("walk_area", "mean"),
        total=("total", "mean"),
        n_quarters=("quarter", "nunique"),
    )
    return annual.sort_index()


def plot(show: bool = False) -> Path:
    a = annual_basic_ridership()
    years = list(a.index)
    x = range(len(years))

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(x, a["on_bus"], marker="o", lw=2.2, color="#1f77b4", label="Yellow bus (on_bus)")
    ax.plot(x, a["transit_pass"], marker="s", lw=2.2, color="#d62728", label="Transit pass (ORCA)")
    ax.plot(x, a["total"], marker="^", lw=1.3, ls="--", color="#7f7f7f",
            label="STARS basic total (on_bus + transit − walk)")

    # Annotate the transit-pass program ending.
    ax.annotate(
        "transit-pass riders → 0\nfrom 2022-2023",
        xy=(years.index("2022-2023"), 0), xytext=(years.index("2021-2022"), 5000),
        fontsize=9, color="#d62728",
        arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.2),
    )

    ax.set_title("Seattle Public Schools basic-program ridership: yellow bus vs. transit pass\n"
                 "(STARS quarterly metrics, annualized over reporting quarters)", fontsize=12)
    ax.set_ylabel("students (basic program)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(years, rotation=30, ha="right")
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper right", framealpha=0.9)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=130)
    print(f"wrote {OUT_PNG}")

    # Echo the underlying table.
    import pandas as pd
    pd.set_option("display.width", 200)
    print("\nAnnual basic-program ridership (mean of reporting quarters):")
    print(a.round(0).astype("Int64").to_string())

    if show:
        plt.show()
    return OUT_PNG


if __name__ == "__main__":
    import sys
    plot(show="--show" in sys.argv)
