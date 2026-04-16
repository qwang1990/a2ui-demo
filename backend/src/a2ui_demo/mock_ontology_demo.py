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
    "mockApplicantQueryEndpoint": "/api/mock-ontology/applicant/query/{fullName}/{idNumber}",
    "mockUserFlagsByUserIdEndpoint": "/api/mock-ontology/user/{userId}/flags",
    "ruleSummary": "开始采集姓名+身份证后，依次用 applicant/query 同源 Mock 判断「已持民生卡」「山姆会员」（均为 HTTP 分支，无单独查询节点）。",
    "flagRules": MOCK_USER_FLAG_RULES,
    "exampleProfiles": [
        {
            "label": "主流程可继续（两标志均为 false）",
            "fullName": "张三",
            "idNumber": "110101199001011234",
            "expectedFlags": {"is_sams_member": False, "has_ms_credit_card": False},
        },
        {
            "label": "山姆会员 → 持民生卡为 false 后山姆 logic 为 true → 不予开卡",
            "fullName": "李四",
            "idNumber": "11010119900101SAMS_MEMBER234",
            "expectedFlags": {"is_sams_member": True, "has_ms_credit_card": False},
        },
        {
            "label": "已持民生卡 → 首条 logic 为 true → 不予开卡",
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
