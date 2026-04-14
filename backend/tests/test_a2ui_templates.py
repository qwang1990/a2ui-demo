from __future__ import annotations

from a2ui_demo.a2ui_templates import (
    SURFACE_ID,
    build_collect_form_messages,
    interrupt_to_a2ui_messages,
    schema_to_a2ui_messages,
)


def test_build_collect_form_messages_shape() -> None:
    msgs = build_collect_form_messages(
        title="T",
        fields=[("phone", "手机", "/user/phone", "shortText", None)],
        initial_attrs={"phone": "139"},
    )
    assert len(msgs) == 3
    assert "surfaceUpdate" in msgs[0]
    assert "dataModelUpdate" in msgs[1]
    assert "beginRendering" in msgs[2]
    assert msgs[2]["beginRendering"]["surfaceId"] == SURFACE_ID
    assert msgs[2]["beginRendering"]["root"] == "root_col"


def test_interrupt_to_a2ui_user_input() -> None:
    msgs = interrupt_to_a2ui_messages(
        {
            "kind": "user_input",
            "node_id": "n1",
            "missing": ["address"],
            "labels": {"address": "住址"},
            "title": "填写",
            "attrs": {"fullName": "A"},
        }
    )
    assert any("surfaceUpdate" in m for m in msgs)
    dm = next(m for m in msgs if "dataModelUpdate" in m)
    contents = dm["dataModelUpdate"]["contents"]
    assert contents[0]["key"] == "user"
    vm = contents[0]["valueMap"]
    assert any(x["key"] == "address" for x in vm)


def test_interrupt_action() -> None:
    msgs = interrupt_to_a2ui_messages(
        {"kind": "action", "node_id": "f", "action_name": "face", "title": "人脸"}
    )
    assert any("beginRendering" in m for m in msgs)


def test_schema_to_a2ui_messages_user_input() -> None:
    msgs = schema_to_a2ui_messages(
        {
            "kind": "user_input",
            "title": "请补充手机号",
            "assistantText": "为了继续办理，请填写手机号。",
            "actionName": "submit_collect",
            "fields": [
                {
                    "fieldId": "phone",
                    "label": "手机号",
                    "path": "/user/phone",
                    "inputType": "shortText",
                    "required": True,
                    "placeholder": "请输入手机号",
                }
            ],
        },
        initial_attrs={"phone": ""},
    )
    assert len(msgs) == 3
    su = msgs[0]["surfaceUpdate"]["components"]
    assert any(c["id"] == "assistant_txt" for c in su)
    assert any(c["id"] == "field_phone_0" for c in su)
