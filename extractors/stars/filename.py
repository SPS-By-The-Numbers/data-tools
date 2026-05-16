"""Parser for filenames produced by ospi-stars-reports.js.

The scraper writes files of the form:
    {school_year} - {report_type} - [{org_type} - ]{org_label}(ccddd) - {orig}.{ext}

Examples
--------
4-segment (most files):
    "2024-2025 - Key Performance Indicators - Almira School District (22017) - Almira.pdf"

5-segment (Efficiency Review only -- the 3rd segment is an org_type/subcategory):
    "2016-2017 - Efficiency Review - Current above 90% Prior below 90% - Everett School District (31002) - Everett.pdf"
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass
class StarsFilename:
    school_year: str          # "2024-2025"
    class_of: int             # 2025
    report_type: str          # "Key Performance Indicators"
    org_type: Optional[str]   # None for 4-segment; subcategory string for 5-segment
    org_label: str            # "Almira School District (22017)"
    ccddd: int                # 22017
    district_name: str        # "Almira School District"
    original_name: str        # filename last segment, sans extension
    extension: str            # "pdf" or "docx"
    path: Path                # absolute path as given


_CCDDD_SUFFIX_RE = re.compile(r"^(.+) \((\d{5})\)$")
_SCHOOL_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


def parse(path: Union[str, Path]) -> StarsFilename:
    p = Path(path)
    stem = p.stem
    ext = p.suffix.lstrip(".").lower()
    if ext not in ("pdf", "docx"):
        raise ValueError(f"Unsupported extension {ext!r} for {p.name!r}")

    parts = stem.split(" - ")
    if len(parts) < 4:
        raise ValueError(
            f"Only {len(parts)} segments in {p.name!r}; need at least 4"
        )

    # Find the org-label segment by its trailing "(NNNNN)" ccddd. This is the
    # one stable anchor in the filename: the district name itself may contain
    # parentheses ("(Spokane)") and the OSPI-supplied original filename may
    # itself contain " - " (e.g., "West Valley - Spokane.pdf"), both of which
    # break a naive segment-count branch.
    ccddd_idx = -1
    ccddd_m = None
    for i, segment in enumerate(parts):
        m = _CCDDD_SUFFIX_RE.match(segment)
        if m:
            ccddd_idx = i
            ccddd_m = m
            break
    if ccddd_idx < 0:
        raise ValueError(f"No (NNNNN) ccddd segment found in {p.name!r}")

    if ccddd_idx == 2:
        school_year, report_type = parts[0], parts[1]
        org_type: Optional[str] = None
    elif ccddd_idx == 3:
        school_year, report_type, org_type = parts[0], parts[1], parts[2]
    else:
        raise ValueError(
            f"ccddd segment at position {ccddd_idx} in {p.name!r}; "
            f"expected 2 (4-segment) or 3 (5-segment)"
        )

    org_label = parts[ccddd_idx]
    # Re-join trailing segments with " - " in case the original filename
    # contained a " - " (it sometimes does for districts like "West Valley").
    original_name = " - ".join(parts[ccddd_idx + 1:])
    if not original_name:
        raise ValueError(f"No original filename segment in {p.name!r}")

    sy_m = _SCHOOL_YEAR_RE.match(school_year)
    if not sy_m:
        raise ValueError(f"Bad school_year {school_year!r} in {p.name!r}")

    return StarsFilename(
        school_year=school_year,
        class_of=int(sy_m.group(2)),
        report_type=report_type,
        org_type=org_type,
        org_label=org_label,
        ccddd=int(ccddd_m.group(2)),
        district_name=ccddd_m.group(1),
        original_name=original_name,
        extension=ext,
        path=p,
    )
