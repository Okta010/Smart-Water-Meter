
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db import Customer, Officer, Reading
from app.security import hash_password


# =========================================================
# FIXTURE: DATABASE KHUSUS UNTUK PENGUJIAN
# =========================================================

@pytest.fixture
def client(tmp_path):
    # Setiap pengujian menggunakan database terpisah.
    db_file = (tmp_path / "test_swm.db").as_posix()
    database_url = f"sqlite:///{db_file}"

    app = create_app(database_url)

    db = app.state.db_factory()

    try:
        # PLG001 belum mempunyai akun.
        customer1 = Customer(
            customer_id="PLG001",
            meter_number="MTR-001",
            name="Ahmad Fauzi",
            address="Jl. Melati No. 12, Bandar Lampung",
            password_hash=None,
        )

        # PLG002 sudah mempunyai akun untuk pengujian login.
        customer2 = Customer(
            customer_id="PLG002",
            meter_number="MTR-002",
            name="Siti Rahma",
            address="Jl. Kenanga No. 8, Bandar Lampung",
            password_hash=hash_password("SitiTest123!"),
        )

        officer = Officer(
            officer_id="ADM001",
            name="Petugas PDAM Demo",
            password_hash=hash_password("AdminTest123!"),
        )

        db.add_all([customer1, customer2, officer])

        # Data simulasi untuk menguji riwayat dan anomali.
        db.add_all([
            Reading(
                customer_id="PLG002",
                measured_at=datetime(2026, 10, 25, 9, 0),
                meter_value=100.0,
                daily_usage=0.55,
            ),
            Reading(
                customer_id="PLG002",
                measured_at=datetime(2026, 10, 26, 9, 0),
                meter_value=100.6,
                daily_usage=0.6,
            ),
            Reading(
                customer_id="PLG002",
                measured_at=datetime(2026, 10, 29, 5, 40),
                meter_value=120.249,
                daily_usage=19.649,
            ),
        ])

        db.commit()
    finally:
        db.close()

    with TestClient(app) as test_client:
        yield test_client

    app.state.engine.dispose()


def login_as(client, identifier, password):
    """Login melalui API utama dan periksa hasilnya."""
    response = client.post(
        "/api/login",
        json={
            "identifier": identifier,
            "password": password,
        },
    )

    assert response.status_code == 200, response.text
    return response


# =========================================================
# 1. HEALTH CHECK DAN CORS
# =========================================================

