"""Static demo payloads for mock ontology HTTP; keeps UI and docs in sync."""

from __future__ import annotations

from typing import Any

# GET /api/mock-ontology/user/{id_number} — uppercase id, then substring rules
MOCK_USER_FLAG_RULES: list[dict[str, str]] = [
    {
        "flag": "is_sams_member",
        "when": "身份证号（大写后）包含子串 SAMS_MEMBER",
    },
    {
        "flag": "has_ms_credit_card",
        "when": "身份证号（大写后）包含子串 HAS_MS",
    },
]

MOCK_ONTOLOGY_DEMO_SEEDS: dict[str, Any] = {
    "mockUserEndpoint": "/api/mock-ontology/user/{idNumber}",
    "ruleSummary": "服务端将身份证号转为大写后做子串匹配；两标志均为 false 时可通过前两步 logic。",
    "flagRules": MOCK_USER_FLAG_RULES,
    "exampleProfiles": [
        {
            "label": "主流程可继续（两标志均为 false）",
            "fullName": "张三",
            "idNumber": "110101199001011234",
            "expectedFlags": {"is_sams_member": False, "has_ms_credit_card": False},
        },
        {
            "label": "山姆会员 → 第一步 logic 为 true → 不予开卡",
            "fullName": "李四",
            "idNumber": "11010119900101SAMS_MEMBER234",
            "expectedFlags": {"is_sams_member": True, "has_ms_credit_card": False},
        },
        {
            "label": "已持民生卡 → 第二步 logic 为 true → 不予开卡",
            "fullName": "王五",
            "idNumber": "11010119900101HAS_MS234",
            "expectedFlags": {"is_sams_member": False, "has_ms_credit_card": True},
        },
        {
            "label": "同时含两子串（先被山姆逻辑拦截）",
            "fullName": "赵六",
            "idNumber": "SAMS_MEMBER_HAS_MS",
            "expectedFlags": {"is_sams_member": True, "has_ms_credit_card": True},
        },
    ],
}
