"""
Backend FastAPI - Smart Water Meter

Sistem terdiri dari:
1. Portal Pelanggan
2. Portal Administrasi PDAM
3. API pengelolaan pelanggan dan pembacaan meter
4. Endpoint upload foto dari ESP32-CAM (/watermeter/upload)

Catatan:
Registrasi berbasis kecocokan identitas masih untuk pengujian.
Untuk produksi diperlukan verifikasi kepemilikan tambahan.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    Form,
)

from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import (
    AIReadingAttempt,
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

from .ai import get_predictor

# ==========================================
# PORTAL ADMINISTRASI PDAM
# ==========================================

from .pdam_portal import install_pdam_portal


COOKIE_NAME = "swm_session"
SESSION_HOURS = 8
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # Maksimal 10 MB

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

    # ==========================================
    # PREDIKSI FOTO METER MENGGUNAKAN AI
    # ==========================================

    @app.post("/api/ai/predict")
    def predict_meter_image(
        file: UploadFile = File(...),
        id_pelanggan: str = Form(...),
        waktu: datetime = Form(...),
        officer: dict = Depends(require_officer),
        db: Session = Depends(db_session),
    ):
        # 1. Memeriksa pelanggan
        customer = db.get(
            Customer,
            id_pelanggan.strip(),
        )

        if not customer:
            raise HTTPException(
                status_code=404,
                detail="Pelanggan tidak ditemukan",
            )

        # 2. Menormalisasi waktu seperti endpoint pembacaan manual
        if waktu.tzinfo is None:
            measured_at = waktu
        else:
            measured_at = (
                waktu.astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

        # 3. Memeriksa format foto
        allowed_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=415,
                detail="Format file harus JPG, PNG, atau WEBP",
            )

        # 4. Membaca foto dengan batas ukuran 10 MB
        image_bytes = file.file.read(MAX_IMAGE_SIZE + 1)

        if not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="File foto kosong",
            )

        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Ukuran foto maksimal 10 MB",
            )

        # 5. Menjalankan model AI
        try:
            predictor = get_predictor()
            hasil = predictor.predict(image_bytes)

        except Exception:
            import logging

            logging.exception(
                "Terjadi kesalahan saat prediksi AI"
            )

            raise HTTPException(
                status_code=500,
                detail="Gagal memproses foto meter menggunakan AI",
            )

        # 6. Mengambil hasil prediksi
        status_ai = str(
            hasil.get("status_validasi") or "perlu_verifikasi"
        )

        alasan_ai = str(
            hasil.get("alasan") or ""
        )

        nilai_raw = hasil.get("nilai_pembacaan")

        nilai = (
            float(nilai_raw)
            if nilai_raw is not None
            else None
        )

        # Status awal penyimpanan
        status_simpan = "tidak_disimpan"
        alasan_simpan = (
            f"Validasi AI belum lolos: {status_ai}. {alasan_ai}"
        )

        pemakaian = None
        pemakaian_24_jam = None
        reading_id = None
        reading_baru = None

        # 7. Memeriksa apakah hasil AI layak disimpan
        if status_ai == "perlu_rescan":

            status_simpan = "tidak_disimpan"
            alasan_simpan = (
                "Foto perlu diambil ulang karena area meter "
                "belum berhasil diproses dengan baik."
            )

        elif status_ai == "perlu_verifikasi":

            status_simpan = "menunggu_verifikasi"
            alasan_simpan = (
                "Hasil pembacaan AI perlu diperiksa secara manual."
            )

        elif status_ai == "valid" and nilai is not None:

            # Mengambil pembacaan resmi terakhir
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

            status_simpan = "tersimpan"
            alasan_simpan = (
                "Validasi AI dan pemeriksaan anomali berhasil."
            )

            # Jika sudah ada pembacaan sebelumnya
            if last:

                # Memeriksa urutan waktu
                if measured_at <= last.measured_at:

                    status_simpan = "menunggu_verifikasi"
                    alasan_simpan = (
                        "Waktu pembacaan tidak lebih baru "
                        "dari pembacaan sebelumnya."
                    )

                # Memeriksa angka meter yang menurun
                elif nilai < last.meter_value:

                    status_simpan = "menunggu_verifikasi"
                    alasan_simpan = (
                        "Angka meter lebih rendah dari pembacaan "
                        "sebelumnya. Perlu pemeriksaan manual."
                    )

                else:

                    # Menghitung selisih angka meter
                    pemakaian = round(
                        nilai - last.meter_value,
                        3,
                    )

                    # Menghitung estimasi pemakaian per 24 jam
                    elapsed_hours = (
                        measured_at - last.measured_at
                    ).total_seconds() / 3600

                    if elapsed_hours <= 0:

                        status_simpan = "menunggu_verifikasi"
                        alasan_simpan = (
                            "Interval waktu pembacaan tidak valid."
                        )

                    else:

                        pemakaian_24_jam = round(
                            pemakaian * 24 / elapsed_hours,
                            3,
                        )

                        # Batas anomali: lebih dari 50 m³ per 24 jam
                        if pemakaian_24_jam > 50:

                            status_simpan = "menunggu_verifikasi"
                            alasan_simpan = (
                                "Estimasi pemakaian melebihi "
                                "50 m³ dalam 24 jam. "
                                "Perlu pemeriksaan manual."
                            )

            else:

                # Pembacaan pertama menjadi nilai awal meter
                pemakaian = 0.0

            # Membuat pembacaan resmi jika semua pemeriksaan lolos
            if status_simpan == "tersimpan":

                reading_baru = Reading(
                    customer_id=customer.customer_id,
                    measured_at=measured_at,
                    meter_value=nilai,
                    daily_usage=pemakaian,
                )

        elif status_ai == "valid":

            status_simpan = "tidak_disimpan"
            alasan_simpan = (
                "Hasil AI berstatus valid, tetapi "
                "nilai pembacaan tidak tersedia."
            )

        else:

            status_simpan = "menunggu_verifikasi"
            alasan_simpan = (
                "Status validasi AI tidak dikenali. "
                "Perlu pemeriksaan manual."
            )

        # 8. Menyimpan pembacaan resmi dan riwayat percobaan
        try:

            if reading_baru:

                db.add(reading_baru)
                db.flush()

                reading_id = reading_baru.id

            attempt = AIReadingAttempt(
                customer_id=customer.customer_id,
                measured_at=measured_at,
                file_name=(file.filename or "foto_meter")[:255],
                area_deteksi=hasil.get("area_deteksi"),
                confidence_score=hasil.get("confidence_score"),
                hasil_ocr=hasil.get("hasil_ocr"),
                ocr_confidence=hasil.get("ocr_confidence"),
                nilai_pembacaan=nilai,
                status_validasi=status_ai,
                alasan=alasan_ai[:500] or None,
                blur_score=hasil.get("blur_score"),
                model_version=hasil.get("model_version"),
                latency_ms=(
                    int(hasil["latency_ms"])
                    if hasil.get("latency_ms") is not None
                    else None
                ),
                status_penyimpanan=status_simpan,
                alasan_penyimpanan=alasan_simpan[:500],
                reading_id=reading_id,
            )

            db.add(attempt)
            db.commit()

        except IntegrityError:

            db.rollback()

            raise HTTPException(
                status_code=409,
                detail="Pembacaan sudah tercatat atau terjadi konflik data.",
            )

        # 9. Mengembalikan hasil ke frontend
        return {
            "message": "Prediksi AI selesai",
            "nama_file": file.filename,
            "id_pelanggan": customer.customer_id,
            "hasil": hasil,
            "penyimpanan": {
                "status": status_simpan,
                "alasan": alasan_simpan,
                "attempt_id": attempt.id,
                "reading_id": reading_id,
                "pemakaian": pemakaian,
                "estimasi_pemakaian_24_jam": pemakaian_24_jam,
            },
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

    # ======================================
    # ENDPOINT UPLOAD FOTO DARI ESP32-CAM
    # (POST /watermeter/upload)
    # ======================================
    # Import dilakukan di dalam fungsi supaya tidak terjadi
    # circular import jika water_upload.py mengimpor modul lain.

    from .water_upload import router as water_router

    app.include_router(water_router)

    return app


# ==========================================
# INSTANCE APLIKASI FASTAPI
# ==========================================

app = create_app()