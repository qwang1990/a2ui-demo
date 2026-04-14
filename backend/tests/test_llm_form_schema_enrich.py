from __future__ import annotations

from a2ui_demo.llm_form_schema import enrich_collect_schema_display_fields


def test_enrich_adds_missing_display_fields() -> None:
    schema = {
        "kind": "user_input",
        "title": "T",
        "fields": [
            {
                "fieldId": "address",
                "label": "家庭住址",
                "path": "/user/address",
                "inputType": "shortText",
                "required": True,
            }
        ],
    }
    intr = {
        "property_api_names": ["fullName", "idNumber", "phone", "age", "address"],
        "missing": ["address"],
        "labels": {
            "fullName": "姓名",
            "idNumber": "身份证",
            "phone": "手机",
            "age": "年龄",
            "address": "家庭住址",
        },
    }
    out = enrich_collect_schema_display_fields(schema, intr)
    ids = [f["fieldId"] for f in out["fields"]]
    assert "age" in ids
    assert "address" in ids
