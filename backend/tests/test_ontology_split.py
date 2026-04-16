from __future__ import annotations

from pathlib import Path

from a2ui_demo.config import ontology_dir
from a2ui_demo.ontology_split import (
    has_split_flow,
    merge_split_to_full_dict,
    merged_raw_for_api,
)


def test_has_split_flow_for_repo_sam_credit() -> None:
    root = ontology_dir()
    assert has_split_flow(root, "sam_credit_card")


def test_merge_split_includes_tbox_and_flow() -> None:
    root = ontology_dir()
    d = merge_split_to_full_dict(root, "sam_credit_card")
    assert d is not None
    assert d["aip_logic"]["id"] == "sam_credit_card"
    assert any(ot.get("apiName") == "ApplicantUser" for ot in d.get("objectTypes", []))


def test_merged_raw_materializes_nodes() -> None:
    raw = merged_raw_for_api(ontology_dir(), "sam_credit_card")
    assert raw is not None
    assert '"nodes"' in raw


def test_tmp_dir_without_flows_uses_legacy_only() -> None:
    tmp = Path(__file__).resolve().parent / "fixtures"
    assert not has_split_flow(tmp, "sam_credit_card")
