"""Smoke test alur demo ke server yang berjalan (container atau VPS), dengan tabel status dan waktu.

    python -m scripts.smoke_container --base-url http://127.0.0.1:8001 --admin-key KUNCI \\
        --url-tanpa-admin http://127.0.0.1:8002

Memakai persona fiktif Rani (config/personas) dan menghapus sesinya di akhir. Uji admin:
- tanpa header X-Admin-Key dan dengan kunci salah harus 401 (server ber-ADMIN_KEY);
- dengan kunci benar harus 200 (payload kosong, tidak mengubah data);
- `--url-tanpa-admin` = server yang ADMIN_KEY-nya kosong: harus 404 walau header dikirim.
Kode keluar 1 bila ada baris yang tidak sesuai harapan. Tidak mencetak kunci apa pun.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import ROOT_DIR

API = "/api/v1"
CONSENT = {"consent": True, "consent_version": "2026-10-13"}
Q_DALAM = "Berapa jumlah pilihan program studi di SNBP 2026?"
Q_LUAR = "Berapa skor UTBK minimal untuk diterima di Kedokteran UI?"


@dataclass
class Baris:
    nama: str
    metode: str
    path: str
    status: int | None
    harapan: int
    detik: float
    catatan: str = ""

    @property
    def ok(self) -> bool:
        return self.status == self.harapan


def persona(nama: str) -> dict[str, Any]:
    return json.loads((ROOT_DIR / "config" / "personas" / f"{nama}.json").read_text("utf-8"))


def jalankan(
    base_url: str,
    *,
    admin_key: str | None,
    url_tanpa_admin: str | None,
    nama_persona: str = "rani",
    timeout: float = 60.0,
    prod: bool = True,
) -> list[Baris]:
    tabel: list[Baris] = []
    p = persona(nama_persona)
    target = (p.get("strategi_demo") or {}).get("SNBT") or [
        "ui-ilmu-komputer",
        "ui-teknik-industri",
    ]
    token = ""

    def tembak(
        c: httpx.Client,
        nama: str,
        metode: str,
        path: str,
        harapan: int = 200,
        *,
        catat=None,
        **kw: Any,
    ) -> httpx.Response | None:
        awal = time.perf_counter()
        try:
            r = c.request(metode, API + path, **kw)
            status, teks = r.status_code, ""
        except httpx.HTTPError as exc:
            r, status, teks = None, None, f"{type(exc).__name__}"
        detik = time.perf_counter() - awal
        if r is not None and catat is not None and r.status_code == harapan:
            try:
                teks = catat(r.json()) if r.content else ""
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                teks = f"respons tak terduga ({type(exc).__name__})"
        tabel.append(Baris(nama, metode, path, status, harapan, detik, teks))
        return r

    with httpx.Client(base_url=base_url, timeout=timeout) as c:
        tembak(c, "Health", "GET", "/health", catat=lambda d: f"db {d['status']}")
        r = tembak(c, "Buat sesi", "POST", "/session", 201, json=CONSENT)
        if r is None or r.status_code != 201:
            return tabel
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        tembak(
            c,
            f"Profil persona {nama_persona.capitalize()}",
            "PUT",
            "/profile",
            json=p["profil"],
            headers=h,
        )
        tembak(
            c,
            "Analyze",
            "POST",
            "/analyze",
            json={"targets": [{"prodi_id": t, "jalur": ["SNBT"]} for t in target]},
            headers=h,
            catat=lambda d: ", ".join(
                f"{x.get('prodi_id')}:{(x.get('penilaian') or {}).get('kategori', '-')}"
                for x in d["hasil"]
            ),
        )
        tembak(
            c,
            "Strategy (simpan)",
            "POST",
            "/strategy",
            json={"jalur": "SNBT", "pilihan": [{"prodi_id": t} for t in target], "simpan": True},
            headers=h,
            catat=lambda d: f"disimpan={d['disimpan']}",
        )
        tembak(
            c,
            "Summary",
            "POST",
            "/summary",
            json={},
            headers=h,
            catat=lambda d: f"narasi_fallback={d.get('narasi_fallback')}",
        )
        tembak(
            c,
            "Query dalam cakupan",
            "POST",
            "/query",
            json={"pertanyaan": Q_DALAM},
            headers=h,
            catat=lambda d: (
                f"yakin={d['yakin']} fallback={d['fallback']} sumber={len(d['sumber'])} terkait={len(d['dokumen_terkait'])}"
            ),
        )
        tembak(
            c,
            "Query di luar cakupan",
            "POST",
            "/query",
            json={"pertanyaan": Q_LUAR},
            headers=h,
            catat=lambda d: (
                f"yakin={d['yakin']} fallback={d['fallback']} sumber={len(d['sumber'])} terkait={len(d['dokumen_terkait'])}"
            ),
        )
        tembak(
            c,
            "Explore",
            "POST",
            "/explore",
            json={"top_n": 3},
            headers=h,
            catat=lambda d: "teratas " + d["rekomendasi"][0]["rumpun"],
        )
        q = tembak(
            c,
            "RIASEC questions",
            "GET",
            "/riasec/questions",
            catat=lambda d: f"{len(d['item'])} butir, contoh={d['instrumen_contoh']}",
        )
        if q is not None and q.status_code == 200:
            item = q.json()["item"]
            skala = q.json()["skala"]
            rentang = skala["maks"] - skala["min"] + 1
            jawaban = {b["id"]: skala["min"] + (i % rentang) for i, b in enumerate(item)}
            tembak(
                c,
                "RIASEC submit",
                "POST",
                "/riasec/submit",
                json={"jawaban": jawaban, "simpan": True},
                headers=h,
                catat=lambda d: f"kode={d['holland_code']} keyakinan={d['keyakinan']}",
            )
        tembak(c, "Hapus sesi", "DELETE", "/session", 204, headers=h)
        if prod:  # dokumentasi interaktif harus mati di produksi
            for path in ("/docs", "/openapi.json"):
                awal = time.perf_counter()
                r2 = c.get(path)
                tabel.append(
                    Baris(
                        "Dokumentasi mati (prod)",
                        "GET",
                        path,
                        r2.status_code,
                        404,
                        time.perf_counter() - awal,
                    )
                )

        # ---- admin (server ber-ADMIN_KEY) ----
        tembak(
            c,
            "Admin ingest tanpa X-Admin-Key",
            "POST",
            "/admin/ingest",
            401 if admin_key else 404,
            json={"tipe": "profesi", "payload": []},
        )
        if admin_key:
            tembak(
                c,
                "Admin ingest kunci salah",
                "POST",
                "/admin/ingest",
                401,
                json={"tipe": "profesi", "payload": []},
                headers={"X-Admin-Key": admin_key + "-salah"},
            )
            tembak(
                c,
                "Admin ingest kunci benar (payload kosong)",
                "POST",
                "/admin/ingest",
                200,
                json={"tipe": "profesi", "payload": []},
                headers={"X-Admin-Key": admin_key},
            )

    # ---- admin (server tanpa ADMIN_KEY) ----
    if url_tanpa_admin:
        with httpx.Client(base_url=url_tanpa_admin, timeout=timeout) as c2:
            tembak(
                c2,
                "Admin ingest, ADMIN_KEY kosong",
                "POST",
                "/admin/ingest",
                404,
                json={"tipe": "profesi", "payload": []},
            )
            tembak(
                c2,
                "Admin ingest, ADMIN_KEY kosong + header",
                "POST",
                "/admin/ingest",
                404,
                json={"tipe": "profesi", "payload": []},
                headers={"X-Admin-Key": "tebakan"},
            )
    return tabel


def cetak(tabel: list[Baris]) -> int:
    print("| Endpoint | Status | Waktu | Hasil |")
    print("|---|---|---|---|")
    for b in tabel:
        tanda = "" if b.ok else f" (HARAP {b.harapan})"
        print(
            f"| {b.metode} {b.path}: {b.nama} | {b.status}{tanda} | {b.detik:.2f} s | "
            f"{'OK' if b.ok else 'GAGAL'}{'; ' + b.catatan if b.catatan else ''} |"
        )
    gagal = [b for b in tabel if not b.ok]
    print(f"\n{len(tabel) - len(gagal)}/{len(tabel)} sesuai harapan")
    return 1 if gagal else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-key", default=None, help="ADMIN_KEY server (untuk uji 401/200)")
    ap.add_argument(
        "--url-tanpa-admin", default=None, help="server dengan ADMIN_KEY kosong (harus 404)"
    )
    ap.add_argument("--persona", default="rani")
    ap.add_argument("--dev", action="store_true", help="server APP_ENV=dev: lewati cek /docs mati")
    a = ap.parse_args(argv)
    return cetak(
        jalankan(
            a.base_url,
            admin_key=a.admin_key,
            url_tanpa_admin=a.url_tanpa_admin,
            nama_persona=a.persona,
            prod=not a.dev,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
