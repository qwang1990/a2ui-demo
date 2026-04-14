from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2ui_demo.flows.compiler import compile_flow
from a2ui_demo.flows.runner import extract_interrupt_value, resume_flow, start_flow
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_models import OntologySpec


@pytest.fixture()
def sam_spec() -> OntologySpec:
    p = Path(__file__).resolve().parents[2] / "ontology" / "sam_credit_card.json"
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
        if "/api/mock-ontology/user/" in path:
            from urllib.parse import unquote

            tail = path.split("/api/mock-ontology/user/", 1)[1].split("?")[0]
            u = unquote(tail).upper()
            return {
                "is_sams_member": "SAMS_MEMBER" in u,
                "has_ms_credit_card": "HAS_MS" in u,
            }
        return {}


@pytest.mark.asyncio
async def test_sam_flow_happy_path(sam_spec: OntologySpec) -> None:
    g = compile_flow(sam_spec, FakeOntologyClient())
    tid, r1 = await start_flow(g, {"fullName": "n", "idNumber": "plain"}, "sam_credit_card")
    assert extract_interrupt_value(r1) is not None
    r2 = await resume_flow(g, tid, {"attrs": {"phone": "13900000000"}})
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
