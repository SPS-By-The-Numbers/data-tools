from .gen_dictionary import build_markdown
from ..fiscal.registry import FAMILY as FISCAL
from ..stars.registry import FAMILY as STARS


def test_every_registry_table_appears():
    md = build_markdown()
    for fam in (FISCAL, STARS):
        for spec in fam.tables:
            assert f"{fam.bq_dataset}.{spec.table}`" in md, spec.table


def test_safs_datasets_appear():
    md = build_markdown()
    for ds in ("safs_f19x", "safs_s275", "safs_domains", "ospi"):
        assert f"sps-btn-data.{ds}." in md


def test_duplicates_carry_canonical_note():
    md = build_markdown()
    # A known SAFS-duplicated fiscal table must point at its canonical source.
    assert "prefer `safs_f19x.general_fund_revenues`" in md
    # A unique table must not be flagged as a duplicate.
    assert "Canonical source:** this table" in md
