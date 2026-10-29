
"""
Backend FastAPI - Smart Water Meter

Sistem terdiri dari:
1. Portal Pelanggan
2. Portal Administrasi PDAM
3. API pengelolaan pelanggan dan pembacaan meter

Catatan:
Registrasi berbasis kecocokan identitas masih untuk pengujian.
Untuk produksi diperlukan verifikasi kepemilikan tambahan.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import (
    Customer,
    Officer,
    Reading,
    SessionToken,
    build_db,
    utc_now,
)

from .schemas import Login, NewReading, Registration

from .security import (
    hash_password,
    new_session_token,
    token_digest,
    verify_password,
)

# ==========================================
# PORTAL ADMINISTRASI PDAM
# ==========================================

from .pdam_portal import install_pdam_portal


COOKIE_NAME = "swm_session"
SESSION_HOURS = 8


# ==========================================
# NORMALISASI DATA TEKS
# ==========================================

def normalize_text(text: str) -> str:
    return " ".join(text.strip().casefold().split())


# ==========================================
# MEMBUAT APLIKASI FASTAPI
# ==========================================

def create_app(database_url: str | None = None) -> FastAPI:

    app = FastAPI(
        title="Smart Water Meter API",
        description=(
            "API pelanggan dan administrasi PDAM "
            "untuk monitoring pemakaian air."
        ),
        version="1.0.0",
    )

    # Koneksi database
    engine, factory = build_db(database_url)

    app.state.engine = engine
    app.state.db_factory = factory

    # ======================================
    # KONFIGURASI CORS
    # ======================================

    origins = [
        origin.strip()
        for origin in os.environ.get(
            "SWM_CORS_ORIGINS",
            (
                "http://127.0.0.1:5500,"
                "http://127.0.0.1:5501,"
                "http://localhost:5500,"
                "http://localhost:5501"
            ),
        ).split(",")
        if origin.strip()
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # ======================================
    # DATABASE SESSION
    # ======================================

    def db_session(request: Request):
        db = request.app.state.db_factory()

        try:
            yield db
        finally:
            db.close()

    # ======================================
    # AUTENTIKASI PENGGUNA
    # ======================================

    def identity(
        request: Request,
        db: Session = Depends(db_session),
    ) -> dict:

        token = request.cookies.get(COOKIE_NAME)

        record = (
            db.get(SessionToken, token_digest(token))
            if token
            else None
        )

        if not record or record.expires_at <= utc_now():
            raise HTTPException(
                status_code=401,
                detail="Silakan login terlebih dahulu",
            )

        # Identitas pelanggan
        if record.role == "pelanggan":

            customer = db.get(Customer, record.actor_id)

            if not customer or not customer.password_hash:
                raise HTTPException(
                    status_code=401,
                    detail="Sesi pelanggan tidak valid",
                )

            return {
                "id": customer.customer_id,
                "nama": customer.name,
                "role": "pelanggan",
            }

        # Identitas petugas PDAM
        if record.role == "pdam":

            officer = db.get(Officer, record.actor_id)

            if not officer:
                raise HTTPException(
                    status_code=401,
                    detail="Sesi petugas tidak valid",
                )

            return {
                "id": officer.officer_id,
                "nama": officer.name,
                "role": "pdam",
            }

        raise HTTPException(
            status_code=401,
            detail="Sesi tidak valid",
        )

    # ======================================
    # HAK AKSES KHUSUS PETUGAS PDAM
    # ======================================

    def require_officer(
        user: dict = Depends(identity),
    ) -> dict:

        if user["role"] != "pdam":
            raise HTTPException(
                status_code=403,
                detail="Akses hanya untuk petugas PDAM",
            )

        return user

    # ======================================
    # RIWAYAT PEMBACAAN METER
    # ======================================

    def history(
        db: Session,
        customer_id: str,
    ) -> list[Reading]:

        return list(
            db.scalars(
                select(Reading)
                .where(Reading.customer_id == customer_id)
                .order_by(Reading.measured_at)
            ).all()
        )

    # ======================================
    # RINGKASAN PEMAKAIAN PELANGGAN
    # ======================================

    def summary(
        db: Session,
        customer: Customer,
    ) -> dict:

        records = history(db, customer.customer_id)

        last = records[-1] if records else None

        # Rata-rata dari pembacaan sebelumnya
        recent_previous = records[-8:-1]

        if recent_previous:
            average = round(
                sum(
                    row.daily_usage
                    for row in recent_previous
                ) / len(recent_previous),
                3,
            )
        else:
            average = 0.0

        usage = (
            round(last.daily_usage, 3)
            if last
            else 0.0
        )

        # Indikator lonjakan sederhana untuk demo
        flagged = bool(
            last
            and len(recent_previous) >= 2
            and average > 0
            and usage > max(1.0, average * 2)
        )

        return {
            "id": customer.customer_id,
            "nama": customer.name,
            "alamat": customer.address,
            "meter": customer.meter_number,
            "hariIni": usage,
            "rata": average,
            "status": (
                "anomali"
                if flagged
                else "normal"
            ),
            "waktu": (
                last.measured_at.isoformat(
                    sep=" ",
                    timespec="minutes",
                )
                if last
                else "Belum ada pembacaan"
            ),
        }

    # ======================================
    # HEALTH CHECK
    # ======================================

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ======================================
    # REGISTRASI AKUN PELANGGAN
    # ======================================

    @app.post("/api/register", status_code=201)
    def register(
        payload: Registration,
        db: Session = Depends(db_session),
    ):

        customer = db.get(
            Customer,
            payload.id_pelanggan,
        )

        if not customer:
            raise HTTPException(
                404,
                "ID pelanggan tidak terdaftar",
            )

        # Validasi identitas pelanggan
        if (
            customer.meter_number != payload.nomor_meter
            or normalize_text(customer.name)
            != normalize_text(payload.nama)
            or normalize_text(customer.address)
            != normalize_text(payload.alamat)
        ):
            raise HTTPException(
                400,
                "Identitas pelanggan atau nomor meter "
                "tidak sesuai data PDAM",
            )

        if customer.password_hash:
            raise HTTPException(
                409,
                "Akun pelanggan sudah didaftarkan",
            )

        customer.password_hash = hash_password(
            payload.password
        )

        db.commit()

        return {
            "message": "Registrasi berhasil"
        }

    # ======================================
    # LOGIN PELANGGAN DAN PETUGAS
    # ======================================

    @app.post("/api/login")
    def login(
        payload: Login,
        response: Response,
        db: Session = Depends(db_session),
    ):

        customer = db.get(
            Customer,
            payload.identifier,
        )

        officer = db.get(
            Officer,
            payload.identifier,
        )

        # Login pelanggan
        if (
            customer
            and customer.password_hash
            and verify_password(
                payload.password,
                customer.password_hash,
            )
        ):
            actor_id = customer.customer_id
            name = customer.name
            role = "pelanggan"

        # Login petugas PDAM
        elif (
            officer
            and verify_password(
                payload.password,
                officer.password_hash,
            )
        ):
            actor_id = officer.officer_id
            name = officer.name
            role = "pdam"

        else:
            raise HTTPException(
                401,
                "ID atau password salah",
            )

        # Membuat session login
        token = new_session_token()

        db.add(
            SessionToken(
                token_hash=token_digest(token),
                actor_id=actor_id,
                role=role,
                expires_at=(
                    utc_now()
                    + timedelta(hours=SESSION_HOURS)
                ),
            )
        )

        db.commit()

        # Cookie sesi
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_HOURS * 3600,
            httponly=True,
            secure=(
                os.environ.get(
                    "SWM_SECURE_COOKIE",
                    "false",
                ).lower() == "true"
            ),
            samesite="lax",
            path="/",
        )

        return {
            "id": actor_id,
            "nama": name,
            "role": role,
        }

    # ======================================
    # INFORMASI AKUN YANG SEDANG LOGIN
    # ======================================

    @app.get("/api/me")
    def me(
        user: dict = Depends(identity),
    ):
        return user

    # ======================================
    # LOGOUT
    # ======================================

    @app.post("/api/logout")
    def logout(
        request: Request,
        response: Response,
        db: Session = Depends(db_session),
    ):

        token = request.cookies.get(COOKIE_NAME)

        if token:
            record = db.get(
                SessionToken,
                token_digest(token),
            )

            if record:
                db.delete(record)
                db.commit()

        response.delete_cookie(
            COOKIE_NAME,
            path="/",
        )

        return {
            "message": "Berhasil keluar"
        }

    # ======================================
    # API DATA PELANGGAN
    # ======================================

    @app.get("/api/pelanggan")
    def pelanggan(
        user: dict = Depends(identity),
        db: Session = Depends(db_session),
    ):

        if user["role"] == "pdam":

            # Petugas bisa melihat seluruh pelanggan
            customers = db.scalars(
                select(Customer)
                .order_by(Customer.customer_id)
            ).all()

        else:

            # Pelanggan hanya melihat datanya sendiri
            customers = [
                db.get(Customer, user["id"])
            ]

        return [
            summary(db, customer)
            for customer in customers
            if customer
        ]

    # ======================================
    # API RIWAYAT PEMAKAIAN
    # ======================================

    @app.get("/api/riwayat")
    def riwayat(
        user: dict = Depends(identity),
        db: Session = Depends(db_session),
    ):

        # Endpoint ini khusus riwayat pelanggan
        if user["role"] != "pelanggan":
            return []

        records = history(
            db,
            user["id"],
        )

        return [
            {
                "tanggal": (
                    row.measured_at.date().isoformat()
                ),
                "meter": row.meter_value,
                "pemakaian": row.daily_usage,
            }
            for row in records
        ]

    # ======================================
    # INPUT PEMBACAAN METER OLEH PETUGAS
    # ======================================

    @app.post("/api/readings", status_code=201)
    def add_reading(
        payload: NewReading,
        officer: dict = Depends(require_officer),
        db: Session = Depends(db_session),
    ):

        customer = db.get(
            Customer,
            payload.id_pelanggan,
        )

        if not customer:
            raise HTTPException(
                404,
                "Pelanggan tidak ditemukan",
            )

        # Pembacaan terakhir
        last = db.scalar(
            select(Reading)
            .where(
                Reading.customer_id
                == customer.customer_id
            )
            .order_by(
                Reading.measured_at.desc()
            )
            .limit(1)
        )

        # Normalisasi waktu ke UTC
        if payload.waktu.tzinfo is None:
            measured_at = payload.waktu
        else:
            measured_at = (
                payload.waktu
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        if last and measured_at <= last.measured_at:
            raise HTTPException(
                409,
                "Waktu pembacaan harus lebih baru "
                "dari pembacaan terakhir",
            )

        # Mencegah angka meter turun
        if last and payload.meter < last.meter_value:
            raise HTTPException(
                422,
                "Angka meter menurun; "
                "perlu pemeriksaan manual",
            )

        # Menghitung selisih angka meter
        usage = (
            round(
                payload.meter - last.meter_value,
                3,
            )
            if last
            else 0.0
        )

        db.add(
            Reading(
                customer_id=customer.customer_id,
                measured_at=measured_at,
                meter_value=payload.meter,
                daily_usage=usage,
            )
        )

        try:
            db.commit()

        except IntegrityError:
            db.rollback()

            raise HTTPException(
                409,
                "Pembacaan sudah ada",
            )

        return {
            "message": "Pembacaan tersimpan",
            "pemakaian": usage,
            "catatan": (
                "Hasil input manual, "
                "belum dari AI atau ESP32-CAM"
            ),
        }

    # ======================================
    # MENGAKTIFKAN PORTAL ADMINISTRASI PDAM
    # ======================================

    install_pdam_portal(
        app,
        db_session=db_session,
        identity=identity,
        require_officer=require_officer,
        summary=summary,
        history=history,
    )

    return app


# ==========================================
# INSTANCE APLIKASI FASTAPI
# ==========================================

app = create_app()
