from __future__ import annotations

from typing import Any

SURFACE_ID = "main"


def _text_component(cid: str, text: str, usage: str = "body") -> dict[str, Any]:
    return {
        "id": cid,
        "component": {
            "Text": {
                "text": {"literalString": text},
                "usageHint": usage,
            }
        },
    }


def _text_field(
    cid: str,
    label: str,
    path: str,
    *,
    input_type: str = "shortText",
    placeholder: str | None = None,
) -> dict[str, Any]:
    out = {
        "id": cid,
        "component": {
            "TextField": {
                "label": {"literalString": label},
                "text": {"path": path},
                "type": input_type,
            }
        },
    }
    if placeholder:
        out["component"]["TextField"]["placeholder"] = {"literalString": placeholder}
    return out


def _column(cid: str, children: list[str]) -> dict[str, Any]:
    return {
        "id": cid,
        "component": {
            "Column": {
                "children": {"explicitList": children},
            }
        },
    }


def _button_submit(cid: str, child: str, action_name: str, paths: list[tuple[str, str]]) -> dict[str, Any]:
    """paths: list of (context_key, data_model_path)"""
    ctx: list[dict[str, Any]] = []
    for key, path in paths:
        ctx.append({"key": key, "value": {"path": path}})
    return {
        "id": cid,
        "component": {
            "Button": {
                "child": child,
                "action": {"name": action_name, "context": ctx},
            }
        },
    }


def build_collect_form_messages(
    *,
    title: str,
    fields: list[tuple[str, str, str, str, str | None]],
    action_name: str = "submit_collect",
    initial_attrs: dict[str, Any] | None = None,
    assistant_text: str | None = None,
) -> list[dict[str, Any]]:
    """
    fields: list of (attr_id, label, path under /user/, input_type, placeholder)
    Returns ServerToClientMessage-compatible dicts for v0.8.
    """
    root = "root_col"
    static_ids: list[str] = ["title_txt"]
    if assistant_text:
        static_ids.append("assistant_txt")
    field_ids: list[str] = []
    paths_for_button: list[tuple[str, str]] = []
    for i, (attr_id, _label, rel_path, _input_type, _placeholder) in enumerate(fields):
        fid = f"field_{attr_id}_{i}"
        field_ids.append(fid)
        paths_for_button.append((attr_id, rel_path))

    children = [*static_ids, *field_ids, "submit_btn_wrap"]
    components: list[dict[str, Any]] = [_text_component("title_txt", title, "h2")]
    if assistant_text:
        components.append(_text_component("assistant_txt", assistant_text, "body"))
    components.extend(
        [
            _text_field(fid, lab, p, input_type=input_type, placeholder=placeholder)
            for fid, (_aid, lab, p, input_type, placeholder) in zip(field_ids, fields, strict=True)
        ]
    )
    components.extend(
        [
            _text_component("submit_lbl", "提交", "body"),
            _button_submit("submit_btn", "submit_lbl", action_name, paths_for_button),
            _column("submit_btn_wrap", ["submit_btn"]),
        ]
    )
    col = _column(root, children)

    initial = dict(initial_attrs or {})
    user_map: list[dict[str, Any]] = []
    for attr_id, _label, rel_path, _input_type, _placeholder in fields:
        key = rel_path.rsplit("/", 1)[-1]
        val = str(initial.get(attr_id, "") or "")
        user_map.append({"key": key, "valueString": val})

    return [
        {
            "surfaceUpdate": {
                "surfaceId": SURFACE_ID,
                "components": [*components, col],
            }
        },
        {
            "dataModelUpdate": {
                "surfaceId": SURFACE_ID,
                "contents": [{"key": "user", "valueMap": user_map}],
            }
        },
        {"beginRendering": {"surfaceId": SURFACE_ID, "root": root}},
    ]


def schema_to_a2ui_messages(
    schema: dict[str, Any],
    *,
    initial_attrs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    kind = schema.get("kind")
    if kind == "user_input":
        title = str(schema.get("title") or "请补全信息")
        action_name = str(schema.get("actionName") or "submit_collect")
        assistant_text = str(schema.get("assistantText") or "").strip() or None
        raw_fields = list(schema.get("fields") or [])
        fields: list[tuple[str, str, str, str, str | None]] = []
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("fieldId") or "").strip()
            if not field_id:
                continue
            label = str(item.get("label") or field_id)
            path = str(item.get("path") or f"/user/{field_id}")
            input_type = str(item.get("inputType") or "shortText")
            placeholder = str(item.get("placeholder") or "").strip() or None
            fields.append((field_id, label, path, input_type, placeholder))
        if not fields:
            raise ValueError("schema user_input has no valid fields")
        return build_collect_form_messages(
            title=title,
            fields=fields,
            action_name=action_name,
            initial_attrs=initial_attrs,
            assistant_text=assistant_text,
        )
    raise ValueError(f"unknown schema kind: {kind}")


def interrupt_to_a2ui_messages(interrupt_payload: dict[str, Any]) -> list[dict[str, Any]]:
    kind = interrupt_payload.get("kind")
    if kind == "user_input":
        missing: list[str] = list(interrupt_payload.get("missing") or [])
        labels: dict[str, str] = dict(interrupt_payload.get("labels") or {})
        title = str(interrupt_payload.get("title") or "请补全信息")
        fields = []
        for m in missing:
            path = f"/user/{m}"
            fields.append((m, labels.get(m, m), path, "shortText", None))
        return build_collect_form_messages(
            title=title,
            fields=fields,
            initial_attrs=dict(interrupt_payload.get("attrs") or {}),
        )
    if kind == "action":
        title = str(interrupt_payload.get("title") or "请完成核验")
        action = str(interrupt_payload.get("action_name") or "action")
        root = "action_col"
        components = [
            _text_component("action_title", title, "h2"),
            _text_component("action_hint", "点击下方按钮模拟人脸识别通过。", "body"),
            _text_component("btn_lbl", "已完成识别", "body"),
            _button_submit(
                "action_btn",
                "btn_lbl",
                f"{action}_confirm",
                [],
            ),
            _column(root, ["action_title", "action_hint", "action_btn"]),
        ]
        return [
            {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
            {"beginRendering": {"surfaceId": SURFACE_ID, "root": root}},
        ]
    return [
        {
            "surfaceUpdate": {
                "surfaceId": SURFACE_ID,
                "components": [
                    _text_component("unk", "未知的交互类型", "body"),
                    _column("c", ["unk"]),
                ],
            }
        },
        {"beginRendering": {"surfaceId": SURFACE_ID, "root": "c"}},
    ]
