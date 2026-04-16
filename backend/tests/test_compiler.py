from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2ui_demo.flows.compiler import _evaluate_logic_result, _template_attrs_for_node, compile_flow
from a2ui_demo.flows.runner import extract_interrupt_value, resume_flow, start_flow
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_models import LogicEdges, LogicParameterBinding, OntologyNode, OntologySpec


@pytest.fixture()
def sam_spec() -> OntologySpec:
    p = Path(__file__).resolve().parent / "fixtures" / "sam_credit_card_full.json"
    return OntologySpec.model_validate(json.loads(p.read_text(encoding="utf-8")))


def test_extract_interrupt_value_accepts_tuple() -> None:
    class _Intr:
        value = {"kind": "user_input", "node_id": "n1"}

    r: dict = {"__interrupt__": (_Intr(),)}
    v = extract_interrupt_value(r)
    assert isinstance(v, dict)
    assert v.get("node_id") == "n1"


class FakeOntologyClient(OntologyPlatformClient):
    def __init__(self) -> None:
        super().__init__("http://unused")

    def get_json(self, path: str) -> dict[str, bool]:
        if "/api/mock-ontology/applicant/query/" in path:
            from urllib.parse import unquote

            tail = path.split("/api/mock-ontology/applicant/query/", 1)[1].split("?")[0]
            parts = tail.split("/")
            full_name = unquote(parts[0]) if parts else ""
            id_number = unquote(parts[1]) if len(parts) > 1 else ""
            uid = f"U_{id_number.upper()}"
            if "HAS_MS" in uid and not uid.endswith("MS"):
                uid = f"{uid}_MS"
            if "SAMS_MEMBER" in uid and not uid.endswith("SAMS"):
                uid = f"{uid}_SAMS"
            return {
                "found": bool(full_name and id_number),
                "userId": uid,
                "is_sams_member": "SAMS_MEMBER" in id_number.upper(),
                "has_ms_credit_card": "HAS_MS" in id_number.upper(),
            }
        if "/api/mock-ontology/user/" in path and path.endswith("/flags"):
            from urllib.parse import unquote

            tail = path.split("/api/mock-ontology/user/", 1)[1].split("/flags")[0]
            u = unquote(tail).upper()
            return {
                "found": True,
                "has_ms_credit_card": u.endswith("MS"),
                "is_sams_member": u.endswith("SAMS"),
            }
        return {}


@pytest.mark.asyncio
async def test_sam_flow_happy_path(sam_spec: OntologySpec) -> None:
    g = compile_flow(sam_spec, FakeOntologyClient())
    tid, r1 = await start_flow(g, {"fullName": "n", "idNumber": "plain"}, "sam_credit_card")
    assert extract_interrupt_value(r1) is not None
    r2 = await resume_flow(g, tid, {"attrs": {"phone": "13900000000", "age": 28}})
    assert extract_interrupt_value(r2) is not None
    r3 = await resume_flow(g, tid, {"attrs": {"address": "addr"}})
    assert extract_interrupt_value(r3) is not None
    r4 = await resume_flow(g, tid, {"confirmed": True})
    assert r4.get("outcome") == "approved"


@pytest.mark.asyncio
async def test_sam_flow_deny_sams_member(sam_spec: OntologySpec) -> None:
    g = compile_flow(sam_spec, FakeOntologyClient())
    tid, r1 = await start_flow(
        g, {"fullName": "n", "idNumber": "xSAMS_MEMBERx"}, "sam_credit_card"
    )
    assert r1.get("outcome") == "denied"
    assert extract_interrupt_value(r1) is None


@pytest.mark.asyncio
async def test_resume_collect_accepts_string_integer_age(sam_spec: OntologySpec) -> None:
    """与前端一致：年龄以字符串提交时应通过 collect，不应卡在 must be an integer。"""
    g = compile_flow(sam_spec, FakeOntologyClient())
    tid, r1 = await start_flow(g, {"fullName": "n", "idNumber": "plain"}, "sam_credit_card")
    assert extract_interrupt_value(r1) is not None
    r2 = await resume_flow(
        g,
        tid,
        {"attrs": {"phone": "13900000000", "age": "28", "address": "北京市朝阳区"}},
    )
    intr = extract_interrupt_value(r2)
    assert isinstance(intr, dict)
    assert intr.get("kind") == "action"


@pytest.mark.asyncio
async def test_collect_node_returns_validation_errors_for_constraint_violation(sam_spec: OntologySpec) -> None:
    g = compile_flow(sam_spec, FakeOntologyClient())
    tid, r1 = await start_flow(g, {"fullName": "n", "idNumber": "plain"}, "sam_credit_card")
    assert extract_interrupt_value(r1) is not None
    r2 = await resume_flow(g, tid, {"attrs": {"phone": "123", "age": 25}})
    intr = extract_interrupt_value(r2)
    assert isinstance(intr, dict)
    errs = intr.get("validationErrors") or []
    assert any(e.get("path") == "phone" for e in errs)


def test_logic_merge_response_to_attrs_from_http() -> None:
    """无 expression 的 logic：按 responseToAttrs 合并 mock HTTP 响应。"""
    from a2ui_demo.flows.state import FlowState

    node = OntologyNode(
        id="q",
        kind="logic",
        edges=LogicEdges(true="a", false="b"),
        logicRef="is_sams_member_by_identity",
        responseToAttrs=["is_sams_member", "has_ms_credit_card"],
    )
    spec = OntologySpec.model_validate_json(
        (Path(__file__).resolve().parent / "fixtures" / "sam_credit_card_full.json").read_text(encoding="utf-8")
    )
    logic_by = spec.logic_by_api_name()
    st: FlowState = {"attrs": {"fullName": "n", "idNumber": "plain"}}
    ok, payload = _evaluate_logic_result(st, node, FakeOntologyClient(), logic_by)
    assert ok is False
    assert "is_sams_member" in payload


def test_template_attrs_for_logic_bindings() -> None:
    node = OntologyNode(
        id="l",
        kind="logic",
        edges=LogicEdges(true="a", false="b"),
        logicParameterBindings=[LogicParameterBinding(fromAttr="uid", templateKey="userId")],
    )
    out = _template_attrs_for_node(node, {"uid": "U1001", "userId": "wrong"})
    assert out["userId"] == "U1001"
