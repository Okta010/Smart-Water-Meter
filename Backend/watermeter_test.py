from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.water_upload import router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # untuk tes; nanti ganti ke alamat frontend asli
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)