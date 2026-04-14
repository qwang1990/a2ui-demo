from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from a2ui_demo.flows.state import FlowState
from a2ui_demo.logging_utils import (
    compiled_graph_edges_summary,
    compiled_graph_mermaid,
    compiled_graph_mermaid_one_line,
    format_compiled_graph,
)
from a2ui_demo.ontology_client import OntologyPlatformClient, interpolate_request_path
from a2ui_demo.ontology_models import LogicDefinition, OntologyNode, OntologySpec
from a2ui_demo.ontology_validation import OntologyValidationError, validate_ontology_semantics

log = logging.getLogger(__name__)


class CompiledFlow:
    def __init__(self, spec: OntologySpec, graph: Any) -> None:
        self.spec = spec
        self.graph = graph
        self.entry = spec.aip_logic.entry


def ensure_compilable(spec: OntologySpec) -> None:
    errs = validate_ontology_semantics(spec)
    if errs:
        raise OntologyValidationError(errs)


def _evaluate_logic(
    state: FlowState,
    node: OntologyNode,
    client: OntologyPlatformClient,
    logic_by_api: dict[str, LogicDefinition],
) -> bool:
    ref = node.logic_ref or ""
    ld = logic_by_api.get(ref)
    if not ld:
        log.debug("logic node=%s missing definition for logicRef=%s", node.id, ref)
        return False
    impl = ld.implementation
    if impl.type != "mock_user_flags":
        log.warning("logic node=%s unsupported implementation type=%s", node.id, impl.type)
        return False
    attrs = state.get("attrs") or {}
    path, missing = interpolate_request_path(impl.request_path_template, attrs)
    if path is None:
        log.debug("logic node=%s: missing attrs for request path: %s", node.id, missing)
        return False
    data = client.get_json(path)
    return bool(data.get(impl.flag_key))


def _logic_router(state: FlowState) -> str:
    b = state.get("_branch")
    return b if b in ("true", "false") else "false"


def _make_logic_node(
    node: OntologyNode,
    client: OntologyPlatformClient,
    logic_by_api: dict[str, LogicDefinition],
) -> Callable[[FlowState], dict[str, Any]]:
    def logic_node(state: FlowState) -> dict[str, Any]:
        value = _evaluate_logic(state, node, client, logic_by_api)
        branch = "true" if value else "false"
        log.info("logic node=%s logicRef=%s branch=%s", node.id, node.logic_ref, branch)
        return {"_branch": branch, "current_node_id": node.id}

    return logic_node


def _make_collect_node(
    node: OntologyNode,
    labels: dict[str, str],
    display_property_names: list[str],
) -> Callable[[FlowState], dict[str, Any]]:
    """display_property_names: 本体对象类型下全部属性顺序，用于 UI 展示已收集项；collect_field_names 仅决定本步缺哪些。"""
    collect_field_names = list(node.property_api_names or [])

    def collect_node(state: FlowState) -> dict[str, Any]:
        attrs = dict(state.get("attrs") or {})
        missing = [k for k in collect_field_names if not str(attrs.get(k, "")).strip()]
        if missing:
            log.info("collect node=%s missing=%s objectType=%s", node.id, missing, node.object_type_api_name)
            resume = interrupt(
                {
                    "kind": "user_input",
                    "node_id": node.id,
                    "missing": missing,
                    "labels": {k: labels.get(k, k) for k in display_property_names},
                    "property_api_names": display_property_names,
                    "collect_field_names": collect_field_names,
                    "title": node.title or "请补全信息",
                    "attrs": dict(attrs),
                    "objectTypeApiName": node.object_type_api_name,
                }
            )
            payload = resume if isinstance(resume, dict) else {}
            merged = {**attrs, **(payload.get("attrs") or {})}
            return {"attrs": merged, "current_node_id": node.id}
        log.info("collect node=%s satisfied all properties", node.id)
        return {"current_node_id": node.id}

    return collect_node


