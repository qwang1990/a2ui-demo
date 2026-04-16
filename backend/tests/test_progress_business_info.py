from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.config import ontology_dir
from a2ui_demo.main import _build_progress_business_info
from a2ui_demo.ontology_models import OntologySpec
from a2ui_demo.ontology_split import merged_raw_for_api


def _load_spec(name: str) -> OntologySpec:
    raw = merged_raw_for_api(ontology_dir(), name)
    if raw is None:
        raw = (Path(__file__).resolve().parents[2] / "ontology" / f"{name}.json").read_text(encoding="utf-8")
    return OntologySpec.model_validate(json.loads(raw))


def _load_spec_fixture(fname: str) -> OntologySpec:
    p = Path(__file__).resolve().parent / "fixtures" / fname
    return OntologySpec.model_validate(json.loads(p.read_text(encoding="utf-8")))


def test_collect_node_contains_title_and_fields() -> None:
    spec = _load_spec("sam_credit_card")
    info = _build_progress_business_info(
        spec=spec,
        current_node_id="start_apply",
        result={"current_node_id": "start_apply"},
    )
    assert info["node_kind"] == "collect"
    assert info["node_title"] == "开始办理"
    assert info["collect_fields"] == ["姓名", "身份证号"]


def test_logic_node_contains_description_result_and_next() -> None:
    spec = _load_spec_fixture("sam_credit_card_full.json")
    info = _build_progress_business_info(
        spec=spec,
        current_node_id="check_sams_member",
        result={"_branch": "false"},
    )
    assert info["node_kind"] == "logic"
    assert info["logic_name"] == "是否山姆会员（按姓名+身份证）"
    assert "姓名+身份证" in info["logic_description"]
    assert info["logic_result"] == "未命中"
    assert info["next_node_id"] == "collect_detail"

