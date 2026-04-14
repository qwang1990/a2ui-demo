from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from a2ui_demo.a2ui_contract import (
    FallbackReason,
    compose_messages_source,
    summarize_context_shape,
)
from a2ui_demo.a2ui_templates import interrupt_to_a2ui_messages, schema_to_a2ui_messages
from a2ui_demo.config import log_level, ontology_dir
from a2ui_demo.flows.loader import FlowRegistry, load_all_json, start_watcher
from a2ui_demo.flows.runner import (
    extract_interrupt_value,
    resume_flow,
    start_flow,
)
from a2ui_demo.logging_utils import (
    sanitize_attrs_for_log,
    sanitize_payload_for_log,
    truncate_json,
)
from a2ui_demo.llm_user_input_union import maybe_user_input_ui_bundle
from a2ui_demo.ontology_client import OntologyPlatformClient

log = logging.getLogger(__name__)


async def _build_a2ui_messages(
    intr: Any,
    *,
    request_id: str,
    thread_id: str,
    flow_id: str,
) -> tuple[list[dict[str, Any]], str, str | None, FallbackReason | None]:
    if not isinstance(intr, dict):
        return interrupt_to_a2ui_messages({}), "template_unknown", None, None
    if intr.get("kind") != "user_input":
        return interrupt_to_a2ui_messages(intr), "template_non_user_input", None, None
    a2ui_msgs, schema, assistant_union, fallback_reason = await maybe_user_input_ui_bundle(
        intr,
        request_id=request_id,
        thread_id=thread_id,
        flow_id=flow_id,
    )
    if a2ui_msgs:
        return a2ui_msgs, "llm_a2ui_v08", assistant_union, None
    if not schema:
        return interrupt_to_a2ui_messages(intr), "template_fallback", None, fallback_reason
    try:
        messages = schema_to_a2ui_messages(schema, initial_attrs=dict(intr.get("attrs") or {}))
    except Exception as exc:
        log.warning(
            "schema_to_a2ui_messages failed request_id=%s thread_id=%s flow_id=%s err=%s schema=%s",
            request_id,
            thread_id,
            flow_id,
            exc,
            truncate_json(schema, 300),
        )
        return interrupt_to_a2ui_messages(intr), "template_on_schema_error", None, "schema_to_messages_error"
    assistant_text = schema.get("assistantText")
    from_schema = str(assistant_text).strip() if assistant_text else ""
    final_asst = from_schema or assistant_union
    return messages, "llm_schema", final_asst, None


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _configure_logging() -> None:
    level_name = log_level()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    log.info("logging configured level=%s", logging.getLevelName(level))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    base = _public_base_url()
    client = OntologyPlatformClient(base)
    registry = FlowRegistry(client)
    odir = ontology_dir()
    n = load_all_json(odir, registry)
    log.info("Loaded %d ontology flows from %s", n, odir)
    loaded_flow_ids = sorted(registry.snapshot().keys())
    log.info("loaded_flow_graphs=%s", loaded_flow_ids)

    def _broadcast_reload() -> None:
        log.info("ontology directory changed; registry reloaded")

    observer = None
    if not os.environ.get("DISABLE_ONTOLOGY_WATCHER"):
        observer = start_watcher(odir, registry, on_reload=_broadcast_reload)
    app.state.ontology_client = client
    app.state.registry = registry
    app.state.observer = observer
    app.state.sessions = {}
    app.state.ontology_dir = odir
    try:
        yield
    finally:
        obs = getattr(app.state, "observer", None)
        if obs:
            obs.stop()
            obs.join(timeout=2)


