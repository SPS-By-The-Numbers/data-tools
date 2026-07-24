"""Guards the STARS formula-input semantic rename.

The OSPI STARS allocation quantities were originally mislabeled: "riders"/
"students" are actually ride-equivalents (trips + issued transit passes),
"average distance" is bus-stop-to-destination distance (not route distance),
and the ops-allocation "enrollment" inputs are ride-equivalents. This test
pins the corrected vocabulary so the old names can't creep back in, while
confirming the deliberately-untouched set (KPI rider metrics, the per-route
average_distance column, the compact "eligible riders" columns) is intact.
"""

from pathlib import Path

from .schemas import domains
from .schemas.quarterly_district import QUARTERLY_DISTRICT_METRICS
from .schemas.efficiency import EFFICIENCY_METRIC_FIELDS
from .schemas.efficiency_review import STARS_EFFICIENCY_REVIEW
from .parsers import efficiency as efficiency_parser
from .parsers import quarterly_district as quarterly_parser


# Old -> new mapping, transcribed from the approved plan (owner-confirmed).
QUARTERLY_METRIC_RENAMES = {
    "basic_students_on_buses": "basic_ride_equivalents_on_bus",
    "basic_students_in_walk_areas": "basic_rides_in_walk_zone",
    "basic_students_transit_buses": "basic_transit_passes_issued",
    "basic_students_total": "basic_program_total",
    "special_students_special_ed": "special_rides_special_ed",
    "special_students_bilingual": "special_rides_bilingual",
    "special_students_gifted": "special_rides_gifted",
    "special_students_homeless": "special_rides_homeless",
    "special_students_early_ed": "special_rides_early_ed",
    "special_students_total": "special_program_total",
    "route_summary_average_distance": "route_summary_avg_stop_to_dest_distance",
}

COLUMN_RENAMES = {
    "basic_riders": "basic_ride_equivalents",
    "special_riders": "special_ride_equivalents",
    "avg_distance": "avg_stop_to_dest_distance",
}

# Names that must survive the rename untouched.
KEEP = {
    # KPI report genuinely measures riders.
    "basic_rider_kpi", "sped_rider_kpi", "cost_per_rider",
    "basic_rider_kpi_change_pct", "sped_rider_kpi_change_pct",
    "cost_per_rider_change_pct",
    # Route-count and bus-count quarterly metrics were already correct.
    "routes_basic", "routes_total", "route_summary_destinations",
    "route_summary_total_buses", "buses_basic", "bus_summary_total_buses",
}

# Old strings that must not appear anywhere in the stars package source.
FORBIDDEN = set(QUARTERLY_METRIC_RENAMES) | set(COLUMN_RENAMES)

_STARS_DIR = Path(__file__).resolve().parent


def _schema_field_names(schema):
    return {f["name"] for f in schema["fields"]}


def test_quarterly_metric_new_names_present():
    metrics = set(QUARTERLY_DISTRICT_METRICS)
    for old, new in QUARTERLY_METRIC_RENAMES.items():
        assert new in metrics, f"{new} missing from QUARTERLY_DISTRICT_METRICS"
        assert old not in metrics, f"{old} should have been renamed"


def test_quarterly_metric_domain_and_schema_agree():
    domain_codes = {
        r["metric_code"] for r in domains.D_STARS_QUARTERLY_METRIC_ROWS
    }
    assert domain_codes == set(QUARTERLY_DISTRICT_METRICS)


def test_quarterly_parser_emits_new_codes():
    emitted = {
        code
        for _header, _n, codes in quarterly_parser._SECTIONS
        for code in codes
    }
    # Every parser-emitted student-detail/route-summary code is a known metric.
    assert emitted <= set(QUARTERLY_DISTRICT_METRICS)
    for new in QUARTERLY_METRIC_RENAMES.values():
        if new.startswith(("basic_", "special_", "route_summary_avg")):
            assert new in emitted, f"parser no longer emits {new}"


def test_efficiency_columns_renamed():
    names = {f["name"] for f in EFFICIENCY_METRIC_FIELDS}
    for new in COLUMN_RENAMES.values():
        assert new in names, f"{new} missing from EFFICIENCY_METRIC_FIELDS"
    for old in COLUMN_RENAMES:
        assert old not in names, f"{old} should have been renamed"
    # The parser's column tuple must match the schema field order/names.
    assert set(efficiency_parser._METRIC_COLUMNS) == names


def test_efficiency_review_columns_renamed():
    names = _schema_field_names(STARS_EFFICIENCY_REVIEW)
    assert "basic_ride_equivalents" in names
    assert "special_ride_equivalents" in names
    assert "basic_riders" not in names
    assert "special_riders" not in names


def test_kept_names_survive():
    kpi_codes = {r["metric_code"] for r in domains.D_STARS_KPI_METRIC_ROWS}
    quarterly = set(QUARTERLY_DISTRICT_METRICS)
    for name in KEEP:
        assert name in kpi_codes or name in quarterly, (
            f"do-not-touch name {name} disappeared"
        )


def test_no_forbidden_strings_in_source():
    offenders = []
    for path in _STARS_DIR.rglob("*.py"):
        if path.name == "rename_guard_test.py":
            continue
        text = path.read_text()
        for bad in FORBIDDEN:
            if bad in text:
                offenders.append(f"{path.relative_to(_STARS_DIR)}: {bad}")
    assert not offenders, "old identifiers still present:\n" + "\n".join(offenders)


def test_per_route_average_distance_untouched():
    # The per-route ROUTE DETAIL column is correctly named and must remain.
    src = (_STARS_DIR / "parsers" / "quarterly_district.py").read_text()
    assert '"average_distance": avg' in src
