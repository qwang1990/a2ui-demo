from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from a2ui_demo.a2ui_contract import FallbackReason, normalize_collect_schema
from a2ui_demo.a2ui_v08_catalog import STANDARD_CATALOG_COMPONENT_NAMES
from a2ui_demo.a2ui_v08_messages import (
    coerce_v08_messages_from_llm,
    sanitize_messages_for_transport,
    validate_v08_message_batch,
)
from a2ui_demo.config import llm_form_schema_enabled, llm_full_a2ui_enabled
from a2ui_demo.llm_form_schema import (
    LlmCollectSchema,
    _extract_json,
    get_openrouter_client,
    maybe_collect_form_schema_with_meta,
)
from a2ui_demo.logging_utils import sanitize_attrs_for_log, truncate_json

log = logging.getLogger(__name__)

_CATALOG_LIST = ", ".join(sorted(STANDARD_CATALOG_COMPONENT_NAMES))


def _union_system_prompt() -> str:
    few_shot = (
        "\n【Few-shot — a2uiV08Messages 正确形状（与 google/A2UI v0.8 一致，components 必须是数组）】\n"
        '{"outputKind":"a2uiV08Messages","assistantText":"请补全手机号",'
        '"messages":['
        '{"surfaceUpdate":{"surfaceId":"main","components":['
        '{"id":"root_col","component":{"Column":{"children":{"explicitList":["title_txt","field_phone","submit_wrap"]}}}},'
        '{"id":"title_txt","component":{"Text":{"text":{"literalString":"补充信息"},"usageHint":"h2"}}},'
        '{"id":"field_phone","component":{"TextField":'
        '{"label":{"literalString":"手机号"},"text":{"path":"/user/phone"},"textFieldType":"shortText"}}},'
        '{"id":"submit_lbl","component":{"Text":{"text":{"literalString":"提交"},"usageHint":"body"}}},'
        '{"id":"submit_btn","component":{"Button":'
        '{"child":"submit_lbl","action":{"name":"submit_collect","context":['
        '{"key":"phone","value":{"path":"/user/phone"}}]}}}},'
        '{"id":"submit_wrap","component":{"Column":{"children":{"explicitList":["submit_btn"]}}}}'
        ']}},'
        '{"dataModelUpdate":{"surfaceId":"main","contents":['
        '{"key":"user","valueMap":[{"key":"phone","valueString":""}]}]}},'
        '{"beginRendering":{"surfaceId":"main","root":"root_col"}}'
        "]}\n"
        "错误反例（不要输出）: components 写成 {\"root_col\":{\"Column\":...}} 这种 **对象 map**。\n"
    )
    head = (
        "你是 A2UI v0.8 流程 UI 助手。请只输出一个 JSON 对象，不要 markdown。\n"
        "参考: https://a2ui.org/reference/messages/ ；仓库总览: https://github.com/google/A2UI\n"
        "标准组件目录键名（component 下唯一键）必须是以下之一: "
        f"{_CATALOG_LIST}\n"
        "每条 server 消息对象必须且只能包含以下顶层键之一: "
        "surfaceUpdate | dataModelUpdate | beginRendering | deleteSurface。\n"
        "推荐顺序（同一 surfaceId）: surfaceUpdate(components) → dataModelUpdate(contents) → beginRendering({surfaceId, root})。\n"
        "surfaceUpdate.components 必须是 **JSON 数组**，元素形如 "
        '{"id":"组件id","component":{"Text"|"TextField"|...:{...}}}。\n'
        "TextField 使用 textFieldType，取值: date | longText | number | shortText | obscured（不要使用 type）。\n"
        "数据绑定路径建议 /user/<fieldId>，与提交动作 submit_collect 的 Button.action.context 中的 path 对齐。\n"
    )
    tail = (
        "\n你必须设置 outputKind 为以下之一:\n"
        '1) "a2uiV08Messages" — 优先。字段: assistantText(可选), messages(数组，元素为 v0.8 消息)。\n'
        '2) "collectSchema" — 当你只想输出窄表单 schema 时。字段与旧版一致: '
        '{"kind":"user_input","title","assistantText","actionName","fields":[{fieldId,label,path,inputType,...}]}。\n'
    )
    return head + few_shot + tail


