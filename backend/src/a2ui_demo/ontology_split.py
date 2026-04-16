"""Split ontology storage: TBox JSON, ABox JSON, LangGraph / AIP flow JSON.

- ``ontology/tbox/{id}.json`` — schema (ontologyVersion, objectTypes, logicDefinitions, actionDefinitions)
- ``ontology/abox/{id}.json`` — mock instance rows keyed by object type apiName
- ``ontology/flows/{flow_id}.json`` — ``aip_logic`` + ``aip_logic_graph`` (or legacy ``nodes``)

When ``ontology/flows/{flow_id}.json`` exists, GET/PUT and startup loading merge/split
automatically. Otherwise a single ``ontology/{flow_id}.json`` is used (tests / legacy).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from a2ui_demo.ontology_models import OntologySpec
from a2ui_demo.ontology_validation import validate_ontology_full

log = logging.getLogger(__name__)

_FLOW_META = frozenset({"schemaVersion", "tboxRef", "aboxRef"})
_TBOX_KEYS = ("ontologyVersion", "objectTypes", "logicDefinitions", "actionDefinitions")


def flow_definition_path(ontology_dir: Path, flow_id: str) -> Path:
    return ontology_dir / "flows" / f"{flow_id}.json"


def has_split_flow(ontology_dir: Path, flow_id: str) -> bool:
    return flow_definition_path(ontology_dir, flow_id).is_file()


def _read_json_dict(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("ontology_split read failed path=%s err=%s", p, e)
        return None
    return data if isinstance(data, dict) else None


def default_tbox_abox_refs(flow_id: str) -> tuple[str, str]:
    if flow_id.startswith("sam_credit"):
        return "sam_credit", "sam_credit"
    return flow_id, flow_id


def read_flow_refs(ontology_dir: Path, flow_id: str) -> tuple[str, str]:
    doc = _read_json_dict(flow_definition_path(ontology_dir, flow_id))
    if not doc:
        return default_tbox_abox_refs(flow_id)
    t0, a0 = default_tbox_abox_refs(flow_id)
    tref = str(doc.get("tboxRef") or t0)
    aref = str(doc.get("aboxRef") or doc.get("tboxRef") or a0)
    return tref, aref


def merge_split_to_full_dict(ontology_dir: Path, flow_id: str) -> dict[str, Any] | None:
    """Merge tbox + flow definition into one dict (before validation / materialize nodes)."""
    flow = _read_json_dict(flow_definition_path(ontology_dir, flow_id))
    if not flow:
        return None
    tref, _aref = read_flow_refs(ontology_dir, flow_id)
    tbox = _read_json_dict(ontology_dir / "tbox" / f"{tref}.json")
    if not tbox:
        log.error("split flow %s: missing tbox %s", flow_id, tref)
        return None
    merged: dict[str, Any] = {k: v for k, v in tbox.items() if k in _TBOX_KEYS}
    for k, v in flow.items():
        if k in _FLOW_META:
            continue
        merged[k] = v
    return merged


def merged_raw_for_api(ontology_dir: Path, flow_id: str) -> str | None:
    """Full ontology JSON string (with materialized ``nodes``) for GET / studio, same shape as legacy file."""
    merged = merge_split_to_full_dict(ontology_dir, flow_id)
    if not merged:
        return None
    spec, errors = validate_ontology_full(merged)
    if spec is None or errors:
        log.error("split merge invalid flow_id=%s errors=%s", flow_id, errors)
        return None
    if spec.aip_logic_graph:
        spec.nodes = spec.aip_logic_graph.to_ontology_nodes()
    return (
        json.dumps(spec.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n"
    )


def write_split_from_spec(ontology_dir: Path, flow_id: str, spec: OntologySpec) -> None:
    """Persist validated spec into ``tbox/{tboxRef}.json`` and ``flows/{flow_id}.json``."""
    flows_dir = ontology_dir / "flows"
    tbox_dir = ontology_dir / "tbox"
    flows_dir.mkdir(parents=True, exist_ok=True)
    tbox_dir.mkdir(parents=True, exist_ok=True)

    tref, aref = read_flow_refs(ontology_dir, flow_id)
    full = spec.model_dump(mode="json", by_alias=True)
    tbox_payload = {k: full[k] for k in _TBOX_KEYS if k in full}
    tbox_path = tbox_dir / f"{tref}.json"
    tbox_path.write_text(json.dumps(tbox_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    flow_payload: dict[str, Any] = {
        "schemaVersion": 1,
        "tboxRef": tref,
        "aboxRef": aref,
        "aip_logic": full["aip_logic"],
    }
    if full.get("aip_logic_graph"):
        flow_payload["aip_logic_graph"] = full["aip_logic_graph"]
    elif full.get("nodes"):
        flow_payload["nodes"] = full["nodes"]

    flow_path = flow_definition_path(ontology_dir, flow_id)
    flow_path.write_text(json.dumps(flow_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("wrote split ontology flow_id=%s tbox=%s flow=%s", flow_id, tbox_path.name, flow_path.name)
