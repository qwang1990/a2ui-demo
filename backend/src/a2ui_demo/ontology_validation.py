from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from a2ui_demo.ontology_models import ObjectProperty, OntologyNode, OntologySpec, PropertyConstraints

INCOMPLETE_TERMINAL_ID = "__aip_incomplete__"


def expand_incomplete_graph_nodes(spec: OntologySpec) -> list[OntologyNode]:
    """When allowIncompleteGraph is set, wire dangling collect/action to a synthetic terminal."""
    base = spec.aip_logic_graph.to_ontology_nodes() if spec.aip_logic_graph else list(spec.nodes)
    if not spec.aip_logic.allow_incomplete_graph:
        return base
    out: list[OntologyNode] = []
    need_terminal = False
    for n in base:
        if n.kind == "collect" and not n.next:
            need_terminal = True
            out.append(n.model_copy(update={"next": INCOMPLETE_TERMINAL_ID}))
        elif n.kind == "action" and not n.next:
            need_terminal = True
            out.append(n.model_copy(update={"next": INCOMPLETE_TERMINAL_ID}))
        else:
            out.append(n)
    ids = {x.id for x in out}
    if need_terminal and INCOMPLETE_TERMINAL_ID not in ids:
        out.append(
            OntologyNode(
                id=INCOMPLETE_TERMINAL_ID,
                kind="terminal",
                title="编排未完成",
                outcome="denied",
                message="请在本体编排页补全 AIP 连线后再运行完整流程",
            )
        )
    return out


class OntologyValidationError(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__(str(errors))


def pydantic_errors_to_list(exc: ValidationError) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        path = ".".join(str(x) for x in loc) if loc else ""
        msg = str(err.get("msg", "validation error"))
        out.append({"path": path, "message": msg})
    return out


def parse_ontology_json(raw: str | bytes | dict[str, Any]) -> tuple[OntologySpec | None, list[dict[str, str]]]:
    """Parse JSON into OntologySpec; on failure return (None, errors)."""
    try:
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, bytes):
            data = json.loads(raw.decode("utf-8"))
        else:
            data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [{"path": "", "message": f"Invalid JSON: {e}"}]

    try:
        return OntologySpec.model_validate(data), []
    except ValidationError as e:
        return None, pydantic_errors_to_list(e)


