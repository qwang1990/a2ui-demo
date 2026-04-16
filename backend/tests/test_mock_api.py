from __future__ import annotations

from fastapi.testclient import TestClient

from a2ui_demo.main import app


def test_mock_ontology_flags() -> None:
    c = TestClient(app)
    r = c.get("/api/mock-ontology/user/plain")
    assert r.status_code == 200
    assert r.json() == {"is_sams_member": False, "has_ms_credit_card": False}
    r2 = c.get("/api/mock-ontology/user/xxSAMS_MEMBERyy")
    assert r2.json()["is_sams_member"] is True
    r3 = c.get("/api/mock-ontology/user/HAS_MS_here")
    assert r3.json()["has_ms_credit_card"] is True

    r4 = c.get("/api/mock-ontology/applicant/query/张三/110101199001011234")
    assert r4.status_code == 200
    assert r4.json()["found"] is True
    assert r4.json()["userId"] == "U1001"

    r5 = c.get("/api/mock-ontology/user/U1003_MS/flags")
    assert r5.status_code == 200
    assert r5.json()["has_ms_credit_card"] is True


def test_abox_list_endpoint() -> None:
    c = TestClient(app)
    r = c.get("/api/mock-ontology/abox/ApplicantUser")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 5
    names = [i["fullName"] for i in data["instances"]]
    assert "张三" in names


def test_abox_query_found() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/mock-ontology/abox/ApplicantUser/query",
        json={"filter": {"fullName": "张三", "idNumber": "110101199001011234"}, "returnKeys": ["userId"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["found"] is True
    assert data["instances"][0]["userId"] == "U1001"


def test_abox_query_not_found() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/mock-ontology/abox/ApplicantUser/query",
        json={"filter": {"fullName": "不存在"}},
    )
    assert r.status_code == 200
    assert r.json()["found"] is False


def test_abox_unknown_type() -> None:
    c = TestClient(app)
    r = c.get("/api/mock-ontology/abox/UnknownType")
    assert r.status_code == 200
    assert r.json()["count"] == 0
