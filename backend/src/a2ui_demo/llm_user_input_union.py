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
from a2ui_demo.config import llm_form_schema_enabled, llm_full_a2ui_enabled, llm_ui_intent_enabled
from a2ui_demo.llm_form_schema import (
    LlmCollectSchema,
    _extract_json,
    get_openrouter_client,
    maybe_collect_form_schema_with_meta,
)
from a2ui_demo.logging_utils import sanitize_attrs_for_log, truncate_json
from a2ui_demo.ui_intent import normalize_ui_intent_payload

log = logging.getLogger(__name__)

_CATALOG_LIST = ", ".join(sorted(STANDARD_CATALOG_COMPONENT_NAMES))


def _union_system_prompt(*, allow_schema: bool, allow_full_a2ui: bool) -> str:
    few_shot = (
        "\n【Few-shot — outputKind=uiIntent】\n"
        '{"outputKind":"uiIntent","version":"1.0","intent":{"kind":"collect_form","title":"补充信息",'
        '"assistantText":"请补全手机号","actionName":"submit_collect","fields":['
        '{"fieldId":"fullName","label":"姓名","displayMode":"readonly","editable":false},'
        '{"fieldId":"phone","label":"手机号","inputType":"shortText","displayMode":"input","editable":true,"placeholder":"请输入手机号"}'
        '],"submitFields":["fullName","phone"]}}'
        "\n"
        "注意：editable=true 的字段必须来自 missing；其余字段必须 readonly。\n"
    )
    head = (
        "你是 A2UI v0.8 流程 UI 意图规划助手（UI Intent Planner）。请只输出一个 JSON 对象，不要 markdown。\n"
        "参考: https://a2ui.org/reference/messages/ ；仓库总览: https://github.com/google/A2UI\n"
        "默认输出 outputKind=uiIntent，结构如下：\n"
        '{"outputKind":"uiIntent","version":"1.0","intent":{"kind":"collect_form","title":"...",'
        '"assistantText":"...","actionName":"submit_collect","fields":[{"fieldId","label","editable","displayMode","inputType","placeholder"}],'
        '"submitFields":["..."]}}\n'
        "fields 必须覆盖 property_api_names 中每一个字段；missing 中字段 editable=true 且 displayMode=input；"
        "非 missing 字段 editable=false 且 displayMode=readonly。\n"
        "若 validationErrors 非空：assistantText 必须说明原因；对出错字段在对应 field 上设置 fieldError（简短错误文案）。\n"
    )
    options: list[str] = ['1) "uiIntent" — 首选。']
    if allow_schema:
        options.append(
            '2) "collectSchema" — 兼容模式。字段: {"kind":"user_input","title","assistantText","actionName","fields":[...]}。'
        )
    if allow_full_a2ui:
        options.append(
            '3) "a2uiV08Messages" — 仅实验模式。标准组件目录键名仅可使用: '
            f"{_CATALOG_LIST}，每条消息顶层键只能是 surfaceUpdate|dataModelUpdate|beginRendering|deleteSurface。"
        )
    tail = "\n你可用的 outputKind：\n" + "\n".join(options) + "\n"
    return head + few_shot + tail


