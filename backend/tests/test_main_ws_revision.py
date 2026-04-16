from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from a2ui_demo.main import app


def _recv_until(ws: Any, target_type: str) -> dict[str, Any]:
    for _ in range(12):
        msg = ws.receive_json()
        if msg.get("type") == target_type:
            return msg
    raise AssertionError(f"did not receive message type={target_type}")


def test_ws_resume_keeps_pinned_ontology_revision(monkeypatch, tmp_path: Path) -> None:
    src = Path(__file__).resolve().parent / "fixtures" / "sam_credit_card_full.json"
    work = tmp_path / "ontology"
    work.mkdir(parents=True, exist_ok=True)
    dst = work / "sam_credit_card.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("ONTOLOGY_DIR", str(work))
    monkeypatch.setenv("ENABLE_LLM_UI_INTENT", "0")
    monkeypatch.setenv("ENABLE_LLM_FORM_SCHEMA", "0")
    monkeypatch.setenv("ENABLE_LLM_FULL_A2UI", "0")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "start_flow",
                    "flow_id": "sam_credit_card",
                    "attrs": {"fullName": "张三", "idNumber": "plain"},
                }
            )
            _ = _recv_until(ws, "flow_progress")
            first_batch = _recv_until(ws, "a2ui_batch")
            thread_id = str(first_batch.get("thread_id") or "")
            first_revision = str(first_batch.get("ontology_revision") or "")
            assert thread_id
            assert first_revision

            payload = json.loads(dst.read_text(encoding="utf-8"))
            payload["nodes"][-1]["message"] = "提交验证-新版"
            r = client.put("/api/ontology/sam_credit_card", json={"raw": json.dumps(payload, ensure_ascii=False)})
            assert r.status_code == 200

            ws.send_json(
                {
                    "type": "resume",
                    "thread_id": thread_id,
                    "payload": {"attrs": {"phone": "13900000000", "age": 25}},
                }
            )
            _ = _recv_until(ws, "flow_progress")
            second_batch = _recv_until(ws, "a2ui_batch")
            assert second_batch.get("ontology_revision") == first_revision
