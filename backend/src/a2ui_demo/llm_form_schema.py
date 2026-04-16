from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from a2ui_demo.a2ui_contract import FallbackReason, normalize_collect_schema
from a2ui_demo.config import (
    llm_form_schema_enabled,
    openrouter_api_key,
    openrouter_app_title,
    openrouter_base_url,
    openrouter_http_referer,
    openrouter_model,
)
from a2ui_demo.logging_utils import sanitize_attrs_for_log, truncate_json

log = logging.getLogger(__name__)


class LlmFormField(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    field_id: str = Field(alias="fieldId")
    label: str
    path: str
    input_type: str = Field("shortText", alias="inputType")
    required: bool = True
    placeholder: str | None = None
    field_error: str | None = Field(
        None,
        alias="fieldError",
        description="当 validationErrors 含该 fieldId 时，填写面向用户的错误说明，展示在输入框下方",
    )


class LlmCollectSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["user_input"] = "user_input"
    title: str
    assistant_text: str | None = Field(None, alias="assistantText")
    action_name: str = Field("submit_collect", alias="actionName")
    fields: list[LlmFormField]


def _openrouter_default_headers() -> dict[str, str] | None:
    h: dict[str, str] = {}
    ref = openrouter_http_referer()
    if ref:
        h["HTTP-Referer"] = ref
    title = openrouter_app_title()
    if title:
        h["X-Title"] = title
    return h or None


def get_openrouter_client() -> ChatOpenAI | None:
    key = openrouter_api_key()
    if not key:
        return None
    headers = _openrouter_default_headers()
    kwargs: dict[str, Any] = {
        "api_key": key,
        "base_url": openrouter_base_url(),
        "model": openrouter_model(),
        "temperature": 0.1,
    }
    if headers:
        kwargs["default_headers"] = headers
    return ChatOpenAI(**kwargs)


def _client() -> ChatOpenAI | None:
    return get_openrouter_client()


def enrich_collect_schema_display_fields(
    schema: dict[str, Any],
    interrupt_payload: dict[str, Any],
) -> dict[str, Any]:
    """LLM 若漏字段，按本体展示顺序补全，避免 collect_detail 只出现 address。"""
    display = list(interrupt_payload.get("property_api_names") or [])
    if not display:
        return schema
    missing = set(interrupt_payload.get("missing") or [])
    labels = dict(interrupt_payload.get("labels") or {})
    fields = list(schema.get("fields") or [])
    seen: set[str] = set()
    for f in fields:
        if isinstance(f, dict) and f.get("fieldId"):
            seen.add(str(f["fieldId"]))
    for key in display:
        if key in seen:
            continue
        fields.append(
            {
                "fieldId": key,
                "label": labels.get(key, key),
                "path": f"/user/{key}",
                "inputType": "shortText",
                "required": key in missing,
            }
        )
    out = dict(schema)
    out["fields"] = fields
    return out


def _extract_json(text: str) -> dict[str, Any] | None:
    s = text.strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    left = s.find("{")
    right = s.rfind("}")
    if left < 0 or right < 0 or right <= left:
        return None
    try:
        obj = json.loads(s[left : right + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def maybe_collect_form_schema(
    interrupt_payload: dict[str, Any],
    *,
    timeout_seconds: float = 8.0,
) -> dict[str, Any] | None:
    schema, _reason = await maybe_collect_form_schema_with_meta(
        interrupt_payload,
        timeout_seconds=timeout_seconds,
    )
    return schema


async def maybe_collect_form_schema_with_meta(
    interrupt_payload: dict[str, Any],
    *,
    timeout_seconds: float = 8.0,
    request_id: str | None = None,
    thread_id: str | None = None,
    flow_id: str | None = None,
) -> tuple[dict[str, Any] | None, FallbackReason | None]:
    """Ask LLM to return collect-form schema JSON; return None when disabled/fail."""
    if interrupt_payload.get("kind") != "user_input":
        return None, None
    if not llm_form_schema_enabled():
        return None, "llm_disabled"
    client = _client()
    if not client:
        return None, "llm_client_unavailable"

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
    sys = SystemMessage(
        content=(
            "你是流程表单设计助手。请仅输出一个 JSON 对象，不要输出 markdown。\n"
            "JSON 结构必须是："
            '{"kind":"user_input","title":"...","assistantText":"...",'
            '"actionName":"submit_collect","fields":[{"fieldId":"phone","label":"手机号",'
            '"path":"/user/phone","inputType":"shortText","required":true,"placeholder":"...","fieldError":"..."}]}'
            "\nfields 必须覆盖「界面展示顺序 property_api_names」中的每一个属性；"
            "对仍缺失的字段设 required=true 并供用户输入；对已出现在已知 attrs 中的字段可设 required=false 表示只读摘要。\n"
            "若 validationErrors 非空：必须在 assistantText 中概括问题；对 validationErrors 里出现的每个 path，"
            "在对应 field 上设置 fieldError 为用户可读的错误原因（与 message 一致或略改写）。"
        )
    )
    human = HumanMessage(
        content=(
            f"业务对象={object_type}; 标题={title}; "
            f"本步负责采集的字段 collect_field_names={collect_field_names}; "
            f"当前仍缺失 missing={missing}; "
            f"界面须展示的本体属性顺序 property_api_names={display}; "
            f"字段标签={labels}; 已知字段(已脱敏)={attrs}; 字段约束 constraints={constraints}; "
            f"当前校验错误 validationErrors={validation_errors}。\n"
            "请为 property_api_names 中每一项生成一条 fields；path 必须是 /user/{fieldId}；"
            "missing 中的项必须可编辑；非 missing 的项用于只读展示已收集信息，不得省略。\n"
            "validationErrors 非空时：assistantText 说明整体情况；每条出错字段必须带 fieldError。"
        )
    )
    t0 = time.perf_counter()
    try:
        msg = await asyncio.wait_for(client.ainvoke([sys, human]), timeout=timeout_seconds)
    except TimeoutError:
        log.warning(
            "llm form schema timeout request_id=%s thread_id=%s flow_id=%s node_id=%s timeout_seconds=%.2f",
            request_id,
            thread_id,
            flow_id,
            node_id,
            timeout_seconds,
        )
        return None, "llm_timeout"
    except Exception as exc:
        log.warning(
            "llm form schema failed request_id=%s thread_id=%s flow_id=%s node_id=%s err=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
            exc,
        )
        return None, "llm_request_error"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = getattr(msg, "content", None)
    raw = str(text).strip() if text else ""
    response_metadata = getattr(msg, "response_metadata", None) or {}
    usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    log.info(
        "llm form schema response request_id=%s thread_id=%s flow_id=%s node_id=%s elapsed_ms=%.1f usage=%s content_preview=%s",
        request_id,
        thread_id,
        flow_id,
        node_id,
        elapsed_ms,
        usage,
        truncate_json(raw, 300),
    )
    payload = _extract_json(raw)
    if not payload:
        log.warning(
            "llm form schema parse failed request_id=%s thread_id=%s flow_id=%s node_id=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
        )
        return None, "json_parse_error"
    try:
        parsed = LlmCollectSchema.model_validate(payload)
    except ValidationError as exc:
        log.warning(
            "llm form schema validation failed request_id=%s thread_id=%s flow_id=%s node_id=%s err=%s payload=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
            exc.errors(),
            truncate_json(payload, 400),
        )
        return None, "schema_validate_error"
    normalized, warnings = normalize_collect_schema(parsed.model_dump(by_alias=True, exclude_none=True))
    if warnings:
        log.info(
            "llm form schema normalized request_id=%s thread_id=%s flow_id=%s node_id=%s warnings=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
            warnings,
        )
    normalized = enrich_collect_schema_display_fields(normalized, interrupt_payload)
    if not normalized.get("fields"):
        log.warning(
            "llm form schema has no fields after normalization request_id=%s thread_id=%s flow_id=%s node_id=%s",
            request_id,
            thread_id,
            flow_id,
            node_id,
        )
        return None, "schema_no_fields"
    return normalized, None