async def maybe_user_input_ui_bundle(
    interrupt_payload: dict[str, Any],
    *,
    timeout_seconds: float = 12.0,
    request_id: str | None = None,
    thread_id: str | None = None,
    flow_id: str | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, str | None, FallbackReason | None]:
    """
    Returns (a2ui_messages, collect_schema, assistant_text, fallback_reason).
    Exactly one of a2ui_messages or collect_schema should be non-None on success.
    """
    if interrupt_payload.get("kind") != "user_input":
        return None, None, None, None

    if not llm_form_schema_enabled() and not llm_full_a2ui_enabled():
        return None, None, None, "llm_disabled"

    if not llm_full_a2ui_enabled():
        schema, reason = await maybe_collect_form_schema_with_meta(
            interrupt_payload,
            timeout_seconds=min(timeout_seconds, 10.0),
            request_id=request_id,
            thread_id=thread_id,
            flow_id=flow_id,
        )
        asst = str(schema.get("assistantText") or "").strip() if schema else None
        return None, schema, asst or None, reason

    client = get_openrouter_client()
    if not client:
        return None, None, None, "llm_client_unavailable"

    missing = list(interrupt_payload.get("missing") or [])
    labels = dict(interrupt_payload.get("labels") or {})
    attrs = sanitize_attrs_for_log(dict(interrupt_payload.get("attrs") or {}))
    title = str(interrupt_payload.get("title") or "请补全信息")
    object_type = str(interrupt_payload.get("objectTypeApiName") or "")
    node_id = str(interrupt_payload.get("node_id") or "")

    sys = SystemMessage(content=_union_system_prompt())
    human = HumanMessage(
        content=(
            f"outputKind 优先选 a2uiV08Messages。\n"
            f"node_id={node_id}; objectTypeApiName={object_type}; title={title}; "
            f"missing={missing}; labels={labels}; attrs_sanitized={attrs}。\n"
            "若输出 a2uiV08Messages: surfaceId 默认用 main；root 必须指向已声明的组件 id。"
        )
    )
    t0 = time.perf_counter()
    try:
        msg = await asyncio.wait_for(client.ainvoke([sys, human]), timeout=timeout_seconds)
    except TimeoutError:
        log.warning(
            "llm user_input union timeout request_id=%s thread_id=%s flow_id=%s node_id=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
        )
        return None, None, None, "llm_timeout"
    except Exception as exc:
        log.warning(
            "llm user_input union failed request_id=%s thread_id=%s flow_id=%s node_id=%s err=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
            exc,
        )
        return None, None, None, "llm_request_error"

    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = getattr(msg, "content", None)
    raw = str(text).strip() if text else ""
    response_metadata = getattr(msg, "response_metadata", None) or {}
    usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    log.info(
        "llm user_input union response request_id=%s thread_id=%s flow_id=%s node_id=%s elapsed_ms=%.1f usage=%s content_preview=%s",
        request_id,
        thread_id,
        flow_id,
        node_id,
        elapsed_ms,
        usage,
        truncate_json(raw, 400),
    )

    payload = _extract_json(raw)
    if not payload:
        return None, None, None, "union_parse_error"

    okind = str(payload.get("outputKind") or payload.get("output_kind") or "").strip().lower()
    if not okind:
        if isinstance(payload.get("messages"), list):
            okind = "a2uiv08messages"
        elif payload.get("kind") == "user_input":
            okind = "collectschema"

    assistant = payload.get("assistantText")
    assistant_str = str(assistant).strip() if assistant else None

    if okind in ("a2uiv08messages", "a2ui_v08_messages"):
        raw_msgs = payload.get("messages")
        if not isinstance(raw_msgs, list):
            log.warning("union a2uiV08Messages missing messages array")
            return None, None, assistant_str, "union_output_kind_invalid"
        coerced = coerce_v08_messages_from_llm(raw_msgs)
        validated, verr = validate_v08_message_batch(coerced)
        if not validated or verr:
            log.warning("union a2ui messages validation failed err=%s", verr)
            return None, None, assistant_str, "a2ui_batch_validate_error"
        safe = sanitize_messages_for_transport(validated)
        return safe, None, assistant_str, None

    if okind in ("collectschema", "collect_schema", "schema"):
        try:
            parsed = LlmCollectSchema.model_validate(payload)
        except ValidationError as exc:
            log.warning("union collectSchema pydantic failed err=%s", exc.errors())
            return None, None, assistant_str, "schema_validate_error"
        normalized, warnings = normalize_collect_schema(parsed.model_dump(by_alias=True, exclude_none=True))
        if warnings:
            log.info(
                "union collectSchema normalized request_id=%s warnings=%s",
                request_id,
                warnings,
            )
        if not normalized.get("fields"):
            return None, None, assistant_str, "schema_no_fields"
        asst2 = str(normalized.get("assistantText") or "").strip() or None
        return None, normalized, asst2, None

    log.warning("union unknown outputKind=%s keys=%s", okind, list(payload.keys()))
    return None, None, assistant_str, "union_output_kind_invalid"
