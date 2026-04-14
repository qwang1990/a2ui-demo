from __future__ import annotations

import copy
import logging
from typing import Any

from a2ui_demo.a2ui_v08_catalog import STANDARD_CATALOG_COMPONENT_NAMES

log = logging.getLogger(__name__)

_TOP_LEVEL_KEYS = frozenset({"beginRendering", "surfaceUpdate", "dataModelUpdate", "deleteSurface"})


def _normalize_textfield_component_props(props: dict[str, Any]) -> None:
    """Lit catalog uses textFieldType; some generators emit legacy key 'type'."""
    if "textFieldType" not in props and "type" in props and isinstance(props["type"], str):
        props["textFieldType"] = props.pop("type")


def _walk_surface_components(components: list[Any]) -> list[str]:
    errors: list[str] = []
    for i, item in enumerate(components):
        if not isinstance(item, dict):
            errors.append(f"components[{i}]_not_object")
            continue
        cid = item.get("id")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"components[{i}]_missing_id")
        comp_wrap = item.get("component")
        if not isinstance(comp_wrap, dict):
            errors.append(f"components[{i}]_missing_component")
            continue
        keys = list(comp_wrap.keys())
        if len(keys) != 1:
            errors.append(f"components[{i}]_expected_one_component_key_got_{keys!r}")
            continue
        tname = keys[0]
        if tname not in STANDARD_CATALOG_COMPONENT_NAMES:
            errors.append(f"components[{i}]_unknown_component_type:{tname}")
            continue
        props = comp_wrap[tname]
        if not isinstance(props, dict):
            errors.append(f"components[{i}]_{tname}_props_not_object")
            continue
        if tname == "TextField":
            _normalize_textfield_component_props(props)
    return errors


def coerce_v08_messages_from_llm(messages: list[Any]) -> list[dict[str, Any]]:
    """
    Best-effort fix common LLM mistakes before strict validation.
    v0.8 requires surfaceUpdate.components to be an array of {id, component}; models often emit an object map id -> componentBody.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)  # type: ignore[arg-type]
            continue
        m = copy.deepcopy(msg)
        su = m.get("surfaceUpdate")
        if isinstance(su, dict):
            comps = su.get("components")
            if isinstance(comps, dict) and comps:
                fixed: list[dict[str, Any]] = []
                for cid, node in comps.items():
                    if not isinstance(cid, str) or not isinstance(node, dict):
                        continue
                    inner = node.get("component")
                    if isinstance(inner, dict) and len(inner) == 1:
                        fixed.append({"id": str(node.get("id") or cid), "component": inner})
                        continue
                    cat_keys = [k for k in node if k in STANDARD_CATALOG_COMPONENT_NAMES]
                    if len(cat_keys) == 1:
                        k0 = cat_keys[0]
                        fixed.append({"id": cid, "component": {k0: node[k0]}})
                if fixed:
                    log.info("a2ui coerce: surfaceUpdate.components dict -> list len=%d", len(fixed))
                    su = dict(su)
                    su["components"] = fixed
                    m["surfaceUpdate"] = su
                elif comps:
                    log.debug("a2ui coerce: components dict but no entries converted keys=%s", list(comps.keys())[:8])
        out.append(m)
    return out


def validate_v08_message_batch(messages: list[Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Structural validation for A2UI v0.8 server-to-client messages (subset).
    See https://a2ui.org/reference/messages/
    """
    if not isinstance(messages, list) or not messages:
        return None, "messages_empty_or_not_array"
    out: list[dict[str, Any]] = []
    component_ids: set[str] = set()
    roots: list[tuple[str, str]] = []

    for mi, msg in enumerate(messages):
        if not isinstance(msg, dict):
            return None, f"message[{mi}]_not_object"
        present = [k for k in _TOP_LEVEL_KEYS if k in msg]
        if len(present) != 1:
            return None, f"message[{mi}]_expected_one_top_key_got_{present!r}"
        if set(msg.keys()) != {present[0]}:
            return None, f"message[{mi}]_extra_keys_{set(msg.keys()) - {present[0]}!r}"
        key = present[0]
        body = msg[key]
        if not isinstance(body, dict):
            return None, f"message[{mi}]_{key}_not_object"

        if key == "surfaceUpdate":
            sid = body.get("surfaceId")
            if not isinstance(sid, str) or not sid.strip():
                return None, f"message[{mi}]_surfaceUpdate_missing_surfaceId"
            comps = body.get("components")
            if not isinstance(comps, list) or not comps:
                return None, f"message[{mi}]_surfaceUpdate_missing_components"
            errs = _walk_surface_components(comps)
            if errs:
                return None, f"message[{mi}]_surfaceUpdate_invalid:{'|'.join(errs)}"
            for item in comps:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    component_ids.add(item["id"])

        elif key == "dataModelUpdate":
            sid = body.get("surfaceId")
            if not isinstance(sid, str) or not sid.strip():
                return None, f"message[{mi}]_dataModelUpdate_missing_surfaceId"
            contents = body.get("contents")
            if not isinstance(contents, list):
                return None, f"message[{mi}]_dataModelUpdate_missing_contents"

        elif key == "beginRendering":
            sid = body.get("surfaceId")
            root = body.get("root")
            if not isinstance(sid, str) or not sid.strip():
                return None, f"message[{mi}]_beginRendering_missing_surfaceId"
            if not isinstance(root, str) or not root.strip():
                return None, f"message[{mi}]_beginRendering_missing_root"
            roots.append((sid, root))

        elif key == "deleteSurface":
            sid = body.get("surfaceId")
            if not isinstance(sid, str) or not sid.strip():
                return None, f"message[{mi}]_deleteSurface_missing_surfaceId"

        out.append(dict(msg))

    if not roots:
        return None, "missing_beginRendering"
    for sid, root in roots:
        if root not in component_ids:
            return None, f"beginRendering_root_not_found:{root!r}_surface={sid!r}"
    return out, None


def sanitize_messages_for_transport(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply in-place safe normalizations (copy outer list)."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        m = dict(msg)
        if "surfaceUpdate" in m:
            su = dict(m["surfaceUpdate"])  # type: ignore[arg-type]
            comps = su.get("components")
            if isinstance(comps, list):
                new_comps = []
                for item in comps:
                    if not isinstance(item, dict):
                        new_comps.append(item)
                        continue
                    it = dict(item)
                    cw = it.get("component")
                    if isinstance(cw, dict) and len(cw) == 1:
                        tname, props = next(iter(cw.items()))
                        if isinstance(props, dict) and tname == "TextField":
                            props2 = dict(props)
                            _normalize_textfield_component_props(props2)
                            it["component"] = {tname: props2}
                    new_comps.append(it)
                su["components"] = new_comps
            m["surfaceUpdate"] = su
        out.append(m)
    return out
