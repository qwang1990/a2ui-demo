from __future__ import annotations

import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from a2ui_demo.a2ui_contract import (
    FallbackReason,
    compose_messages_source,
    summarize_context_shape,
)
from a2ui_demo.a2ui_templates import (
    SURFACE_ID as A2UI_SURFACE_ID,
    build_flow_done_messages,
    collect_editable_field_keys_for_user_input,
    intent_to_a2ui_messages,
    interrupt_to_a2ui_messages,
    schema_to_a2ui_messages,
)
from a2ui_demo.config import log_level, ontology_dir
from a2ui_demo.flows.loader import FlowRegistry, load_all_json
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
from a2ui_demo.abox_store import abox_list, abox_query, reload_abox_from_dir
from a2ui_demo.mock_ontology_demo import MOCK_ONTOLOGY_DEMO_SEEDS
from a2ui_demo.ontology_client import OntologyPlatformClient
from a2ui_demo.ontology_models import OntologySpec
from a2ui_demo.ontology_split import has_split_flow, merged_raw_for_api, write_split_from_spec
from a2ui_demo.ontology_validation import validate_ontology_full, validate_user_attrs

log = logging.getLogger(__name__)

_FLOW_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _safe_flow_id(flow_id: str) -> str:
    if not flow_id or not _FLOW_ID_RE.match(flow_id):
        raise HTTPException(status_code=400, detail="invalid flow_id")
    return flow_id


def _ontology_file_path(app: FastAPI, flow_id: str) -> Path:
    _safe_flow_id(flow_id)
    base: Path = app.state.ontology_dir
    path = (base / f"{flow_id}.json").resolve()
    if not str(path).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    return path


def _tbox_file_path(app: FastAPI, ref: str) -> Path:
    _safe_flow_id(ref)
    base: Path = app.state.ontology_dir / "tbox"
    path = (base / f"{ref}.json").resolve()
    if not str(path).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    return path


def _abox_file_path(app: FastAPI, ref: str) -> Path:
    _safe_flow_id(ref)
    base: Path = app.state.ontology_dir / "abox"
    path = (base / f"{ref}.json").resolve()
    if not str(path).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    return path


