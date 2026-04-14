from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from langgraph.types import Command

from a2ui_demo.flows.compiler import CompiledFlow
from a2ui_demo.flows.state import FlowState
from a2ui_demo.logging_utils import (
    log_interrupt_brief,
    sanitize_attrs_for_log,
    truncate_json,
)

log = logging.getLogger(__name__)


def _normalize_langgraph_result(result: dict[str, Any]) -> dict[str, Any]:
    """Align stream output with `invoke` (__interrupt__ as list)."""
    out = dict(result)
    intr = out.get("__interrupt__")
    if isinstance(intr, tuple):
        out["__interrupt__"] = list(intr)
    return out


def _log_stream_update(
    *,
    thread_id: str,
    flow_id: str,
    step: int,
    node_id: str,
    delta: Any,
) -> None:
    if node_id == "__interrupt__":
        intr: Any = None
        if isinstance(delta, tuple) and delta:
            first = delta[0]
            intr = getattr(first, "value", first)
        log.info(
            "graph stream step=%s thread_id=%s flow_id=%s node=%s interrupted=1",
            step,
            thread_id,
            flow_id,
            node_id,
        )
        log_interrupt_brief(log, intr)
        return
    brief: dict[str, Any] = {}
    if isinstance(delta, dict):
        if "current_node_id" in delta:
            brief["current_node_id"] = delta["current_node_id"]
        if "attrs" in delta and isinstance(delta["attrs"], dict):
            brief["attrs"] = sanitize_attrs_for_log(delta["attrs"])
        if "outcome" in delta:
            brief["outcome"] = delta["outcome"]
        if "_branch" in delta:
            brief["_branch"] = delta["_branch"]
        if "terminal_message" in delta:
            brief["terminal_message"] = delta["terminal_message"]
        if not brief:
            brief["keys"] = list(delta.keys())
    log.info(
        "graph stream step=%s thread_id=%s flow_id=%s node=%s state=%s",
        step,
        thread_id,
        flow_id,
        node_id,
        truncate_json(brief, 500),
    )


def _invoke_sync_with_stream_log(
    graph: Any,
    payload: dict[str, Any] | Command,
    config: dict[str, Any],
    *,
    thread_id: str,
    flow_id: str,
) -> dict[str, Any]:
    """Same end state as `invoke`, with per-step updates logged."""
    last_values: dict[str, Any] | None = None
    step = 0
    stream_items = 0
    last_mode: str | None = None
    last_chunk_type: str | None = None
    for item in graph.stream(  # type: ignore[no-untyped-call]
        payload,
        config,
        stream_mode=["updates", "values"],
    ):
        stream_items += 1
        if not isinstance(item, tuple) or len(item) != 2:
            log.debug("graph stream unexpected item type=%s", type(item).__name__)
            continue
        mode, chunk = item[0], item[1]
        last_mode = str(mode)
        last_chunk_type = type(chunk).__name__
        if mode == "values" and isinstance(chunk, dict):
            last_values = chunk
        elif mode == "updates" and isinstance(chunk, dict):
            for node_id, delta in chunk.items():
                step += 1
                _log_stream_update(
                    thread_id=thread_id,
                    flow_id=flow_id,
                    step=step,
                    node_id=str(node_id),
                    delta=delta,
                )
    if last_values is None:
        log.warning(
            "graph stream produced no values chunk; falling back to invoke thread_id=%s flow_id=%s stream_items=%d last_mode=%s last_chunk_type=%s",
            thread_id,
            flow_id,
            stream_items,
            last_mode,
            last_chunk_type,
        )
        return _normalize_langgraph_result(graph.invoke(payload, config))  # type: ignore[no-any-return]
    normalized = _normalize_langgraph_result(last_values)
    attrs = normalized.get("attrs") if isinstance(normalized.get("attrs"), dict) else {}
    log.info(
        "graph final_state thread_id=%s flow_id=%s current_node_id=%s outcome=%s interrupted=%s attrs=%s",
        thread_id,
        flow_id,
        normalized.get("current_node_id"),
        normalized.get("outcome"),
        "__interrupt__" in normalized,
        truncate_json(sanitize_attrs_for_log(attrs), 400),
    )
    return normalized


async def start_flow(
    compiled: CompiledFlow,
    attrs: dict[str, Any],
    flow_id: str,
) -> tuple[str, dict[str, Any]]:
    """Start a new thread; returns (thread_id, result_or_interrupt_payload)."""
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial: FlowState = {"attrs": dict(attrs), "flow_id": flow_id}
    log.info("graph start_flow thread_id=%s flow_id=%s attr_keys=%s", thread_id, flow_id, list(attrs.keys()))
    result = await asyncio.to_thread(
        _invoke_sync_with_stream_log,
        compiled.graph,
        initial,
        config,
        thread_id=thread_id,
        flow_id=flow_id,
    )
    log.info(
        "graph invoke done thread_id=%s result_keys=%s interrupted=%s",
        thread_id,
        list(result.keys()),
        "__interrupt__" in result,
    )
    if "__interrupt__" in result:
        intr = extract_interrupt_value(result)
        log_interrupt_brief(log, intr)
        log.debug("graph raw result snippet=%s", truncate_json(result, 600))
    return thread_id, result


async def resume_flow(
    compiled: CompiledFlow,
    thread_id: str,
    resume_payload: dict[str, Any],
) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    cmd = Command(resume=resume_payload)
    log.info(
        "graph resume thread_id=%s payload_keys=%s",
        thread_id,
        list(resume_payload.keys()),
    )
    log.debug("graph resume payload=%s", truncate_json(resume_payload, 400))
    result = await asyncio.to_thread(
        _invoke_sync_with_stream_log,
        compiled.graph,
        cmd,
        config,
        thread_id=thread_id,
        flow_id=compiled.spec.aip_logic.id,
    )
    log.info(
        "graph resume done thread_id=%s result_keys=%s interrupted=%s outcome=%s",
        thread_id,
        list(result.keys()),
        "__interrupt__" in result,
        result.get("outcome"),
    )
    if "__interrupt__" in result:
        intr = extract_interrupt_value(result)
        log_interrupt_brief(log, intr)
    return result


def extract_interrupt_value(result: dict[str, Any]) -> Any | None:
    """Return the payload passed to interrupt(), or None if not interrupted."""
    items = result.get("__interrupt__")
    if not items:
        return None
    if isinstance(items, (list, tuple)):
        first = items[0]
    else:
        first = items
    return getattr(first, "value", first)
