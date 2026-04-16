from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from a2ui_demo.flows.compiler import CompiledFlow, compile_flow
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_split import merged_raw_for_api
from a2ui_demo.ontology_validation import validate_ontology_full

log = logging.getLogger(__name__)


class FlowRegistry:
    """In-memory registry of compiled flows keyed by aip_logic.id."""

    def __init__(self, ontology_client: OntologyPlatformClient) -> None:
        self._client = ontology_client
        self._flows: dict[str, CompiledFlow] = {}
        self._lock = threading.Lock()

    def register(self, flow: CompiledFlow) -> None:
        with self._lock:
            self._flows[flow.spec.aip_logic.id] = flow

    def get(self, flow_id: str) -> CompiledFlow | None:
        with self._lock:
            return self._flows.get(flow_id)

    def snapshot(self) -> dict[str, CompiledFlow]:
        with self._lock:
            return dict(self._flows)

    def load_file(self, path: Path) -> CompiledFlow | None:
        try:
            raw = path.read_text(encoding="utf-8")
            return self.load_from_raw(raw, source=str(path))
        except (OSError, ValueError) as e:
            log.error("Failed to load ontology %s: %s", path, e)
            return None

    def load_from_raw(self, raw: str, *, source: str = "") -> CompiledFlow | None:
        try:
            spec, errors = validate_ontology_full(raw)
            if spec is None:
                log.error("Failed to validate ontology source=%s: %s", source or "(raw)", errors)
                return None
            flow = compile_flow(spec, self._client)
            self.register(flow)
            log.info("Loaded ontology flow %s from %s", spec.aip_logic.id, source or "raw")
            return flow
        except (OSError, ValueError) as e:
            log.error("Failed to load ontology source=%s: %s", source or "(raw)", e)
            return None


def load_all_json(dir_path: Path, registry: FlowRegistry) -> int:
    if not dir_path.is_dir():
        return 0
    loaded_ids: set[str] = set()
    n = 0
    flows_dir = dir_path / "flows"
    if flows_dir.is_dir():
        for p in sorted(flows_dir.glob("*.json")):
            fid = p.stem
            raw = merged_raw_for_api(dir_path, fid)
            if raw and registry.load_from_raw(raw, source=f"split:{fid}"):
                loaded_ids.add(fid)
                n += 1
    for p in sorted(dir_path.glob("*.json")):
        if p.stem in loaded_ids:
            continue
        if registry.load_file(p):
            n += 1
    return n
