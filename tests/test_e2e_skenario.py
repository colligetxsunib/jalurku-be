"""Task 17: alur end-to-end Skenario A (belum punya target) dan B (sudah punya target), PRD bagian 5.

Satu alur utuh lewat API: sesi, profil, katalog, analisis, strategi, what-if, ringkasan, tanya-jawab,
lalu hapus data. Persona fiktif dari config/personas. LLM diganti FakeLLM (tanpa jaringan).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import AppConfig
from app.main import create_app
from app.services import persona as modul_persona
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.helpers import CONSENT, SEED_DIR  # noqa: F401  (SEED_DIR memastikan helper termuat)

pytestmark = pytest.mark.db

API = "/api/v1"
IK, TI, TE, TM = "ui-ilmu-komputer", "ui-teknik-industri", "ui-teknik-elektro", "ui-teknik-mesin"
AKUN, VOK_D3 = "ui-akuntansi", "ui-v-akuntansi-d3"
KEMBAR_PERSEN = re.compile(r"\d\s*%|probabilitas|peluang\s+\d", re.IGNORECASE)


class Alur:
    """Pembungkus klien: mencatat setiap teks respons untuk pemeriksaan lintas-endpoint."""

    def __init__(self, c: TestClient) -> None:
        self.c = c
        self.teks: list[str] = []
        self.h: dict[str, str] = {}

    def _catat(self, r):
        def jelajah(x: Any):
            if isinstance(x, str):
                if not x.startswith(("http://", "https://")):  # URL boleh memuat %20
                    self.teks.append(x)
            elif isinstance(x, dict):
                for v in x.values():
                    jelajah(v)
            elif isinstance(x, list):
                for v in x:
                    jelajah(v)

        if r.headers.get("content-type", "").startswith("application/json"):
            jelajah(r.json())
        return r

    def post(self, path, **kw):
        return self._catat(self.c.post(f"{API}{path}", headers=self.h, **kw))

    def put(self, path, **kw):
        return self._catat(self.c.put(f"{API}{path}", headers=self.h, **kw))

    def get(self, path, **kw):
        return self._catat(self.c.get(f"{API}{path}", headers=self.h, **kw))

    def delete(self, path, **kw):
        return self.c.delete(f"{API}{path}", headers=self.h, **kw)

    def mulai(self, nama_persona: str) -> Any:
        r = self.c.post(f"{API}/session", json=CONSENT)
        assert r.status_code == 201, r.text
        self.h = {"Authorization": f"Bearer {r.json()['token']}"}
        p = modul_persona.muat(nama_persona)
        r = self.put("/profile", json=p.profil)
        assert r.status_code == 200, r.text
        return p

    def bersih_dari_klaim_peluang(self) -> None:
        salah = [t for t in self.teks if KEMBAR_PERSEN.search(t)]
        assert not salah, f"klaim persentase/peluang ditemukan: {salah[:3]}"


@pytest.fixture()
def alur(clean_db: Engine, app_config: AppConfig) -> Iterator[Alur]:
    from sqlalchemy.orm import Session

    from app.ingest.service import ingest_direktori

    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    fake = FakeLLM(teks="Hasil ini berasal dari mesin aturan dan bersifat indikatif.")
    app = create_app(make_settings(), app_config, clean_db, llm_client=fake)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield Alur(c)


def hitung(engine: Engine, tabel: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {tabel}")).scalar()  # noqa: S608


def temuan(d: dict, kode: str) -> dict | None:
    return next((t for t in d["temuan"] if t["kode"] == kode), None)


# =============================================================================== Skenario A


def test_skenario_a_belum_punya_target(alur: Alur, clean_db: Engine):
    """Rani: menelusuri katalog, menganalisis kandidat, menyusun strategi SNBT, meringkas, menghapus."""
    rani = alur.mulai("rani")

    # Profil dan kekurangan data (tidak menebak)
    prof = alur.get("/profile").json()
    assert prof["profil"]["provinsi"] == "Jawa Barat" and set(prof["data_kurang"]) >= {"SNBP"}
    assert alur.get("/session").json()["sisa_detik"] > 0

    # Eksplorasi (Skenario A): rumpun yang cocok + PTN pembukanya + kelayakan SNBT per rumpun
    e = alur.post("/explore", json={"top_n": 3, "jalur": "SNBT"}).json()
    assert len(e["rekomendasi"]) == 3 and e["data_kurang"] == []
    teratas = e["rekomendasi"][0]
    assert teratas["rumpun"] in ("Teknologi Informasi", "Teknik") and teratas["contoh_profesi"]
    assert teratas["kelayakan"]["gate"] == "lolos" and teratas["ptn"]
    dari_explore = teratas["prodi_ids"][:2]
    r = alur.post(
        "/analyze", json={"targets": [{"prodi_id": p, "jalur": ["SNBT"]} for p in dari_explore]}
    )
    assert r.status_code == 200  # shortlist dari eksplorasi langsung bisa dianalisis
    # Telusuri katalog: filter rumpun lalu buka detail
    daftar = alur.get("/catalog/prodi", params={"rumpun": "Teknologi Informasi"}).json()
    assert daftar["total"] >= 1 and IK in {p["id"] for p in daftar["items"]}
    detail = alur.get(f"/catalog/prodi/{IK}")
    assert detail.status_code == 200
    assert alur.get("/catalog/ptn", params={"provinsi": "Jawa Barat"}).json()["total"] >= 1

    # Analisis kandidat: tiap hasil membawa sumber, status verifikasi, dan label indikatif
    kandidat = [IK, TI, TE, AKUN, VOK_D3]
    hasil = alur.post(
        "/analyze", json={"targets": [{"prodi_id": p, "jalur": ["SNBT"]} for p in kandidat]}
    ).json()["hasil"]
    assert [h["prodi_id"] for h in hasil] == kandidat
    for h in hasil:
        assert h["gate"]["status"] == "lolos"
        assert h["sumber"] and "terakhir_diverifikasi" in h
        assert h["status_verifikasi"] == "belum_diverifikasi"  # data belum diverifikasi manusia
        assert h["penilaian"]["indikatif"] is True
        assert h["penilaian"]["kategori"] in ("reach", "match", "safe")
    sesuai = {h["prodi_id"]: h["penilaian"]["kategori"] for h in hasil}
    for pid, harap in rani.harapan.penilaian["SNBT"].items():
        assert sesuai[pid] == harap  # sama dengan persona golden

    # Strategi melanggar aturan komposisi SNBT: 3 pilihan Sarjana tanpa vokasi
    salah = alur.post(
        "/strategy",
        json={
            "jalur": "SNBT",
            "pilihan": [{"prodi_id": p} for p in (IK, TI, TE)],
            "shortlist": [VOK_D3],
        },
    ).json()
    pelanggaran = temuan(salah, "butuh_vokasi")
    assert pelanggaran and pelanggaran["tingkat"] == "pelanggaran"
    assert any(
        s["dengan"] == VOK_D3 for s in pelanggaran["saran_swap"]
    )  # saran swap dari shortlist

    # Strategi yang benar (2 Sarjana + 1 D3) lalu simpan
    benar = alur.post(
        "/strategy",
        json={
            "jalur": "SNBT",
            "pilihan": [{"prodi_id": p} for p in (IK, TI, VOK_D3)],
            "simpan": True,
        },
    ).json()
    assert temuan(benar, "komposisi_snbt_tidak_valid") is None and benar["disimpan"] is True
    assert benar["komposisi"]["jumlah"] == 3 and benar["komposisi"]["d3"] == 1

    # What-if tidak menyimpan apa pun dan tidak mengubah profil
    sebelum = (hitung(clean_db, "strategies"), alur.get("/profile").json()["profil"])
    wi = alur.post(
        "/strategy",
        json={
            "jalur": "SNBT",
            "pilihan": [{"prodi_id": p} for p in (IK, TI, VOK_D3)],
            "override": {"tahun_lulus": 2023},
            "simpan": True,  # dipaksa false saat ada override
        },
    ).json()
    assert wi["disimpan"] is False
    assert {h["gate"]["status"] for h in wi["hasil"]} == {"tidak_memenuhi_syarat"}
    assert (hitung(clean_db, "strategies"), alur.get("/profile").json()["profil"]) == sebelum

    # Ringkasan siap cetak dari strategi tersimpan
    s = alur.post("/summary", json={}).json()
    assert [p["prodi_id"] for p in s["pilihan_akhir"]] == [IK, TI, VOK_D3]
    assert len(s["dokumen_syarat"]) == 8 and all(d["sumber_url"] for d in s["dokumen_syarat"])
    assert s["fokus_persiapan"] and s["catatan"] and s["narasi"]

    # Tanya-jawab: penjelasan "Kenapa?" (mode jelaskan) dan pertanyaan di luar cakupan
    q = alur.post(
        "/query",
        json={
            "pertanyaan": "Kenapa hasilnya begitu?",
            "mode": "jelaskan",
            "konteks": {"prodi_id": IK, "jalur": "SNBT"},
        },
    ).json()
    assert q["mode"] == "jelaskan" and q["jenis_jawaban"] == "penjelasan" and q["yakin"] is True
    luar = alur.post(
        "/query", json={"pertanyaan": "Berapa skor UTBK minimal untuk diterima di Kedokteran UI?"}
    ).json()
    assert luar["yakin"] is False  # jujur: tidak ada dokumen resmi yang menjawab

    alur.bersih_dari_klaim_peluang()

    # Hapus data saya: sesi dan seluruh data turunannya hilang, token tidak berlaku lagi
    assert alur.delete("/session").status_code == 204
    assert alur.get("/profile").status_code == 401
    for tabel in ("sessions", "profiles", "strategies", "query_logs"):
        assert hitung(clean_db, tabel) == 0, tabel


# =============================================================================== Skenario B


def test_skenario_b_sudah_punya_target(alur: Alur, clean_db: Engine):
    """Dimas: target teknik UI di SNBP dan SNBT, cek syarat, batas pilihan, what-if, ringkasan."""
    dimas = alur.mulai("dimas")
    assert dimas.target_prodi_ids == [TI, TE, TM]

    # Dua jalur sekaligus untuk tiga target
    hasil = alur.post(
        "/analyze",
        json={
            "targets": [{"prodi_id": p, "jalur": ["SNBP", "SNBT"]} for p in dimas.target_prodi_ids]
        },
    ).json()["hasil"]
    assert len(hasil) == 6
    snbp = [h for h in hasil if h["jalur"] == "SNBP"]
    snbt = [h for h in hasil if h["jalur"] == "SNBT"]
    assert {h["gate"]["status"] for h in snbp + snbt} == {"lolos"}
    assert {h["penilaian"]["kategori"] for h in snbp} == {"belum_ada_acuan"}  # tanpa data SNBP
    assert all(h["penilaian"]["tier"] for h in snbp)  # tier siswa tetap ditampilkan, tanpa menebak
    assert {h["penilaian"]["kategori"] for h in snbt} <= {"reach", "match", "safe"}

    # Aturan resmi: SNBP maksimal 2 pilihan; SNBT maksimal 2 Sarjana bila 3-4 pilihan
    tiga = alur.post(
        "/strategy", json={"jalur": "SNBP", "pilihan": [{"prodi_id": p} for p in (TI, TE, TM)]}
    ).json()
    assert temuan(tiga, "melebihi_batas_pilihan")["tingkat"] == "pelanggaran"
    empat = alur.post(
        "/strategy",
        json={
            "jalur": "SNBT",
            "pilihan": [{"prodi_id": p} for p in (TI, TE, TM, VOK_D3)],
            "shortlist": ["ui-v-fisioterapi"],
        },
    ).json()
    assert temuan(empat, "komposisi_snbt_tidak_valid")["tingkat"] == "pelanggaran"

    # Simpan dua jalur
    for jalur, ids in (("SNBP", (TI, TE)), ("SNBT", (TI, TE, VOK_D3))):
        r = alur.post(
            "/strategy",
            json={"jalur": jalur, "pilihan": [{"prodi_id": p} for p in ids], "simpan": True},
        ).json()
        assert r["disimpan"] is True and not [
            t for t in r["temuan"] if t["tingkat"] == "pelanggaran"
        ]

    # What-if: peringkat satu tingkat di luar kuota membuat SNBP gugur, profil tersimpan tidak berubah
    wi = alur.post(
        "/analyze",
        json={
            "targets": [{"prodi_id": TI, "jalur": ["SNBP"]}],
            "override": {"peringkat_sekolah": 31},
        },
    ).json()["hasil"][0]
    assert wi["gate"]["status"] == "tidak_memenuhi_syarat" and wi["penilaian"] is None
    assert alur.get("/profile").json()["profil"]["peringkat_sekolah"] == 30

    # Ringkasan dua jalur, urut SNBP lalu SNBT, memuat peringatan lintas jalur
    s = alur.post("/summary", json={}).json()
    assert [(p["jalur"], p["prodi_id"]) for p in s["pilihan_akhir"]] == [
        ("SNBP", TI),
        ("SNBP", TE),
        ("SNBT", TI),
        ("SNBT", TE),
        ("SNBT", VOK_D3),
    ]
    assert any("Lulus SNBP menutup" in c for c in s["catatan"])
    assert {d["jalur"] for d in s["dokumen_syarat"]} == {"SNBP", "SNBT"}

    # Pertanyaan keputusan dijawab mesin aturan (bukan LLM), lengkap dengan sumber
    k = alur.post(
        "/query",
        json={
            "pertanyaan": "Apakah saya lolos syarat SNBP?",
            "konteks": {"prodi_id": TI, "jalur": "SNBP"},
        },
    ).json()
    assert k["jenis_jawaban"] == "mesin_aturan" and k["yakin"] is True and k["sumber"]
    assert "bukan opini AI" in k["jawaban"]

    # Privasi: sesi lain tidak bisa membaca strategi ini
    sid = s["strategi"][0]["strategy_id"]
    token_lama = alur.h
    alur.mulai("rani")
    r = alur.post("/summary", json={"strategy_id": sid})
    assert r.status_code == 404
    alur.h = token_lama

    alur.bersih_dari_klaim_peluang()
    assert alur.delete("/session").status_code == 204
    assert alur.get("/summary").status_code in (401, 405)


def test_skenario_data_kurang_tidak_menebak(alur: Alur):
    """Sinta (profil sebagian): tidak ada keputusan, hanya pertanyaan yang perlu dijawab."""
    alur.mulai("sinta")
    h = alur.post("/analyze", json={"targets": [{"prodi_id": IK, "jalur": ["SNBT"]}]}).json()[
        "hasil"
    ][0]
    assert h["gate"]["status"] == "data_kurang" and h["penilaian"] is None
    assert h["data_kurang"] and all(d["pertanyaan"] for d in h["data_kurang"])
    prof = alur.get("/profile").json()
    assert prof["pertanyaan"]  # pertanyaan siap ditampilkan frontend
    e = alur.post("/explore", json={}).json()
    assert e["rekomendasi"] == [] and {d["field"] for d in e["data_kurang"]} == {
        "minat",
        "nilai_rapor",
    }
    alur.bersih_dari_klaim_peluang()


def test_skenario_gagal_syarat_tidak_dinilai(alur: Alur):
    """Budi (lulusan 2023): SNBT gugur dengan alasan, penilaian null, ringkasan jujur."""
    alur.mulai("budi")
    h = alur.post("/analyze", json={"targets": [{"prodi_id": IK, "jalur": ["SNBT"]}]}).json()[
        "hasil"
    ][0]
    assert h["gate"]["status"] == "tidak_memenuhi_syarat" and h["penilaian"] is None
    gagal = [s for s in h["gate"]["syarat"] if s["status"] == "gagal"]
    assert gagal and "lulusan lebih lama" in gagal[0]["alasan"]
    alur.post(
        "/strategy",
        json={"jalur": "SNBT", "pilihan": [{"prodi_id": IK}, {"prodi_id": VOK_D3}], "simpan": True},
    )
    s = alur.post("/summary", json={}).json()
    assert {p["status_gate"] for p in s["pilihan_akhir"]} == {"tidak_memenuhi_syarat"}
    assert {p["kategori"] for p in s["pilihan_akhir"]} == {None}
    assert any(f["jenis"] == "syarat" for f in s["fokus_persiapan"])
    alur.bersih_dari_klaim_peluang()
