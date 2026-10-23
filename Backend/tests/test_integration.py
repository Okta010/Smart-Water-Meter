"""Integration tests use an isolated temporary SQLite database."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import Customer, Officer, Reading
from app.main import create_app
from app.security import hash_password


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'test.sqlite').as_posix()}")
    db = app.state.db_factory()
    db.add_all([
        Customer(customer_id="PLG001", meter_number="MTR-001", name="Ahmad Fauzi",
                 address="Jl. Melati No. 12, Bandar Lampung"),
        Customer(customer_id="PLG002", meter_number="MTR-002", name="Siti Rahma",
                 address="Jl. Kenanga No. 8, Bandar Lampung", password_hash=hash_password("Another-Pass-123")),
        Officer(officer_id="ADM001", name="Operator", password_hash=hash_password("Demo-Staff-123")),
        Reading(customer_id="PLG001", measured_at=datetime(2026, 10, 21, 9), meter_value=127.1, daily_usage=0.5),
        Reading(customer_id="PLG001", measured_at=datetime(2026, 10, 22, 9), meter_value=128.9, daily_usage=1.8),
    ])
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


def register_payload(**changes):
    payload = {
        "id_pelanggan": "PLG001", "nomor_meter": "MTR-001", "nama": "Ahmad Fauzi",
        "alamat": "Jl. Melati No. 12, Bandar Lampung", "password": "Test-Password-123",
    }
    payload.update(changes)
    return payload


def test_health_and_cors(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.options("/api/register", headers={
        "Origin": "http://127.0.0.1:5501", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:5501"


def test_registration_login_me_logout(client):
    assert client.post("/api/register", json=register_payload()).status_code == 201
    assert client.post("/api/register", json=register_payload()).status_code == 409
    login = client.post("/api/login", json={"identifier": "PLG001", "password": "Test-Password-123"})
    assert login.status_code == 200
    assert login.json()["role"] == "pelanggan"
    assert "httponly" in login.headers["set-cookie"].lower()
    assert client.get("/api/me").json()["id"] == "PLG001"
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_registration_validation(client):
    assert client.post("/api/register", json=register_payload(id_pelanggan="NOT_FOUND")).status_code == 404
    assert client.post("/api/register", json=register_payload(nomor_meter="WRONG")).status_code == 400
    assert client.post("/api/register", json=register_payload(password="short")).status_code == 422


def test_customers_are_private(client):
    client.post("/api/register", json=register_payload())
    client.post("/api/login", json={"identifier": "PLG001", "password": "Test-Password-123"})
    people = client.get("/api/pelanggan")
    assert people.status_code == 200
    assert [p["id"] for p in people.json()] == ["PLG001"]
    hist = client.get("/api/riwayat")
    assert hist.status_code == 200
    assert len(hist.json()) == 2
    assert client.post("/api/readings", json={"id_pelanggan": "PLG002", "meter": 200, "waktu": "2026-10-23T09:00:00"}).status_code == 403


def test_officer_access_and_ingest(client):
    assert client.get("/api/pelanggan").status_code == 401
    assert client.post("/api/login", json={"identifier": "ADM001", "password": "Demo-Staff-123"}).status_code == 200
    people = client.get("/api/pelanggan")
    assert people.status_code == 200 and len(people.json()) == 2
    body = {"id_pelanggan": "PLG001", "meter": 130.2, "waktu": "2026-10-23T09:00:00"}
    r = client.post("/api/readings", json=body)
    assert r.status_code == 201
    assert abs(r.json()["pemakaian"] - 1.3) < 0.001
    assert client.post("/api/readings", json=body).status_code == 409
    assert client.get("/api/riwayat").json() == []
