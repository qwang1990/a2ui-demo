from __future__ import annotations

from typing import Any

SURFACE_ID = "main"


def field_errors_from_validation_list(validation_errors: list[dict[str, Any]] | None) -> dict[str, str]:
    """把 {path, message} 列表转为 fieldId -> 错误文案（后者覆盖前者）。"""
    out: dict[str, str] = {}
    for e in validation_errors or []:
        if not isinstance(e, dict):
            continue
        p = str(e.get("path") or "").strip()
        m = str(e.get("message") or "").strip()
        if p and m:
            out[p] = m
    return out


def merge_assistant_with_validation(
    base: str | None,
    validation_errors: list[dict[str, Any]] | None,
) -> str | None:
    """在 assistant 文案中追加「请修正」列表，便于用户理解；Markdown 粗体。"""
    lines: list[str] = []
    for e in validation_errors or []:
        if not isinstance(e, dict):
            continue
        p = str(e.get("path") or "").strip()
        m = str(e.get("message") or "").strip()
        if p and m:
            lines.append(f"- **{p}**：{m}")
    if not lines:
        return base.strip() if base else None
    block = "请修正以下问题：\n" + "\n".join(lines)
    b = base.strip() if base else ""
    if b:
        return b + "\n\n" + block
    return block


def merge_field_errors_for_collect(
    *,
    server_validation_errors: list[dict[str, Any]] | None,
    per_field_from_llm: dict[str, str] | None,
) -> dict[str, str]:
    """LLM 给出的 fieldError 与服务器校验合并；服务器结果覆盖同名字段。"""
    out = dict(per_field_from_llm or {})
    out.update(field_errors_from_validation_list(server_validation_errors))
    return out


def _attr_value_nonblank(attrs: dict[str, Any], path: str) -> bool:
    v = attrs.get(path)
    if v is None:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    if isinstance(v, str):
        return bool(v.strip())
    return True


def should_show_validation_error_details(interrupt_payload: dict[str, Any]) -> bool:
    """
    首次进入采集步骤、待填项均为空时，不展示「请修正」与字段下红字（避免一进来就满屏报错）。
    当至少有一条 validationErrors 指向「用户已填过非空值」的采集字段时，才展示详细错误（格式/范围等）。
    """
    attrs = dict(interrupt_payload.get("attrs") or {})
    ve = list(interrupt_payload.get("validationErrors") or [])
    collect = set(interrupt_payload.get("collect_field_names") or interrupt_payload.get("missing") or [])
    for e in ve:
        if not isinstance(e, dict):
            continue
        p = str(e.get("path") or "").strip()
        if not p:
            continue
        if collect and p not in collect:
            continue
        if _attr_value_nonblank(attrs, p):
            return True
    return False


