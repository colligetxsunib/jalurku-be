"""Smoke test pasca-deploy: menjalankan alur persona fiktif lewat HTTP ke server yang berjalan.

    python -m scripts.smoke_test --base-url http://localhost:8080 --prod --lewat-proxy
    python -m scripts.smoke_test --base-url https://api.contoh.id --prod --lewat-proxy --admin-key $ADMIN_KEY

Hanya memakai persona fiktif (config/personas) dan menghapus sesinya di akhir. Endpoint admin hanya
diuji penolakannya (tanpa kunci / kunci salah) dan tidak pernah mengubah data. Kode keluar 1 bila ada
pemeriksaan yang gagal. /query tidak mensyaratkan GEMINI_API_KEY: respons `fallback` tetap lulus.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import ROOT_DIR

API = "/api/v1"
CONSENT = {"consent": True, "consent_version": "2026-10-13"}
KUNCI_QUERY = {"jawaban", "sumber", "yakin", "fallback", "mode"}
PERTANYAAN_UJI = "Berapa jumlah pilihan program studi di SNBP 2026?"


@dataclass
class Hasil:
    nama: str
    ok: bool
    detail: str = ""


def muat_persona(nama: str) -> dict[str, Any]:
    berkas = ROOT_DIR / "config" / "personas" / f"{nama}.json"
    return json.loads(berkas.read_text(encoding="utf-8"))


def _harap(r: httpx.Response, kode: int) -> None:
    assert r.status_code == kode, f"status {r.status_code}, diharapkan {kode}: {r.text[:200]}"


def _harap_salah_satu(r: httpx.Response, kode: set[int]) -> None:
    assert r.status_code in kode, f"status {r.status_code}, diharapkan salah satu {sorted(kode)}"


def jalankan(
    client: httpx.Client,
    *,
    persona: str = "dimas",
    jalur: str = "SNBT",
    prod: bool = False,
    lewat_proxy: bool = False,
    admin_key: str | None = None,
) -> list[Hasil]:
    """Jalankan semua pemeriksaan. `client` boleh httpx.Client atau TestClient (untuk tes)."""
    hasil: list[Hasil] = []
    p = muat_persona(persona)
    # Persona skenario A tidak punya target: pakai dua prodi seed UI yang sama dengan tes.
    target = (p.get("target_prodi_ids") or ["ui-ilmu-komputer", "ui-akuntansi"])[:2]
    state: dict[str, Any] = {}

    def cek(nama: str, fn: Callable[[], str | None]) -> bool:
        try:
            hasil.append(Hasil(nama, True, fn() or ""))
            return True
        except (
            AssertionError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            httpx.HTTPError,
        ) as exc:
            hasil.append(Hasil(nama, False, f"{type(exc).__name__}: {exc}"))
            return False

    def auth() -> dict[str, str]:
        return {"Authorization": f"Bearer {state['token']}"}

    # ---- kesehatan & keamanan dasar ----
    def health() -> str:
        r = client.get(f"{API}/health")
        _harap(r, 200)
        assert r.json() == {"status": "ok"}, r.text
        state["health_headers"] = r.headers
        return "database terjangkau"

    if not cek("GET /health", health):
        return hasil  # server tidak hidup: sisanya tidak bermakna

    def tanpa_token() -> str:
        for metode, path in (("GET", "/profile"), ("POST", "/analyze"), ("POST", "/summary")):
            r = client.request(metode, f"{API}{path}")
            _harap(r, 401)
        return "401 tanpa token"

    cek("endpoint sesi menolak tanpa token", tanpa_token)

    def tolak_tanpa_consent() -> str:
        r = client.post(f"{API}/session", json={"consent": False, "consent_version": "x"})
        _harap(r, 400)
        return "consent wajib"

    cek("POST /session menolak tanpa consent", tolak_tanpa_consent)

    def buat_sesi() -> str:
        r = client.post(f"{API}/session", json=CONSENT)
        _harap(r, 201)
        state["token"] = r.json()["token"]
        assert r.json()["sisa_detik"] > 0
        return "sesi dibuat"

    if not cek("POST /session", buat_sesi):
        return hasil

    # ---- alur persona ----
    def isi_profil() -> str:
        r = client.put(f"{API}/profile", json=p["profil"], headers=auth())
        _harap(r, 200)
        r2 = client.get(f"{API}/profile", headers=auth())
        _harap(r2, 200)
        return f"profil persona '{persona}' tersimpan"

    cek("PUT/GET /profile (persona fiktif)", isi_profil)

    def katalog() -> str:
        r = client.get(f"{API}/catalog/prodi", params={"limit": 5}, headers=auth())
        _harap(r, 200)
        d = r.json()
        assert d["total"] > 0 and d["items"], "katalog kosong (seed belum diingest?)"
        r2 = client.get(f"{API}/catalog/prodi/{target[0]}", headers=auth())
        _harap(r2, 200)
        return f"{d['total']} prodi di katalog"

    cek("GET /catalog/prodi", katalog)

    def explore() -> str:
        r = client.post(f"{API}/explore", json={"top_n": 3}, headers=auth())
        _harap(r, 200)
        d = r.json()
        assert {"rekomendasi", "data_kurang", "catatan"} <= d.keys(), "kunci respons kurang"
        if p["profil"].get("minat") and p["profil"].get("nilai_rapor"):
            assert d["rekomendasi"], "profil lengkap tetapi tidak ada rekomendasi"
            assert d["rekomendasi"][0]["contoh_profesi"], "contoh profesi kosong"
            return f"{len(d['rekomendasi'])} rumpun, teratas {d['rekomendasi'][0]['rumpun']}"
        return "profil belum lengkap: data_kurang " + ", ".join(
            x["field"] for x in d["data_kurang"]
        )

    cek("POST /explore", explore)

    def analyze() -> str:
        body = {"targets": [{"prodi_id": t, "jalur": [jalur]} for t in target]}
        r = client.post(f"{API}/analyze", json=body, headers=auth())
        _harap(r, 200)
        hasil_analisis = r.json()["hasil"]
        assert len(hasil_analisis) == len(target), r.text[:200]
        return f"{len(hasil_analisis)} hasil {jalur}"

    cek("POST /analyze", analyze)

    def strategy() -> str:
        body = {"jalur": jalur, "pilihan": [{"prodi_id": t} for t in target], "simpan": True}
        r = client.post(f"{API}/strategy", json=body, headers=auth())
        _harap(r, 200)
        assert r.json()["disimpan"] is True
        return "strategi tersimpan"

    strategi_ok = cek("POST /strategy", strategy)

    def summary() -> str:
        r = client.post(f"{API}/summary", json={}, headers=auth())
        _harap(r, 200)
        assert isinstance(r.json(), dict) and r.json(), "ringkasan kosong"
        return "ringkasan terbentuk"

    if strategi_ok:
        cek("POST /summary", summary)

    def query() -> str:
        r = client.post(f"{API}/query", json={"pertanyaan": PERTANYAAN_UJI}, headers=auth())
        _harap(r, 200)
        d = r.json()
        assert KUNCI_QUERY <= d.keys(), f"kunci respons kurang: {KUNCI_QUERY - d.keys()}"
        if d["fallback"]:
            return "fallback (LLM/embedding belum tersedia atau dokumen belum diingest)"
        return f"{len(d['sumber'])} sumber, yakin={d['yakin']}"

    cek("POST /query", query)

    # ---- admin: hanya penolakan ----
    def admin() -> str:
        r = client.post(f"{API}/admin/ingest", json={"tipe": "ketentuan", "payload": []})
        if admin_key is None:
            _harap_salah_satu(r, {401, 404})
            return f"tanpa kunci ditolak ({r.status_code})"
        _harap(r, 401)
        salah = client.post(
            f"{API}/admin/ingest",
            json={"tipe": "ketentuan", "payload": []},
            headers={"X-Admin-Key": admin_key + "-salah"},
        )
        _harap(salah, 401)
        # Kunci benar + badan tidak valid: lolos autentikasi lalu ditolak validasi (tanpa efek).
        benar = client.post(
            f"{API}/admin/ingest", json={"tipe": "tidak-ada"}, headers={"X-Admin-Key": admin_key}
        )
        _harap(benar, 422)
        return "kunci kosong/salah 401, kunci benar lolos autentikasi"

    cek("POST /admin/ingest (hanya penolakan)", admin)

    # ---- lingkungan produksi / reverse proxy ----
    if prod:

        def docs_mati() -> str:
            for path in ("/docs", "/redoc", "/openapi.json", f"{API}/docs", f"{API}/openapi.json"):
                _harap(client.get(path), 404)
            return "dokumentasi interaktif tidak terekspos"

        cek("dokumentasi API mati di produksi", docs_mati)

    if lewat_proxy:

        def header_proxy() -> str:
            h = state["health_headers"]
            assert h.get("x-content-type-options") == "nosniff", "X-Content-Type-Options hilang"
            assert "no-store" in h.get("cache-control", ""), "Cache-Control: no-store hilang"
            server = h.get("server", "")
            assert not re.search(r"\d", server), f"versi server bocor: {server}"
            return "header keamanan ada"

        cek("header keamanan nginx", header_proxy)

        def akar_tidak_terproksi() -> str:
            _harap(client.get("/"), 404)
            return "/ tidak diteruskan ke API"

        cek("jalur di luar /api tidak diteruskan", akar_tidak_terproksi)

    # ---- hapus data ----
    def hapus() -> str:
        r = client.delete(f"{API}/session", headers=auth())
        _harap(r, 204)
        _harap(client.get(f"{API}/profile", headers=auth()), 401)
        return "sesi dan datanya terhapus"

    cek("DELETE /session (hapus data saya)", hapus)
    return hasil


def cetak(hasil: list[Hasil]) -> int:
    gagal = [h for h in hasil if not h.ok]
    for h in hasil:
        print(f"[{'OK' if h.ok else 'GAGAL'}] {h.nama}" + (f" - {h.detail}" if h.detail else ""))
    print(f"\n{len(hasil) - len(gagal)}/{len(hasil)} pemeriksaan lulus")
    return 1 if gagal else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--persona", default="dimas")
    ap.add_argument("--jalur", choices=["SNBP", "SNBT"], default="SNBT")
    ap.add_argument("--prod", action="store_true", help="harap /docs dan /openapi.json mati")
    ap.add_argument("--lewat-proxy", action="store_true", help="periksa header keamanan nginx")
    ap.add_argument("--admin-key", default=None, help="kunci admin untuk uji penolakan")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="jangan verifikasi TLS (sertifikat staging/self-signed)",
    )
    a = ap.parse_args(argv)
    with httpx.Client(base_url=a.base_url, timeout=a.timeout, verify=not a.insecure) as c:
        hasil = jalankan(
            c,
            persona=a.persona,
            jalur=a.jalur,
            prod=a.prod,
            lewat_proxy=a.lewat_proxy,
            admin_key=a.admin_key,
        )
    return cetak(hasil)


if __name__ == "__main__":
    sys.exit(main())
