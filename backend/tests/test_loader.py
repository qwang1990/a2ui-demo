from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.flows.loader import FlowRegistry, load_all_json
from a2ui_demo.ontology_client import OntologyPlatformClient


class FakeOntologyClient(OntologyPlatformClient):
    def __init__(self) -> None:
        super().__init__("http://unused")

    def fetch_user_flags(self, id_number: str) -> dict[str, bool]:
        return {"is_sams_member": False, "has_ms_credit_card": False}


def test_load_all_json(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[2] / "ontology" / "simple_kyc.json"
    dst = tmp_path / "simple_kyc.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    reg = FlowRegistry(FakeOntologyClient())
    n = load_all_json(tmp_path, reg)
    assert n == 1
    assert reg.get("simple_kyc") is not None


def test_registry_reload_single_file(tmp_path: Path) -> None:
    p = tmp_path / "flow.json"
    p.write_text(
        json.dumps(
            {
                "aip_logic": {"id": "hot_reload_x", "entry": "t"},
                "objectTypes": [
                    {
                        "apiName": "EmptyType",
                        "displayName": "Empty",
                        "properties": [],
                    }
                ],
                "nodes": [
                    {
                        "id": "t",
                        "kind": "terminal",
                        "outcome": "approved",
                        "message": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reg = FlowRegistry(FakeOntologyClient())
    assert reg.load_file(p) is not None
    assert reg.get("hot_reload_x") is not None