def validation_errors_for_ui(interrupt_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """供模板 / schema 合成：首次空表不返回错误列表。"""
    if not should_show_validation_error_details(interrupt_payload):
        return []
    return list(interrupt_payload.get("validationErrors") or [])


def _mask_tail(s: str, *, keep_last: int = 4) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    if len(t) <= keep_last:
        return "*" * len(t)
    return "*" * (len(t) - keep_last) + t[-keep_last:]


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


def _readonly_field_text(*, label: str, attr_id: str, raw_value: str) -> str:
    """单行 Markdown：已填项只读展示（身份证做尾部脱敏）。"""
    v = (raw_value or "").strip()
    if not v:
        display = "—"
    elif attr_id in ("idNumber", "phone"):
        display = _mask_tail(v)
    else:
        display = v
    return f"**{label}**　{display}"


def _column(cid: str, children: list[str], *, alignment: str | None = None) -> dict[str, Any]:
    col: dict[str, Any] = {"children": {"explicitList": children}}
    if alignment:
        col["alignment"] = alignment
    return {"id": cid, "component": {"Column": col}}


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
    fields: list[tuple[str, str, str, str, str | None, bool]],
    action_name: str = "submit_collect",
    initial_attrs: dict[str, Any] | None = None,
    assistant_text: str | None = None,
    submit_paths: list[tuple[str, str]] | None = None,
    field_errors: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    fields: list of (attr_id, label, path under /user/, input_type, placeholder, editable)
    - editable True → TextField；False → Text（只读摘要，不参与编辑）
    field_errors: attr_id -> 错误说明；在对应字段下方展示，便于用户修改。
    submit_paths: 提交按钮从数据模型读取的 (attr_id, path) 列表；默认取 fields 中每一项的路径
    Returns ServerToClientMessage-compatible dicts for v0.8.
    """
    root = "root_col"
    fe = field_errors or {}
    children: list[str] = ["title_txt"]
    if assistant_text:
        children.append("assistant_txt")
    for i, (attr_id, _label, _rel_path, _input_type, _placeholder, _editable) in enumerate(fields):
        fid = f"field_{attr_id}_{i}"
        children.append(fid)
        if fe.get(attr_id):
            children.append(f"err_{attr_id}_{i}")
    children.append("submit_btn_wrap")

    if submit_paths is None:
        paths_for_button = [(attr_id, p) for attr_id, _lab, p, _it, _ph, _ed in fields]
    else:
        paths_for_button = list(submit_paths)

    components: list[dict[str, Any]] = [_text_component("title_txt", title, "h2")]
    if assistant_text:
        components.append(_text_component("assistant_txt", assistant_text, "body"))

    initial = dict(initial_attrs or {})
    for i, (attr_id, lab, p, input_type, placeholder, editable) in enumerate(fields):
        fid = f"field_{attr_id}_{i}"
        if editable:
            components.append(_text_field(fid, lab, p, input_type=input_type, placeholder=placeholder))
        else:
            raw = str(initial.get(attr_id, "") or "")
            components.append(_text_component(fid, _readonly_field_text(label=lab, attr_id=attr_id, raw_value=raw), "body"))
        err_msg = fe.get(attr_id)
        if err_msg:
            components.append(
                _text_component(f"err_{attr_id}_{i}", f"错误：{err_msg}", "body"),
            )

    components.extend(
        [
            _text_component("submit_lbl", "提交", "h3"),
            _button_submit("submit_btn", "submit_lbl", action_name, paths_for_button),
            _column("submit_btn_wrap", ["submit_btn"], alignment="stretch"),
        ]
    )
    col = _column(root, children, alignment="stretch")

    user_map: list[dict[str, Any]] = []
    for attr_id, _label, rel_path, _input_type, _placeholder, _editable in fields:
        key = rel_path.rsplit("/", 1)[-1]
        val = str(initial.get(attr_id, "") or "")
        user_map.append({"key": key, "valueString": val})
    # 提交路径可能包含只读字段：确保 valueMap 含所有 submit_paths 键
    seen = {entry["key"] for entry in user_map}
    for attr_id, rel_path in paths_for_button:
        key = rel_path.rsplit("/", 1)[-1]
        if key in seen:
            continue
        val = str(initial.get(attr_id, "") or "")
        user_map.append({"key": key, "valueString": val})
        seen.add(key)

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


def build_flow_done_messages(
    *,
    outcome: str,
    terminal_message: str,
    attrs: dict[str, Any],
    property_labels: dict[str, str],
    ordered_property_keys: list[str],
) -> list[dict[str, Any]]:
    """
    流程结束只读摘要：标签来自本体 property_labels，字段顺序为 objectTypes 声明顺序，
    其余 attrs 键按字母序追加（与前端写死列表无关）。
    """
    oc = (outcome or "").strip()
    tm = (terminal_message or "").strip()
    if oc == "approved":
        headline = "办理结果：已通过"
    elif oc == "denied":
        headline = "办理结果：未通过"
    elif not oc:
        headline = "流程已结束"
    else:
        headline = f"流程已结束（{oc}）"

    keys_seen: set[str] = set()
    row_keys: list[str] = []
    for k in ordered_property_keys:
        if k not in attrs:
            continue
        if not str(attrs.get(k, "")).strip():
            continue
        row_keys.append(k)
        keys_seen.add(k)
    for k in sorted(attrs.keys()):
        if k in keys_seen:
            continue
        if not str(attrs.get(k, "")).strip():
            continue
        row_keys.append(k)

    root = "flow_done_root"
    children: list[str] = ["fd_head"]
    components: list[dict[str, Any]] = [
        _text_component("fd_head", headline, "h2"),
    ]
    if tm:
        children.append("fd_msg")
        components.append(_text_component("fd_msg", tm, "body"))

    for i, key in enumerate(row_keys):
        lab = property_labels.get(key, key)
        raw = str(attrs.get(key, "") or "")
        cid = f"fd_attr_{i}"
        children.append(cid)
        components.append(
            _text_component(
                cid,
                _readonly_field_text(label=lab, attr_id=key, raw_value=raw),
                "body",
            )
        )

    children.append("fd_foot")
    components.append(
        _text_component("fd_foot", "流程已结束。如需重新办理，请点击「重新开始」。", "body"),
    )
    components.append(_column(root, children, alignment="stretch"))

    return [
        {"surfaceUpdate": {"surfaceId": SURFACE_ID, "components": components}},
        {"beginRendering": {"surfaceId": SURFACE_ID, "root": root}},
    ]


def schema_to_a2ui_messages(
    schema: dict[str, Any],
    *,
    initial_attrs: dict[str, Any] | None = None,
    missing_keys: list[str] | None = None,
    validation_errors: list[dict[str, Any]] | None = None,
    interrupt_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    kind = schema.get("kind")
    if kind == "user_input":
        title = str(schema.get("title") or "请补全信息")
        action_name = str(schema.get("actionName") or "submit_collect")
        assistant_text = str(schema.get("assistantText") or "").strip() or None
        if interrupt_payload is not None:
            ve_for_ui = validation_errors_for_ui(interrupt_payload)
        else:
            ve_for_ui = list(validation_errors or [])
        show_llm_errors = interrupt_payload is None or should_show_validation_error_details(interrupt_payload)
        assistant_text = merge_assistant_with_validation(assistant_text, ve_for_ui)
        raw_fields = list(schema.get("fields") or [])
        missing_set = set(missing_keys) if missing_keys is not None else None
        llm_field_err: dict[str, str] = {}
        fields: list[tuple[str, str, str, str, str | None, bool]] = []
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
            editable = True if missing_set is None else field_id in missing_set
            fields.append((field_id, label, path, input_type, placeholder, editable))
            fe = str(item.get("fieldError") or "").strip()
            if fe and show_llm_errors:
                llm_field_err[field_id] = fe
        if not fields:
            raise ValueError("schema user_input has no valid fields")
        merged_err = merge_field_errors_for_collect(
            server_validation_errors=ve_for_ui,
            per_field_from_llm=llm_field_err,
        )
        return build_collect_form_messages(
            title=title,
            fields=fields,
            action_name=action_name,
            initial_attrs=initial_attrs,
            assistant_text=assistant_text,
            field_errors=merged_err or None,
        )
    raise ValueError(f"unknown schema kind: {kind}")


def intent_to_a2ui_messages(
    intent: dict[str, Any],
    *,
    initial_attrs: dict[str, Any] | None = None,
    missing_keys: list[str] | None = None,
    validation_errors: list[dict[str, Any]] | None = None,
    interrupt_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Compile normalized uiIntent into deterministic A2UI messages.
    Normalized intent shape:
    {
      "kind": "collect_form",
      "title": "...",
      "assistantText": "...",
      "actionName": "submit_collect",
      "fields": [{"fieldId","label","path","inputType","placeholder","editable"}],
      "submitFields": ["..."]
    }
    """
    kind = str(intent.get("kind") or "").strip()
    if kind != "collect_form":
        raise ValueError(f"unknown intent kind: {kind}")
    title = str(intent.get("title") or "请补全信息")
    action_name = str(intent.get("actionName") or "submit_collect")
    assistant_text = str(intent.get("assistantText") or "").strip() or None
    if interrupt_payload is not None:
        ve_for_ui = validation_errors_for_ui(interrupt_payload)
    else:
        ve_for_ui = list(validation_errors or [])
    show_llm_errors = interrupt_payload is None or should_show_validation_error_details(interrupt_payload)
    assistant_text = merge_assistant_with_validation(assistant_text, ve_for_ui)
    raw_fields = list(intent.get("fields") or [])
    missing_set = set(missing_keys) if missing_keys is not None else None

    llm_field_err: dict[str, str] = {}
    fields: list[tuple[str, str, str, str, str | None, bool]] = []
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
        editable_from_intent = bool(item.get("editable", False))
        editable = editable_from_intent
        if missing_set is not None:
            editable = field_id in missing_set
        fields.append((field_id, label, path, input_type, placeholder, editable))
        fe = str(item.get("fieldError") or "").strip()
        if fe and show_llm_errors:
            llm_field_err[field_id] = fe
    if not fields:
        raise ValueError("intent collect_form has no valid fields")

    submit_fields = [str(x).strip() for x in list(intent.get("submitFields") or []) if str(x).strip()]
    submit_field_set = set(submit_fields)
    if submit_field_set:
        submit_paths = [(attr_id, p) for attr_id, _lab, p, _it, _ph, _ed in fields if attr_id in submit_field_set]
        if not submit_paths:
            submit_paths = [(attr_id, p) for attr_id, _lab, p, _it, _ph, _ed in fields]
    else:
        submit_paths = [(attr_id, p) for attr_id, _lab, p, _it, _ph, _ed in fields]

    merged_err = merge_field_errors_for_collect(
        server_validation_errors=ve_for_ui,
        per_field_from_llm=llm_field_err,
    )
    return build_collect_form_messages(
        title=title,
        fields=fields,
        action_name=action_name,
        initial_attrs=initial_attrs,
        assistant_text=assistant_text,
        submit_paths=submit_paths,
        field_errors=merged_err or None,
    )


def collect_editable_field_keys_for_user_input(interrupt_payload: dict[str, Any]) -> list[str]:
    """
    可编辑字段 = missing（未填）∪ 本步采集字段上仍有校验错误的 path。
    仅 missing 时：校验失败但已填的字段会被标成只读，用户无法改正。
    """
    missing = list(interrupt_payload.get("missing") or [])
    collect_field_names = list(interrupt_payload.get("collect_field_names") or [])
    collect_set = set(collect_field_names)
    prop_order: list[str] = list(interrupt_payload.get("property_api_names") or missing)
    if not prop_order:
        prop_order = list(missing)
    errs = interrupt_payload.get("validationErrors") or []
    paths: set[str] = set()
    for e in errs:
        if isinstance(e, dict) and e.get("path"):
            paths.add(str(e["path"]))
    if collect_set:
        invalid = paths & collect_set
    else:
        invalid = paths & set(prop_order)
    seen: set[str] = set()
    ordered: list[str] = []
    for k in missing:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    for k in prop_order:
        if k in invalid and k not in seen:
            seen.add(k)
            ordered.append(k)
    for k in invalid:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered


def interrupt_to_a2ui_messages(interrupt_payload: dict[str, Any]) -> list[dict[str, Any]]:
    kind = interrupt_payload.get("kind")
    if kind == "user_input":
        editable_keys = collect_editable_field_keys_for_user_input(interrupt_payload)
        editable_set = set(editable_keys)
        labels: dict[str, str] = dict(interrupt_payload.get("labels") or {})
        title = str(interrupt_payload.get("title") or "请补全信息")
        attrs = dict(interrupt_payload.get("attrs") or {})
        prop_order: list[str] = list(interrupt_payload.get("property_api_names") or editable_keys)
        if not prop_order:
            prop_order = list(editable_keys)

        fields: list[tuple[str, str, str, str, str | None, bool]] = []
        for m in prop_order:
            path = f"/user/{m}"
            lab = labels.get(m, m)
            fields.append((m, lab, path, "shortText", None, m in editable_set))

        submit_paths = [(k, f"/user/{k}") for k in prop_order]
        ve = validation_errors_for_ui(interrupt_payload)
        assistant = merge_assistant_with_validation(None, ve)
        merged_err = merge_field_errors_for_collect(
            server_validation_errors=ve,
            per_field_from_llm=None,
        )
        return build_collect_form_messages(
            title=title,
            fields=fields,
            initial_attrs=attrs,
            submit_paths=submit_paths,
            assistant_text=assistant,
            field_errors=merged_err or None,
        )
    if kind == "action":
        title = str(interrupt_payload.get("title") or "请完成核验")
        action = str(interrupt_payload.get("action_name") or "action")
        root = "action_col"
        components = [
            _text_component("action_title", title, "h2"),
            _text_component("action_hint", "点击下方按钮模拟人脸识别通过。", "body"),
            _text_component("btn_lbl", "已完成识别", "h3"),
            _button_submit(
                "action_btn",
                "btn_lbl",
                f"{action}_confirm",
                [],
            ),
            _column(root, ["action_title", "action_hint", "action_btn"], alignment="stretch"),
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
