"""Load explicitly labeled DEMO customers and print a generated local officer login.

Run only on a throwaway/local development database: python -m app.seed
"""
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from .db import Customer, Officer, Reading, build_db
from .security import hash_password


CUSTOMERS = [
    ("PLG001", "MTR-001", "Ahmad Fauzi", "Jl. Melati No. 12, Bandar Lampung"),
    ("PLG002", "MTR-002", "Siti Rahma", "Jl. Kenanga No. 8, Bandar Lampung"),
    ("PLG003", "MTR-003", "Budi Santoso", "Jl. Mawar No. 5, Bandar Lampung"),
    ("PLG004", "MTR-004", "Dewi Lestari", "Jl. Anggrek No. 19, Bandar Lampung"),
]


def main():
    if os.environ.get("SWM_DEMO_SEED") != "YES":
        print("Untuk menggunakan data simulasi, set SWM_DEMO_SEED=YES terlebih dahulu.")
        print("Jangan jalankan seed pada database produksi atau database anggota kelompok.")
        return
    engine, make_session = build_db()
    with make_session() as db:
        for customer_id, meter_number, name, address in CUSTOMERS:
            if db.get(Customer, customer_id) is None:
                db.add(Customer(customer_id=customer_id, meter_number=meter_number,
                                name=name, address=address))
        db.flush()
        # Sample values from the uploaded frontend's data.js, with dates relative to today.
        today = datetime.now().date()
        samples = {
            "PLG001": [(.5, 124.5), (.6, 125.1), (.4, 125.5), (.5, 126.0), (.6, 126.6), (.5, 127.1), (1.8, 128.9)],
            "PLG002": [(.55, 100.0), (.6, 100.6)],
            "PLG003": [(.6, 50.0), (.5, 50.5), (1.5, 52.0)],
            "PLG004": [(.48, 300.0), (.4, 300.4)],
        }
        for customer_id, readings in samples.items():
            if db.scalar(select(Reading.id).where(Reading.customer_id == customer_id).limit(1)) is not None:
                continue
            for idx, (usage, meter) in enumerate(readings):
                days_ago = len(readings) - idx - 1
                ts = datetime.combine(today - timedelta(days=days_ago), datetime.min.time()).replace(hour=9)
                db.add(Reading(customer_id=customer_id, measured_at=ts,
                               meter_value=meter, daily_usage=usage))
        password = None
        if db.get(Officer, "ADM001") is None:
            password = os.environ.get("SWM_OFFICER_PASSWORD") or secrets.token_urlsafe(14)
            db.add(Officer(officer_id="ADM001", name="Petugas PDAM Demo", password_hash=hash_password(password)))
        db.commit()
        if password:
            print("\n=== AKUN PETUGAS DEMO (hanya tampil sekali) ===")
            print("ID Petugas: ADM001")
            print("Password:", password)
            print("Simpan secara privat. Jangan commit hasil terminal ini ke GitHub.\n")
        else:
            print("Akun ADM001 sudah ada; password lama tetap dipakai.")
        print("\n=== PELANGGAN DEMO YANG DAPAT REGISTRASI ===")
        for record in CUSTOMERS:
            print("ID:", record[0], "| Meter:", record[1], "| Nama:", record[2], "| Alamat:", record[3])
        print("Data ini fiktif untuk demo. Verifikasi kepemilikan pelanggan belum aman untuk produksi.")
    engine.dispose()


if __name__ == "__main__":
    main()
