from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from a2ui_demo.ontology_models import OntologySpec


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
    nodes = spec.node_by_id()
    ids = set(nodes.keys())

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

    for n in spec.nodes:
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
                errors.append({"path": f"{prefix}.next", "message": "action node requires next"})
            elif n.next not in ids:
                errors.append({"path": f"{prefix}.next", "message": f"next {n.next!r} is not a node id"})
        elif n.kind == "terminal":
            pass

    # Reachability: at least one terminal reachable from entry
    if entry in nodes:
        from collections import deque

        q = deque([entry])
        seen: set[str] = set()
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            cn = nodes[cur]
            if cn.kind == "terminal":
                continue
            if cn.kind == "logic" and cn.edges:
                for t in (cn.edges.true, cn.edges.false):
                    if t:
                        q.append(t)
            elif cn.next:
                q.append(cn.next)
        reachable_terminal = any(nodes[i].kind == "terminal" for i in seen)
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
    return spec, []
