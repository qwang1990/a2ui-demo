from __future__ import annotations

from typing import Any

import pytest

from a2ui_demo import llm_form_schema


class _Msg:
    def __init__(self, content: str, response_metadata: dict[str, Any] | None = None) -> None:
        self.content = content
        self.response_metadata = response_metadata or {}


class _FakeClient:
    def __init__(self, content: str, response_metadata: dict[str, Any] | None = None) -> None:
        self._content = content
        self._response_metadata = response_metadata or {}

    async def ainvoke(self, _messages: list[Any]) -> _Msg:
        return _Msg(self._content, self._response_metadata)


@pytest.mark.asyncio
async def test_maybe_collect_form_schema_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_form_schema, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(
        llm_form_schema,
        "_client",
        lambda: _FakeClient(
            '{"kind":"user_input","title":"补充信息","assistantText":"请继续填写","actionName":"submit_collect",'
            '"fields":[{"fieldId":"phone","label":"手机号","path":"/user/phone","inputType":"shortText","required":true}]}'
        ),
    )
    out = await llm_form_schema.maybe_collect_form_schema(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "labels": {"phone": "手机号"},
            "title": "补全信息",
            "attrs": {"fullName": "wq", "idNumber": "123456"},
        }
    )
    assert out is not None
    assert out["actionName"] == "submit_collect"
    assert out["fields"][0]["fieldId"] == "phone"


@pytest.mark.asyncio
async def test_maybe_collect_form_schema_bad_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_form_schema, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_form_schema, "_client", lambda: _FakeClient("not-json"))
    out = await llm_form_schema.maybe_collect_form_schema(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "labels": {"phone": "手机号"},
            "title": "补全信息",
            "attrs": {},
        }
    )
    assert out is None


@pytest.mark.asyncio
async def test_maybe_collect_form_schema_with_meta_returns_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_form_schema, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_form_schema, "_client", lambda: _FakeClient("not-json"))
    out, reason = await llm_form_schema.maybe_collect_form_schema_with_meta(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "labels": {"phone": "手机号"},
            "title": "补全信息",
            "attrs": {},
            "node_id": "collect_phone",
        },
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert out is None
    assert reason == "json_parse_error"


@pytest.mark.asyncio
async def test_maybe_collect_form_schema_with_meta_normalizes_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_form_schema, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(
        llm_form_schema,
        "_client",
        lambda: _FakeClient(
            '{"kind":"user_input","title":"补充信息","assistantText":"请继续填写","actionName":"invalid",'
            '"fields":[{"fieldId":"phone","label":"手机号","path":"/x/phone","inputType":"bad"}]}',
            {"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ),
    )
    out, reason = await llm_form_schema.maybe_collect_form_schema_with_meta(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "labels": {"phone": "手机号"},
            "title": "补全信息",
            "attrs": {},
            "node_id": "collect_phone",
        }
    )
    assert reason is None
    assert out is not None
    assert out["actionName"] == "submit_collect"
    assert out["fields"][0]["path"] == "/user/phone"
    assert out["fields"][0]["inputType"] == "shortText"
