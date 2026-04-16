from __future__ import annotations

from a2ui_demo.ui_intent import normalize_ui_intent_payload


def test_normalize_ui_intent_payload_success() -> None:
    payload = {
        "outputKind": "uiIntent",
        "version": "1.0",
        "intent": {
            "kind": "collect_form",
            "title": "补全信息",
            "assistantText": "请补全手机号",
            "actionName": "submit_collect",
            "fields": [
                {
                    "fieldId": "phone",
                    "label": "手机号",
                    "inputType": "shortText",
                    "editable": True,
                    "displayMode": "input",
                }
            ],
            "submitFields": ["phone"],
        },
    }
    intr = {
        "missing": ["phone"],
        "property_api_names": ["fullName", "phone"],
        "labels": {"fullName": "姓名", "phone": "手机号"},
    }
    normalized, warnings, err = normalize_ui_intent_payload(payload, intr)
    assert err is None
    assert warnings == []
    assert normalized is not None
    assert normalized["kind"] == "collect_form"
    fields = normalized["fields"]
    assert [f["fieldId"] for f in fields] == ["fullName", "phone"]
    assert fields[0]["editable"] is False
    assert fields[1]["editable"] is True
    assert normalized["submitFields"] == ["phone"]


def test_normalize_ui_intent_payload_invalid_action_rewritten() -> None:
    payload = {
        "outputKind": "uiIntent",
        "intent": {
            "kind": "collect_form",
            "actionName": "not_allowed",
            "fields": [{"fieldId": "phone", "label": "手机号"}],
            "submitFields": [],
        },
    }
    intr = {"missing": ["phone"], "property_api_names": ["phone"], "labels": {"phone": "手机号"}}
    normalized, warnings, err = normalize_ui_intent_payload(payload, intr)
    assert err is None
    assert normalized is not None
    assert normalized["actionName"] == "submit_collect"
    assert any(w.startswith("invalid_action:") for w in warnings)


def test_normalize_ui_intent_payload_validation_error_field_editable() -> None:
    """missing 为空但 validationErrors 指向采集字段时，该字段应为 input。"""
    payload = {
        "outputKind": "uiIntent",
        "version": "1.0",
        "intent": {
            "kind": "collect_form",
            "title": "补全",
            "fields": [{"fieldId": "age", "label": "年龄"}],
            "submitFields": ["age"],
        },
    }
    intr = {
        "missing": [],
        "collect_field_names": ["age"],
        "validationErrors": [{"path": "age", "message": "must be an integer"}],
        "property_api_names": ["fullName", "age"],
        "labels": {"fullName": "姓名", "age": "年龄"},
    }
    normalized, warnings, err = normalize_ui_intent_payload(payload, intr)
    assert err is None
    assert normalized is not None
    fields = {f["fieldId"]: f for f in normalized["fields"]}
    assert fields["fullName"]["editable"] is False
    assert fields["age"]["editable"] is True


def test_normalize_ui_intent_payload_no_fields() -> None:
    payload = {"outputKind": "uiIntent", "intent": {"kind": "collect_form", "fields": []}}
    intr = {"missing": [], "property_api_names": []}
    normalized, warnings, err = normalize_ui_intent_payload(payload, intr)
    assert warnings == []
    assert normalized is None
    assert err == "intent_no_fields"