def validate_ontology_semantics(spec: OntologySpec) -> list[dict[str, str]]:
    """Structural checks after Pydantic: entry, edges, refs to catalog."""
    errors: list[dict[str, str]] = []
    materialized_nodes = spec.aip_logic_graph.to_ontology_nodes() if spec.aip_logic_graph else spec.nodes
    nodes = {n.id: n for n in materialized_nodes}
    ids = set(nodes.keys())
    expanded = expand_incomplete_graph_nodes(spec)
    expanded_by_id = {n.id: n for n in expanded}

    logic_map = spec.logic_by_api_name()
    action_map = spec.action_by_api_name()

    # Unique logic / action apiNames
    if len({d.api_name for d in spec.logic_definitions}) != len(spec.logic_definitions):
        errors.append({"path": "logicDefinitions", "message": "Duplicate logicDefinitions.apiName"})
    if len({d.api_name for d in spec.action_definitions}) != len(spec.action_definitions):
        errors.append({"path": "actionDefinitions", "message": "Duplicate actionDefinitions.apiName"})

    all_property_api_names: set[str] = set()
    for ot in spec.object_types:
        for p in ot.properties:
            all_property_api_names.add(p.api_name)

    for ld in spec.logic_definitions:
        impl = ld.implementation
        if impl.type != "mock_user_flags":
            continue
        tpl = impl.request_path_template
        for key in re.findall(r"\{([\w]+)\}", tpl):
            if key not in all_property_api_names:
                errors.append(
                    {
                        "path": f"logicDefinitions.{ld.api_name}.implementation.requestPathTemplate",
                        "message": (
                            f"placeholder {{{key}}} must match an object property apiName "
                            f"declared under objectTypes"
                        ),
                    }
                )

    entry = spec.aip_logic.entry
    if entry not in nodes:
        errors.append({"path": "aip_logic.entry", "message": f"entry node {entry!r} not found in nodes"})

    ot_by_name = {ot.api_name: ot for ot in spec.object_types}
    prop_sets: dict[str, set[str]] = {}
    for name, ot in ot_by_name.items():
        prop_sets[name] = {p.api_name for p in ot.properties}

    for n in materialized_nodes:
        prefix = f"nodes[{n.id}]"
        if n.kind == "logic":
            if not n.logic_ref:
                errors.append({"path": f"{prefix}.logicRef", "message": "logic node requires logicRef"})
            elif n.logic_ref not in logic_map:
                errors.append(
                    {
                        "path": f"{prefix}.logicRef",
                        "message": f"unknown logicRef {n.logic_ref!r}; not in logicDefinitions",
                    }
                )
            if not n.edges or (not n.edges.true and not n.edges.false):
                errors.append({"path": f"{prefix}.edges", "message": "logic node requires edges.true / edges.false"})
            for label, target in (("true", n.edges.true if n.edges else None), ("false", n.edges.false if n.edges else None)):
                if target and target not in ids:
                    errors.append(
                        {
                            "path": f"{prefix}.edges.{label}",
                            "message": f"edge target {target!r} is not a node id",
                        }
                    )
        elif n.kind == "collect":
            if not n.property_api_names:
                errors.append({"path": f"{prefix}.propertyApiNames", "message": "collect node requires propertyApiNames"})
            if not n.object_type_api_name:
                errors.append({"path": f"{prefix}.objectTypeApiName", "message": "collect node requires objectTypeApiName"})
            elif n.object_type_api_name not in ot_by_name:
                errors.append(
                    {
                        "path": f"{prefix}.objectTypeApiName",
                        "message": f"unknown object type {n.object_type_api_name!r}",
                    }
                )
            else:
                ps = prop_sets.get(n.object_type_api_name, set())
                for pname in n.property_api_names or []:
                    if pname not in ps:
                        errors.append(
                            {
                                "path": f"{prefix}.propertyApiNames",
                                "message": f"property {pname!r} not on object type {n.object_type_api_name}",
                            }
                        )
            if not n.next:
                if not spec.aip_logic.allow_incomplete_graph:
                    errors.append({"path": f"{prefix}.next", "message": "collect node requires next"})
            elif n.next not in ids:
                errors.append({"path": f"{prefix}.next", "message": f"next {n.next!r} is not a node id"})
        elif n.kind == "action":
            if not n.action_ref:
                errors.append({"path": f"{prefix}.actionRef", "message": "action node requires actionRef"})
            elif n.action_ref not in action_map:
                errors.append(
                    {
                        "path": f"{prefix}.actionRef",
                        "message": f"unknown actionRef {n.action_ref!r}; not in actionDefinitions",
                    }
                )
            if not n.next:
                if not spec.aip_logic.allow_incomplete_graph:
                    errors.append({"path": f"{prefix}.next", "message": "action node requires next"})
            elif n.next not in ids:
                errors.append({"path": f"{prefix}.next", "message": f"next {n.next!r} is not a node id"})
        elif n.kind == "terminal":
            pass

    # Reachability: at least one terminal reachable from entry (use expanded graph if draft)
    if entry in expanded_by_id:
        from collections import deque

        q = deque([entry])
        seen: set[str] = set()
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            cn = expanded_by_id[cur]
            if cn.kind == "terminal":
                continue
            if cn.kind == "logic" and cn.edges:
                for t in (cn.edges.true, cn.edges.false):
                    if t:
                        q.append(t)
            elif cn.next:
                q.append(cn.next)
        reachable_terminal = any(expanded_by_id[i].kind == "terminal" for i in seen)
        if not reachable_terminal:
            errors.append({"path": "aip_logic.entry", "message": "No terminal node is reachable from entry"})

    return errors


def validate_ontology_full(raw: str | bytes | dict[str, Any]) -> tuple[OntologySpec | None, list[dict[str, str]]]:
    """Parse JSON and run semantic validation."""
    spec, errs = parse_ontology_json(raw)
    if spec is None:
        return None, errs
    sem = validate_ontology_semantics(spec)
    if sem:
        return None, errs + sem
    if spec.aip_logic_graph:
        spec.nodes = spec.aip_logic_graph.to_ontology_nodes()
    return spec, []


def _find_property(spec: OntologySpec, api_name: str, object_type_api_name: str | None = None) -> ObjectProperty | None:
    for ot in spec.object_types:
        if object_type_api_name and ot.api_name != object_type_api_name:
            continue
        for p in ot.properties:
            if p.api_name == api_name:
                return p
    return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _coerce_value_for_property(value: Any, prop: ObjectProperty) -> Any:
    """表单/WebSocket 常为字符串；在类型校验前将整型/浮点数字面量转为 Python 数值。"""
    if _is_blank(value):
        return value
    if prop.type == "integer" and isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"-?\d+", s):
            return int(s)
    if prop.type == "double" and isinstance(value, str):
        s = value.strip()
        if re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", s):
            try:
                return float(s)
            except ValueError:
                return value
    return value