app = FastAPI(title="A2UI Ontology Demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(
        ","
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/mock-ontology/user/{id_number}")
def mock_ontology_user(id_number: str) -> dict[str, bool]:
    u = id_number.upper()
    out = {
        "is_sams_member": "SAMS_MEMBER" in u,
        "has_ms_credit_card": "HAS_MS" in u,
    }
    log.info(
        "mock_ontology_user id_len=%d flags=%s",
        len(id_number),
        out,
    )
    return out


@app.get("/api/flows")
def list_flows() -> dict[str, Any]:
    reg: FlowRegistry = app.state.registry
    return {"flows": list(reg.snapshot().keys())}


async def _send_flow_done(
    ws: WebSocket,
    thread_id: str,
    result: dict[str, Any],
    *,
    request_id: str,
) -> None:
    body = {
        "type": "flow_done",
        "request_id": request_id,
        "thread_id": thread_id,
        "outcome": result.get("outcome"),
        "message": result.get("terminal_message"),
        "attrs": result.get("attrs"),
    }
    log.info(
        "ws send flow_done request_id=%s thread_id=%s outcome=%s attrs=%s",
        request_id,
        thread_id,
        result.get("outcome"),
        sanitize_attrs_for_log(dict(result.get("attrs") or {})),
    )
    await ws.send_json(body)


async def _send_progress(
    ws: WebSocket,
    thread_id: str,
    result: dict[str, Any],
    *,
    request_id: str,
    interrupt_value: dict[str, Any] | None = None,
) -> None:
    cur = result.get("current_node_id")
    if interrupt_value and interrupt_value.get("node_id"):
        cur = interrupt_value.get("node_id")
    body = {
        "type": "flow_progress",
        "request_id": request_id,
        "thread_id": thread_id,
        "current_node_id": cur,
        "step_hint": result.get("step_hint"),
    }
    log.info(
        "ws send flow_progress request_id=%s thread_id=%s current_node_id=%s has_hint=%s",
        request_id,
        thread_id,
        cur,
        bool(result.get("step_hint")),
    )
    await ws.send_json(body)


async def _send_a2ui_batch(
    ws: WebSocket,
    *,
    request_id: str,
    thread_id: str,
    flow_id: str,
    intr: Any,
    messages: list[dict[str, Any]],
    source: str,
    assistant_text: str | None,
    fallback_reason: FallbackReason | None,
    reason_tag: str,
) -> None:
    source_with_reason = compose_messages_source(source, fallback_reason)
    log.info(
        "ws send a2ui_batch request_id=%s thread_id=%s flow_id=%s reason=%s messages_count=%d source=%s fallback_reason=%s interrupt=%s",
        request_id,
        thread_id,
        flow_id,
        reason_tag,
        len(messages),
        source_with_reason,
        fallback_reason,
        truncate_json(intr, 500),
    )
    await ws.send_json(
        {
            "type": "a2ui_batch",
            "request_id": request_id,
            "thread_id": thread_id,
            "flow_id": flow_id,
            "messages": messages,
            "interrupt": intr,
            "assistant_text": assistant_text,
            "messages_source": source_with_reason,
            "fallback_reason": fallback_reason,
        }
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    reg: FlowRegistry = app.state.registry
    sessions: dict[str, str] = app.state.sessions
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            request_id = str(msg.get("request_id") or uuid.uuid4())
            log.info("ws recv request_id=%s type=%s keys=%s", request_id, mtype, list(msg.keys()))
            if mtype == "start_flow":
                flow_id = str(msg.get("flow_id") or "")
                compiled = reg.get(flow_id)
                if not compiled:
                    log.warning("unknown flow_id=%s", flow_id)
                    await ws.send_json({"type": "error", "message": f"Unknown flow_id: {flow_id}"})
                    continue
                attrs = dict(msg.get("attrs") or {})
                log.info(
                    "start_flow request_id=%s flow_id=%s attrs=%s",
                    request_id,
                    flow_id,
                    sanitize_attrs_for_log(attrs),
                )
                thread_id, result = await start_flow(compiled, attrs, flow_id)
                sessions[thread_id] = flow_id
                intr = extract_interrupt_value(result)
                await _send_progress(
                    ws,
                    thread_id,
                    result,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                )
                if intr is not None:
                    messages, source, assistant_text, fallback_reason = await _build_a2ui_messages(
                        intr,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                    )
                    await _send_a2ui_batch(
                        ws,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                        intr=intr,
                        messages=messages,
                        source=source,
                        assistant_text=assistant_text,
                        fallback_reason=fallback_reason,
                        reason_tag="start_flow",
                    )
                elif result.get("outcome") is not None:
                    await _send_flow_done(ws, thread_id, result, request_id=request_id)
                else:
                    log.error("unexpected graph result keys=%s", list(result.keys()))
                    await ws.send_json({"type": "error", "message": "Unexpected graph result", "result": result})
            elif mtype == "resume":
                thread_id = str(msg.get("thread_id") or "")
                flow_id = str(msg.get("flow_id") or sessions.get(thread_id) or "")
                compiled = reg.get(flow_id)
                if not compiled:
                    await ws.send_json({"type": "error", "message": "Unknown flow for resume"})
                    continue
                payload = dict(msg.get("payload") or {})
                log.info(
                    "resume request_id=%s thread_id=%s flow_id=%s payload=%s payload_shape=%s",
                    request_id,
                    thread_id,
                    flow_id,
                    sanitize_payload_for_log(payload),
                    summarize_context_shape(payload),
                )
                result = await resume_flow(compiled, thread_id, payload)
                intr = extract_interrupt_value(result)
                await _send_progress(
                    ws,
                    thread_id,
                    result,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                )
                if intr is not None:
                    messages, source, assistant_text, fallback_reason = await _build_a2ui_messages(
                        intr,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                    )
                    await _send_a2ui_batch(
                        ws,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                        intr=intr,
                        messages=messages,
                        source=source,
                        assistant_text=assistant_text,
                        fallback_reason=fallback_reason,
                        reason_tag="resume",
                    )
                elif result.get("outcome") is not None:
                    await _send_flow_done(ws, thread_id, result, request_id=request_id)
                else:
                    log.error("unexpected graph result after resume keys=%s", list(result.keys()))
                    await ws.send_json({"type": "error", "message": "Unexpected graph result", "result": result})
            elif mtype == "a2ui_event":
                thread_id = str(msg.get("thread_id") or "")
                flow_id = str(msg.get("flow_id") or sessions.get(thread_id) or "")
                compiled = reg.get(flow_id)
                if not compiled:
                    await ws.send_json({"type": "error", "message": "Unknown flow for event"})
                    continue
                name = str(msg.get("name") or "")
                ctx = dict(msg.get("context") or {})
                log.info(
                    "a2ui_event request_id=%s thread_id=%s flow_id=%s name=%s context=%s context_shape=%s",
                    request_id,
                    thread_id,
                    flow_id,
                    name,
                    sanitize_attrs_for_log(ctx),
                    summarize_context_shape(ctx),
                )
                resume_payload: dict[str, Any]
                if name == "submit_collect":
                    resume_payload = {"attrs": ctx}
                elif name.endswith("_confirm"):
                    resume_payload = {"confirmed": True}
                else:
                    await ws.send_json({"type": "error", "message": f"Unknown action: {name}"})
                    continue
                result = await resume_flow(compiled, thread_id, resume_payload)
                intr = extract_interrupt_value(result)
                await _send_progress(
                    ws,
                    thread_id,
                    result,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                )
                if intr is not None:
                    messages, source, assistant_text, fallback_reason = await _build_a2ui_messages(
                        intr,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                    )
                    await _send_a2ui_batch(
                        ws,
                        request_id=request_id,
                        thread_id=thread_id,
                        flow_id=flow_id,
                        intr=intr,
                        messages=messages,
                        source=source,
                        assistant_text=assistant_text,
                        fallback_reason=fallback_reason,
                        reason_tag="a2ui_event",
                    )
                elif result.get("outcome") is not None:
                    await _send_flow_done(ws, thread_id, result, request_id=request_id)
                else:
                    log.error("unexpected graph result after event keys=%s", list(result.keys()))
                    await ws.send_json({"type": "error", "message": "Unexpected graph result", "result": result})
            else:
                log.warning("unknown ws message type=%s", mtype)
                await ws.send_json({"type": "error", "message": f"Unknown message type: {mtype}"})
    except WebSocketDisconnect:
        log.info("WebSocket disconnected")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "a2ui_demo.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
