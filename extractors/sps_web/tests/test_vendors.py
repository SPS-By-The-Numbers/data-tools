"""Tests for the vendor normalizer (extractors.sps_web.vendors, card F1)."""

import csv

import pytest

from extractors.sps_web import vendors as V


@pytest.mark.parametrize("raw,expected", [
    # legal suffixes and punctuation
    ("Lydig Construction, Inc.", "lydig construction"),
    ("Lydig Construction Company", "lydig construction"),
    ("BLRB Architects, P.S.", "blrb architects"),
    ("Cope Construction Company", "cope construction"),
    ("Bayley Construction, LP", "bayley construction"),
    ("Western Ventures Construction Co, Inc.", "western ventures construction"),
    # curly quotes / ampersands / accents
    ("King County Directors’ Association", "king county directors association"),
    ("Kassel & Associates, Inc.", "kassel and associates"),
    # leading "the"
    ("The Boeing Company", "boeing"),
    # abbreviation folding
    ("Regency NW Construction", "regency northwest construction"),
    ("Rolluda Architects, Inc.", "rolluda architects"),
    ("Rolluda Architecture", "rolluda architects"),
    # E1 capture noise: contract/bid prefixes
    ("Contract D5050 to Western Ventures Construction Co, Inc.",
     "western ventures construction"),
    ("D-5045 to A-1 Landscaping and Construction, Inc.",
     "a 1 landscaping and construction"),
    ("Alternates A-2 and B-1 to Absher Construction Company", "absher construction"),
    # E1 capture noise: trailing project descriptors
    ("Western Ventures Construction, Inc. to Meany Middle School Phase",
     "western ventures construction"),
    ("Sylvan Learning Center for Supplemental Education Services",
     "sylvan learning center"),
    ("Seattle Community College for the Provision of Career Links Services",
     "seattle community college"),
    # pdftotext hyphenation artifact
    ("Apus Construc-tion, Inc", "apus construction"),
    # dba
    ("Contract Flooring Services, Inc. dba Spectra Contract Flooring",
     "contract flooring services"),
    (None, ""),
    ("", ""),
])
def test_canonical_key(raw, expected):
    assert V.canonical_key(raw) == expected


def test_alias_table_loads_and_is_well_formed():
    aliases = V.load_aliases()
    assert len(aliases) > 300
    for key, (canon, klass, _note) in aliases.items():
        assert key == V.canonical_key(key), f"{key!r} is not a canonical key"
        assert klass in V.VALID_CLASSES
        # every alias resolves to something that is itself in the table
        if klass != V.NOT_A_VENDOR:
            assert V.canonical_key(canon) in aliases


def test_seeded_aliases_collapse():
    aliases = V.load_aliases()
    for alias, canonical in [
        ("CHILD", "Children's Institute of Learning Differences"),
        ("KCDA", "King County Directors' Association"),
        ("APL", "Academy for Precision Learning"),
        ("WSRMP", "Washington Schools Risk Management Pool"),
        ("SEA", "Seattle Education Association"),
    ]:
        assert aliases[V.canonical_key(alias)][0] == canonical


def test_seattle_public_schools_is_never_a_vendor():
    aliases = V.load_aliases()
    assert aliases[V.canonical_key("Seattle Public Schools")][1] == V.NOT_A_VENDOR


def test_government_counterparties_are_flagged():
    aliases = V.load_aliases()
    for name in ["City of Seattle", "King County", "OSPI", "University of Washington"]:
        assert aliases[V.canonical_key(name)][1] == "government"


def test_classify_heuristics():
    assert V.classify("Acme Construction Company") == "contractor"
    assert V.classify("City of Kent") == "government"
    assert V.classify("Some Directors Association") == "cooperative"
    assert V.classify("Nowhere Academy") == "school_placement"
    assert V.classify("Zzz Foundation") == "nonprofit"
    assert V.classify("Blorp") == "unknown"


