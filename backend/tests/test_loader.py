from __future__ import annotations

import json
from pathlib import Path

from a2ui_demo.config import ontology_dir
from a2ui_demo.flows.loader import FlowRegistry, load_all_json
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_split import merged_raw_for_api


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


def test_load_all_json(tmp_path: Path) -> None:
    raw = merged_raw_for_api(ontology_dir(), "sam_credit_card")
    assert raw is not None
    dst = tmp_path / "sam_credit_card.json"
    dst.write_text(raw, encoding="utf-8")
    reg = FlowRegistry(FakeOntologyClient())
    n = load_all_json(tmp_path, reg)
    assert n == 1
    assert reg.get("sam_credit_card") is not None


def test_registry_reload_single_file(tmp_path: Path) -> None:
    p = tmp_path / "flow.json"
    p.write_text(
        json.dumps(
            {
                "ontologyVersion": 1,
                "logicDefinitions": [],
                "actionDefinitions": [],
                "aip_logic": {"id": "hot_reload_x", "entry": "t", "inputs": []},
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


def test_registry_load_file_with_aip_logic_graph(tmp_path: Path) -> None:
    p = tmp_path / "graph_flow.json"
    p.write_text(
        json.dumps(
            {
                "ontologyVersion": 1,
                "logicDefinitions": [],
                "actionDefinitions": [],
                "aip_logic": {"id": "graph_flow", "entry": "collect_1", "inputs": []},
                "objectTypes": [{"apiName": "Applicant", "properties": [{"apiName": "name", "type": "string"}]}],
                "nodes": [],
                "aip_logic_graph": {
                    "version": 1,
                    "nodes": [
                        {
                            "id": "collect_1",
                            "kind": "collect",
                            "objectTypeApiName": "Applicant",
                            "propertyApiNames": ["name"],
                        },
                        {"id": "terminal_1", "kind": "terminal", "outcome": "approved", "message": "ok"},
                    ],
                    "edges": [{"source": "collect_1", "target": "terminal_1", "condition": "next"}],
                },
            }
        ),
        encoding="utf-8",
    )
    reg = FlowRegistry(FakeOntologyClient())
    flow = reg.load_file(p)
    assert flow is not None
    assert flow.spec.nodes[0].id == "collect_1"