def coerce_attrs_for_properties(
    spec: OntologySpec,
    attrs: dict[str, Any],
    *,
    object_type_api_name: str | None,
    property_api_names: list[str],
) -> dict[str, Any]:
    """按本体属性类型把可解析的数字字符串写入 attrs（供 collect 写回状态与后续节点使用）。"""
    out = dict(attrs)
    for key in property_api_names:
        prop = _find_property(spec, key, object_type_api_name)
        if not prop or key not in out:
            continue
        out[key] = _coerce_value_for_property(out[key], prop)
    return out


def _validate_type(value: Any, prop: ObjectProperty) -> str | None:
    if prop.type == "string":
        if not isinstance(value, str):
            return "must be a string"
    elif prop.type == "boolean":
        if not isinstance(value, bool):
            return "must be a boolean"
    elif prop.type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "must be an integer"
    elif prop.type == "double":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "must be a number"
    elif prop.type == "timestamp":
        if not isinstance(value, str):
            return "must be an ISO timestamp string"
    return None


def _validate_constraints(value: Any, constraints: PropertyConstraints) -> str | None:
    if constraints.enum_values and str(value) not in constraints.enum_values:
        return constraints.message or f"must be one of {constraints.enum_values}"
    if isinstance(value, str):
        if constraints.min_length is not None and len(value) < constraints.min_length:
            return constraints.message or f"length must be >= {constraints.min_length}"
        if constraints.max_length is not None and len(value) > constraints.max_length:
            return constraints.message or f"length must be <= {constraints.max_length}"
        if constraints.pattern:
            try:
                if not re.fullmatch(constraints.pattern, value):
                    return constraints.message or "does not match required pattern"
            except re.error:
                return "invalid regex pattern in constraints.pattern"
        if constraints.format == "cn_phone_11" and not re.fullmatch(r"\d{11}", value):
            return constraints.message or "must be an 11-digit phone number"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if constraints.minimum is not None and numeric < constraints.minimum:
            return constraints.message or f"must be >= {constraints.minimum}"
        if constraints.maximum is not None and numeric > constraints.maximum:
            return constraints.message or f"must be <= {constraints.maximum}"
    return None


def summarize_property_constraints(
    spec: OntologySpec,
    *,
    object_type_api_name: str | None,
    property_api_names: list[str],
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for key in property_api_names:
        prop = _find_property(spec, key, object_type_api_name)
        if not prop:
            continue
        item: dict[str, Any] = {
            "type": prop.type,
            "required": bool(prop.required),
            "label": prop.display_name or prop.api_name,
        }
        if prop.constraints:
            item.update(
                {
                    "constraintRequired": bool(prop.constraints.required) if prop.constraints.required is not None else None,
                    "minLength": prop.constraints.min_length,
                    "maxLength": prop.constraints.max_length,
                    "pattern": prop.constraints.pattern,
                    "format": prop.constraints.format,
                    "minimum": prop.constraints.minimum,
                    "maximum": prop.constraints.maximum,
                    "enumValues": prop.constraints.enum_values,
                    "message": prop.constraints.message,
                }
            )
        summary[key] = {k: v for k, v in item.items() if v is not None}
    return summary


def validate_user_attrs(
    spec: OntologySpec,
    attrs: dict[str, Any],
    *,
    object_type_api_name: str | None,
    property_api_names: list[str],
    require_all: bool = False,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for key in property_api_names:
        prop = _find_property(spec, key, object_type_api_name)
        if not prop:
            continue
        value = _coerce_value_for_property(attrs.get(key), prop)
        constraints = prop.constraints
        required = require_all or prop.required
        if not require_all and constraints and constraints.required is not None:
            required = bool(constraints.required)
        if required and _is_blank(value):
            errors.append({"path": key, "message": constraints.message if constraints and constraints.message else f"{key} is required"})
            continue
        if _is_blank(value):
            continue
        type_err = _validate_type(value, prop)
        if type_err:
            errors.append({"path": key, "message": type_err})
            continue
        if constraints:
            c_err = _validate_constraints(value, constraints)
            if c_err:
                errors.append({"path": key, "message": c_err})
    return errors