def _rows():
    return [
        {"vendor_raw": "Lydig Construction, Inc.", "meeting_date": "2019-01-01",
         "amount": 100.0, "action_type": "new", "era": "modern", "title": "t1"},
        {"vendor_raw": "Lydig Construction Company", "meeting_date": "2007-01-01",
         "amount": None, "action_type": "amendment", "era": "legacy", "title": "t2"},
        {"vendor_raw": "KCDA", "meeting_date": "2010-01-01", "amount": 50.0,
         "action_type": "purchase", "era": "archive", "title": "t3"},
        {"vendor_raw": "Seattle Public Schools", "meeting_date": "2010-01-01",
         "amount": 1.0, "action_type": "other", "era": "archive", "title": "t4"},
    ]


def test_build_groups_by_exact_key_and_alias():
    groups, proposals = V.build(_rows(), V.load_aliases(), {})
    res = V.emit(groups, proposals, _rows(), write=False)
    by_name = {v["canonical_name"]: v for v in res["vendors"]}
    lydig = by_name["Lydig Construction Inc."]
    assert lydig["n_actions"] == 2
    assert lydig["first_seen"] == "2007-01-01" and lydig["last_seen"] == "2019-01-01"
    assert lydig["total_amount_sum"] == 100.0
    assert lydig["by_action_type"] == {"new": 1, "amendment": 1}
    assert by_name["King County Directors' Association"]["vendor_class"] == "cooperative"
    # SPS is dropped from the vendor dimension but kept in the map with a null id
    assert "Seattle Public Schools" not in by_name
    sps = [m for m in res["mappings"] if m["vendor_raw"] == "Seattle Public Schools"]
    assert sps and sps[0]["vendor_id"] is None


def test_map_methods():
    groups, proposals = V.build(_rows(), V.load_aliases(), {})
    res = V.emit(groups, proposals, _rows(), write=False)
    method = {m["vendor_raw"]: m["method"] for m in res["mappings"]}
    assert method["Lydig Construction, Inc."] == "exact"
    assert method["KCDA"] == "alias"


def test_approved_review_marks_merge_with_method_cluster():
    rows = _rows() + [{"vendor_raw": "Lydig Constructon", "meeting_date": "2020-01-01",
                       "amount": None, "action_type": "new", "era": "modern",
                       "title": "typo"}]
    decisions = {("lydig constructon", "lydig construction"):
                 {"key_a": "lydig constructon", "key_b": "lydig construction",
                  "decision": "y", "canonical_a": "", "canonical_b": "", "note": ""}}
    groups, proposals = V.build(rows, V.load_aliases(), decisions)
    res = V.emit(groups, proposals, rows, write=False)
    by_name = {v["canonical_name"]: v for v in res["vendors"]}
    assert by_name["Lydig Construction Inc."]["n_actions"] == 3
    method = {m["vendor_raw"]: m["method"] for m in res["mappings"]}
    assert method["Lydig Constructon"] == "cluster"


def test_merges_are_only_proposed_not_applied():
    rows = _rows() + [{"vendor_raw": "Lydig Constructon", "meeting_date": "2020-01-01",
                       "amount": None, "action_type": "new", "era": "modern",
                       "title": "typo"}]
    groups, proposals = V.build(rows, V.load_aliases(), {})
    res = V.emit(groups, proposals, rows, write=False)
    by_name = {v["canonical_name"]: v for v in res["vendors"]}
    assert by_name["Lydig Construction Inc."]["n_actions"] == 2
    assert "Lydig Constructon" in by_name
    assert any(p["key_a"] == "lydig constructon" or p["key_b"] == "lydig constructon"
               for p in proposals)


def test_slugify_is_stable_and_url_safe():
    assert V.slugify("King County Directors' Association") == "king-county-directors-association"
    assert V.slugify("Wayne’s Roofing Inc.") == "waynes-roofing-inc"


# --------------------------------------------------------------------------
# durable merge decisions (vendor_merges.csv)
# --------------------------------------------------------------------------

def _typo_rows():
    return _rows() + [{"vendor_raw": "Lydig Constructon", "meeting_date": "2020-01-01",
                       "amount": None, "action_type": "new", "era": "modern",
                       "title": "typo"}]


