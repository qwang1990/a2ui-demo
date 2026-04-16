from __future__ import annotations

import logging
import hashlib
import json
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
from a2ui_demo.ontology_validation import (
    OntologyValidationError,
    coerce_attrs_for_properties,
    expand_incomplete_graph_nodes,
    summarize_property_constraints,
    validate_ontology_semantics,
    validate_user_attrs,
)

log = logging.getLogger(__name__)


class CompiledFlow:
    def __init__(self, spec: OntologySpec, graph: Any) -> None:
        self.spec = spec
        self.graph = graph
        self.entry = spec.aip_logic.entry
        raw = json.dumps(spec.model_dump(mode="json", by_alias=True), sort_keys=True, ensure_ascii=False)
        self.ontology_revision = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def ensure_compilable(spec: OntologySpec) -> None:
    errs = validate_ontology_semantics(spec)
    if errs:
        raise OntologyValidationError(errs)


def _materialized_nodes(spec: OntologySpec) -> list[OntologyNode]:
    return expand_incomplete_graph_nodes(spec)


def _template_attrs_for_node(node: OntologyNode, attrs: dict[str, Any]) -> dict[str, Any]:
    """HTTP 路径模板与 logic 表达式共用上下文：可将 attrs[fromAttr] 映射到模板占位符 templateKey。"""
    if not node.logic_parameter_bindings:
        return attrs
    out = dict(attrs)
    for b in node.logic_parameter_bindings:
        if b.from_attr in attrs:
            out[b.template_key] = attrs[b.from_attr]
    return out


def evaluate_expression(expression: str, attrs: dict[str, Any]) -> bool:
    """Evaluate a simple boolean expression against attrs.

    Supports:  attrs.key == value, !=, >, >=, <, <=, &&, ||, !
    Values:    true, false, numeric literals, "string" literals, unquoted treated as string.
    """
    if not expression or not expression.strip():
        return False
    expr = expression.strip()
    expr = expr.replace("&&", " and ").replace("||", " or ").replace("!", " not ")
    import re
    expr = re.sub(r"attrs\.(\w+)", lambda m: repr(attrs.get(m.group(1))), expr)
    expr = re.sub(r"\btrue\b", "True", expr)
    expr = re.sub(r"\bfalse\b", "False", expr)
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception as exc:
        log.warning("expression eval failed expr=%r error=%s", expression, exc)
        return False


def _evaluate_logic_result(
    state: FlowState,
    node: OntologyNode,
    client: OntologyPlatformClient,
    logic_by_api: dict[str, LogicDefinition],
) -> tuple[bool, dict[str, Any]]:
    """表达式优先；否则按 logicRef 调 mock HTTP，返回 (分支布尔, 完整 payload 供 responseToAttrs 合并)。"""
    attrs = state.get("attrs") or {}
    template_attrs = _template_attrs_for_node(node, attrs)
    if node.expression:
        return evaluate_expression(node.expression, attrs), {}
    ref = node.logic_ref or ""
    ld = logic_by_api.get(ref)
    if not ld:
        log.debug("logic node=%s missing definition for logicRef=%s", node.id, ref)
        return False, {}
    impl = ld.implementation
    if impl.type != "mock_user_flags":
        log.warning("logic node=%s unsupported implementation type=%s", node.id, impl.type)
        return False, {}
    path, missing = interpolate_request_path(impl.request_path_template, template_attrs)
    if path is None:
        log.debug("logic node=%s: missing attrs for request path: %s", node.id, missing)
        return False, {}
    try:
        payload = client.get_json(path)
    except Exception:
        # POC: mock endpoint 不可用时回退为确定性规则，避免流程中断。
        id_number = str(template_attrs.get("idNumber") or "")
        user_id = str(template_attrs.get("userId") or f"U_{id_number.upper()}")
        payload = {
            "found": bool(str(template_attrs.get("fullName") or "").strip() and id_number.strip()),
            "userId": user_id,
            "has_ms_credit_card": "HAS_MS" in id_number.upper() or user_id.upper().endswith("MS"),
            "is_sams_member": "SAMS_MEMBER" in id_number.upper() or user_id.upper().endswith("SAMS"),
        }
    if not isinstance(payload, dict):
        payload = {}
    return bool(payload.get(impl.flag_key)), payload


