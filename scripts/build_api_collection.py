"""Bangun API collection (Postman v2.1) dan environment JalurKu.

    python -m scripts.build_api_collection            # tulis ke api-collection/
    python -m scripts.build_api_collection --cek      # gagal (kode 1) bila berkas di repo sudah usang

Format Postman Collection v2.1 bisa diimpor ke Postman, Insomnia, Bruno, dan Thunder Client.
Bodi persona diambil dari config/personas sehingga selalu sinkron dengan data demo. Berkas hasil
TIDAK diedit tangan: ubah spesifikasi di berkas ini lalu jalankan ulang. Tes
(tests/test_api_collection.py) memastikan semua endpoint API tercakup dan seluruh alur koleksi
benar-benar berjalan terhadap API.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR
from app.services import persona as modul_persona

OUT_DEFAULT = ROOT_DIR / "api-collection"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
NAMESPACE = uuid.UUID("5b0f6c1e-0f0a-4c64-9a52-0c9a6f1d6a11")
PREFIX = ("api", "v1")

# Variabel koleksi (nilai awal). baseUrl dan adminKey ada di environment.
VARIABEL_KOLEKSI = {
    "token": "",
    "strategyId": "",
    "prodiId": "ui-ilmu-komputer",
    "dokumenId": "snpmb-paparan-2026",
    "consentVersion": "2026-10-13",
}


@dataclass(frozen=True)
class Req:
    nama: str
    method: str
    path: str  # relatif terhadap /api/v1, boleh memuat {{variabel}}
    deskripsi: str
    body: Any = None  # JSON
    query: tuple[tuple[str, str, bool], ...] = ()  # (kunci, nilai, aktif)
    status: int = 200
    auth: str = "bearer"  # bearer | none | admin
    tangkap: tuple[tuple[str, str], ...] = ()  # (variabel koleksi, nama kunci JSON respons)
    kunci: tuple[str, ...] = ()  # kunci yang harus ada di respons
    temuan: str | None = None  # kode temuan yang harus ada (POST /strategy)
    yakin: bool | None = None  # nilai `yakin` yang diharapkan (POST /query)
    berkas: bool = False  # unggah berkas (multipart)
    replay: bool = True  # False = dilewati tes replay (butuh berkas nyata)


@dataclass(frozen=True)
class Folder:
    nama: str
    deskripsi: str
    isi: tuple[Req, ...] = field(default_factory=tuple)


# ============================================================================ spesifikasi


def _profil(nama: str) -> dict[str, Any]:
    return modul_persona.muat(nama).profil


def _desk_persona(nama: str) -> str:
    p = modul_persona.muat(nama)
    return f"{p.deskripsi}\n\nPersona fiktif `{p.id}` dari `config/personas/{p.id}.json`."


R_HEALTH = Req(
    "Cek kesehatan",
    "GET",
    "/health",
    "Memeriksa koneksi database saja (tidak memanggil LLM). Tidak butuh token.",
    auth="none",
    kunci=("status",),
)
R_SESI = Req(
    "Buat sesi (consent)",
    "POST",
    "/session",
    "Membuat sesi tamu. `consent: true` wajib. Token disimpan otomatis ke variabel koleksi `token` "
    "dan dipakai semua request lain. Sesi berlaku sesuai TTL (bawaan 24 jam). Respons memuat "
    + "`pemberitahuan` (catatan demo data fiktif) yang wajib ditampilkan di UI.",
    body={"consent": True, "consent_version": "{{consentVersion}}"},
    status=201,
    auth="none",
    tangkap=(("token", "token"),),
    kunci=("token", "expires_at", "sisa_detik", "pemberitahuan"),
)
R_STATUS = Req(
    "Status sesi",
    "GET",
    "/session",
    "Waktu dibuat, consent, dan sisa detik sebelum sesi kedaluwarsa.",
    kunci=("sisa_detik", "expires_at", "pemberitahuan"),
)
R_HAPUS = Req(
    "Hapus data saya",
    "DELETE",
    "/session",
    "Menghapus sesi beserta seluruh data turunannya (profil, strategi, log pertanyaan). Token tidak "
    "berlaku lagi setelah ini, jadi buat sesi baru bila ingin lanjut.",
    status=204,
)


def _put_profil(persona: str, judul: str) -> Req:
    return Req(
        f"Simpan profil: {judul}",
        "PUT",
        "/profile",
        _desk_persona(persona)
        + "\n\nPUT bersifat parsial: field yang tidak dikirim tidak berubah, `null` menghapus nilai. "
        "Respons memuat `data_kurang` per jalur dan `pertanyaan` yang bisa langsung ditampilkan ke siswa.",
        body=_profil(persona),
        kunci=("profil", "data_kurang", "pertanyaan"),
    )


R_PROFIL_RANI = _put_profil("rani", "Rani (belum punya target)")
R_PROFIL_DIMAS = _put_profil("dimas", "Dimas (sudah punya target)")
R_PROFIL_BUDI = _put_profil("budi", "Budi (lulusan 2023, SNBT gugur)")
R_PROFIL_SINTA = _put_profil("sinta", "Sinta (data sebagian, data_kurang)")
R_PROFIL_GET = Req(
    "Baca profil",
    "GET",
    "/profile",
    "Profil tersimpan beserta `data_kurang` dan pertanyaannya.",
    kunci=("profil", "data_kurang", "pertanyaan"),
)
R_PROFIL_PARSIAL = Req(
    "Ubah sebagian profil",
    "PUT",
    "/profile",
    "Hanya mengubah peringkat sekolah. Field lain dibiarkan.",
    body={"peringkat_sekolah": 28},
    kunci=("profil",),
)
R_PROFIL_HAPUS = Req(
    "Hapus satu nilai profil",
    "PUT",
    "/profile",
    "`null` menghapus nilai. Di sini skor tryout dikosongkan.",
    body={"skor_tryout": None},
    kunci=("profil",),
)

R_PTN = Req(
    "Daftar PTN",
    "GET",
    "/catalog/ptn",
    "Pencarian PTN dengan filter dan paginasi. Nama provinsi harus baku (38 provinsi).",
    query=(
        ("q", "Indonesia", False),
        ("provinsi", "Jawa Barat", True),
        ("page", "1", True),
        ("limit", "20", True),
    ),
    kunci=("items", "total", "page", "limit"),
)
R_PRODI = Req(
    "Daftar prodi",
    "GET",
    "/catalog/prodi",
    "Pencarian prodi. Filter: `q`, `rumpun`, `provinsi`, `jalur` (SNBP/SNBT), `ptn_id`, `program` "
    "(akademik/vokasi), `jenjang` (S1/D3/D4). Aktifkan filter lain di tab Params.",
    query=(
        ("q", "komputer", False),
        ("rumpun", "Teknik", True),
        ("provinsi", "Jawa Barat", False),
        ("jalur", "SNBT", False),
        ("ptn_id", "ui", False),
        ("program", "akademik", True),
        ("jenjang", "S1", False),
        ("page", "1", True),
        ("limit", "10", True),
    ),
    kunci=("items", "total"),
)
R_PRODI_VOKASI = Req(
    "Daftar prodi vokasi UI",
    "GET",
    "/catalog/prodi",
    "Contoh filter `program=vokasi` untuk melengkapi komposisi pilihan SNBT.",
    query=(("ptn_id", "ui", True), ("program", "vokasi", True), ("limit", "20", True)),
    kunci=("items", "total"),
)
R_PRODI_DETAIL = Req(
    "Detail prodi",
    "GET",
    "/catalog/prodi/{{prodiId}}",
    "Detail satu prodi: keketatan per jalur (daya tampung, peminat), acuan skor bila ada, dan status "
    "verifikasi. Ubah variabel `prodiId` untuk prodi lain.",
    kunci=("id", "nama"),
)

# Jawaban contoh tes minat RIASEC (profil dominan investigatif). id item dari config/app.yaml.
_RIASEC_JAWABAN = {
    "r1": 1, "r2": 1, "r3": 0, "r4": 1,
    "i1": 4, "i2": 4, "i3": 4, "i4": 4,
    "a1": 1, "a2": 0, "a3": 1, "a4": 1,
    "s1": 2, "s2": 2, "s3": 1, "s4": 2,
    "e1": 2, "e2": 2, "e3": 1, "e4": 2,
    "c1": 3, "c2": 3, "c3": 2, "c4": 3,
}
R_RIASEC_QUESTIONS = Req(
    "Daftar pertanyaan tes minat",
    "GET",
    "/riasec/questions",
    "Instrumen tes minat RIASEC (item aktivitas + skala Likert) untuk ditampilkan. Publik: tidak "
    "butuh token dan tidak memuat kunci skoring.",
    auth="none",
    kunci=("versi_instrumen", "skala", "dimensi", "item"),
)
R_RIASEC_SUBMIT = Req(
    "Kirim jawaban tes minat",
    "POST",
    "/riasec/submit",
    "Menghitung vektor minat dari jawaban (deterministik, tanpa LLM) dan, bila `simpan: true`, "
    "menuliskannya ke profil sehingga langsung dipakai `/explore`. id item mengikuti "
    "`/riasec/questions`; nilai sesuai skala (0..4).",
    body={"jawaban": _RIASEC_JAWABAN, "simpan": True},
    kunci=("skor_norm", "holland_code", "dimensi_teratas", "tersimpan"),
)

R_EXPLORE = Req(
    "Rekomendasi rumpun",
    "POST",
    "/explore",
    "Rekomendasi rumpun jurusan dari minat dan nilai rapor (deterministik, tanpa LLM). Perlu profil "
    "dengan `minat` dan `nilai_rapor` (mis. Rani atau Dimas). Tiap rekomendasi memuat komponen skor, "
    "alasan, contoh profesi, dan daftar PTN pembukanya.",
    body={"top_n": 5},
    kunci=("rekomendasi", "data_kurang", "catatan"),
)
R_EXPLORE_JALUR = Req(
    "Rekomendasi rumpun + kelayakan SNBT",
    "POST",
    "/explore",
    "Sama seperti di atas, ditambah `kelayakan` per rumpun: ringkasan gate dan kategori "
    "reach/match/safe dari mesin yang sama dengan `/analyze`.",
    body={"top_n": 3, "jalur": "SNBT"},
    kunci=("rekomendasi", "jalur"),
)

T_DIMAS = ["ui-teknik-industri", "ui-teknik-elektro", "ui-teknik-mesin"]
R_ANALYZE = Req(
    "Analisis satu target",
    "POST",
    "/analyze",
    "Gate lalu penilaian untuk satu prodi di satu jalur. Penilaian `null` bila gate tidak lolos.",
    body={"targets": [{"prodi_id": "{{prodiId}}", "jalur": ["SNBT"]}]},
    kunci=("hasil",),
)
R_ANALYZE_DIMAS = Req(
    "Analisis tiga target, dua jalur",
    "POST",
    "/analyze",
    "Persona Dimas: tiga prodi teknik UI di SNBP dan SNBT sekaligus (6 hasil). SNBP butuh "
    "`konfirmasi_syarat_prodi` yang sudah ada di profil Dimas.",
    body={"targets": [{"prodi_id": p, "jalur": ["SNBP", "SNBT"]} for p in T_DIMAS]},
    kunci=("hasil",),
)
R_ANALYZE_WHATIF = Req(
    "What-if: peringkat satu tingkat di luar kuota",
    "POST",
    "/analyze",
    "`override` menghitung ulang tanpa menyimpan apa pun. Dengan peringkat 31 dari 120 (25,83 persen) "
    "SNBP akreditasi B tanpa e-Rapor gugur karena kuota sekolah 25 persen; profil tersimpan tidak "
    "berubah.",
    body={
        "targets": [{"prodi_id": "ui-teknik-industri", "jalur": ["SNBP"]}],
        "override": {"peringkat_sekolah": 31},
    },
    kunci=("hasil",),
)

R_STRATEGI_EVAL = Req(
    "Evaluasi komposisi SNBT",
    "POST",
    "/strategy",
    "Mengevaluasi pilihan SNBT tanpa menyimpan: komposisi, temuan (pelanggaran/peringatan/info), dan "
    "saran swap dari `shortlist`.",
    body={
        "jalur": "SNBT",
        "pilihan": [
            {"prodi_id": "ui-teknik-industri"},
            {"prodi_id": "ui-teknik-elektro"},
            {"prodi_id": "ui-v-akuntansi-d3"},
        ],
        "shortlist": ["ui-v-fisioterapi", "ui-teknik-mesin"],
        "simpan": False,
    },
    kunci=("hasil", "komposisi", "temuan", "disimpan"),
)
R_STRATEGI_PELANGGARAN = Req(
    "Contoh pelanggaran: 3 Sarjana tanpa vokasi",
    "POST",
    "/strategy",
    "SNBT dengan 3 pilihan tidak boleh seluruhnya Sarjana. Respons memuat temuan `butuh_vokasi` "
    "(pelanggaran) dan saran swap ke prodi vokasi dari `shortlist`.",
    body={
        "jalur": "SNBT",
        "pilihan": [{"prodi_id": p} for p in T_DIMAS],
        "shortlist": ["ui-v-akuntansi-d3"],
    },
    temuan="butuh_vokasi",
    kunci=("temuan",),
)
R_STRATEGI_BATAS = Req(
    "Contoh pelanggaran: SNBP lebih dari 2 pilihan",
    "POST",
    "/strategy",
    "SNBP maksimal 2 pilihan. Respons memuat temuan `melebihi_batas_pilihan`.",
    body={"jalur": "SNBP", "pilihan": [{"prodi_id": p} for p in T_DIMAS]},
    temuan="melebihi_batas_pilihan",
    kunci=("temuan",),
)
R_STRATEGI_WHATIF = Req(
    "What-if strategi SNBT",
    "POST",
    "/strategy",
    "Dengan `override`, hasil dihitung ulang dan `simpan` dipaksa `false`: tidak ada yang tersimpan.",
    body={
        "jalur": "SNBT",
        "pilihan": [{"prodi_id": "ui-teknik-industri"}, {"prodi_id": "ui-v-akuntansi-d3"}],
        "override": {"peringkat_sekolah": 100},
        "simpan": True,
    },
    kunci=("hasil", "disimpan"),
)
R_STRATEGI_SIMPAN_SNBP = Req(
    "Simpan strategi SNBP",
    "POST",
    "/strategy",
    "Menyimpan pilihan SNBP (maks 2) agar dipakai `/summary`.",
    body={
        "jalur": "SNBP",
        "pilihan": [{"prodi_id": "ui-teknik-industri"}, {"prodi_id": "ui-teknik-elektro"}],
        "simpan": True,
    },
    tangkap=(("strategyId", "strategy_id"),),
    kunci=("strategy_id", "disimpan"),
)
R_STRATEGI_SIMPAN_SNBT = Req(
    "Simpan strategi SNBT",
    "POST",
    "/strategy",
    "Menyimpan pilihan SNBT (2 Sarjana + 1 D3). `strategy_id` disimpan ke variabel `strategyId`.",
    body={
        "jalur": "SNBT",
        "pilihan": [
            {"prodi_id": "ui-teknik-industri"},
            {"prodi_id": "ui-teknik-elektro"},
            {"prodi_id": "ui-v-akuntansi-d3"},
        ],
        "simpan": True,
    },
    tangkap=(("strategyId", "strategy_id"),),
    kunci=("strategy_id", "disimpan"),
)
R_STRATEGI_SIMPAN_RANI = Req(
    "Simpan strategi SNBT (Rani)",
    "POST",
    "/strategy",
    "Pilihan SNBT untuk persona Rani: 2 Sarjana + 1 D3.",
    body={
        "jalur": "SNBT",
        "pilihan": [
            {"prodi_id": "ui-ilmu-komputer"},
            {"prodi_id": "ui-teknik-industri"},
            {"prodi_id": "ui-v-akuntansi-d3"},
        ],
        "simpan": True,
    },
    tangkap=(("strategyId", "strategy_id"),),
    kunci=("strategy_id", "disimpan"),
)

R_RINGKAS = Req(
    "Ringkasan (strategi tersimpan terbaru)",
    "POST",
    "/summary",
    "Ringkasan siap cetak dari strategi tersimpan terbaru per jalur. Butuh minimal satu strategi "
    "yang disimpan (404 `strategi_belum_disimpan` bila belum). Tidak ada tautan publik.",
    body={},
    kunci=("pilihan_akhir", "fokus_persiapan", "dokumen_syarat", "narasi", "narasi_fallback"),
)
R_RINGKAS_ID = Req(
    "Ringkasan (strategy_id tertentu)",
    "POST",
    "/summary",
    "Memakai strategi yang `strategy_id`-nya disimpan di variabel `strategyId`.",
    body={"strategy_id": "{{strategyId}}"},
    kunci=("pilihan_akhir", "narasi"),
)

_KUNCI_QUERY = ("jawaban", "sumber", "yakin", "fallback", "mode", "jenis_jawaban")
R_Q_TANYA = Req(
    "Tanya dokumen resmi (RAG)",
    "POST",
    "/query",
    "Pertanyaan bebas dijawab dari dokumen resmi dengan sitasi. Tanpa `GEMINI_API_KEY` atau dokumen "
    "belum di-ingest, hasilnya `yakin: false` dan `fallback: true` (HTTP tetap 200).",
    body={"pertanyaan": "Berapa jumlah pilihan program studi di SNBP 2026?", "mode": "tanya"},
    kunci=_KUNCI_QUERY,
)
R_Q_KEPUTUSAN = Req(
    "Tanya keputusan (dijawab mesin aturan)",
    "POST",
    "/query",
    "Pertanyaan keputusan pribadi dijawab mesin aturan, bukan LLM. Sertakan `konteks` agar bisa "
    "dihitung; tanpa konteks, respons meminta `konteks.prodi_id` dan `konteks.jalur`.",
    body={
        "pertanyaan": "Apakah saya lolos syarat SNBP?",
        "mode": "tanya",
        "konteks": {"prodi_id": "ui-teknik-industri", "jalur": "SNBP"},
    },
    kunci=_KUNCI_QUERY,
)
R_Q_JELASKAN = Req(
    "Kenapa hasilnya begitu? (mode jelaskan)",
    "POST",
    "/query",
    'Tombol "Kenapa?". `konteks.prodi_id` dan `konteks.jalur` wajib. Server menghitung ulang '
    "analisis, LLM hanya menjelaskan fakta itu. Tanpa LLM, dipakai teks cadangan.",
    body={
        "pertanyaan": "Kenapa hasilnya begitu?",
        "mode": "jelaskan",
        "konteks": {"prodi_id": "ui-teknik-industri", "jalur": "SNBT"},
    },
    kunci=_KUNCI_QUERY,
)
R_Q_LUAR = Req(
    "Di luar cakupan (harus yakin: false)",
    "POST",
    "/query",
    "Tidak ada passing grade resmi, jadi sistem harus jujur: `yakin` bernilai `false`.",
    body={
        "pertanyaan": "Berapa skor UTBK minimal untuk diterima di Kedokteran UI?",
        "mode": "tanya",
    },
    kunci=_KUNCI_QUERY,
    yakin=False,
)

R_ADMIN_PROFESI = Req(
    "Ingest profesi (contoh)",
    "POST",
    "/admin/ingest",
    "Memuat data lewat API. Butuh header `X-Admin-Key` (variabel environment `adminKey`); tanpa "
    "`ADMIN_KEY` di server endpoint ini 404. `tipe`: `rules`, `ketentuan`, `katalog`, `acuan`, "
    "`dokumen`, `profesi`. Kolom `payload` sama dengan berkas CSV di `data/seed`. Satu tipe = satu "
    "transaksi. PERHATIAN: ingest adalah upsert; baris tanpa `terakhir_diverifikasi` menimpa tanggal "
    "verifikasi yang sudah ada dengan kosong. Contoh ini hanya menambah satu profesi.",
    body={"tipe": "profesi", "payload": [{"rumpun": "Hukum", "nama": "Notaris"}]},
    auth="admin",
    kunci=("tipe", "diterima", "ringkasan"),
)
R_ADMIN_BERKAS = Req(
    "Unggah PDF sumber RAG",
    "POST",
    "/admin/dokumen/{{dokumenId}}/berkas",
    "Mengunggah PDF resmi (maks 30 MB, harus berheader %PDF-). Pilih berkas pada field `berkas`. "
    "`proses=true` langsung memotong dan meng-embed (memakai kuota API). `dokumenId` harus sudah "
    "terdaftar lewat ingest `dokumen`.",
    query=(("proses", "false", True),),
    auth="admin",
    berkas=True,
    replay=False,
    kunci=("dokumen_id", "berkas"),
)

R_GAGAL_CONSENT = Req(
    "Buat sesi tanpa consent (400)",
    "POST",
    "/session",
    "Consent wajib sebelum data apa pun diproses.",
    body={"consent": False, "consent_version": "{{consentVersion}}"},
    status=400,
    auth="none",
)
R_GAGAL_TOKEN = Req(
    "Tanpa token (401)",
    "GET",
    "/profile",
    "Semua endpoint selain `/health` dan `POST /session` butuh token.",
    status=401,
    auth="none",
)
R_GAGAL_422 = Req(
    "Validasi gagal (422)",
    "POST",
    "/analyze",
    "Format error seragam: `error.kode`, `error.pesan`, `error.detail.field[]`.",
    body={"targets": []},
    status=422,
)
R_GAGAL_404 = Req(
    "Prodi tidak ada (404)",
    "POST",
    "/analyze",
    "Memuat daftar lengkap prodi yang tidak ditemukan di `error.detail`.",
    body={"targets": [{"prodi_id": "tidak-ada", "jalur": ["SNBT"]}]},
    status=404,
)
R_GAGAL_EXTRA = Req(
    "Field tak dikenal ditolak (422)",
    "PUT",
    "/profile",
    "Skema profil sengaja tanpa identitas (nama, kontak, NIK). Field tak dikenal ditolak.",
    body={"nama_lengkap": "Contoh"},
    status=422,
)


def _alur(req: Req, nomor: int) -> Req:
    return replace(req, nama=f"{nomor}. {req.nama}")


def alur_b() -> Folder:
    langkah = [
        R_SESI,
        R_PROFIL_DIMAS,
        R_PROFIL_GET,
        R_PRODI,
        R_ANALYZE_DIMAS,
        R_ANALYZE_WHATIF,
        R_STRATEGI_EVAL,
        R_STRATEGI_SIMPAN_SNBP,
        R_STRATEGI_SIMPAN_SNBT,
        R_RINGKAS,
        R_Q_KEPUTUSAN,
        R_HAPUS,
    ]
    return Folder(
        "00 Alur lengkap: Skenario B (sudah punya target, Dimas)",
        "Jalankan seluruh folder ini berurutan (Collection Runner atau Run folder). Alur: sesi, profil, "
        "katalog, analisis, what-if, strategi, simpan, ringkasan, tanya-jawab, hapus data. Mandiri: "
        "membuat sesi sendiri dan menghapusnya di akhir.",
        tuple(_alur(r, i) for i, r in enumerate(langkah, start=1)),
    )


def alur_a() -> Folder:
    langkah = [
        R_SESI,
        R_PROFIL_RANI,
        R_EXPLORE_JALUR,
        R_PRODI_VOKASI,
        R_ANALYZE,
        R_STRATEGI_SIMPAN_RANI,
        R_RINGKAS,
        R_Q_JELASKAN,
        R_HAPUS,
    ]
    return Folder(
        "00 Alur lengkap: Skenario A (belum punya target, Rani)",
        "Alur eksplorasi: sesi, profil Rani, rekomendasi rumpun beserta kelayakannya, katalog, analisis "
        "kandidat, simpan strategi, ringkasan, penjelasan, hapus data. Mandiri seperti Skenario B.",
        tuple(_alur(r, i) for i, r in enumerate(langkah, start=1)),
    )


def semua_folder() -> tuple[Folder, ...]:
    return (
        alur_a(),
        alur_b(),
        Folder("01 Kesehatan", "Cek hidup layanan.", (R_HEALTH,)),
        Folder(
            "02 Sesi",
            "Mulai dari sini untuk request satuan: **Buat sesi** menyimpan token ke variabel `token`.",
            (R_SESI, R_STATUS),
        ),
        Folder(
            "03 Profil",
            "Empat persona fiktif dan contoh pembaruan parsial. Profil terakhir yang dikirim "
            "digabung dengan yang sebelumnya (shallow merge), jadi buat sesi baru untuk mulai bersih.",
            (
                R_PROFIL_DIMAS,
                R_PROFIL_RANI,
                R_PROFIL_BUDI,
                R_PROFIL_SINTA,
                R_PROFIL_GET,
                R_PROFIL_PARSIAL,
                R_PROFIL_HAPUS,
            ),
        ),
        Folder(
            "04 Katalog",
            "Penelusuran PTN dan prodi.",
            (R_PTN, R_PRODI, R_PRODI_VOKASI, R_PRODI_DETAIL),
        ),
        Folder(
            "05 Tes minat (RIASEC)",
            "Tes minat Holland/RIASEC: ambil pertanyaan lalu kirim jawaban. Hasilnya vektor minat yang "
            "disimpan ke profil dan dipakai Eksplorasi. Deterministik, tanpa LLM.",
            (R_RIASEC_QUESTIONS, R_RIASEC_SUBMIT),
        ),
        Folder(
            "06 Eksplorasi",
            "Rekomendasi rumpun, deterministik tanpa LLM.",
            (R_EXPLORE, R_EXPLORE_JALUR),
        ),
        Folder(
            "07 Analisis",
            "Gate lalu penilaian reach/match/safe.",
            (R_ANALYZE, R_ANALYZE_DIMAS, R_ANALYZE_WHATIF),
        ),
        Folder(
            "08 Strategi",
            "Evaluasi komposisi pilihan per jalur, what-if, dan penyimpanan.",
            (
                R_STRATEGI_EVAL,
                R_STRATEGI_PELANGGARAN,
                R_STRATEGI_BATAS,
                R_STRATEGI_WHATIF,
                R_STRATEGI_SIMPAN_SNBP,
                R_STRATEGI_SIMPAN_SNBT,
            ),
        ),
        Folder("09 Ringkasan", "Perlu strategi tersimpan.", (R_RINGKAS, R_RINGKAS_ID)),
        Folder(
            "10 Tanya jawab",
            "Setiap request ini dibatasi 10 per menit per sesi. Tanpa kunci Gemini semuanya tetap 200 "
            "dengan teks cadangan.",
            (R_Q_TANYA, R_Q_KEPUTUSAN, R_Q_JELASKAN, R_Q_LUAR),
        ),
        Folder(
            "11 Admin",
            "Hanya dengan header `X-Admin-Key` (isi variabel environment `adminKey`).",
            (R_ADMIN_PROFESI, R_ADMIN_BERKAS),
        ),
        Folder(
            "12 Kasus gagal",
            "Contoh respons error: consent, token, validasi, dan 404.",
            (R_GAGAL_CONSENT, R_GAGAL_TOKEN, R_GAGAL_422, R_GAGAL_404, R_GAGAL_EXTRA),
        ),
        Folder("13 Akhiri sesi", "Hapus data sesi aktif.", (R_HAPUS,)),
    )


# ============================================================================ pembangun JSON


def skrip_uji(r: Req) -> list[str]:
    baris = [
        f'pm.test("Status {r.status}", function () {{ pm.response.to.have.status({r.status}); }});'
    ]
    perlu_json = bool(r.kunci or r.tangkap or r.temuan or r.yakin is not None)
    if perlu_json and r.status != 204:
        baris.append("const j = pm.response.json();")
        if r.kunci:
            daftar = json.dumps(list(r.kunci), ensure_ascii=False)[1:-1]
            baris.append(
                f'pm.test("Respons memuat {", ".join(r.kunci)}", function () {{ '
                f"pm.expect(j).to.include.keys({daftar}); }});"
            )
        if r.temuan:
            baris.append(
                f'pm.test("Ada temuan {r.temuan}", function () {{ '
                "pm.expect(j.temuan.map(function (t) { return t.kode; }))"
                f'.to.include("{r.temuan}"); }});'
            )
        if r.yakin is not None:
            nilai = "true" if r.yakin else "false"
            baris.append(
                f'pm.test("yakin = {nilai}", function () {{ pm.expect(j.yakin).to.eql({nilai}); }});'
            )
        for variabel, kunci in r.tangkap:
            baris.append(f'pm.collectionVariables.set("{variabel}", j.{kunci});')
    return baris


def _url(r: Req) -> dict[str, Any]:
    segmen = [s for s in r.path.strip("/").split("/") if s]
    aktif = [f"{k}={v}" for k, v, on in r.query if on]
    raw = "{{baseUrl}}/" + "/".join([*PREFIX, *segmen]) + ("?" + "&".join(aktif) if aktif else "")
    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": [*PREFIX, *segmen]}
    if r.query:
        url["query"] = [
            {"key": k, "value": v, **({} if on else {"disabled": True})} for k, v, on in r.query
        ]
    return url


def _item(r: Req) -> dict[str, Any]:
    header: list[dict[str, Any]] = []
    body: dict[str, Any] | None = None
    if r.berkas:
        body = {"mode": "formdata", "formdata": [{"key": "berkas", "type": "file", "src": []}]}
    elif r.body is not None:
        header.append({"key": "Content-Type", "value": "application/json", "type": "text"})
        body = {
            "mode": "raw",
            "raw": json.dumps(r.body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    if r.auth == "admin":
        header.append({"key": "X-Admin-Key", "value": "{{adminKey}}", "type": "text"})
    request: dict[str, Any] = {"method": r.method, "header": header, "url": _url(r)}
    if r.auth in ("none", "admin"):
        request["auth"] = {"type": "noauth"}
    if body is not None:
        request["body"] = body
    request["description"] = r.deskripsi
    return {
        "name": r.nama,
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": skrip_uji(r)}}],
        "request": request,
        "response": [],
    }


def _folder(f: Folder) -> dict[str, Any]:
    return {"name": f.nama, "description": f.deskripsi, "item": [_item(r) for r in f.isi]}


DESKRIPSI_KOLEKSI = """\
API JalurKu (backend SNBP dan SNBT). Dibuat otomatis oleh `scripts/build_api_collection.py`, jangan diedit tangan.

