from __future__ import annotations

from typing import Any

import pytest

from a2ui_demo import llm_user_input_union


class _Msg:
    def __init__(self, content: str, response_metadata: dict[str, Any] | None = None) -> None:
        self.content = content
        self.response_metadata = response_metadata or {}


class _FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, _messages: list[Any]) -> _Msg:
        return _Msg(self._content)


class _CaptureClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.messages: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> _Msg:
        self.messages = messages
        return _Msg(self._content)


@pytest.mark.asyncio
async def test_maybe_user_input_ui_bundle_ui_intent_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_user_input_union, "llm_ui_intent_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_full_a2ui_enabled", lambda: False)
    monkeypatch.setattr(
        llm_user_input_union,
        "get_openrouter_client",
        lambda: _FakeClient(
            '{"outputKind":"uiIntent","version":"1.0","intent":{"kind":"collect_form","title":"补全信息",'
            '"assistantText":"请补全手机号","actionName":"submit_collect","fields":[{"fieldId":"phone","label":"手机号","editable":true}],'
            '"submitFields":["phone"]}}'
        ),
    )
    a2ui_msgs, schema, intent, assistant_text, fallback_reason = await llm_user_input_union.maybe_user_input_ui_bundle(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "property_api_names": ["fullName", "phone"],
            "labels": {"fullName": "姓名", "phone": "手机号"},
            "attrs": {"fullName": "张三"},
        }
    )
    assert a2ui_msgs is None
    assert schema is None
    assert fallback_reason is None
    assert assistant_text == "请补全手机号"
    assert intent is not None
    assert intent["kind"] == "collect_form"
    assert [f["fieldId"] for f in intent["fields"]] == ["fullName", "phone"]


@pytest.mark.asyncio
async def test_maybe_user_input_ui_bundle_reject_full_a2ui_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_user_input_union, "llm_ui_intent_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_full_a2ui_enabled", lambda: False)
    monkeypatch.setattr(
        llm_user_input_union,
        "get_openrouter_client",
        lambda: _FakeClient(
            '{"outputKind":"a2uiV08Messages","messages":[{"beginRendering":{"surfaceId":"main","root":"r"}}]}'
        ),
    )
    out = await llm_user_input_union.maybe_user_input_ui_bundle(
        {"kind": "user_input", "missing": ["phone"], "property_api_names": ["phone"], "labels": {"phone": "手机号"}}
    )
    assert out[4] == "union_output_kind_invalid"


@pytest.mark.asyncio
async def test_maybe_user_input_ui_bundle_schema_compat_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_schema(*_args, **_kwargs):
        return (
            {
                "kind": "user_input",
                "title": "补全信息",
                "assistantText": "请补充手机号",
                "actionName": "submit_collect",
                "fields": [{"fieldId": "phone", "label": "手机号", "path": "/user/phone", "inputType": "shortText"}],
            },
            None,
        )

    monkeypatch.setattr(llm_user_input_union, "llm_ui_intent_enabled", lambda: False)
    monkeypatch.setattr(llm_user_input_union, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_full_a2ui_enabled", lambda: False)
    monkeypatch.setattr(llm_user_input_union, "maybe_collect_form_schema_with_meta", _fake_schema)

    a2ui_msgs, schema, intent, assistant_text, fallback_reason = await llm_user_input_union.maybe_user_input_ui_bundle(
        {"kind": "user_input", "missing": ["phone"], "property_api_names": ["phone"], "labels": {"phone": "手机号"}}
    )
    assert a2ui_msgs is None
    assert intent is None
    assert fallback_reason is None
    assert assistant_text == "请补充手机号"
    assert schema is not None


@pytest.mark.asyncio
async def test_maybe_user_input_ui_bundle_includes_constraints_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _CaptureClient(
        '{"outputKind":"uiIntent","version":"1.0","intent":{"kind":"collect_form","title":"补全信息",'
        '"assistantText":"请补全手机号","actionName":"submit_collect","fields":[{"fieldId":"phone","label":"手机号","editable":true}],'
        '"submitFields":["phone"]}}'
    )
    monkeypatch.setattr(llm_user_input_union, "llm_ui_intent_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_form_schema_enabled", lambda: True)
    monkeypatch.setattr(llm_user_input_union, "llm_full_a2ui_enabled", lambda: False)
    monkeypatch.setattr(llm_user_input_union, "get_openrouter_client", lambda: capture)

    await llm_user_input_union.maybe_user_input_ui_bundle(
        {
            "kind": "user_input",
            "missing": ["phone"],
            "property_api_names": ["phone"],
            "labels": {"phone": "手机号"},
            "constraints": {"phone": {"format": "cn_phone_11"}},
            "validationErrors": [{"path": "phone", "message": "手机号必须为11位数字"}],
        }
    )
    assert capture.messages
    human_text = str(capture.messages[-1].content)
    assert "constraints" in human_text
    assert "validationErrors" in human_text
