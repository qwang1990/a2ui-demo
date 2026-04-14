from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.main import _build_progress_business_info
from a2ui_demo.ontology_models import OntologySpec


def _load_spec(name: str) -> OntologySpec:
    root = Path(__file__).resolve().parents[2]
    raw = (root / "ontology" / f"{name}.json").read_text(encoding="utf-8")
    return OntologySpec.model_validate(json.loads(raw))


def test_collect_node_contains_title_and_fields() -> None:
    spec = _load_spec("sam_credit_card")
    info = _build_progress_business_info(
        spec=spec,
        current_node_id="collect_basic",
        result={"current_node_id": "collect_basic"},
    )
    assert info["node_kind"] == "collect"
    assert info["node_title"] == "请填写三要素（姓名、身份证、手机号、年龄）"
    assert info["collect_fields"] == ["姓名", "身份证号", "手机号", "年龄"]


def test_logic_node_contains_description_result_and_next() -> None:
    spec = _load_spec("sam_credit_card")
    info = _build_progress_business_info(
        spec=spec,
        current_node_id="check_sams_member",
        result={"_branch": "false"},
    )
    assert info["node_kind"] == "logic"
    assert info["logic_name"] == "是否山姆会员"
    assert "演示 Mock" in info["logic_description"]
    assert info["logic_result"] == "未命中"
    assert info["next_node_id"] == "collect_basic"

