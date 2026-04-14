from __future__ import annotations

from a2ui_demo.a2ui_v08_messages import (
    coerce_v08_messages_from_llm,
    sanitize_messages_for_transport,
    validate_v08_message_batch,
)


def _minimal_main_surface() -> list[dict]:
    return [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": [
                    {
                        "id": "root_col",
                        "component": {
                            "Column": {"children": {"explicitList": ["title_txt"]}},
                        },
                    },
                    {
                        "id": "title_txt",
                        "component": {
                            "Text": {
                                "text": {"literalString": "Hello"},
                                "usageHint": "h2",
                            }
                        },
                    },
                ],
            }
        },
        {
            "dataModelUpdate": {
                "surfaceId": "main",
                "contents": [{"key": "user", "valueMap": []}],
            }
        },
        {"beginRendering": {"surfaceId": "main", "root": "root_col"}},
    ]


def test_validate_v08_message_batch_ok() -> None:
    msgs, err = validate_v08_message_batch(_minimal_main_surface())
    assert err is None
    assert msgs is not None
    assert len(msgs) == 3


def test_validate_rejects_unknown_component() -> None:
    bad = [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": [
                    {
                        "id": "x",
                        "component": {"NotARealComponent": {}},
                    },
                ],
            }
        },
        {"beginRendering": {"surfaceId": "main", "root": "x"}},
    ]
    msgs, err = validate_v08_message_batch(bad)
    assert msgs is None
    assert err is not None
    assert "unknown_component_type" in err


def test_validate_rejects_missing_begin_rendering_root() -> None:
    bad = [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": [
                    {
                        "id": "a",
                        "component": {"Text": {"text": {"literalString": "x"}, "usageHint": "body"}},
                    },
                ],
            }
        },
        {"beginRendering": {"surfaceId": "main", "root": "missing"}},
    ]
    msgs, err = validate_v08_message_batch(bad)
    assert msgs is None
    assert "beginRendering_root_not_found" in (err or "")


def test_coerce_components_dict_to_array() -> None:
    wrong = [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": {
                    "root_col": {"Column": {"children": {"explicitList": ["t1"]}}},
                    "t1": {"Text": {"text": {"literalString": "Hi"}, "usageHint": "body"}},
                },
            }
        },
        {"dataModelUpdate": {"surfaceId": "main", "contents": [{"key": "user", "valueMap": []}]}},
        {"beginRendering": {"surfaceId": "main", "root": "root_col"}},
    ]
    fixed = coerce_v08_messages_from_llm(wrong)
    ok, err = validate_v08_message_batch(fixed)
    assert err is None, err
    assert ok is not None
    comps = ok[0]["surfaceUpdate"]["components"]
    assert isinstance(comps, list)
    assert {c["id"] for c in comps} == {"root_col", "t1"}


def test_sanitize_textfield_type_alias() -> None:
    raw = [
        {
            "surfaceUpdate": {
                "surfaceId": "main",
                "components": [
                    {
                        "id": "f1",
                        "component": {
                            "TextField": {
                                "label": {"literalString": "L"},
                                "text": {"path": "/user/phone"},
                                "type": "shortText",
                            }
                        },
                    },
                ],
            }
        },
        {"beginRendering": {"surfaceId": "main", "root": "f1"}},
    ]
    ok, _ = validate_v08_message_batch(raw)
    assert ok
    out = sanitize_messages_for_transport(ok)
    tf = out[0]["surfaceUpdate"]["components"][0]["component"]["TextField"]
    assert tf.get("textFieldType") == "shortText"
    assert "type" not in tf
