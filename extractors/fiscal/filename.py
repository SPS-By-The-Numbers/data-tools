"""Path parser for files under data/fiscal/ post-reorg.

After `extractors.fiscal.reorg` runs, every file lives at one of these paths:

    apportionment/{yyyy-yyyy}/district/{ccddd}_{slug}/{leaf}
    apportionment/{yyyy-yyyy}/esd/{esd_code}_{slug}/{ccddd_or_slug}/{leaf}
    apportionment/{yyyy-yyyy}/college/{code}_{slug}/{leaf}
    apportionment/{yyyy-yyyy}/state_agency/{code}_{slug}/{leaf}
    fiscal/{yyyy-yyyy}/{ccddd}_{slug}/{leaf}
    state_institutions/{yyyy-yyyy}/{leaf}           # leaf prefix: '{ccddd} {name} 1191SI'
    esd_allocations/{yyyy-yyyy}/{leaf}
    county_treasurer/{yyyy-yyyy}/{leaf}
    state_agencies_schools_colleges/{yyyy-yyyy}/{leaf}
    technical_colleges/{yyyy-yyyy}/{leaf}

This module turns a Path into structured fields. The path is the only stable
anchor (the original ` - `-separated filename was lossy and the original code
went into the directory layer instead).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


@dataclass
class FiscalFilename:
    report_type: str            # 'apportionment' | 'fiscal' | 'state_institutions' | ...
    school_year: str            # '2024-2025'
    class_of: int               # 2025
    org_type: Optional[str]     # 'district' | 'esd' | 'college' | 'state_agency' | None
    ccddd: Optional[int]        # None for orgs with no CCDDD (colleges, state agencies, or unmapped ESD members)
    org_code: Optional[str]     # raw code from the org dir (kept as str because some are <5 digits)
    org_slug: Optional[str]     # slug portion of org dir
    esd_code: Optional[str]     # for apportionment_esd, the parent ESD code
    esd_slug: Optional[str]
    leaf: str                   # filename stem
    extension: str              # 'pdf' (mostly) — sometimes '' for no-extension files
    path: Path


_YEAR_RE = re.compile(r"^\d{4}-\d{4}$")
_ORG_DIR_RE = re.compile(r"^(\d+)_(.*)$")
_LEADING_CCDDD_RE = re.compile(r"^(\d{5})\s+")


def _split_org_dir(dirname: str):
    """`{code}_{slug}` -> (code, slug); else (None, dirname)."""
    m = _ORG_DIR_RE.match(dirname)
    if m:
        return m.group(1), m.group(2)
    return None, dirname


def parse(path: Union[str, Path], base: Optional[Path] = None) -> FiscalFilename:
    """Parse a fiscal corpus path into structured fields.

    `base` is the data/fiscal/ root; if omitted the path is interpreted as
    relative to its own top-level. Either way only the segments below the
    report-type level are inspected.
    """
    p = Path(path)
    parts = p.parts
    # Locate the report-type segment by scanning from the end; it sits 1 below
    # whichever segment is `data/fiscal` (the caller may or may not pass an
    # absolute path).
    try:
        anchor = parts.index("fiscal")
    except ValueError:
        anchor = -1
    # We may have multiple 'fiscal' segments (the report-type 'fiscal' is one
    # of them). The corpus root 'data/fiscal' is followed by one of the eight
    # known report-type dirs; find the deepest match.
    REPORT_TYPES = {
        "apportionment", "fiscal", "state_institutions", "esd_allocations",
        "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
    }
    rt_idx = None
    for i, seg in enumerate(parts):
        if seg in REPORT_TYPES and i + 1 < len(parts) and _YEAR_RE.match(parts[i + 1]):
            rt_idx = i
    if rt_idx is None:
        raise ValueError(f"Could not locate report-type segment in {p}")
    rt = parts[rt_idx]
    year = parts[rt_idx + 1]
    class_of = int(year.split("-")[1])

    leaf_path = Path(parts[-1])
    leaf_stem = leaf_path.stem
    ext = leaf_path.suffix.lstrip(".").lower()

    org_type: Optional[str] = None
    ccddd: Optional[int] = None
    org_code: Optional[str] = None
    org_slug: Optional[str] = None
    esd_code: Optional[str] = None
    esd_slug: Optional[str] = None

    if rt == "apportionment":
        # parts: ... apportionment / year / org_type / org_dir / [member_dir /] leaf
        if rt_idx + 4 >= len(parts):
            raise ValueError(f"Truncated apportionment path: {p}")
        org_type = parts[rt_idx + 2]
        org_dir = parts[rt_idx + 3]
        code, slug = _split_org_dir(org_dir)
        if org_type == "esd":
            esd_code, esd_slug = code, slug
            # If a member-district dir is present, its code is the CCDDD anchor.
            if rt_idx + 5 < len(parts):
                member_dir = parts[rt_idx + 4]
                mcode, mslug = _split_org_dir(member_dir)
                if mcode and mcode.isdigit():
                    ccddd = int(mcode)
                org_code = mcode
                org_slug = mslug
            else:
                org_code = code
                org_slug = slug
        else:
            org_code = code
            org_slug = slug
            if code and code.isdigit() and len(code) == 5:
                ccddd = int(code)
    elif rt == "fiscal":
        # parts: ... fiscal / year / org_dir / leaf
        if rt_idx + 3 >= len(parts):
            raise ValueError(f"Truncated fiscal path: {p}")
        org_type = "district"
        org_dir = parts[rt_idx + 2]
        code, slug = _split_org_dir(org_dir)
        org_code = code
        org_slug = slug
        if code and code.isdigit() and len(code) == 5:
            ccddd = int(code)
    elif rt == "state_institutions":
        # parts: ... state_institutions / year / leaf
        # leaf prefix carries the served-by CCDDD: '03017 Benton County Adult Jail 1191SI'
        m = _LEADING_CCDDD_RE.match(leaf_stem)
        if m:
            ccddd = int(m.group(1))
            org_code = m.group(1)
    # Other flat report types: no CCDDD anchor (those forms address counties or all-ESD
    # rollups; org info has to be recovered from PDF content, deferred for now).

    return FiscalFilename(
        report_type=rt,
        school_year=year,
        class_of=class_of,
        org_type=org_type,
        ccddd=ccddd,
        org_code=org_code,
        org_slug=org_slug,
        esd_code=esd_code,
        esd_slug=esd_slug,
        leaf=leaf_stem,
        extension=ext,
        path=p,
    )
