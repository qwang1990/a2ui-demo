from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from a2ui_demo.flows.compiler import CompiledFlow, compile_flow
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_models import OntologySpec

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
            data = json.loads(path.read_text(encoding="utf-8"))
            spec = OntologySpec.model_validate(data)
            flow = compile_flow(spec, self._client)
            self.register(flow)
            log.info("Loaded ontology flow %s from %s", spec.aip_logic.id, path)
            return flow
        except (ValidationError, json.JSONDecodeError, OSError, ValueError) as e:
            log.error("Failed to load ontology %s: %s", path, e)
            return None


def load_all_json(dir_path: Path, registry: FlowRegistry) -> int:
    if not dir_path.is_dir():
        return 0
    n = 0
    for p in sorted(dir_path.glob("*.json")):
        if registry.load_file(p):
            n += 1
    return n


class OntologyReloadHandler(FileSystemEventHandler):
    def __init__(self, registry: FlowRegistry, on_reload: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._registry = registry
        self._on_reload = on_reload

    def dispatch(self, event: Any) -> None:  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        path = getattr(event, "src_path", None)
        if not path or not str(path).endswith(".json"):
            return
        p = Path(str(path))
        self._registry.load_file(p)
        if self._on_reload:
            self._on_reload()


def start_watcher(dir_path: Path, registry: FlowRegistry, on_reload: Callable[[], None] | None = None) -> Observer:
    handler = OntologyReloadHandler(registry, on_reload=on_reload)
    observer = Observer()
    observer.schedule(handler, str(dir_path), recursive=False)
    observer.start()
    log.info("Watching ontology directory %s", dir_path)
    return observer