def _run(tmp_path, rows, merges, review_marks=None):
    """One full vendors.py cycle against temp copies of both CSVs."""
    monkey = {"MERGES_CSV": V.MERGES_CSV, "OUT_REVIEW": V.OUT_REVIEW}
    review = tmp_path / "vendors_review.csv"
    if review_marks is not None:
        with review.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=V.REVIEW_FIELDS)
            w.writeheader()
            for (a, b), mark in review_marks.items():
                w.writerow({f: "" for f in V.REVIEW_FIELDS} |
                           {"approve": mark, "key_a": a, "key_b": b})
    stored = V.load_merges(merges)
    harvested = V.harvest_review_marks(review)
    decisions = V.merge_decisions(stored, harvested)
    V.save_merges(decisions, merges)
    groups, proposals = V.build(rows, V.load_aliases(), decisions)
    res = V.emit(groups, proposals, rows, write=False)
    assert monkey  # nothing global was mutated
    return res, proposals


def test_approved_pair_survives_consecutive_runs(tmp_path):
    """The regression this file exists for: a merge must not evaporate on run 2."""
    merges = tmp_path / "vendor_merges.csv"
    rows = _typo_rows()

    # run 1: the pair is proposed, a human marks it y in the worksheet
    res1, props1 = _run(tmp_path, rows, merges)
    assert any({p["key_a"], p["key_b"]} == {"lydig constructon", "lydig construction"}
               for p in props1)
    res1, props1 = _run(tmp_path, rows, merges,
                        {("lydig constructon", "lydig construction"): "y"})
    by1 = {v["canonical_name"]: v for v in res1["vendors"]}
    assert by1["Lydig Construction Inc."]["n_actions"] == 3
    assert not props1, "a decided pair must leave the worksheet"

    # run 2: worksheet is empty again -- the decision must still be in force
    res2, props2 = _run(tmp_path, rows, merges, {})
    by2 = {v["canonical_name"]: v for v in res2["vendors"]}
    assert by2["Lydig Construction Inc."]["n_actions"] == 3
    assert not props2

    # run 3, for good measure
    res3, props3 = _run(tmp_path, rows, merges, {})
    assert {v["canonical_name"]: v["n_actions"] for v in res3["vendors"]} == \
           {v["canonical_name"]: v["n_actions"] for v in res2["vendors"]}
    assert not props3


def test_rejected_pair_is_never_re_proposed(tmp_path):
    merges = tmp_path / "vendor_merges.csv"
    rows = _typo_rows()
    _run(tmp_path, rows, merges, {("lydig constructon", "lydig construction"): "n"})
    for _ in range(2):
        res, props = _run(tmp_path, rows, merges, {})
        assert not props
        by = {v["canonical_name"]: v for v in res["vendors"]}
        assert by["Lydig Construction Inc."]["n_actions"] == 2   # not merged
        assert "Lydig Constructon" in by


def test_decisions_are_keyed_unordered(tmp_path):
    merges = tmp_path / "vendor_merges.csv"
    rows = _typo_rows()
    # mark the pair with the keys the other way round
    _run(tmp_path, rows, merges, {("lydig construction", "lydig constructon"): "y"})
    res, props = _run(tmp_path, rows, merges, {})
    assert not props
    by = {v["canonical_name"]: v for v in res["vendors"]}
    assert by["Lydig Construction Inc."]["n_actions"] == 3


def test_orphaned_key_warns_and_does_not_fail(tmp_path, capsys):
    merges = tmp_path / "vendor_merges.csv"
    V.save_merges({("gone a", "gone b"):
                   {"key_a": "gone a", "key_b": "gone b", "decision": "y",
                    "canonical_a": "", "canonical_b": "", "note": "stale"}}, merges)
    res, _ = _run(tmp_path, _rows(), merges, {})
    assert res["vendors"], "a stale decision must not break the run"
    assert "no vendor group" in capsys.readouterr().err


def test_shipped_merge_table_is_well_formed():
    decisions = V.load_merges()
    assert len(decisions) >= 40
    for (a, b), row in decisions.items():
        assert a <= b, "pairs are stored sorted"
        assert row["decision"] in {"y", "n"}
        assert a == V.canonical_key(a) and b == V.canonical_key(b), \
            f"{a!r}/{b!r} is not a canonical_key -- did canonical_key() change?"
