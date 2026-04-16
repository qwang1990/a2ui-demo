from __future__ import annotations

import pytest

from a2ui_demo import main


@pytest.mark.asyncio
async def test_build_a2ui_messages_non_user_input() -> None:
    messages, source, assistant_text, fallback_reason = await main._build_a2ui_messages(
        {"kind": "action", "title": "确认"},
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert messages
    assert source == "template_non_user_input"
    assert assistant_text is None
    assert fallback_reason is None


@pytest.mark.asyncio
async def test_build_a2ui_messages_llm_fallback_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_bundle(*_args, **_kwargs):
        return None, None, None, None, "json_parse_error"

    monkeypatch.setattr(main, "maybe_user_input_ui_bundle", _fake_bundle)
    messages, source, assistant_text, fallback_reason = await main._build_a2ui_messages(
        {"kind": "user_input", "missing": ["phone"], "labels": {"phone": "手机号"}},
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert messages
    assert source == "template_fallback"
    assert assistant_text is None
    assert fallback_reason == "json_parse_error"


@pytest.mark.asyncio
async def test_build_a2ui_messages_llm_schema_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_bundle(*_args, **_kwargs):
        return (
            None,
            {
                "kind": "user_input",
                "title": "补全信息",
                "assistantText": "请补充手机号",
                "actionName": "submit_collect",
                "fields": [
                    {
                        "fieldId": "phone",
                        "label": "手机号",
                        "path": "/user/phone",
                        "inputType": "shortText",
                    }
                ],
            },
            None,
            "请补充手机号",
            None,
        )

    monkeypatch.setattr(main, "maybe_user_input_ui_bundle", _fake_bundle)
    messages, source, assistant_text, fallback_reason = await main._build_a2ui_messages(
        {"kind": "user_input", "attrs": {}, "missing": ["phone"], "labels": {"phone": "手机号"}},
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert len(messages) == 3
    assert source == "llm_schema"
    assert assistant_text == "请补充手机号"
    assert fallback_reason is None


@pytest.mark.asyncio
async def test_build_a2ui_messages_llm_full_a2ui_v08(monkeypatch: pytest.MonkeyPatch) -> None:
    a2ui = [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": [
                    {
                        "id": "r",
                        "component": {"Column": {"children": {"explicitList": ["t"]}}},
                    },
                    {
                        "id": "t",
                        "component": {"Text": {"text": {"literalString": "X"}, "usageHint": "body"}},
                    },
                ],
            }
        },
        {"dataModelUpdate": {"surfaceId": "main", "contents": [{"key": "user", "valueMap": []}]}},
        {"beginRendering": {"surfaceId": "main", "root": "r"}},
    ]

    async def _fake_bundle(*_args, **_kwargs):
        return a2ui, None, None, "助手说明", None

    monkeypatch.setattr(main, "maybe_user_input_ui_bundle", _fake_bundle)
    messages, source, assistant_text, fallback_reason = await main._build_a2ui_messages(
        {"kind": "user_input", "missing": ["phone"], "labels": {"phone": "手机号"}},
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert messages == a2ui
    assert source == "llm_a2ui_v08"
    assert assistant_text == "助手说明"
    assert fallback_reason is None


@pytest.mark.asyncio
async def test_build_a2ui_messages_llm_intent_compiled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_bundle(*_args, **_kwargs):
        return (
            None,
            None,
            {
                "kind": "collect_form",
                "title": "补全信息",
                "assistantText": "请补全手机号",
                "actionName": "submit_collect",
                "fields": [
                    {
                        "fieldId": "fullName",
                        "label": "姓名",
                        "path": "/user/fullName",
                        "inputType": "shortText",
                        "editable": False,
                    },
                    {
                        "fieldId": "phone",
                        "label": "手机号",
                        "path": "/user/phone",
                        "inputType": "shortText",
                        "editable": True,
                    },
                ],
                "submitFields": ["fullName", "phone"],
            },
            "请补全手机号",
            None,
        )

    monkeypatch.setattr(main, "maybe_user_input_ui_bundle", _fake_bundle)
    messages, source, assistant_text, fallback_reason = await main._build_a2ui_messages(
        {
            "kind": "user_input",
            "attrs": {"fullName": "张三"},
            "missing": ["phone"],
            "labels": {"fullName": "姓名", "phone": "手机号"},
            "property_api_names": ["fullName", "phone"],
        },
        request_id="req-1",
        thread_id="th-1",
        flow_id="flow-1",
    )
    assert len(messages) == 3
    assert source == "llm_intent_compiled"
    assert assistant_text == "请补全手机号"
    assert fallback_reason is None
