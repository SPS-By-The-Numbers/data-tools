"""Parser for STARS Efficiency Detail (PDF + DOCX).

One report per district per school year. Each report carries:

  - One "self" row with the subject's own transportation metrics.
  - Zero or more "Cohort <Peer>" rows with each peer district's metrics
    and a cohort weight percentage (weights sum to ~100%).
  - One "Target <District> Target 100%" row with the target expenditure
    and target bus count.
  - A "Relative Efficiency Rating <pct>%" footer line.

The parser yields two streams:
  - one stars_efficiency dict (subject + target + RER for that district)
  - N stars_efficiency_cohort dicts (one per peer)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .common import parse_decimal, read_lines, tokenize_value_line
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# Column order for the 10 numeric metrics shared by self / cohort / peer rows.
_METRIC_COLUMNS = (
    "prior_year_expenditures",
    "buses",
    "basic_ride_equivalents",
    "special_ride_equivalents",
    "avg_stop_to_dest_distance",
    "num_destinations",
    "land_area",
    "k_rte",
    "road_miles_per_sq_mile",
    "students_per_road_mile",
)

# Integer-valued metric codes (the rest are decimal).
_INT_METRICS = {
    "buses", "basic_ride_equivalents", "special_ride_equivalents",
    "num_destinations", "k_rte",
}


@dataclass
class _ParsedRow:
    role: str                # 'self', 'cohort', 'target', 'rating'
    name: Optional[str]      # district name (for self / cohort / target) or None
    weight_pct: Optional["object"]  # Decimal % or None
    metrics: dict            # metric_code -> value (only populated cells)
    rating: Optional["object"] = None  # for the rating row


_DOCX_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ---------- shared metric coercion -------------------------------------

def _coerce_metrics(numerics: List["object"]) -> dict:
    """Map an ordered list of decimals to metric_code -> value, with int
    coercion for the count-valued columns."""
    out = {}
    for code, val in zip(_METRIC_COLUMNS, numerics):
        if val is None:
            out[code] = None
        elif code in _INT_METRICS:
            try:
                out[code] = int(val)
            except (ValueError, TypeError):
                out[code] = None
        else:
            out[code] = val
    return out


# ---------- PDF parsing ------------------------------------------------

_PCT_RE = re.compile(r"^-?[\d.]+%$")


def _split_at_pct(tokens: List[str]) -> Tuple[List[str], Optional[str], List[str]]:
    """Return (before_pct, pct_token_or_None, after_pct)."""
    for i, t in enumerate(tokens):
        if _PCT_RE.match(t):
            return tokens[:i], t, tokens[i + 1:]
    return tokens, None, []


def _split_at_dollar(tokens: List[str]) -> Tuple[List[str], List[str]]:
    """Return (before_dollar_token, from_dollar_onwards). First $ token starts."""
    for i, t in enumerate(tokens):
        if t.startswith("$"):
            return tokens[:i], tokens[i:]
    return tokens, []


def _parse_pdf_row(line: str) -> Optional[_ParsedRow]:
    """Classify and parse one Efficiency Detail data line."""
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("Relative Efficiency Rating"):
        # "Relative Efficiency Rating 74.95%"
        m = re.search(r"(-?[\d.]+)%", stripped)
        if not m:
            return None
        return _ParsedRow(
            role="rating", name=None, weight_pct=None, metrics={},
            rating=parse_decimal(m.group(1)),
        )

    tokens = tokenize_value_line(line)
    if not tokens:
        return None

    if tokens[0] == "Cohort":
        # "Cohort <name...> X.X% $... 1 23 0 17.63 1 116.9 0 0.30 0.68"
        name_tokens, pct, value_tokens = _split_at_pct(tokens[1:])
        if pct is None:
            return None
        name = " ".join(name_tokens)
        numerics = [parse_decimal(t) for t in value_tokens]
        if len(numerics) < len(_METRIC_COLUMNS):
            return None
        return _ParsedRow(
            role="cohort", name=name,
            weight_pct=parse_decimal(pct),
            metrics=_coerce_metrics(numerics[: len(_METRIC_COLUMNS)]),
        )

    if tokens[0] == "Target":
        # "Target <label...> 100% $... 2"
        _, pct, value_tokens = _split_at_pct(tokens[1:])
        if pct is None:
            return None
        numerics = [parse_decimal(t) for t in value_tokens]
        # Target row only carries the first two metrics (expenditures, buses).
        if len(numerics) < 2:
            return None
        return _ParsedRow(
            role="target", name=None,
            weight_pct=parse_decimal(pct),
            metrics={
                "prior_year_expenditures": numerics[0],
                "buses": int(numerics[1]) if numerics[1] is not None else None,
            },
        )

    # Self row: "<district name...> $... 1 23 0 17.63 1 116.9 0 0.30 0.68"
    name_tokens, value_tokens = _split_at_dollar(tokens)
    if not value_tokens:
        return None
    numerics = [parse_decimal(t) for t in value_tokens]
    if len(numerics) < len(_METRIC_COLUMNS):
        return None
    return _ParsedRow(
        role="self",
        name=" ".join(name_tokens),
        weight_pct=None,
        metrics=_coerce_metrics(numerics[: len(_METRIC_COLUMNS)]),
    )


def _parse_pdf_rows(lines: List[str]) -> Iterator[_ParsedRow]:
    for line in lines:
        # Skip page chrome / column headers / footer notes.
        if not line.strip():
            continue
        if line.startswith("Page ") or line.startswith("State of Washington"):
            continue
        if line.startswith("Superintendent of Public Instruction"):
            continue
        if line.startswith("School Year "):
            continue
        if line.startswith("Efficiency Detail Report"):
            continue
        if "Workload" in line and "Site Characteristics" in line:
            continue
        if line.startswith(("Prior Year", "Cohort District", "Expenditures",
                            "Site Characteristics ", "v1.")):
            continue
        if line.startswith("STF-"):
            continue
        row = _parse_pdf_row(line)
        if row is not None:
            yield row


# ---------- DOCX parsing -----------------------------------------------


def _parse_docx_rows(path: Path) -> Iterator[_ParsedRow]:
    """Yield _ParsedRows from the underlying DOCX table.

    The Efficiency Detail DOCX renders the data table as 13-cell <w:tr>
    rows: col 0 is the row-role marker ('Cohort' / 'Target' / blank for
    self), col 1 is the district name (or "Almira Target" for target),
    col 2 is the weight percentage, cols 3-12 are the 10 numeric metrics.
    """
    import docx
    d = docx.Document(path)
    for tr in d.element.body.iter(f"{_DOCX_W}tr"):
        cells = list(tr.iter(f"{_DOCX_W}tc"))
        if len(cells) != 13:
            continue
        texts = []
        for tc in cells:
            text = "".join((t.text or "") for t in tc.iter(f"{_DOCX_W}t")).strip()
            texts.append(text)
        # The header row has "Cohort" / "District" / "Weight" in cols 0-2.
        # The visual "ALMIRA Workload Site Characteristics..." banner row
        # also has 13 cells but with mostly empty payload cells.
        marker = texts[0]
        name = texts[1]
        weight = texts[2]
        # Skip header / banner / footer rows: they don't have a sensible
        # numeric payload in cols 3-12.
        if not any(texts[3:]):
            continue
        if marker == "Cohort" and weight == "Weight":  # column header row
            continue

        # The "Relative Efficiency Rating" row lives in this table too,
        # with col 0 = "Relative Efficiency Rating" and col 3 = the pct.
        if marker == "Relative Efficiency Rating":
            yield _ParsedRow(
                role="rating", name=None, weight_pct=None,
                metrics={}, rating=parse_decimal(texts[3]),
            )
            continue

        # Numeric payload is cols 3-12 (10 entries).
        numerics = [parse_decimal(t) for t in texts[3:13]]

        if marker == "Cohort":
            yield _ParsedRow(
                role="cohort",
                name=name,
                weight_pct=parse_decimal(weight),
                metrics=_coerce_metrics(numerics),
            )
        elif marker == "Target":
            yield _ParsedRow(
                role="target", name=None,
                weight_pct=parse_decimal(weight),
                metrics={
                    "prior_year_expenditures": numerics[0],
                    "buses": int(numerics[1]) if numerics[1] is not None else None,
                },
            )
        elif marker == "" and name:
            # Self row (blank marker, district name in col 1).
            yield _ParsedRow(
                role="self", name=name, weight_pct=None,
                metrics=_coerce_metrics(numerics),
            )


# ---------- assembly ---------------------------------------------------


def parse_efficiency(info: StarsFilename) -> Tuple[Optional[dict], List[dict]]:
    """Return (subject_row_dict, list_of_cohort_row_dicts) for one file.

    subject_row_dict is None when the file produced no recognizable self
    or rating rows.
    """
    ext = info.path.suffix.lower()
    if ext == ".pdf":
        rows = list(_parse_pdf_rows(read_lines(info.path)))
    elif ext == ".docx":
        rows = list(_parse_docx_rows(info.path))
    else:
        raise ValueError(f"Unsupported extension {ext!r}")

    self_row: Optional[_ParsedRow] = None
    target_row: Optional[_ParsedRow] = None
    rating: Optional["object"] = None
    cohort_rows: List[_ParsedRow] = []
    for r in rows:
        if r.role == "self":
            self_row = r
        elif r.role == "cohort":
            cohort_rows.append(r)
        elif r.role == "target":
            target_row = r
        elif r.role == "rating":
            rating = r.rating

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "_source": info.path.name,
    }

    subject: Optional[dict] = None
    if self_row is not None or target_row is not None or rating is not None:
        subject = {
            **base,
            "_source_table": "stars_efficiency",
            **{code: None for code in _METRIC_COLUMNS},
            "target_prior_year_expenditures": None,
            "target_buses": None,
            "relative_efficiency_rating": rating,
        }
        if self_row is not None:
            subject.update(self_row.metrics)
        if target_row is not None:
            subject["target_prior_year_expenditures"] = (
                target_row.metrics.get("prior_year_expenditures"))
            subject["target_buses"] = target_row.metrics.get("buses")

    cohort_out: List[dict] = []
    for cr in cohort_rows:
        row = {
            **base,
            "_source_table": "stars_efficiency_cohort",
            "cohort_district": cr.name,
            "weight_pct": cr.weight_pct,
            **cr.metrics,
        }
        cohort_out.append(row)

    return subject, cohort_out
