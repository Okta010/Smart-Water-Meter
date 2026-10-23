"""Input schemas follow the uploaded original Frontend/js/api.js."""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class Registration(BaseModel):
    id_pelanggan: str = Field(min_length=1, max_length=40)
    nomor_meter: str = Field(min_length=1, max_length=50)
    nama: str = Field(min_length=1, max_length=120)
    alamat: str = Field(min_length=1, max_length=300)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("id_pelanggan", "nomor_meter", "nama", "alamat")
    @classmethod
    def strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Kolom wajib tidak boleh kosong")
        return v


class Login(BaseModel):
    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class NewReading(BaseModel):
    id_pelanggan: str
    meter: float = Field(ge=0)
    waktu: datetime
