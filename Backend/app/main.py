"""FastAPI backend compatible with the original uploaded Smart Water Meter frontend.

DEVELOPMENT DEMO ONLY: matching a customer ID, meter, name and address does NOT
prove ownership. Production signup requires an independent verification step.
"""
import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Customer, Officer, Reading, SessionToken, build_db, utc_now
from .schemas import Login, NewReading, Registration
from .security import hash_password, new_session_token, token_digest, verify_password

COOKIE_NAME = "swm_session"
SESSION_HOURS = 8


def normalize_text(s: str) -> str:
    return " ".join(s.strip().casefold().split())


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Smart Water Meter API", version="1.0.0")
    engine, factory = build_db(database_url)
    app.state.engine = engine
    app.state.db_factory = factory

    origins = [s.strip() for s in os.environ.get(
        "SWM_CORS_ORIGINS",
        "http://127.0.0.1:5500,http://127.0.0.1:5501,http://localhost:5500,http://localhost:5501"
    ).split(",") if s.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    def db_session(request: Request):
        db = request.app.state.db_factory()
        try:
            yield db
        finally:
            db.close()

    def identity(request: Request, db: Session = Depends(db_session)) -> dict:
        token = request.cookies.get(COOKIE_NAME)
        record = db.get(SessionToken, token_digest(token)) if token else None
        if not record or record.expires_at <= utc_now():
            raise HTTPException(status_code=401, detail="Silakan login terlebih dahulu")
        if record.role == "pelanggan":
            actor = db.get(Customer, record.actor_id)
            if not actor or not actor.password_hash:
                raise HTTPException(status_code=401, detail="Sesi tidak valid")
            return {"id": actor.customer_id, "nama": actor.name, "role": "pelanggan"}
        if record.role == "pdam":
            officer = db.get(Officer, record.actor_id)
            if not officer:
                raise HTTPException(status_code=401, detail="Sesi tidak valid")
            return {"id": officer.officer_id, "nama": officer.name, "role": "pdam"}
        raise HTTPException(status_code=401, detail="Sesi tidak valid")

    def require_officer(user: dict = Depends(identity)) -> dict:
        if user["role"] != "pdam":
            raise HTTPException(status_code=403, detail="Akses hanya untuk petugas PDAM")
        return user

    def history(db: Session, customer_id: str) -> list[Reading]:
        return list(db.scalars(select(Reading).where(Reading.customer_id == customer_id).order_by(Reading.measured_at)).all())

    def summary(db: Session, customer: Customer) -> dict:
        records = history(db, customer.customer_id)
        last = records[-1] if records else None
        # Use earlier readings for baseline, not today's reading itself.
        recent_previous = records[-8:-1]
        avg = round(sum(r.daily_usage for r in recent_previous) / len(recent_previous), 3) if recent_previous else 0.0
        today = round(last.daily_usage, 3) if last else 0.0
        flagged = bool(last and len(recent_previous) >= 2 and avg > 0 and today > max(1.0, avg * 2))
        return {
            "id": customer.customer_id, "nama": customer.name, "alamat": customer.address,
            "meter": customer.meter_number, "hariIni": today, "rata": avg,
            "status": "anomali" if flagged else "normal",
            "waktu": last.measured_at.isoformat(sep=" ", timespec="minutes") if last else "Belum ada pembacaan",
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/register", status_code=201)
    def register(payload: Registration, db: Session = Depends(db_session)):
        # Only pre-provisioned customers can register. Demo matching != proof of ownership.
        customer = db.get(Customer, payload.id_pelanggan)
        if not customer:
            raise HTTPException(404, "ID pelanggan tidak terdaftar")
        if (customer.meter_number != payload.nomor_meter
            or normalize_text(customer.name) != normalize_text(payload.nama)
            or normalize_text(customer.address) != normalize_text(payload.alamat)):
            raise HTTPException(400, "Identitas pelanggan atau nomor meter tidak sesuai data PDAM")
        if customer.password_hash:
            raise HTTPException(409, "Akun pelanggan sudah didaftarkan")
        customer.password_hash = hash_password(payload.password)
        db.commit()
        return {"message": "Registrasi berhasil"}

    @app.post("/api/login")
    def login(payload: Login, response: Response, db: Session = Depends(db_session)):
        customer = db.get(Customer, payload.identifier)
        officer = db.get(Officer, payload.identifier)
        if customer and customer.password_hash and verify_password(payload.password, customer.password_hash):
            actor_id, name, role = customer.customer_id, customer.name, "pelanggan"
        elif officer and verify_password(payload.password, officer.password_hash):
            actor_id, name, role = officer.officer_id, officer.name, "pdam"
        else:
            raise HTTPException(401, "ID atau password salah")

        token = new_session_token()
        db.add(SessionToken(token_hash=token_digest(token), actor_id=actor_id, role=role,
                            expires_at=utc_now() + timedelta(hours=SESSION_HOURS)))
        db.commit()
        response.set_cookie(
            COOKIE_NAME, token, max_age=SESSION_HOURS * 3600, httponly=True,
            secure=os.environ.get("SWM_SECURE_COOKIE", "false").lower() == "true",
            samesite="lax", path="/",
        )
        return {"id": actor_id, "nama": name, "role": role}

    @app.get("/api/me")
    def me(user: dict = Depends(identity)):
        return user

    @app.post("/api/logout")
    def logout(request: Request, response: Response, db: Session = Depends(db_session)):
        token = request.cookies.get(COOKIE_NAME)
        if token:
            record = db.get(SessionToken, token_digest(token))
            if record:
                db.delete(record)
                db.commit()
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"message": "Berhasil keluar"}

    @app.get("/api/pelanggan")
    def pelanggan(user: dict = Depends(identity), db: Session = Depends(db_session)):
        if user["role"] == "pdam":
            customers = db.scalars(select(Customer).order_by(Customer.customer_id)).all()
        else:
            customers = [db.get(Customer, user["id"])]
        return [summary(db, c) for c in customers if c]

    @app.get("/api/riwayat")
    def riwayat(user: dict = Depends(identity), db: Session = Depends(db_session)):
        # The original UI only exposes history for the logged-in customer.
        if user["role"] != "pelanggan":
            return []
        return [
            {"tanggal": r.measured_at.date().isoformat(), "meter": r.meter_value,
             "pemakaian": r.daily_usage}
            for r in history(db, user["id"])
        ]

    @app.post("/api/readings", status_code=201)
    def add_reading(payload: NewReading, officer: dict = Depends(require_officer), db: Session = Depends(db_session)):
        """Manual/testing input, NOT an ESP32-CAM ingest or OCR integration."""
        customer = db.get(Customer, payload.id_pelanggan)
        if not customer:
            raise HTTPException(404, "Pelanggan tidak ditemukan")
        last = db.scalar(select(Reading).where(Reading.customer_id == customer.customer_id)
                         .order_by(Reading.measured_at.desc()).limit(1))
        measured_at = payload.waktu.replace(tzinfo=None) if payload.waktu.tzinfo is None else payload.waktu.astimezone(timezone.utc).replace(tzinfo=None)
        if last and measured_at <= last.measured_at:
            raise HTTPException(409, "Waktu pembacaan harus lebih baru dari pembacaan terakhir")
        if last and payload.meter < last.meter_value:
            raise HTTPException(422, "Angka meter menurun; perlu pemeriksaan manual")
        usage = round(payload.meter - last.meter_value, 3) if last else 0.0
        db.add(Reading(customer_id=customer.customer_id, measured_at=measured_at,
                       meter_value=payload.meter, daily_usage=usage))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Pembacaan sudah ada")
        return {"message": "Pembacaan tersimpan", "pemakaian": usage,
                "catatan": "Hasil input manual, belum dari model AI atau ESP32-CAM"}

    return app


app = create_app()
