import os
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/watermeter", tags=["watermeter"])

# folder Backend (dua tingkat di atas file ini)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
LOG_FILE = os.path.join(BASE_DIR, "readings.csv")
os.makedirs(UPLOAD_DIR, exist_ok=True)

API_KEY = os.environ.get("WATERMETER_API_KEY", "k3Xv9_TqLw2mP8aZrA1bQg")


def baca_angka(path_foto: str):
    # TODO: panggil AI di sini, kembalikan angka meteran sebagai string
    return None


@router.post("/upload")
async def upload(request: Request, x_api_key: str = Header(default=None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Kosong")

    waktu = datetime.now()
    nama = waktu.strftime("%Y%m%d_%H%M%S") + ".jpg"
    path = os.path.join(UPLOAD_DIR, nama)

    with open(path, "wb") as f:
        f.write(data)

    angka = baca_angka(path)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{waktu.isoformat()},{nama},{angka or ''}\n")

    return {"status": "ok", "file": nama}


@router.get("/readings/latest")
def latest(request: Request):
    if not os.path.exists(LOG_FILE):
        return None
    with open(LOG_FILE, encoding="utf-8") as f:
        baris = f.read().strip().splitlines()
    if not baris:
        return None
    waktu, nama, angka = baris[-1].split(",")
    return {
        "waktu": waktu,
        "foto": str(request.base_url) + "watermeter/photos/" + nama,
        "angka": angka or None,
    }


@router.get("/photos/{nama}")
def foto(nama: str):
    path = os.path.join(UPLOAD_DIR, os.path.basename(nama))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Tidak ditemukan")
    return FileResponse(path, media_type="image/jpeg")