def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_preflight(client):
    response = client.options(
        "/api/register",
        headers={
            "Origin": "http://127.0.0.1:5501",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://127.0.0.1:5501"
    )
    assert (
        response.headers.get("access-control-allow-credentials")
        == "true"
    )


# =========================================================
# 2. REGISTRASI PELANGGAN
# =========================================================

def test_registration_success(client):
    response = client.post(
        "/api/register",
        json={
            "id_pelanggan": "PLG001",
            "nomor_meter": "MTR-001",
            "nama": "Ahmad Fauzi",
            "alamat": "Jl. Melati No. 12, Bandar Lampung",
            "password": "AhmadTest123!",
        },
    )

    assert response.status_code == 201
    assert "message" in response.json()

    # Pastikan akun yang baru dibuat dapat login.
    login_response = client.post(
        "/api/login",
        json={
            "identifier": "PLG001",
            "password": "AhmadTest123!",
        },
    )

    assert login_response.status_code == 200
    assert login_response.json()["role"] == "pelanggan"


def test_registration_unknown_customer(client):
    response = client.post(
        "/api/register",
        json={
            "id_pelanggan": "PLG999",
            "nomor_meter": "MTR-999",
            "nama": "Pelanggan Tidak Terdaftar",
            "alamat": "Alamat Uji",
            "password": "Password123!",
        },
    )

    assert response.status_code == 404


def test_registration_wrong_identity(client):
    response = client.post(
        "/api/register",
        json={
            "id_pelanggan": "PLG001",
            "nomor_meter": "MTR-001",
            "nama": "Nama Tidak Sesuai",
            "alamat": "Jl. Melati No. 12, Bandar Lampung",
            "password": "Password123!",
        },
    )

    assert response.status_code == 400


def test_registration_duplicate_account(client):
    payload = {
        "id_pelanggan": "PLG001",
        "nomor_meter": "MTR-001",
        "nama": "Ahmad Fauzi",
        "alamat": "Jl. Melati No. 12, Bandar Lampung",
        "password": "AhmadTest123!",
    }

    first = client.post("/api/register", json=payload)
    second = client.post("/api/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


# =========================================================
# 3. LOGIN, SESSION, DAN LOGOUT
# =========================================================

def test_customer_login(client):
    response = login_as(client, "PLG002", "SitiTest123!")

    assert response.json()["id"] == "PLG002"
    assert response.json()["role"] == "pelanggan"

    me_response = client.get("/api/me")

    assert me_response.status_code == 200
    assert me_response.json()["id"] == "PLG002"


def test_officer_login(client):
    response = login_as(client, "ADM001", "AdminTest123!")

    assert response.json()["id"] == "ADM001"
    assert response.json()["role"] == "pdam"


def test_wrong_password(client):
    response = client.post(
        "/api/login",
        json={
            "identifier": "PLG002",
            "password": "PasswordSalah123!",
        },
    )

    assert response.status_code == 401


def test_logout_invalidates_session(client):
    login_as(client, "PLG002", "SitiTest123!")

    logout_response = client.post("/api/logout")

    assert logout_response.status_code == 200

    me_response = client.get("/api/me")

    assert me_response.status_code == 401


def test_protected_endpoint_requires_login(client):
    response = client.get("/api/pelanggan")

    assert response.status_code == 401


# =========================================================
# 4. HAK AKSES DAN DATA PELANGGAN
# =========================================================

def test_customer_only_sees_own_data(client):
    login_as(client, "PLG002", "SitiTest123!")

    response = client.get("/api/pelanggan")

    assert response.status_code == 200

    customers = response.json()

    assert len(customers) == 1
    assert customers[0]["id"] == "PLG002"


def test_officer_can_see_all_customers(client):
    login_as(client, "ADM001", "AdminTest123!")

    response = client.get("/api/pelanggan")

    assert response.status_code == 200

    customer_ids = {
        customer["id"] for customer in response.json()
    }

    assert customer_ids == {"PLG001", "PLG002"}


def test_customer_can_view_own_history(client):
    login_as(client, "PLG002", "SitiTest123!")

    response = client.get("/api/riwayat")

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_customer_cannot_submit_manual_reading(client):
    login_as(client, "PLG002", "SitiTest123!")

    response = client.post(
        "/api/readings",
        json={
            "id_pelanggan": "PLG002",
            "meter": 121.0,
            "waktu": "2026-10-30T09:00:00",
        },
    )

    assert response.status_code == 403


# =========================================================
# 5. PEMBACAAN METER DAN DETEKSI ANOMALI
# =========================================================

def test_officer_can_save_manual_reading(client):
    login_as(client, "ADM001", "AdminTest123!")

    response = client.post(
        "/api/readings",
        json={
            "id_pelanggan": "PLG001",
            "meter": 100.0,
            "waktu": "2026-10-30T09:00:00",
        },
    )

    assert response.status_code == 201
    assert response.json()["pemakaian"] == 0.0


def test_meter_value_cannot_decrease(client):
    login_as(client, "ADM001", "AdminTest123!")

    response = client.post(
        "/api/readings",
        json={
            "id_pelanggan": "PLG002",
            "meter": 120.0,
            "waktu": "2026-10-30T09:00:00",
        },
    )

    assert response.status_code == 422


def test_customer_usage_spike_is_flagged(client):
    login_as(client, "ADM001", "AdminTest123!")

    response = client.get("/api/pelanggan")

    assert response.status_code == 200

    siti = next(
        customer
        for customer in response.json()
        if customer["id"] == "PLG002"
    )

    assert siti["status"] == "anomali"
    assert siti["hariIni"] == pytest.approx(19.649)


# =========================================================
# 6. HALAMAN LOGIN PORTAL PDAM
# =========================================================

def test_pdam_login_page_available(client):
    response = client.get("/pdam/login")

    assert response.status_code == 200
    assert "html" in response.headers.get(
        "content-type", ""
    ).lower()
