from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Customer


# ==========================================
# VALIDASI DATA PELANGGAN BARU
# ==========================================

class CustomerCreate(BaseModel):
    id_pelanggan: str = Field(min_length=1, max_length=40)
    nomor_meter: str = Field(min_length=1, max_length=50)
    nama: str = Field(min_length=1, max_length=120)
    alamat: str = Field(min_length=1, max_length=300)

    @field_validator(
        "id_pelanggan", "nomor_meter", "nama", "alamat"
    )
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Kolom wajib tidak boleh kosong")

        return value


# ==========================================
# PORTAL ADMINISTRASI PDAM
# ==========================================

def install_pdam_portal(
    app,
    *,
    db_session,
    identity,
    require_officer,
    summary,
    history,
):
    """
    Menghubungkan halaman dan API petugas
    PDAM ke backend FastAPI yang sudah ada.
    """

    ui_dir = Path(__file__).parent / "pdam_ui"

    # CSS dan JavaScript khusus Admin PDAM
    app.mount(
        "/pdam/assets",
        StaticFiles(directory=str(ui_dir / "assets")),
        name="pdam-assets",
    )

    # ======================================
    # HALAMAN UTAMA BACKEND
    # ======================================

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(
            "/pdam/login",
            status_code=307,
        )

    # ======================================
    # HALAMAN LOGIN PETUGAS
    # ======================================

    @app.get("/pdam/login", include_in_schema=False)
    def pdam_login_page(
        request: Request,
        db: Session = Depends(db_session),
    ):
        try:
            user = identity(request, db)
        except HTTPException:
            user = None

        if user and user["role"] == "pdam":
            return RedirectResponse(
                "/pdam/dashboard",
                status_code=303,
            )

        return FileResponse(
            ui_dir / "login.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    # ======================================
    # HALAMAN DASHBOARD ADMIN PDAM
    # ======================================

    @app.get("/pdam/dashboard", include_in_schema=False)
    def pdam_dashboard_page(
        request: Request,
        db: Session = Depends(db_session),
    ):
        try:
            user = identity(request, db)
        except HTTPException:
            return RedirectResponse(
                "/pdam/login",
                status_code=303,
            )

        if user["role"] != "pdam":
            return HTMLResponse(
                "Halaman hanya untuk Petugas PDAM",
                status_code=403,
            )

        return FileResponse(
            ui_dir / "dashboard.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    # ======================================
    # API DASHBOARD ADMIN
    # ======================================

    @app.get("/api/pdam/dashboard")
    def admin_dashboard(
        officer: dict = Depends(require_officer),
        db: Session = Depends(db_session),
    ):
        customers = list(
            db.scalars(
                select(Customer).order_by(
                    Customer.customer_id
                )
            ).all()
        )

        rows = []

        for customer in customers:
            item = summary(db, customer)
            readings = history(
                db, customer.customer_id
            )

            item["punyaPembacaan"] = bool(readings)
            item["meterTerakhir"] = (
                readings[-1].meter_value
                if readings else None
            )

            rows.append(item)

        with_reading = [
            item for item in rows
            if item["punyaPembacaan"]
        ]

        return {
            "petugas": officer,
            "statistik": {
                "totalPelanggan": len(rows),
                "totalMeter": len(rows),
                "indikasiAnomali": sum(
                    item["status"] == "anomali"
                    for item in with_reading
                ),
                "pemakaianNormal": sum(
                    item["status"] == "normal"
                    for item in with_reading
                ),
                "belumAdaPembacaan": (
                    len(rows) - len(with_reading)
                ),
            },
            "pelanggan": rows,
            "catatan": (
                "Anomali adalah indikasi yang perlu "
                "diperiksa, bukan kepastian kebocoran."
            ),
        }

    # ======================================
    # API RIWAYAT PELANGGAN UNTUK PETUGAS
    # ======================================

    @app.get(
        "/api/pdam/pelanggan/{customer_id}/riwayat"
    )
    def admin_customer_history(
        customer_id: str,
        officer: dict = Depends(require_officer),
        db: Session = Depends(db_session),
    ):
        customer = db.get(Customer, customer_id)

        if not customer:
            raise HTTPException(
                404, "Pelanggan tidak ditemukan"
            )

        readings = history(db, customer_id)

        return {
            "id_pelanggan": customer.customer_id,
            "nama": customer.name,
            "nomor_meter": customer.meter_number,
            "riwayat": [
                {
                    "tanggal": (
                        row.measured_at.date().isoformat()
                    ),
                    "waktu": (
                        row.measured_at.isoformat(
                            sep=" ", timespec="minutes"
                        )
                    ),
                    "meter": row.meter_value,
                    "pemakaian": row.daily_usage,
                }
                for row in reversed(readings[-100:])
            ],
        }

    # ======================================
    # API TAMBAH PELANGGAN OLEH PDAM
    # ======================================

    @app.post(
        "/api/pdam/pelanggan",
        status_code=201,
    )
    def admin_create_customer(
        payload: CustomerCreate,
        officer: dict = Depends(require_officer),
        db: Session = Depends(db_session),
    ):
        # Mencegah ID pelanggan duplikat
        if db.get(Customer, payload.id_pelanggan):
            raise HTTPException(
                409, "ID pelanggan sudah terdaftar"
            )

        # Mencegah nomor meter duplikat
        existing_meter = db.scalar(
            select(Customer.customer_id).where(
                Customer.meter_number
                == payload.nomor_meter
            )
        )

        if existing_meter:
            raise HTTPException(
                409, "Nomor meter sudah digunakan"
            )

        customer = Customer(
            customer_id=payload.id_pelanggan,
            meter_number=payload.nomor_meter,
            name=payload.nama,
            address=payload.alamat,
        )

        db.add(customer)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409,
                "ID pelanggan atau nomor meter sudah digunakan",
            )

        return {
            "message": (
                "Data pelanggan berhasil dibuat. "
                "Pelanggan dapat melakukan registrasi."
            ),
            "id_pelanggan": customer.customer_id,
            "nomor_meter": customer.meter_number,
        }
