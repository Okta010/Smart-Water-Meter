# Smart Water Meter — Frontend

## 1. Deskripsi
Frontend Smart Water Meter digunakan pelanggan untuk login, registrasi, melihat pemakaian air, riwayat pembacaan meter, dan notifikasi anomali.

## 2. Fitur
- `index.html`: Login pelanggan.
- `register.html`: Registrasi pelanggan.
- `dashboard-pelanggan.html`: Dashboard pemakaian air.
- `riwayat.html`: Riwayat pembacaan meter.
- `notifikasi.html`: Notifikasi anomali.

## 3. Menjalankan Aplikasi
1. Jalankan Backend FastAPI pada port `8001`.
2. Jalankan Frontend menggunakan Live Server atau server HTTP lokal.
3. Buka halaman `index.html` melalui browser.

## 4. Konfigurasi API
Alamat API diatur pada `js/api.js`:

`http://127.0.0.1:8001/api`

Endpoint yang digunakan: `/api/register`, `/api/login`, `/api/me`, `/api/logout`, `/api/pelanggan`, dan `/api/riwayat`.

## 5. Portal Petugas
Petugas PDAM menggunakan portal Backend:

`http://127.0.0.1:8001/pdam/login`

## 6. Catatan
Untuk deployment, gunakan alamat Backend HTTPS dan konfigurasi CORS serta cookie sesi dengan benar. Notifikasi anomali merupakan indikasi yang memerlukan pemeriksaan lebih lanjut.