def _logic_router(state: FlowState) -> str:
    b = state.get("_branch")
    return b if b in ("true", "false") else "false"


def _make_logic_node(
    node: OntologyNode,
    client: OntologyPlatformClient,
    logic_by_api: dict[str, LogicDefinition],
) -> Callable[[FlowState], dict[str, Any]]:
    def logic_node(state: FlowState) -> dict[str, Any]:
        attrs = dict(state.get("attrs") or {})
        ok, payload = _evaluate_logic_result(state, node, client, logic_by_api)
        merged = {**attrs}
        keys = list(node.response_to_attrs or [])
        if payload and keys:
            for k in keys:
                if k in payload:
                    merged[k] = payload[k]
        branch = "true" if ok else "false"
        log.info("logic node=%s logicRef=%s branch=%s", node.id, node.logic_ref, branch)
        return {"attrs": merged, "_branch": branch, "current_node_id": node.id}

    return logic_node


def _make_collect_node(
    node: OntologyNode,
    spec: OntologySpec,
    labels: dict[str, str],
    display_property_names: list[str],
) -> Callable[[FlowState], dict[str, Any]]:
    """display_property_names: 本体对象类型下全部属性顺序，用于 UI 展示已收集项；collect_field_names 仅决定本步缺哪些。"""
    collect_field_names = list(node.property_api_names or [])

    def collect_node(state: FlowState) -> dict[str, Any]:
        constraints = summarize_property_constraints(
            spec,
            object_type_api_name=node.object_type_api_name,
            property_api_names=display_property_names,
        )
        merged = dict(state.get("attrs") or {})
        while True:
            merged = coerce_attrs_for_properties(
                spec,
                merged,
                object_type_api_name=node.object_type_api_name,
                property_api_names=display_property_names,
            )
            validation_errors = validate_user_attrs(
                spec,
                merged,
                object_type_api_name=node.object_type_api_name,
                property_api_names=collect_field_names,
                require_all=True,
            )
            missing = [
                k
                for k in collect_field_names
                if any(
                    e.get("path") == k
                    and (merged.get(k) is None or (isinstance(merged.get(k), str) and not merged.get(k).strip()))
                    for e in validation_errors
                )
            ]
            if not validation_errors:
                log.info("collect node=%s satisfied all properties", node.id)
                return {"attrs": merged, "current_node_id": node.id}
            log.info(
                "collect node=%s missing=%s validation_errors=%s objectType=%s",
                node.id,
                missing,
                validation_errors,
                node.object_type_api_name,
            )
            resume = interrupt(
                {
                    "kind": "user_input",
                    "node_id": node.id,
                    "missing": missing,
                    "labels": {k: labels.get(k, k) for k in display_property_names},
                    "property_api_names": display_property_names,
                    "collect_field_names": collect_field_names,
                    "title": node.title or "请补全信息",
                    "attrs": dict(merged),
                    "objectTypeApiName": node.object_type_api_name,
                    "constraints": constraints,
                    "validationErrors": validation_errors,
                }
            )
            payload = resume if isinstance(resume, dict) else {}
            merged = {**merged, **(payload.get("attrs") or {})}

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

    nodes = _materialized_nodes(spec)
    for node in nodes:
        if node.kind == "logic":
            builder.add_node(node.id, _make_logic_node(node, client, logic_by_api))
        elif node.kind == "collect":
            if not node.property_api_names:
                raise ValueError(f"collect node {node.id} missing propertyApiNames")
            display = spec.property_names_for_object_type(node.object_type_api_name)
            if not display:
                display = list(node.property_api_names or [])
            builder.add_node(node.id, _make_collect_node(node, spec, labels, display))
        elif node.kind == "action":
            builder.add_node(node.id, _make_action_node(node, spec))
        elif node.kind == "terminal":
            builder.add_node(node.id, _make_terminal_node(node))
        else:
            raise ValueError(f"Unknown node kind: {node.kind}")

    entry = spec.aip_logic.entry
    builder.add_edge(START, entry)

    for node in nodes:
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
        len(nodes),
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
