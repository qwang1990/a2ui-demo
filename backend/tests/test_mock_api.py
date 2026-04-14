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