**Mulai cepat**
1. Impor koleksi ini dan salah satu environment (Lokal atau Produksi), lalu pilih environment itu.
2. Isi `baseUrl` (dan `adminKey` bila perlu) di environment.
3. Jalankan folder **00 Alur lengkap** dengan Collection Runner, atau mulai dari **02 Sesi > Buat sesi** untuk request satuan.

**Variabel**
- Environment: `baseUrl`, `adminKey`.
- Koleksi (diisi otomatis oleh skrip uji): `token`, `strategyId`. Bisa diubah: `prodiId`, `dokumenId`, `consentVersion`.

Semua kategori reach/match/safe bersifat **indikatif**. Persona selalu fiktif.\
"""


def bangun_collection() -> dict[str, Any]:
    return {
        "info": {
            "_postman_id": str(uuid.uuid5(NAMESPACE, "koleksi")),
            "name": "JalurKu API",
            "description": DESKRIPSI_KOLEKSI,
            "schema": SCHEMA,
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
        },
        "variable": [{"key": k, "value": v, "type": "string"} for k, v in VARIABEL_KOLEKSI.items()],
        "item": [_folder(f) for f in semua_folder()],
    }


ENVIRONMENT = {
    "JalurKu.lokal.postman_environment.json": ("JalurKu Lokal", "http://localhost:8000"),
    "JalurKu.produksi.postman_environment.json": ("JalurKu Produksi", "https://jalurku.contoh.id"),
}


def bangun_environment(nama: str, base_url: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid5(NAMESPACE, nama)),
        "name": nama,
        "values": [
            {"key": "baseUrl", "value": base_url, "type": "default", "enabled": True},
            {"key": "adminKey", "value": "", "type": "secret", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }


def berkas_yang_dihasilkan() -> dict[str, dict[str, Any]]:
    hasil = {"JalurKu.postman_collection.json": bangun_collection()}
    for berkas, (nama, url) in ENVIRONMENT.items():
        hasil[berkas] = bangun_environment(nama, url)
    return hasil


def _serialisasi(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def semua_request() -> list[Req]:
    return [r for f in semua_folder() for r in f.isi]


def variabel_dirujuk() -> set[str]:
    teks = _serialisasi(bangun_collection())
    return set(re.findall(r"\{\{(\w+)\}\}", teks))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument(
        "--cek", action="store_true", help="hanya periksa apakah berkas di repo masih mutakhir"
    )
    a = ap.parse_args(argv)
    out = Path(a.out)

    usang: list[str] = []
    for nama, isi in berkas_yang_dihasilkan().items():
        path = out / nama
        if a.cek:
            try:
                sama = json.loads(path.read_text(encoding="utf-8")) == isi
            except (OSError, json.JSONDecodeError):
                sama = False
            if not sama:
                usang.append(nama)
            continue
        out.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(_serialisasi(isi))
        print(f"[OK] {path}")
    if usang:
        print(
            "Berkas usang (jalankan: python -m scripts.build_api_collection): " + ", ".join(usang)
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
