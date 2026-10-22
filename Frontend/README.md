# Smart Water Meter — Frontend revisi login dan registrasi

## Halaman
- `index.html`: login dengan ID Pelanggan atau ID Petugas + password.
- `register.html`: registrasi mandiri pelanggan dengan ID Pelanggan, nomor meter, nama, alamat, password.
- Dashboard dan halaman riwayat/notifikasi tetap dipertahankan.

## Menjalankan
Buka `index.html` menggunakan Live Server di VS Code. Backend diatur pada `js/api.js` (`http://127.0.0.1:8000/api`).

## Penting: kontrak API yang harus dibuat tim backend
`POST /api/register` menerima JSON:
```json
{"id_pelanggan":"PLG00125","nomor_meter":"MTR00125","nama":"Contoh Nama","alamat":"Contoh alamat","password":"contoh-password-kuat"}
```
Respons sukses: HTTP 201, JSON misalnya `{"message":"Registrasi berhasil"}`.
Error: HTTP 400/409 dengan `{"detail":"..."}`.
`POST /api/login` menerima `{ "identifier": "PLG00125", "password": "..." }`; mengembalikan `{ "id": "PLG00125", "nama": "...", "role": "pelanggan" }` atau `role: "pdam"` dan mengatur sesi melalui cookie HttpOnly.
Endpoint lain yang digunakan: `GET /api/me`, `POST /api/logout`, `GET /api/pelanggan`, `GET /api/riwayat`.

**Backend FastAPI dari paket sebelumnya belum memiliki endpoint `/api/register`.** Registrasi akan menampilkan kesalahan sampai backend diperbarui. Jangan menyimpan password di JavaScript atau `localStorage`. Backend harus memverifikasi kepemilikan ID dan nomor meter (misalnya OTP/kode aktivasi), hash password, dan membatasi percobaan login/registrasi. ID petugas tidak boleh bisa didaftarkan lewat halaman publik.

## Deploy
File statis cocok untuk Cloudflare. Atur `API_BASE_URL` ke alamat API HTTPS produksi dan konfigurasi cookie/CORS yang sesuai.