def _make_action_node(node: OntologyNode, spec: OntologySpec) -> Callable[[FlowState], dict[str, Any]]:
    ad = spec.action_by_api_name().get(node.action_ref or "")
    name = ad.implementation_key if ad else "action"

    def action_node(state: FlowState) -> dict[str, Any]:
        log.info("action node=%s waiting for user confirm action_name=%s", node.id, name)
        resume = interrupt(
            {
                "kind": "action",
                "node_id": node.id,
                "action_name": name,
                "title": node.title or "请完成核验",
            }
        )
        payload = resume if isinstance(resume, dict) else {}
        ok = bool(payload.get("confirmed"))
        log.info("action node=%s resumed confirmed=%s", node.id, ok)
        if not ok:
            return {"current_node_id": node.id}
        return {"current_node_id": node.id}

    return action_node


def _make_terminal_node(node: OntologyNode) -> Callable[[FlowState], dict[str, Any]]:
    outcome = node.outcome or "denied"
    message = node.message or ("完成" if outcome == "approved" else "不予开卡")

    def terminal_node(state: FlowState) -> dict[str, Any]:
        log.info("terminal node=%s outcome=%s", node.id, outcome)
        return {
            "outcome": outcome,
            "terminal_message": message,
            "terminal_node_id": node.id,
            "current_node_id": node.id,
        }

    return terminal_node


def compile_flow(spec: OntologySpec, client: OntologyPlatformClient) -> CompiledFlow:
    ensure_compilable(spec)
    labels = spec.property_labels()
    logic_by_api = spec.logic_by_api_name()
    builder = StateGraph(FlowState)

    for node in spec.nodes:
        if node.kind == "logic":
            builder.add_node(node.id, _make_logic_node(node, client, logic_by_api))
        elif node.kind == "collect":
            if not node.property_api_names:
                raise ValueError(f"collect node {node.id} missing propertyApiNames")
            display = spec.property_names_for_object_type(node.object_type_api_name)
            if not display:
                display = list(node.property_api_names or [])
            builder.add_node(node.id, _make_collect_node(node, labels, display))
        elif node.kind == "action":
            builder.add_node(node.id, _make_action_node(node, spec))
        elif node.kind == "terminal":
            builder.add_node(node.id, _make_terminal_node(node))
        else:
            raise ValueError(f"Unknown node kind: {node.kind}")

    entry = spec.aip_logic.entry
    builder.add_edge(START, entry)

    for node in spec.nodes:
        if node.kind == "logic":
            edges = node.edges
            if not edges:
                raise ValueError(f"logic node {node.id} missing edges")
            mapping: dict[str, str] = {}
            if edges.true:
                mapping["true"] = edges.true
            if edges.false:
                mapping["false"] = edges.false
            builder.add_conditional_edges(node.id, _logic_router, mapping)
        elif node.kind in ("collect", "action"):
            nxt = node.next
            if not nxt:
                raise ValueError(f"node {node.id} missing next")
            builder.add_edge(node.id, nxt)
        elif node.kind == "terminal":
            builder.add_edge(node.id, END)

    memory = MemorySaver()
    graph = builder.compile(checkpointer=memory)
    summary = format_compiled_graph(graph)
    log.info(
        "compiled flow id=%s entry=%s spec_nodes=%d langgraph_nodes=%d langgraph_edges=%d langgraph_edges_preview=%s",
        spec.aip_logic.id,
        entry,
        len(spec.nodes),
        len(summary["nodes"]),
        len(summary["edges"]),
        compiled_graph_edges_summary(summary["edges"]),
    )
    log.info(
        "compiled langgraph flow_id=%s nodes=%s",
        spec.aip_logic.id,
        summary["nodes"],
    )
    log.info(
        "compiled langgraph flow_id=%s mermaid_single_line=%s",
        spec.aip_logic.id,
        compiled_graph_mermaid_one_line(summary),
    )
    log.debug(
        "compiled langgraph flow_id=%s mermaid_multiline=\n%s",
        spec.aip_logic.id,
        compiled_graph_mermaid(summary),
    )
    log.debug(
        "compiled langgraph flow_id=%s edges_full=%s",
        spec.aip_logic.id,
        summary["edges"],
    )
    return CompiledFlow(spec=spec, graph=graph)
