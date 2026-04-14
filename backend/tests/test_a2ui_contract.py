from __future__ import annotations

from a2ui_demo.a2ui_contract import compose_messages_source, normalize_collect_schema, summarize_context_shape


def test_compose_messages_source_with_reason() -> None:
    assert compose_messages_source("template_fallback", "json_parse_error") == "template_fallback:json_parse_error"
    assert compose_messages_source("llm_schema", None) == "llm_schema"


def test_normalize_collect_schema_rewrites_invalid_values() -> None:
    normalized, warnings = normalize_collect_schema(
        {
            "kind": "user_input",
            "title": "补充信息",
            "actionName": "dangerous_action",
            "fields": [
                {
                    "fieldId": "phone",
                    "label": "手机号",
                    "path": "/x/phone",
                    "inputType": "number",
                },
                {"fieldId": "bad-id", "label": "bad", "path": "/user/bad-id"},
            ],
        }
    )
    assert normalized["actionName"] == "submit_collect"
    assert normalized["fields"][0]["path"] == "/user/phone"
    assert normalized["fields"][0]["inputType"] == "shortText"
    assert len(normalized["fields"]) == 1
    assert warnings


def test_summarize_context_shape() -> None:
    shape = summarize_context_shape({"a": " ", "b": "hello", "c": [1, 2], "d": None})
    assert set(shape["keys"]) == {"a", "b", "c", "d"}
    assert "a" in shape["empty_keys"]
    assert "d" in shape["empty_keys"]
    assert shape["value_lengths"]["b"] == 5
    assert shape["value_lengths"]["c"] == 2
