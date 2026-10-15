"""Siapkan demo persona (default Rani): sesi berumur panjang, cache LLM hangat, uji konsistensi.

    # 1) Sesi demo + profil persona + strategi_demo, satu perintah. Cetak token untuk dashboard/video.
    python -m scripts.siapkan_demo --base-url http://127.0.0.1:8000

    # 2) Sama, lalu hangatkan cache LLM (summary, /query, "Kenapa?") dan buktikan jawaban kedua dari cache.
    python -m scripts.siapkan_demo --base-url http://127.0.0.1:8000 --hangatkan

    # 3) Ulangi alur demo 3 kali dan bandingkan hasil keputusan dan narasi (sesi sekali pakai).
    python -m scripts.siapkan_demo --base-url http://127.0.0.1:8000 --uji-konsistensi 3 [--kosongkan-cache]

Sesi demo dibuat langsung di basis data (butuh DATABASE_URL yang sama dengan server; jalankan di dalam
kontainer `api` atau dari mesin yang bisa menjangkau DB) memakai `sesi.ttl_demo_jam` (bawaan 72 jam),
bukan lewat POST /session, jadi umur sesi publik tetap `sesi.ttl_jam`. Semua data persona fiktif.

Narasi dan jawaban /query SELALU dari LLM; skrip ini tidak menulis teks sendiri. "Menghangatkan" hanya
memanggil API agar hasil LLM tersimpan di `llm_cache` (kunci = model + prompt + fakta/pertanyaan, bebas
sesi), sehingga pemanggilan berikutnya (rekaman video) dijawab dari cache selama TTL cache (`llm.cache_ttl_detik`).
Cache tidak berlaku bila model, prompt, atau data berubah.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_app_config, get_settings
from app.db.session import make_engine
from app.services import persona as modul_persona
from app.services.persona import Persona
from app.services.sessions import buat_sesi

API = "/api/v1"
CONSENT_DEMO = "demo-persona"
PERTANYAAN_BAWAAN = (
    "Apa saja dokumen yang perlu disiapkan untuk SNBP?",
    "Apa syarat mengikuti SNBT?",
)
PERTANYAAN_KENAPA = "Kenapa hasilnya begitu?"


class DemoError(RuntimeError):
    pass


@dataclass
class Langkah:
    nama: str
    detik: float


@dataclass
class HasilAlur:
    langkah: list[Langkah] = field(default_factory=list)
    keputusan_hash: str = ""
    narasi: str = ""
    narasi_fallback: bool | None = None
    jawaban: dict[str, str] = field(default_factory=dict)  # pertanyaan -> jawaban
    fallback_llm: int = 0  # jumlah respons LLM yang jatuh ke teks template
    tidak_yakin: list[str] = field(default_factory=list)  # pertanyaan /query yang yakin=false

    def total_llm(self) -> float:
        return sum(
            item.detik for item in self.langkah if item.nama.startswith(("summary", "query"))
        )


def _harap(r: httpx.Response, kode: int, apa: str) -> Any:
    if r.status_code != kode:
        raise DemoError(f"{apa} gagal (HTTP {r.status_code}): {r.text[:160]}")
    return r.json() if r.content else {}


def buat_sesi_demo(database_url: str, ttl_jam: int) -> tuple[str, str]:
    """Sesi persona demo di DB dengan umur `ttl_jam`. Mengembalikan (token, berlaku_sampai ISO)."""
    engine = make_engine(database_url)
    try:
        with Session(engine) as db:
            token, sesi = buat_sesi(db, consent_version=CONSENT_DEMO, ttl_jam=ttl_jam)
            return token, sesi.expires_at.isoformat(timespec="seconds")
    finally:
        engine.dispose()


def muat_persona_ke_sesi(
    client: httpx.Client, headers: dict[str, str], p: Persona
) -> dict[str, str]:
    """Profil persona dan strategi_demo ke sesi (seperti tombol 'Muat persona demo')."""
    _harap(client.put(f"{API}/profile", json=p.profil, headers=headers), 200, "PUT /profile")
    tersimpan: dict[str, str] = {}
    for jalur, ids in p.strategi_demo.items():
        body = {"jalur": jalur, "pilihan": [{"prodi_id": i} for i in ids], "simpan": True}
        d = _harap(
            client.post(f"{API}/strategy", json=body, headers=headers), 200, f"strategy {jalur}"
        )
        tersimpan[jalur] = d["strategy_id"]
    return tersimpan


def _kanon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def alur_demo(
    client: httpx.Client, headers: dict[str, str], p: Persona, pertanyaan: tuple[str, ...]
) -> HasilAlur:
    """Satu putaran alur demo: analyze, strategy, summary, /query, dan 'Kenapa?'."""
    hasil = HasilAlur()
    bagian_keputusan: list[Any] = []

    def panggil(nama: str, metode: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        awal = time.perf_counter()
        r = client.request(metode, f"{API}{path}", json=body, headers=headers)
        hasil.langkah.append(Langkah(nama, time.perf_counter() - awal))
        return _harap(r, 200, nama)

    for jalur, ids in p.strategi_demo.items():
        a = panggil(
            f"analyze {jalur}",
            "POST",
            "/analyze",
            {"targets": [{"prodi_id": i, "jalur": [jalur]} for i in ids]},
        )
        bagian_keputusan.append(a)
        s = panggil(
            f"strategy {jalur}",
            "POST",
            "/strategy",
            {"jalur": jalur, "pilihan": [{"prodi_id": i} for i in ids], "simpan": False},
        )
        s.pop("strategy_id", None)
        bagian_keputusan.append(s)

    ringkasan = panggil("summary (narasi LLM)", "POST", "/summary", {})
    hasil.narasi = ringkasan.get("narasi", "")
    hasil.narasi_fallback = ringkasan.get("narasi_fallback")
    hasil.fallback_llm += 1 if ringkasan.get("narasi_fallback") else 0
    keputusan_summary = {
        k: v
        for k, v in ringkasan.items()
        if k not in ("dihasilkan_pada", "narasi", "narasi_fallback")
    }
    # Hanya metadata yang dibuang (waktu dan id unik per sesi); semua isi keputusan tetap dibandingkan.
    keputusan_summary["strategi"] = [
        {k: v for k, v in s.items() if k not in ("strategy_id", "disimpan_pada")}
        for s in ringkasan.get("strategi", [])
    ]
    bagian_keputusan.append(keputusan_summary)

    for q in pertanyaan:
        d = panggil(f"query: {q[:38]}", "POST", "/query", {"pertanyaan": q})
        hasil.jawaban[q] = d["jawaban"]
        hasil.fallback_llm += 1 if d.get("fallback") else 0
        if not d.get("yakin"):
            hasil.tidak_yakin.append(q)

    jalur0 = next(iter(p.strategi_demo), None)
    if jalur0 and p.strategi_demo[jalur0]:
        body = {
            "pertanyaan": PERTANYAAN_KENAPA,
            "mode": "jelaskan",
            "konteks": {"prodi_id": p.strategi_demo[jalur0][0], "jalur": jalur0},
        }
        d = panggil("query: Kenapa? (jelaskan)", "POST", "/query", body)
        hasil.jawaban[PERTANYAAN_KENAPA] = d["jawaban"]
        hasil.fallback_llm += 1 if d.get("fallback") else 0

    hasil.keputusan_hash = hashlib.sha256(_kanon(bagian_keputusan).encode()).hexdigest()[:16]
    return hasil


def kemiripan(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def kosongkan_cache(database_url: str) -> int:
    engine = make_engine(database_url)
    try:
        with engine.begin() as conn:
            return conn.execute(text("DELETE FROM llm_cache")).rowcount or 0
    finally:
        engine.dispose()


def cetak_waktu(judul: str, hasil: HasilAlur) -> None:
    print(f"\n{judul}")
    print("| Langkah | Waktu |")
    print("|---|---|")
    for item in hasil.langkah:
        print(f"| {item.nama} | {item.detik:.2f} s |")
    print(
        f"Total panggilan LLM-relevan: {hasil.total_llm():.2f} s; jatuh ke template: {hasil.fallback_llm}"
    )


def laporan_konsistensi(daftar: list[HasilAlur]) -> bool:
    print("\n== Konsistensi antar putaran ==")
    sama = len({h.keputusan_hash for h in daftar}) == 1
    print(
        f"Hasil keputusan (analyze, strategy, ringkasan tanpa narasi) identik: {'YA' if sama else 'TIDAK'}"
    )
    print("Hash keputusan: " + ", ".join(h.keputusan_hash for h in daftar))
    pasangan = [(i, j) for i in range(len(daftar)) for j in range(i + 1, len(daftar))]
    if pasangan:
        nar = [kemiripan(daftar[i].narasi, daftar[j].narasi) for i, j in pasangan]
        print(
            f"Narasi /summary: kemiripan teks antar putaran min {min(nar):.2f}, maks {max(nar):.2f} (1.00 = persis sama)"
        )
        pertanyaan = daftar[0].jawaban.keys()
        for q in pertanyaan:
            r = [
                kemiripan(daftar[i].jawaban.get(q, ""), daftar[j].jawaban.get(q, ""))
                for i, j in pasangan
            ]
            print(f"  jawaban '{q[:44]}': min {min(r):.2f}, maks {max(r):.2f}")
        print(
            f"Narasi dari LLM di semua putaran: {all(h.narasi_fallback is False for h in daftar)}"
        )
    return sama


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--persona", default="rani")
    ap.add_argument("--database-url", default=None, help="bawaan: DATABASE_URL dari .env/env")
    ap.add_argument("--ttl-jam", type=int, default=None, help="bawaan: sesi.ttl_demo_jam")
    ap.add_argument(
        "--hangatkan", action="store_true", help="panggil alur LLM dua kali; kedua dari cache"
    )
    ap.add_argument(
        "--uji-konsistensi", type=int, metavar="N", help="ulangi alur N kali (sesi sekali pakai)"
    )
    ap.add_argument(
        "--kosongkan-cache", action="store_true", help="hapus llm_cache sebelum tiap putaran"
    )
    ap.add_argument("--pertanyaan", action="append", help="pertanyaan /query (boleh berulang)")
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args(argv)

    settings, config = get_settings(), get_app_config()
    db_url = a.database_url or settings.database_url
    pertanyaan = tuple(a.pertanyaan) if a.pertanyaan else PERTANYAAN_BAWAAN
    try:
        p = modul_persona.muat(a.persona)
    except modul_persona.PersonaError as exc:
        print(f"Persona: {exc}", file=sys.stderr)
        return 2

    try:
        with httpx.Client(base_url=a.base_url, timeout=a.timeout) as client:
            if a.uji_konsistensi:
                daftar: list[HasilAlur] = []
                for n in range(1, a.uji_konsistensi + 1):
                    if a.kosongkan_cache:
                        kosongkan_cache(db_url)
                    sesi = _harap(
                        client.post(
                            f"{API}/session",
                            json={"consent": True, "consent_version": CONSENT_DEMO},
                        ),
                        201,
                        "POST /session",
                    )
                    h = {"Authorization": f"Bearer {sesi['token']}"}
                    muat_persona_ke_sesi(client, h, p)
                    hasil = alur_demo(client, h, p, pertanyaan)
                    client.delete(f"{API}/session", headers=h)
                    cetak_waktu(
                        f"Putaran {n}" + (" (cache dikosongkan)" if a.kosongkan_cache else ""),
                        hasil,
                    )
                    daftar.append(hasil)
                return 0 if laporan_konsistensi(daftar) else 1

            ttl = a.ttl_jam or config.sesi.ttl_demo_jam
            token, sampai = buat_sesi_demo(db_url, ttl)
            h = {"Authorization": f"Bearer {token}"}
            tersimpan = muat_persona_ke_sesi(client, h, p)
            print(f"[OK] Sesi demo '{p.id}' ({p.nama}) berlaku {ttl} jam, sampai {sampai}")
            print(f"     Authorization: Bearer {token}")
            print(f"     strategi tersimpan: {tersimpan}")
            if a.hangatkan:
                # Jawaban tidak yakin tersimpan di cache seperti jawaban lain. Kosongkan cache dan coba lagi
                # (sampai 3 kali) agar rekaman tidak memutar jawaban "belum menemukan" yang kebetulan.
                for percobaan in range(1, 4):
                    pertama = alur_demo(client, h, p, pertanyaan)
                    if not (pertama.tidak_yakin or pertama.fallback_llm):
                        break
                    print(
                        f"Percobaan {percobaan}: belum bersih (tidak yakin: {pertama.tidak_yakin or '-'}, "
                        f"template: {pertama.fallback_llm}); cache dikosongkan lalu diulang."
                    )
                    kosongkan_cache(db_url)
                kedua = alur_demo(client, h, p, pertanyaan)
                cetak_waktu("Putaran 1 (mengisi cache)", pertama)
                cetak_waktu("Putaran 2 (seharusnya dari cache)", kedua)
                sama = pertama.narasi == kedua.narasi and pertama.jawaban == kedua.jawaban
                print(
                    f"\nNarasi dan jawaban putaran 2 persis sama dengan putaran 1: {'YA' if sama else 'TIDAK'}"
                )
                if pertama.fallback_llm or kedua.fallback_llm or pertama.tidak_yakin:
                    print(
                        "PERINGATAN: ada jawaban yang tidak yakin atau jatuh ke template setelah 3 percobaan "
                        f"({pertama.tidak_yakin or 'template'}). Ganti pertanyaan (--pertanyaan) atau ulangi nanti."
                    )
                    return 1
                return 0 if sama else 1
    except (DemoError, httpx.HTTPError) as exc:
        print(f"[GAGAL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
