from __future__ import annotations

import re
from typing import Any, Literal

A2uiMessagesSource = Literal[
    "llm_intent_compiled",
    "llm_schema",
    "llm_a2ui_v08",
    "template_unknown",
    "template_non_user_input",
    "template_fallback",
    "template_on_intent_error",
    "template_on_schema_error",
]

FallbackReason = Literal[
    "llm_disabled",
    "llm_client_unavailable",
    "llm_timeout",
    "llm_request_error",
    "json_parse_error",
    "schema_validate_error",
    "schema_no_fields",
    "schema_to_messages_error",
    "intent_validate_error",
    "intent_no_fields",
    "intent_to_messages_error",
    "union_parse_error",
    "union_output_kind_invalid",
    "a2ui_batch_validate_error",
]

ALLOWED_INPUT_TYPES = frozenset({"shortText", "longText"})
ALLOWED_ACTION_NAMES = frozenset({"submit_collect"})
ALLOWED_COMPONENT_TYPES = frozenset({"Text", "TextField", "Column", "Button"})

_FIELD_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def compose_messages_source(source: str, fallback_reason: str | None) -> str:
    if not fallback_reason:
        return source
    return f"{source}:{fallback_reason}"


def normalize_collect_schema(schema: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Normalize model-generated collect schema with allow-list constraints.
    Returns (normalized_schema, warnings).
    """
    warnings: list[str] = []
    out = dict(schema)
    out["kind"] = "user_input"

    action_name = str(out.get("actionName") or "submit_collect").strip()
    if action_name not in ALLOWED_ACTION_NAMES:
        warnings.append(f"invalid_action:{action_name}")
        action_name = "submit_collect"
    out["actionName"] = action_name

    raw_fields = list(out.get("fields") or [])
    normalized_fields: list[dict[str, Any]] = []
    for item in raw_fields:
        if not isinstance(item, dict):
            warnings.append("field_not_object")
            continue
        field_id = str(item.get("fieldId") or "").strip()
        if not field_id:
            warnings.append("field_missing_id")
            continue
        if not _FIELD_ID_RE.match(field_id):
            warnings.append(f"field_invalid_id:{field_id}")
            continue

        label = str(item.get("label") or field_id).strip() or field_id
        path = str(item.get("path") or "").strip()
        expected_path = f"/user/{field_id}"
        if path != expected_path:
            warnings.append(f"field_path_rewritten:{field_id}")
            path = expected_path

        input_type = str(item.get("inputType") or "shortText").strip() or "shortText"
        if input_type not in ALLOWED_INPUT_TYPES:
            warnings.append(f"field_input_type_rewritten:{field_id}:{input_type}")
            input_type = "shortText"

        placeholder = str(item.get("placeholder") or "").strip() or None
        field_error = str(item.get("fieldError") or "").strip() or None
        nf: dict[str, Any] = {
            "fieldId": field_id,
            "label": label,
            "path": path,
            "inputType": input_type,
            "required": bool(item.get("required", True)),
            "placeholder": placeholder,
        }
        if field_error:
            nf["fieldError"] = field_error
        normalized_fields.append(nf)

    out["fields"] = normalized_fields
    if "assistantText" in out and out["assistantText"] is not None:
        out["assistantText"] = str(out["assistantText"]).strip()
    if "title" in out:
        out["title"] = str(out["title"]).strip() or "请补全信息"
    else:
        out["title"] = "请补全信息"
    return out, warnings


def summarize_context_shape(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {"keys": [], "empty_keys": [], "value_lengths": {}}
    keys = list(data.keys())
    empty_keys: list[str] = []
    lengths: dict[str, int | None] = {}
    for key, value in data.items():
        if value is None:
            empty_keys.append(key)
            lengths[key] = None
            continue
        text = str(value).strip() if isinstance(value, str) else None
        if text is not None:
            if not text:
                empty_keys.append(key)
            lengths[key] = len(text)
            continue
        if isinstance(value, (list, tuple, set, dict)):
            lengths[key] = len(value)
            if len(value) == 0:
                empty_keys.append(key)
            continue
        lengths[key] = None
    return {"keys": keys, "empty_keys": empty_keys, "value_lengths": lengths}
