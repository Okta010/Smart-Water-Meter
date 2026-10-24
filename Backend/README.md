# Smart Water Meter — FastAPI Backend (compatible with ORIGINAL frontend)

Backend ini dibuat khusus untuk **versi frontend yang mengandung `window.API_BASE_URL = 'http://127.0.0.1:8000/api'`** dan memakai **cookie HttpOnly (`credentials:'include'`)**. Jangan campur dengan backend versi lain yang menggunakan `/api/v1` dan Bearer token.

## 1. Persiapan

Dari folder `Backend` pada PowerShell (Windows):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Jika `.venv` sudah ada, tidak perlu membuatnya ulang. Jika backend lama sudah ada, **backup dulu**; jangan timpa database/backend teman kelompok.

## 2. Siapkan data demo lokal (opsional)

```powershell
$env:SWM_DEMO_SEED = 'YES'
.\.venv\Scripts\python.exe -m app.seed
Remove-Item Env:\SWM_DEMO_SEED
```

Seed ini menambahkan **empat pelanggan fiktif** (tanpa password sampai mendaftar), contoh riwayat, dan akun petugas `ADM001`. Password petugas yang dihasilkan secara acak hanya ditampilkan sekali di terminal. Simpan secara privat. Jangan seed database nyata/bersama.

Contoh registrasi pelanggan data demo:

- ID Pelanggan: `PLG001`
- Nomor Meter: `MTR-001`
- Nama: `Ahmad Fauzi`
- Alamat: `Jl. Melati No. 12, Bandar Lampung`
- Password: buat sendiri (minimal 8 karakter)

Registrasi hanya berhasil jika data pelanggan yang dimasukkan sama dengan data yang sudah ada dan belum mempunyai akun. Lihat empat pelanggan demo lain yang dicetak saat seed.

**Peringatan keamanan:** pencocokan ID, nomor meter, nama, dan alamat **bukan verifikasi kepemilikan yang memadai untuk produksi**. Sebelum digunakan PDAM nyata, tambahkan kode aktivasi/OTP dari kanal terverifikasi, approval petugas, rate limiting, audit log, HTTPS, dan migrasi formal.

## 3. Jalankan backend

Dari folder `Backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Health: `http://127.0.0.1:8000/health`
- Swagger: `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/` menampilkan 404 adalah NORMAL; tidak ada route untuk root.

Jangan jalankan dua server Uvicorn pada port yang sama. Jika terjadi `WinError 10048`, identifikasi proses lama dahulu.

## 4. Jalankan frontend

Di **terminal lain**, dari folder `Frontend` original:

```powershell
python -m http.server 5501 --bind 127.0.0.1
```

Buka `http://127.0.0.1:5501/index.html` atau `http://127.0.0.1:5501/register.html`.

CORS diizinkan untuk `127.0.0.1` dan `localhost` pada port 5500/5501 dengan cookie. Gunakan host yang konsisten (`127.0.0.1`) agar cookie berfungsi.

## 5. Kontrak endpoint dengan frontend original

| Endpoint | Metode | Fungsi | Autentikasi |
| --- | --- | --- | --- |
| `/api/register` | POST | Registrasi pelanggan yang telah dipra-daftarkan | Publik untuk demo |
| `/api/login` | POST | Login pelanggan/petugas (mengatur cookie) | Publik |
| `/api/me` | GET | Identitas + role pengguna saat ini | Cookie |
| `/api/logout` | POST | Hapus sesi server + cookie | Opsional |
| `/api/pelanggan` | GET | Customer: data diri saja. PDAM: seluruh pelanggan | Cookie |
| `/api/riwayat` | GET | Riwayat customer aktif. PDAM: daftar kosong | Cookie |
| `/api/readings` | POST | Input pembacaan manual pengujian | Petugas |
| `/health` | GET | Health check | Publik |
| `/docs` | GET | Swagger UI | Publik (untuk dev) |

Frontend menggunakan role `pelanggan` dan `pdam`, bukan `customer` dan `officer`.

## 6. Jalankan pengujian terisolasi

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tes memakai SQLite sementara, bukan database pelanggan lokal.

## 7. Batasan

- Data seed dan pembacaan adalah **SIMULASI** sesuai label di frontend.
- Belum menerima gambar ESP32-CAM atau menjalankan YOLOv8 + TrOCR.
- Endpoint input pembacaan hanya untuk simulasi petugas, belum autentikasi perangkat IoT.
- Status anomali adalah pemeriksaan sederhana relatif terhadap pembacaan sebelumnya, bukan Isolation Forest atau deteksi kebocoran final.
- Dashboard pelanggan yang diunggah menggunakan `hist.at(-1)` tanpa pengecekan ketika data riwayat kosong; bila ingin mendukung pelanggan tanpa pembacaan, bagian frontend tersebut perlu ditangani terpisah.
- `notifikasi.html` memakai `demo_role` untuk tautan kembali PDAM; ganti pembacaan role menjadi `role` untuk navigasi petugas yang benar.
- Dibuat sebagai backend **baru dan terpisah** supaya backend teman kelompok yang sebelumnya sudah dikembangkan tidak tertimpa. Audit kontrak sebelum memindahkan file apa pun.
