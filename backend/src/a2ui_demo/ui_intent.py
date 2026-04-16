from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from a2ui_demo.a2ui_contract import ALLOWED_ACTION_NAMES, ALLOWED_INPUT_TYPES
from a2ui_demo.a2ui_templates import collect_editable_field_keys_for_user_input


class UiIntentField(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    field_id: str = Field(alias="fieldId")
    label: str | None = None
    input_type: str = Field("shortText", alias="inputType")
    placeholder: str | None = None
    editable: bool | None = None
    display_mode: str | None = Field(None, alias="displayMode")
    field_error: str | None = Field(None, alias="fieldError")


class UiIntentBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["collect_form"] = "collect_form"
    title: str | None = None
    assistant_text: str | None = Field(None, alias="assistantText")
    action_name: str | None = Field(None, alias="actionName")
    fields: list[UiIntentField] = Field(default_factory=list)
    submit_fields: list[str] = Field(default_factory=list, alias="submitFields")


class UiIntentEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    output_kind: Literal["uiIntent"] = Field(alias="outputKind")
    version: str | None = "1.0"
    intent: UiIntentBody


def normalize_ui_intent_payload(
    payload: dict[str, Any],
    interrupt_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """
    Parse + normalize a model-generated uiIntent payload.
    Returns (normalized_intent, warnings, error_code).
    """
    warnings: list[str] = []
    try:
        parsed = UiIntentEnvelope.model_validate(payload)
    except ValidationError:
        return None, warnings, "intent_validate_error"

    intent = parsed.intent
    title = str(intent.title or interrupt_payload.get("title") or "请补全信息").strip() or "请补全信息"
    assistant_text = str(intent.assistant_text or "").strip() or None

    action_name = str(intent.action_name or "submit_collect").strip() or "submit_collect"
    if action_name not in ALLOWED_ACTION_NAMES:
        warnings.append(f"invalid_action:{action_name}")
        action_name = "submit_collect"

    editable_set = set(collect_editable_field_keys_for_user_input(interrupt_payload))
    labels = dict(interrupt_payload.get("labels") or {})
    missing_fallback = list(interrupt_payload.get("missing") or [])
    display = list(interrupt_payload.get("property_api_names") or missing_fallback)

    by_id: dict[str, UiIntentField] = {}
    for raw in intent.fields:
        fid = str(raw.field_id or "").strip()
        if not fid or fid in by_id:
            continue
        by_id[fid] = raw

    if not display:
        display = list(by_id.keys()) or list(missing_fallback)
    if not display:
        return None, warnings, "intent_no_fields"

    normalized_fields: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for field_id in display:
        fid = str(field_id or "").strip()
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)
        raw = by_id.get(fid)
        label = labels.get(fid) or (str(raw.label).strip() if raw and raw.label else fid)
        editable = fid in editable_set
        input_type = str(raw.input_type).strip() if raw else "shortText"
        if input_type not in ALLOWED_INPUT_TYPES:
            warnings.append(f"field_input_type_rewritten:{fid}:{input_type}")
            input_type = "shortText"
        placeholder = str(raw.placeholder or "").strip() if raw and raw.placeholder else ""
        row: dict[str, Any] = {
            "fieldId": fid,
            "label": label,
            "path": f"/user/{fid}",
            "inputType": input_type,
            "placeholder": placeholder or None,
            "editable": editable,
            "displayMode": "input" if editable else "readonly",
        }
        if raw and raw.field_error and str(raw.field_error).strip():
            row["fieldError"] = str(raw.field_error).strip()
        normalized_fields.append(row)

    if not normalized_fields:
        return None, warnings, "intent_no_fields"

    submit_fields: list[str] = []
    raw_submit = list(intent.submit_fields or [])
    allowed_ids = {f["fieldId"] for f in normalized_fields}
    for key in raw_submit:
        fid = str(key or "").strip()
        if not fid or fid not in allowed_ids or fid in submit_fields:
            continue
        submit_fields.append(fid)
    if not submit_fields:
        submit_fields = [f["fieldId"] for f in normalized_fields]

    return (
        {
            "kind": "collect_form",
            "title": title,
            "assistantText": assistant_text,
            "actionName": action_name,
            "fields": normalized_fields,
            "submitFields": submit_fields,
        },
        warnings,
        None,
    )
