"""Format error standar PRD bagian 11: {"error": {"kode", "pesan", "detail"}}."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("jalurku.errors")

_KODE_HTTP = {
    400: "permintaan_salah",
    401: "tidak_terautentikasi",
    403: "dilarang",
    404: "tidak_ditemukan",
    405: "metode_tidak_diizinkan",
    409: "konflik",
    413: "terlalu_besar",
    422: "validasi_gagal",
    429: "terlalu_banyak_permintaan",
    503: "dependensi_tidak_tersedia",
}


_PESAN_HTTP = {
    401: "Token tidak ada, tidak valid, atau sesi sudah kedaluwarsa",
    404: "Sumber daya tidak ditemukan",
    405: "Metode tidak diizinkan untuk endpoint ini",
}


class AppError(Exception):
    """Error bisnis yang dipetakan langsung ke respons standar."""

    def __init__(
        self,
        kode: str,
        pesan: str,
        status_code: int = 400,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(pesan)
        self.kode = kode
        self.pesan = pesan
        self.status_code = status_code
        self.detail = detail or {}
        self.headers = headers


def error_body(kode: str, pesan: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"kode": kode, "pesan": pesan, "detail": detail or {}}}


def _respond(
    status: int,
    kode: str,
    pesan: str,
    detail: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(kode, pesan, detail), status_code=status, headers=headers)


def field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Ringkas error validasi per field. Nilai input sengaja tidak disertakan (bisa memuat PII)."""
    hasil: list[dict[str, str]] = []
    for e in exc.errors():
        # "[key]" = penanda pydantic untuk error pada KUNCI dict; kunci yang salah sudah ada di path.
        lokasi = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path", "[key]")]
        hasil.append(
            {
                "field": ".".join(lokasi) or "(body)",
                "pesan": str(e.get("msg", "")),
                "tipe": e["type"],
            }
        )
    return hasil


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _respond(exc.status_code, exc.kode, exc.pesan, exc.detail, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        kode = _KODE_HTTP.get(exc.status_code, "kesalahan_http")
        standar = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus else ""
        if isinstance(exc.detail, str) and exc.detail != standar:
            pesan = exc.detail
        else:
            pesan = _PESAN_HTTP.get(exc.status_code, kode.replace("_", " ").capitalize())
        return _respond(exc.status_code, kode, pesan, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _respond(
            422,
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            {"field": field_errors(exc)},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Jangan mencatat body, token, atau teks pertanyaan mentah.
        log.error(
            "Kesalahan tak tertangani di %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return _respond(500, "kesalahan_internal", "Terjadi kesalahan pada server")
