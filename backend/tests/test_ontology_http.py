from __future__ import annotations

from fastapi.testclient import TestClient

from a2ui_demo.main import app


def test_validate_endpoint_ok() -> None:
    with TestClient(app) as client:
        r = client.post("/api/ontology/validate", json={"raw": '{"not": "ontology"}'})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert isinstance(body.get("errors"), list)


def test_get_ontology_sam() -> None:
    with TestClient(app) as client:
        r = client.get("/api/ontology/sam_credit_card")
    assert r.status_code == 200
    data = r.json()
    assert "sam_credit_card" in data.get("raw", "")


def test_get_tbox_and_abox_files() -> None:
    with TestClient(app) as client:
        rt = client.get("/api/ontology/tbox/sam_credit")
        ra = client.get("/api/ontology/abox/sam_credit")
    assert rt.status_code == 200
    assert ra.status_code == 200
    assert "objectTypes" in rt.json()
    assert "ApplicantUser" in ra.json()


def test_demo_seeds() -> None:
    with TestClient(app) as client:
        r = client.get("/api/mock-ontology/demo-seeds")
    assert r.status_code == 200
    body = r.json()
    assert "exampleProfiles" in body
    assert len(body["exampleProfiles"]) >= 1
