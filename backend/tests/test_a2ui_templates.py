from __future__ import annotations

from a2ui_demo.a2ui_templates import (
    SURFACE_ID,
    build_collect_form_messages,
    build_flow_done_messages,
    interrupt_to_a2ui_messages,
    schema_to_a2ui_messages,
)


def test_build_collect_form_messages_shape() -> None:
    msgs = build_collect_form_messages(
        title="T",
        fields=[("phone", "手机", "/user/phone", "shortText", None, True)],
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


def test_interrupt_partial_collect_shows_readonly_and_editable() -> None:
    """只缺 phone 时：姓名/身份证为 Text 摘要，手机为 TextField；提交仍带齐三路径。"""
    msgs = interrupt_to_a2ui_messages(
        {
            "kind": "user_input",
            "node_id": "collect_basic",
            "missing": ["phone"],
            "labels": {"fullName": "姓名", "idNumber": "身份证号", "phone": "手机号"},
            "property_api_names": ["fullName", "idNumber", "phone"],
            "title": "请填写三要素",
            "attrs": {"fullName": "张三", "idNumber": "110101199001011234", "phone": ""},
        }
    )
    su = next(m for m in msgs if "surfaceUpdate" in m)["surfaceUpdate"]["components"]
    ids = [c["id"] for c in su]
    assert "field_fullName_0" in ids
    assert "field_idNumber_1" in ids
    assert "field_phone_2" in ids
    ro_fn = next(c for c in su if c["id"] == "field_fullName_0")
    assert "Text" in ro_fn["component"]
    assert "张三" in ro_fn["component"]["Text"]["text"]["literalString"]
    phone_f = next(c for c in su if c["id"] == "field_phone_2")
    assert "TextField" in phone_f["component"]

    btn = next(c for c in su if c["id"] == "submit_btn")
    ctx = btn["component"]["Button"]["action"]["context"]
    keys = [x["key"] for x in ctx]
    assert keys == ["fullName", "idNumber", "phone"]

    dm = next(m for m in msgs if "dataModelUpdate" in m)
    vm = dm["dataModelUpdate"]["contents"][0]["valueMap"]
    keys_dm = sorted(x["key"] for x in vm)
    assert keys_dm == ["fullName", "idNumber", "phone"]


def test_interrupt_action() -> None:
    msgs = interrupt_to_a2ui_messages(
        {"kind": "action", "node_id": "f", "action_name": "face", "title": "人脸"}
    )
    assert any("beginRendering" in m for m in msgs)
    su = next(m for m in msgs if "surfaceUpdate" in m)["surfaceUpdate"]["components"]
    hint = next(c for c in su if c["id"] == "action_hint")
    assert "模拟" in hint["component"]["Text"]["text"]["literalString"]


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


def test_build_flow_done_messages_dynamic_attrs() -> None:
    msgs = build_flow_done_messages(
        outcome="approved",
        terminal_message="提交验证",
        attrs={"fullName": "张三", "age": "13", "idNumber": "110101199001011234"},
        property_labels={"fullName": "姓名", "idNumber": "身份证号", "age": "年龄"},
        ordered_property_keys=["fullName", "idNumber", "phone", "address", "age"],
    )
    assert len(msgs) == 2
    su = next(m for m in msgs if "surfaceUpdate" in m)["surfaceUpdate"]["components"]
    texts = [
        c["component"]["Text"]["text"]["literalString"]
        for c in su
        if "Text" in c.get("component", {})
    ]
    joined = "\n".join(texts)
    assert "办理结果：已通过" in joined
    assert "年龄" in joined and "13" in joined
    assert "姓名" in joined