def _validate_start_attrs(spec: OntologySpec, attrs: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    input_names: list[str] = []
    for inp in spec.aip_logic.inputs:
        input_names.append(inp.attribute_api_name)
        if not inp.required:
            continue
        v = attrs.get(inp.attribute_api_name)
        if v is None or (isinstance(v, str) and not str(v).strip()):
            errors.append(
                {
                    "path": inp.attribute_api_name,
                    "message": f"Missing required attribute: {inp.attribute_api_name}",
                }
            )
    errors.extend(
        validate_user_attrs(
            spec,
            attrs,
            object_type_api_name=None,
            property_api_names=input_names,
        )
    )
    return errors


def _logic_result_text(branch: str | None) -> str | None:
    if branch == "true":
        return "命中"
    if branch == "false":
        return "未命中"
    return None


def _build_progress_business_info(
    *,
    spec: OntologySpec,
    current_node_id: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    node_map = spec.node_by_id()
    node = node_map.get(current_node_id or "")
    if not node:
        return {}
    info: dict[str, Any] = {
        "node_id": node.id,
        "node_kind": node.kind,
    }
    if node.title:
        info["node_title"] = node.title
    if node.kind == "collect":
        labels = spec.property_labels()
        props = list(node.property_api_names or [])
        display = [labels.get(k, k) for k in props]
        if display:
            info["collect_fields"] = display
        if node.object_type_api_name:
            info["object_type"] = node.object_type_api_name
    elif node.kind == "action":
        action = spec.action_by_api_name().get(node.action_ref or "")
        if action:
            info["action_name"] = action.display_name or action.api_name
            if action.description:
                info["action_description"] = action.description
    elif node.kind == "logic":
        logic = spec.logic_by_api_name().get(node.logic_ref or "")
        if logic:
            info["logic_name"] = logic.display_name or logic.api_name
            if logic.description:
                info["logic_description"] = logic.description
        branch = str(result.get("_branch") or "").strip()
        if branch:
            info["logic_result"] = _logic_result_text(branch) or branch
            info["logic_branch"] = branch
            if node.edges:
                nxt = node.edges.true if branch == "true" else node.edges.false
                if nxt:
                    info["next_node_id"] = nxt
    return info


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
    a2ui_msgs, schema, intent, assistant_union, fallback_reason = await maybe_user_input_ui_bundle(
        intr,
        request_id=request_id,
        thread_id=thread_id,
        flow_id=flow_id,
    )
    if a2ui_msgs:
        return a2ui_msgs, "llm_a2ui_v08", assistant_union, None
    if intent:
        try:
            messages = intent_to_a2ui_messages(
                intent,
                initial_attrs=dict(intr.get("attrs") or {}),
                missing_keys=collect_editable_field_keys_for_user_input(intr),
                interrupt_payload=intr,
            )
        except Exception as exc:
            log.warning(
                "intent_to_a2ui_messages failed request_id=%s thread_id=%s flow_id=%s err=%s intent=%s",
                request_id,
                thread_id,
                flow_id,
                exc,
                truncate_json(intent, 300),
            )
            return interrupt_to_a2ui_messages(intr), "template_on_intent_error", None, "intent_to_messages_error"
        assistant_text = str(intent.get("assistantText") or "").strip() or assistant_union
        return messages, "llm_intent_compiled", assistant_text, None
    if not schema:
        return interrupt_to_a2ui_messages(intr), "template_fallback", None, fallback_reason
    try:
        messages = schema_to_a2ui_messages(
            schema,
            initial_attrs=dict(intr.get("attrs") or {}),
            missing_keys=collect_editable_field_keys_for_user_input(intr),
            interrupt_payload=intr,
        )
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
    reload_abox_from_dir(odir)
    log.info("Loaded %d ontology flows from %s", n, odir)
    loaded_flow_ids = sorted(registry.snapshot().keys())
    log.info("loaded_flow_graphs=%s", loaded_flow_ids)

    app.state.ontology_client = client
    app.state.registry = registry
    app.state.sessions = {}
    app.state.ontology_dir = odir
    try:
        yield
    finally:
        pass


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


@app.get("/api/mock-ontology/user/{user_id}/flags")
def mock_ontology_user_flags(user_id: str) -> dict[str, Any]:
    uid = user_id.upper()
    ms = uid.endswith("MS")
    sams = uid.endswith("SAMS")
    return {
        "found": True,
        "userId": user_id,
        "has_ms_credit_card": ms,
        "is_sams_member": sams,
    }


@app.get("/api/mock-ontology/applicant/query/{full_name}/{id_number}")
def mock_ontology_query_applicant(full_name: str, id_number: str) -> dict[str, Any]:
    fid = f"{full_name.strip().upper()}::{id_number.strip().upper()}"
    known = {
        "张三::110101199001011234": {"userId": "U1001", "has_ms_credit_card": False, "is_sams_member": False},
        "李四::11010119900101SAMS_MEMBER234": {"userId": "U1002_SAMS", "has_ms_credit_card": False, "is_sams_member": True},
        "王五::11010119900101HAS_MS234": {"userId": "U1003_MS", "has_ms_credit_card": True, "is_sams_member": False},
    }
    hit = known.get(fid)
    if hit:
        return {"found": True, "fullName": full_name, "idNumber": id_number, **hit}
    uid = f"U_{id_number.strip().upper()}"[:40]
    if "HAS_MS" in uid and not uid.endswith("MS"):
        uid = f"{uid}_MS"
    if "SAMS_MEMBER" in uid and not uid.endswith("SAMS"):
        uid = f"{uid}_SAMS"
    return {
        "found": bool(full_name.strip() and id_number.strip()),
        "fullName": full_name,
        "idNumber": id_number,
        "userId": uid,
        "has_ms_credit_card": "HAS_MS" in id_number.upper(),
        "is_sams_member": "SAMS_MEMBER" in id_number.upper(),
    }


@app.get("/api/mock-ontology/abox/{object_type}")
def mock_abox_list(object_type: str) -> dict[str, Any]:
    """列出某对象类型的全部 ABox 实例。"""
    instances = abox_list(object_type)
    return {"objectType": object_type, "count": len(instances), "instances": instances}


@app.post("/api/mock-ontology/abox/{object_type}/query")
def mock_abox_query(object_type: str, body: Any = Body(...)) -> dict[str, Any]:
    """按属性查询 ABox 实例。

    body: {"filter": {"fullName": "张三", "idNumber": "..."}, "returnKeys": ["userId", "fullName"]}
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    filter_attrs = body.get("filter") or {}
    return_keys = body.get("returnKeys")
    matches = abox_query(object_type, filter_attrs, return_keys)
    return {
        "objectType": object_type,
        "found": len(matches) > 0,
        "count": len(matches),
        "instances": matches,
    }


@app.get("/api/mock-ontology/demo-seeds")
def mock_ontology_demo_seeds() -> dict[str, Any]:
    """演示用姓名+身份证样例及预期 flags，供前端与人工对照。"""
    return dict(MOCK_ONTOLOGY_DEMO_SEEDS)


@app.get("/api/flows")
def list_flows() -> dict[str, Any]:
    reg: FlowRegistry = app.state.registry
    return {"flows": list(reg.snapshot().keys())}


def _coerce_validate_payload(body: Any) -> str | dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("raw"), str):
        return body["raw"]
    return body


@app.post("/api/ontology/validate")
def validate_ontology_endpoint(body: Any = Body(...)) -> dict[str, Any]:
    payload = _coerce_validate_payload(body)
    _spec, errors = validate_ontology_full(payload)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "errors": []}


@app.get("/api/ontology/tbox/{ref}")
def get_ontology_tbox(ref: str) -> dict[str, Any]:
    """只读：返回 ``ontology/tbox/{ref}.json``（Mock，后续可由本体平台对接替换数据源）。"""
    path = _tbox_file_path(app, ref)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="tbox file not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/ontology/abox/{ref}")
def get_ontology_abox(ref: str) -> dict[str, Any]:
    """只读：返回 ``ontology/abox/{ref}.json``（Mock 实例数据）。"""
    path = _abox_file_path(app, ref)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="abox file not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/ontology/{flow_id}")
def get_ontology(flow_id: str) -> dict[str, Any]:
    flow_id = _safe_flow_id(flow_id)
    odir: Path = app.state.ontology_dir
    if has_split_flow(odir, flow_id):
        raw = merged_raw_for_api(odir, flow_id)
        if raw is None:
            raise HTTPException(status_code=500, detail="failed to merge split ontology files")
        return {"flow_id": flow_id, "raw": raw}
    path = _ontology_file_path(app, flow_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="ontology file not found")
    return {"flow_id": flow_id, "raw": path.read_text(encoding="utf-8")}


@app.put("/api/ontology/{flow_id}")
def put_ontology(flow_id: str, body: Any = Body(...)) -> dict[str, Any]:
    flow_id = _safe_flow_id(flow_id)
    odir: Path = app.state.ontology_dir
    path = _ontology_file_path(app, flow_id)
    payload = _coerce_validate_payload(body)
    spec, errors = validate_ontology_full(payload)
    if spec is None or errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "ontology validation failed", "errors": errors or []},
        )
    if spec.aip_logic.id != flow_id:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "aip_logic.id must match URL flow_id",
                "errors": [
                    {
                        "path": "aip_logic.id",
                        "message": f"expected {flow_id!r}, got {spec.aip_logic.id!r}",
                    }
                ],
            },
        )
    if spec.aip_logic_graph:
        spec.nodes = spec.aip_logic_graph.to_ontology_nodes()
    reg: FlowRegistry = app.state.registry
    if has_split_flow(odir, flow_id):
        write_split_from_spec(odir, flow_id, spec)
        raw_reload = merged_raw_for_api(odir, flow_id)
        if raw_reload is None:
            raise HTTPException(status_code=500, detail="failed to merge ontology after split write")
        loaded = reg.load_from_raw(raw_reload, source=f"split:{flow_id}")
    else:
        raw_out = (
            json.dumps(spec.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
            + "\n"
        )
        path.write_text(raw_out, encoding="utf-8")
        loaded = reg.load_file(path)
    if loaded is None:
        raise HTTPException(status_code=500, detail="failed to compile ontology after write")
    reload_abox_from_dir(odir)
    return {"ok": True, "flow_id": spec.aip_logic.id, "errors": []}


async def _send_flow_done(
    ws: WebSocket,
    thread_id: str,
    result: dict[str, Any],
    *,
    request_id: str,
    flow_id: str,
    registry: FlowRegistry,
    compiled_flow: Any | None = None,
) -> None:
    attrs = dict(result.get("attrs") or {})
    a2ui_messages: list[dict[str, Any]] = []
    compiled = compiled_flow or (registry.get(flow_id) if flow_id else None)
    if compiled:
        spec = compiled.spec
        a2ui_messages = build_flow_done_messages(
            outcome=str(result.get("outcome") or ""),
            terminal_message=str(result.get("terminal_message") or ""),
            attrs=attrs,
            property_labels=spec.property_labels(),
            ordered_property_keys=spec.property_api_names_ordered(),
        )
    body: dict[str, Any] = {
        "type": "flow_done",
        "request_id": request_id,
        "thread_id": thread_id,
        "flow_id": flow_id,
        "outcome": result.get("outcome"),
        "message": result.get("terminal_message"),
        "attrs": result.get("attrs"),
        "a2ui_messages": a2ui_messages,
        "surface_id": A2UI_SURFACE_ID,
    }
    log.info(
        "ws send flow_done request_id=%s thread_id=%s outcome=%s attrs=%s a2ui_count=%d",
        request_id,
        thread_id,
        result.get("outcome"),
        sanitize_attrs_for_log(attrs),
        len(a2ui_messages),
    )
    await ws.send_json(body)


async def _send_progress(
    ws: WebSocket,
    thread_id: str,
    result: dict[str, Any],
    spec: OntologySpec,
    *,
    request_id: str,
    interrupt_value: dict[str, Any] | None = None,
    ontology_revision: str | None = None,
) -> None:
    cur = result.get("current_node_id")
    if interrupt_value and interrupt_value.get("node_id"):
        cur = interrupt_value.get("node_id")
    cur_id = str(cur) if cur is not None else None
    business_info = _build_progress_business_info(spec=spec, current_node_id=cur_id, result=result)
    body = {
        "type": "flow_progress",
        "request_id": request_id,
        "thread_id": thread_id,
        "current_node_id": cur_id,
        "step_hint": result.get("step_hint"),
        "business_info": business_info,
        "ontology_revision": ontology_revision,
    }
    log.info(
        "ws send flow_progress request_id=%s thread_id=%s current_node_id=%s has_hint=%s business_keys=%s",
        request_id,
        thread_id,
        cur_id,
        bool(result.get("step_hint")),
        list(business_info.keys()),
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
    ontology_revision: str | None = None,
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
            "ontology_revision": ontology_revision,
        }
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    reg: FlowRegistry = app.state.registry
    sessions: dict[str, dict[str, Any]] = app.state.sessions
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
                start_errs = _validate_start_attrs(compiled.spec, attrs)
                if start_errs:
                    log.warning("start_flow validation failed flow_id=%s errors=%s", flow_id, start_errs)
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "Flow start input validation failed",
                            "errors": start_errs,
                        }
                    )
                    continue
                log.info(
                    "start_flow request_id=%s flow_id=%s attrs=%s",
                    request_id,
                    flow_id,
                    sanitize_attrs_for_log(attrs),
                )
                thread_id, result = await start_flow(compiled, attrs, flow_id)
                revision = compiled.ontology_revision
                sessions[thread_id] = {
                    "flow_id": flow_id,
                    "ontology_revision": revision,
                    "compiled_flow": compiled,
                }
                intr = extract_interrupt_value(result)
                await _send_progress(
                    ws,
                    thread_id,
                    result,
                    compiled.spec,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                    ontology_revision=revision,
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
                        ontology_revision=revision,
                    )
                elif result.get("outcome") is not None:
                    fid = str((sessions.get(thread_id) or {}).get("flow_id") or flow_id or "")
                    done_compiled = (sessions.get(thread_id) or {}).get("compiled_flow")
                    await _send_flow_done(
                        ws,
                        thread_id,
                        result,
                        request_id=request_id,
                        flow_id=fid,
                        registry=reg,
                        compiled_flow=done_compiled,
                    )
                else:
                    log.error("unexpected graph result keys=%s", list(result.keys()))
                    await ws.send_json({"type": "error", "message": "Unexpected graph result", "result": result})
            elif mtype == "resume":
                thread_id = str(msg.get("thread_id") or "")
                session = sessions.get(thread_id) or {}
                flow_id = str(msg.get("flow_id") or session.get("flow_id") or "")
                compiled = session.get("compiled_flow") or reg.get(flow_id)
                revision = str(session.get("ontology_revision") or getattr(compiled, "ontology_revision", ""))
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
                    compiled.spec,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                    ontology_revision=revision or None,
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
                        ontology_revision=revision or None,
                    )
                elif result.get("outcome") is not None:
                    fid = str((sessions.get(thread_id) or {}).get("flow_id") or flow_id or "")
                    done_compiled = (sessions.get(thread_id) or {}).get("compiled_flow")
                    await _send_flow_done(
                        ws,
                        thread_id,
                        result,
                        request_id=request_id,
                        flow_id=fid,
                        registry=reg,
                        compiled_flow=done_compiled,
                    )
                else:
                    log.error("unexpected graph result after resume keys=%s", list(result.keys()))
                    await ws.send_json({"type": "error", "message": "Unexpected graph result", "result": result})
            elif mtype == "a2ui_event":
                thread_id = str(msg.get("thread_id") or "")
                session = sessions.get(thread_id) or {}
                flow_id = str(msg.get("flow_id") or session.get("flow_id") or "")
                compiled = session.get("compiled_flow") or reg.get(flow_id)
                revision = str(session.get("ontology_revision") or getattr(compiled, "ontology_revision", ""))
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
                    compiled.spec,
                    request_id=request_id,
                    interrupt_value=intr if isinstance(intr, dict) else None,
                    ontology_revision=revision or None,
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
                        ontology_revision=revision or None,
                    )
                elif result.get("outcome") is not None:
                    fid = str((sessions.get(thread_id) or {}).get("flow_id") or flow_id or "")
                    done_compiled = (sessions.get(thread_id) or {}).get("compiled_flow")
                    await _send_flow_done(
                        ws,
                        thread_id,
                        result,
                        request_id=request_id,
                        flow_id=fid,
                        registry=reg,
                        compiled_flow=done_compiled,
                    )
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