async def maybe_user_input_ui_bundle(
    interrupt_payload: dict[str, Any],
    *,
    timeout_seconds: float = 12.0,
    request_id: str | None = None,
    thread_id: str | None = None,
    flow_id: str | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, dict[str, Any] | None, str | None, FallbackReason | None]:
    """
    Returns (a2ui_messages, collect_schema, ui_intent, assistant_text, fallback_reason).
    On success, exactly one of a2ui_messages / collect_schema / ui_intent should be non-None.
    """
    if interrupt_payload.get("kind") != "user_input":
        return None, None, None, None, None

    allow_intent = llm_ui_intent_enabled()
    allow_schema = llm_form_schema_enabled()
    allow_full_a2ui = llm_full_a2ui_enabled()
    if not allow_intent and not allow_schema and not allow_full_a2ui:
        return None, None, None, None, "llm_disabled"

    if not allow_intent and not allow_full_a2ui:
        schema, reason = await maybe_collect_form_schema_with_meta(
            interrupt_payload,
            timeout_seconds=min(timeout_seconds, 10.0),
            request_id=request_id,
            thread_id=thread_id,
            flow_id=flow_id,
        )
        asst = str(schema.get("assistantText") or "").strip() if schema else None
        return None, schema, None, asst or None, reason

    client = get_openrouter_client()
    if not client:
        return None, None, None, None, "llm_client_unavailable"

    missing = list(interrupt_payload.get("missing") or [])
    collect_field_names = list(interrupt_payload.get("collect_field_names") or missing)
    display = list(interrupt_payload.get("property_api_names") or missing)
    labels = dict(interrupt_payload.get("labels") or {})
    attrs = sanitize_attrs_for_log(dict(interrupt_payload.get("attrs") or {}))
    title = str(interrupt_payload.get("title") or "请补全信息")
    object_type = str(interrupt_payload.get("objectTypeApiName") or "")
    node_id = str(interrupt_payload.get("node_id") or "")
    constraints = dict(interrupt_payload.get("constraints") or {})
    validation_errors = list(interrupt_payload.get("validationErrors") or [])

    sys = SystemMessage(content=_union_system_prompt(allow_schema=allow_schema, allow_full_a2ui=allow_full_a2ui))
    human = HumanMessage(
        content=(
            "outputKind 优先选 uiIntent。\n"
            f"node_id={node_id}; objectTypeApiName={object_type}; title={title}; "
            f"collect_field_names={collect_field_names}; missing={missing}; "
            f"property_api_names(本体展示顺序)={display}; labels={labels}; attrs_sanitized={attrs}。\n"
            f"字段约束 constraints={constraints}; 当前校验错误 validationErrors={validation_errors}。\n"
            "你必须覆盖 property_api_names 中每个属性。"
            "missing 中字段必须 editable=true；其余字段 editable=false。"
            "validationErrors 非空时：assistantText 概括问题；对 validationErrors 中每个 path，在对应 field 上写 fieldError。"
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
        return None, None, None, None, "llm_timeout"
    except Exception as exc:
        log.warning(
            "llm user_input union failed request_id=%s thread_id=%s flow_id=%s node_id=%s err=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
            exc,
        )
        return None, None, None, None, "llm_request_error"

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
        return None, None, None, None, "union_parse_error"

    okind = str(payload.get("outputKind") or payload.get("output_kind") or "").strip().lower()
    if not okind:
        if isinstance(payload.get("intent"), dict):
            okind = "uiintent"
        elif isinstance(payload.get("messages"), list):
            okind = "a2uiv08messages"
        elif payload.get("kind") == "user_input":
            okind = "collectschema"

    assistant = payload.get("assistantText")
    assistant_str = str(assistant).strip() if assistant else None

    if okind in ("uiintent", "ui_intent"):
        if not allow_intent:
            return None, None, None, assistant_str, "union_output_kind_invalid"
        normalized_intent, warnings, err = normalize_ui_intent_payload(payload, interrupt_payload)
        if warnings:
            log.info(
                "union uiIntent normalized request_id=%s warnings=%s",
                request_id,
                warnings,
            )
        if err:
            return None, None, None, assistant_str, err
        if not normalized_intent:
            return None, None, None, assistant_str, "intent_validate_error"
        asst2 = str(normalized_intent.get("assistantText") or "").strip() or assistant_str
        return None, None, normalized_intent, asst2, None

    if okind in ("a2uiv08messages", "a2ui_v08_messages"):
        if not allow_full_a2ui:
            return None, None, None, assistant_str, "union_output_kind_invalid"
        raw_msgs = payload.get("messages")
        if not isinstance(raw_msgs, list):
            log.warning("union a2uiV08Messages missing messages array")
            return None, None, None, assistant_str, "union_output_kind_invalid"
        coerced = coerce_v08_messages_from_llm(raw_msgs)
        validated, verr = validate_v08_message_batch(coerced)
        if not validated or verr:
            log.warning("union a2ui messages validation failed err=%s", verr)
            return None, None, None, assistant_str, "a2ui_batch_validate_error"
        safe = sanitize_messages_for_transport(validated)
        return safe, None, None, assistant_str, None

    if okind in ("collectschema", "collect_schema", "schema"):
        if not allow_schema:
            return None, None, None, assistant_str, "union_output_kind_invalid"
        try:
            parsed = LlmCollectSchema.model_validate(payload)
        except ValidationError as exc:
            log.warning("union collectSchema pydantic failed err=%s", exc.errors())
            return None, None, None, assistant_str, "schema_validate_error"
        normalized, warnings = normalize_collect_schema(parsed.model_dump(by_alias=True, exclude_none=True))
        if warnings:
            log.info(
                "union collectSchema normalized request_id=%s warnings=%s",
                request_id,
                warnings,
            )
        if not normalized.get("fields"):
            return None, None, None, assistant_str, "schema_no_fields"
        asst2 = str(normalized.get("assistantText") or "").strip() or None
        return None, normalized, None, asst2, None

    log.warning("union unknown outputKind=%s keys=%s", okind, list(payload.keys()))
    return None, None, None, assistant_str, "union_output_kind_invalid"
