from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.config import ontology_dir
from a2ui_demo.ontology_models import OntologySpec
from a2ui_demo.ontology_split import merged_raw_for_api
from a2ui_demo.ontology_validation import (
    coerce_attrs_for_properties,
    validate_ontology_full,
    validate_ontology_semantics,
    validate_user_attrs,
)


def _sam_credit_merged_raw() -> str:
    raw = merged_raw_for_api(ontology_dir(), "sam_credit_card")
    assert raw is not None
    return raw


def test_validate_sam_credit_card_file() -> None:
    spec, errs = validate_ontology_full(_sam_credit_merged_raw())
    assert spec is not None
    assert errs == []


def test_semantic_unknown_logic_ref() -> None:
    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "sam_credit_card_full.json").read_text(
            encoding="utf-8"
        )
    )
    for node in data["nodes"]:
        if node.get("kind") == "logic":
            node["logicRef"] = "nonexistent"
            break
    for node in data.get("aip_logic_graph", {}).get("nodes", []):
        if node.get("kind") == "logic":
            node["logicRef"] = "nonexistent"
            break
    spec = OntologySpec.model_validate(data)
    errs = validate_ontology_semantics(spec)
    assert any("logicRef" in e.get("path", "") for e in errs)


def test_validate_full_returns_errors_for_bad_json() -> None:
    spec, errs = validate_ontology_full("{not json")
    assert spec is None
    assert errs


def test_path_placeholder_must_match_object_property() -> None:
    data = json.loads(_sam_credit_merged_raw())
    data["logicDefinitions"][0]["implementation"]["requestPathTemplate"] = "/api/x/{unknownAttr}"
    spec = OntologySpec.model_validate(data)
    errs = validate_ontology_semantics(spec)
    assert any("requestPathTemplate" in e.get("path", "") for e in errs)


def test_validate_user_attrs_phone_constraints() -> None:
    spec, errs = validate_ontology_full(_sam_credit_merged_raw())
    assert spec is not None
    assert errs == []
    bad = validate_user_attrs(
        spec,
        {"phone": "123", "age": 16},
        object_type_api_name="ApplicantUser",
        property_api_names=["phone", "age"],
    )
    assert any(e.get("path") == "phone" for e in bad)
    assert any(e.get("path") == "age" for e in bad)


def test_validate_user_attrs_coerces_age_string_to_integer() -> None:
    """前端 submit_collect 用字符串提交；integer 属性应能按字面量校验通过。"""
    spec, errs = validate_ontology_full(_sam_credit_merged_raw())
    assert spec is not None
    assert errs == []
    ok = validate_user_attrs(
        spec,
        {"phone": "13900000000", "age": "28"},
        object_type_api_name="ApplicantUser",
        property_api_names=["phone", "age"],
    )
    assert ok == []


def test_coerce_attrs_for_properties_writes_int() -> None:
    spec, errs = validate_ontology_full(_sam_credit_merged_raw())
    assert spec is not None
    out = coerce_attrs_for_properties(
        spec,
        {"fullName": "n", "age": "28"},
        object_type_api_name="ApplicantUser",
        property_api_names=["fullName", "age"],
    )
    assert out["age"] == 28
    assert out["fullName"] == "n"


def test_validate_full_with_aip_logic_graph_only() -> None:
    raw = {
        "ontologyVersion": 1,
        "logicDefinitions": [],
        "actionDefinitions": [],
        "aip_logic": {"id": "graph_flow", "entry": "collect1", "inputs": []},
        "objectTypes": [{"apiName": "Applicant", "properties": [{"apiName": "name", "type": "string"}]}],
        "nodes": [],
        "aip_logic_graph": {
            "version": 1,
            "nodes": [
                {"id": "collect1", "kind": "collect", "objectTypeApiName": "Applicant", "propertyApiNames": ["name"]},
                {"id": "terminal1", "kind": "terminal", "outcome": "approved", "message": "ok"},
            ],
            "edges": [{"source": "collect1", "target": "terminal1", "condition": "next"}],
        },
    }
    spec, errs = validate_ontology_full(raw)
    assert errs == []
    assert spec is not None
    assert [n.id for n in spec.nodes] == ["collect1", "terminal1"]

