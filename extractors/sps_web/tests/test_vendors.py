"""Tests for the vendor normalizer (extractors.sps_web.vendors, card F1)."""

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
    marks = {("lydig constructon", "lydig construction"): "y"}
    groups, proposals = V.build(rows, V.load_aliases(), marks)
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
