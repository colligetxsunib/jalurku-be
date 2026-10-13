"""Task 13: chunking, ekstraksi, ingest dokumen RAG (idempoten), retrieve pgvector, unggah multipart."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.llm.client import l2_normalisasi
from app.llm.errors import LLMGagal, LLMKuotaHabis
from app.main import create_app
from app.rag import extract
from app.rag.chunking import (
    ChunkTerlaluBesar,
    perkiraan_token,
    potong_dokumen,
    potong_halaman,
    rapikan,
)
from app.rag.extract import BerkasTidakAda, TanpaTeks, cari_berkas
from app.rag.ingest import DokumenTidakTerdaftar, buat_chunk, embed_dengan_retry, ingest_dokumen
from app.rag.retrieve import cari, di_atas_ambang
from scripts import ingest_docs
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.pdfgen import buat_pdf, paragraf

# ============================================================== chunking (murni)

PARAM = dict(minimum=100, maksimum=300, overlap=60)


def banyak_kalimat(n: int = 30) -> str:
    return " ".join(
        f"Kalimat ke-{i} menerangkan ketentuan seleksi nasional dengan rincian nomor {i * 7}."
        for i in range(n)
    )


def test_rapikan_menyatukan_baris_pdf_dan_kata_terpenggal():
    assert rapikan("Peserta wajib\nmemiliki akun\n\nParagraf   kedua\u00a0di sini") == (
        "Peserta wajib memiliki akun Paragraf kedua di sini"
    )
    assert rapikan("pendaftar-\nan dibuka") == "pendaftaran dibuka"
    assert rapikan("  \n\n ") == ""


def test_ukuran_chunk_dalam_batas_dan_urut():
    chunks = potong_halaman(banyak_kalimat(), **PARAM)
    assert len(chunks) > 3
    assert all(len(c) <= PARAM["maksimum"] for c in chunks)
    assert all(len(c) >= PARAM["minimum"] for c in chunks[:-1])


def test_overlap_antar_chunk_berurutan():
    chunks = potong_halaman(banyak_kalimat(), **PARAM)
    for a, b in zip(chunks, chunks[1:], strict=False):
        awal = b[:25]
        assert awal in a, "awal chunk berikutnya harus berasal dari ekor chunk sebelumnya (overlap)"
        mulai = a.rindex(
            awal
        )  # frasa berulang di teks sintetis: ambil kemunculan terakhir (di ekor)
        sama = len(a) - mulai
        assert 20 <= sama <= PARAM["overlap"], sama
        assert a[mulai - 1] == " "  # overlap dimulai di batas kata


def test_tidak_ada_isi_yang_hilang():
    teks = banyak_kalimat()
    gabungan = " ".join(potong_halaman(teks, **PARAM))
    assert set(teks.split()) <= set(gabungan.split())


def test_deterministik_dan_teks_pendek_satu_chunk():
    assert potong_halaman(banyak_kalimat(), **PARAM) == potong_halaman(banyak_kalimat(), **PARAM)
    pendek = "Hanya satu kalimat pendek tentang SNBP."
    assert potong_halaman(pendek, **PARAM) == [pendek]
    assert potong_halaman("", **PARAM) == []


def test_kalimat_lebih_panjang_dari_batas_dipotong_per_kata():
    panjang = " ".join(f"kata{i}" for i in range(200))  # tanpa tanda baca
    chunks = potong_halaman(panjang, **PARAM)
    assert len(chunks) > 1 and all(len(c) <= 300 for c in chunks)
    assert "kata0" in chunks[0] and "kata199" in chunks[-1]


def test_token_tunggal_super_panjang_dipecah():
    chunks = potong_halaman("https://" + "a" * 700, **PARAM)
    assert all(len(c) <= 300 for c in chunks) and len(chunks) >= 3


def test_ekor_pendek_digabung_ke_chunk_sebelumnya():
    # tanpa ekor pendek, chunk terakhir bisa sangat pendek; hasilnya tidak boleh punya sisa 1-2 kata
    for n in range(8, 20):
        chunks = potong_halaman(banyak_kalimat(n), **PARAM)
        assert len(chunks[-1]) >= 100 or len(chunks) == 1 or len(chunks[-1]) + len(chunks[-2]) > 300


def test_parameter_tidak_masuk_akal_ditolak():
    with pytest.raises(ValueError):
        potong_halaman("x", minimum=500, maksimum=100, overlap=10)
    with pytest.raises(ValueError):
        potong_halaman("x", minimum=10, maksimum=100, overlap=100)


def test_chunk_tidak_melintasi_halaman_dan_urutan_berlanjut():
    halaman = [(1, banyak_kalimat(12)), (2, banyak_kalimat(12)), (3, banyak_kalimat(12))]
    chunks = potong_dokumen(halaman, **PARAM)
    assert [c.urutan for c in chunks] == list(range(len(chunks)))
    assert [c.halaman for c in chunks] == sorted(c.halaman for c in chunks)
    assert {c.halaman for c in chunks} == {1, 2, 3}
    assert all(c.teks for c in chunks)


def test_chunk_terlalu_kecil_dibuang_dan_batas_token_dijaga():
    assert potong_dokumen([(1, "12"), (2, "Halaman 3 dari 40")], **PARAM) == []
    assert perkiraan_token("a" * 300) == 100
    with pytest.raises(ChunkTerlaluBesar, match="halaman 2"):
        potong_dokumen(
            [
                (1, "pendek tapi cukup panjang untuk lolos penyaring noise ya"),
                (2, banyak_kalimat(40)),
            ],
            minimum=100,
            maksimum=900,
            overlap=60,
            maks_token=100,
        )


# ============================================================== ekstraksi


def test_ekstrak_pdf_per_halaman(tmp_path: Path):
    p = tmp_path / "d.pdf"
    p.write_bytes(buat_pdf(["Halaman satu memuat aturan SNBP", "Halaman dua memuat aturan SNBT"]))
    hasil = extract.ekstrak(p)
    assert [no for no, _ in hasil] == [1, 2]
    assert "SNBP" in hasil[0][1] and "SNBT" in hasil[1][1]


def test_ekstrak_pdf_tanpa_teks_ditolak(tmp_path: Path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(buat_pdf(["", ""]))
    with pytest.raises(TanpaTeks, match="scan"):
        extract.ekstrak(p)


def test_ekstrak_html_membuang_skrip_dan_navigasi(tmp_path: Path):
    p = tmp_path / "faq.html"
    p.write_text(
        "<html><nav>Menu Utama</nav><script>var x='rahasia';</script><style>.a{}</style>"
        "<body><h1>FAQ</h1><p>Isi jawaban resmi.</p></body><footer>Hak cipta</footer></html>",
        encoding="utf-8",
    )
    ((_, teks),) = extract.ekstrak(p)
    assert "Isi jawaban resmi" in teks and "FAQ" in teks
    assert "Menu Utama" not in teks and "rahasia" not in teks and "Hak cipta" not in teks


def test_cari_berkas_dan_pesan_unduh_manual(tmp_path: Path):
    with pytest.raises(BerkasTidakAda, match="Unduh manual"):
        cari_berkas(tmp_path, "tidak-ada")
    (tmp_path / "a.txt").write_text("isi", encoding="utf-8")
    (tmp_path / "a.pdf").write_bytes(b"%PDF-")
    assert cari_berkas(tmp_path, "a").suffix == ".pdf"  # PDF didahulukan
    with pytest.raises(ValueError):
        extract.ekstrak(tmp_path / "a.docx")


# ============================================================== ingest (DB)

URL = "https://files.snpmb.id/uji/doc1.pdf"
KONFIG = dict(
    ukuran_chunk_min=100, ukuran_chunk_maks=300, overlap_chunk=60, ukuran_batch_embedding=4
)


def konfig_kecil(app_config: AppConfig, **ubah) -> AppConfig:
    rag = app_config.rag.model_copy(update={**KONFIG, **ubah})
    return app_config.model_copy(update={"rag": rag})


def daftar_dokumen(engine: Engine, dokumen_id: str = "doc1", tahun: int = 2026) -> None:
    with Session(engine) as db:
        db.merge(
            m.DokumenSumber(
                id=dokumen_id,
                judul=f"Dokumen {dokumen_id}",
                url=URL,
                jenis="PDF uji",
                tahun_siklus=tahun,
            )
        )
        db.commit()


def tulis_pdf(folder: Path, halaman: list[str], nama: str = "doc1") -> Path:
    p = folder / f"{nama}.pdf"
    p.write_bytes(buat_pdf(halaman))
    return p


def hitung(engine: Engine, dokumen_id: str = "doc1") -> int:
    with engine.connect() as c:
        return c.execute(
            text("SELECT count(*) FROM rag_chunks WHERE dokumen_id = :d"), {"d": dokumen_id}
        ).scalar()


class KuotaDulu(FakeLLM):
    """Gagal 429 pada N panggilan embedding pertama."""

    def __init__(self, gagal_pertama: int, **kw):
        super().__init__(**kw)
        self.sisa = gagal_pertama

    def embed(self, teks, *, task_type):
        if self.sisa > 0:
            self.sisa -= 1
            self.panggilan_embed += 1
            raise LLMKuotaHabis("429")
        return super().embed(teks, task_type=task_type)


@pytest.mark.db
class TestIngestDokumen:
    HAL = [paragraf("pertama"), paragraf("kedua"), paragraf("ketiga")]

    def test_ingest_pertama_menyimpan_chunk_berstandar_pada(self, clean_db, app_config, tmp_path):
        cfg = konfig_kecil(app_config)
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        fake = FakeLLM()
        with Session(clean_db) as db:
            r = ingest_dokumen(db, fake, cfg, "doc1", tmp_path)
        n = r.jumlah_chunk
        assert n > 6 and (r.di_embed, r.tidak_berubah, r.dihapus) == (n, 0, 0)
        assert r.panggilan_embed == math.ceil(n / 4) == fake.panggilan_embed  # per batch
        assert set(fake.task_types) == {"RETRIEVAL_DOCUMENT"}  # dokumen, bukan query
        assert hitung(clean_db) == n

        with clean_db.connect() as c:
            baris = c.execute(
                text(
                    "SELECT urutan, halaman, sumber_url, tahun_siklus, embedding_model, vector_dims(embedding), "
                    "vector_norm(embedding) FROM rag_chunks ORDER BY urutan"
                )
            ).all()
        assert [b[0] for b in baris] == list(range(n))
        assert {b[1] for b in baris} == {1, 2, 3} and [b[1] for b in baris] == sorted(
            b[1] for b in baris
        )
        assert {b[2] for b in baris} == {URL} and {b[3] for b in baris} == {2026}
        assert {b[4] for b in baris} == {"gemini-embedding-001"}
        assert {b[5] for b in baris} == {768}
        assert all(b[6] == pytest.approx(1.0, abs=1e-5) for b in baris)  # ternormalisasi L2

    def test_ulang_tanpa_perubahan_tidak_memanggil_api(self, clean_db, app_config, tmp_path):
        cfg = konfig_kecil(app_config)
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        fake = FakeLLM()
        with Session(clean_db) as db:
            r1 = ingest_dokumen(db, fake, cfg, "doc1", tmp_path)
            dipanggil = fake.panggilan_embed
            r2 = ingest_dokumen(db, fake, cfg, "doc1", tmp_path)
        assert fake.panggilan_embed == dipanggil and r2.panggilan_embed == 0
        assert (r2.di_embed, r2.tidak_berubah) == (0, r1.jumlah_chunk)
        assert hitung(clean_db) == r1.jumlah_chunk  # tidak menggandakan

    def test_hanya_chunk_yang_berubah_di_embed_ulang(self, clean_db, app_config, tmp_path):
        cfg = konfig_kecil(app_config)
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        fake = FakeLLM()
        with Session(clean_db) as db:
            ingest_dokumen(db, fake, cfg, "doc1", tmp_path)
            lama = {(c.urutan, c.halaman, c.teks) for c in buat_chunk(tmp_path / "doc1.pdf", cfg)}
            tulis_pdf(tmp_path, [self.HAL[0], paragraf("EDIT"), self.HAL[2]])
            baru = {(c.urutan, c.halaman, c.teks) for c in buat_chunk(tmp_path / "doc1.pdf", cfg)}
            sebelum = fake.panggilan_embed
            r = ingest_dokumen(db, fake, cfg, "doc1", tmp_path)
        berubah = len(baru - lama)
        assert 0 < berubah < r.jumlah_chunk
        assert r.di_embed == berubah and fake.panggilan_embed - sebelum == math.ceil(berubah / 4)

    def test_dokumen_menyusut_menghapus_chunk_usang(self, clean_db, app_config, tmp_path):
        cfg = konfig_kecil(app_config)
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        with Session(clean_db) as db:
            r1 = ingest_dokumen(db, FakeLLM(), cfg, "doc1", tmp_path)
            tulis_pdf(tmp_path, [self.HAL[0]])
            r2 = ingest_dokumen(db, FakeLLM(), cfg, "doc1", tmp_path)
        assert r2.dihapus == r1.jumlah_chunk - r2.jumlah_chunk > 0
        assert hitung(clean_db) == r2.jumlah_chunk

    def test_gagal_embedding_tidak_menyimpan_apa_pun(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        with Session(clean_db) as db, pytest.raises(LLMGagal):
            ingest_dokumen(
                db, FakeLLM(gagal_embed=LLMGagal("x")), konfig_kecil(app_config), "doc1", tmp_path
            )
        assert hitung(clean_db) == 0

    def test_gagal_di_batch_kedua_membatalkan_semuanya(self, clean_db, app_config, tmp_path):
        class GagalBatchKedua(FakeLLM):
            def embed(self, teks, *, task_type):
                if self.panggilan_embed >= 1:
                    self.panggilan_embed += 1
                    raise LLMGagal("batch kedua gagal")
                return super().embed(teks, task_type=task_type)

        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        with Session(clean_db) as db, pytest.raises(LLMGagal):
            ingest_dokumen(
                db, GagalBatchKedua(), konfig_kecil(app_config), "doc1", tmp_path, retry=0
            )
        assert hitung(clean_db) == 0

    def test_retry_saat_kuota_habis_dengan_jeda_bertambah(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, [paragraf("satu", 3)])
        tidur: list[float] = []
        fake = KuotaDulu(2)
        with Session(clean_db) as db:
            r = ingest_dokumen(
                db,
                fake,
                konfig_kecil(app_config, ukuran_batch_embedding=100),
                "doc1",
                tmp_path,
                retry=3,
                jeda_detik=2,
                tidur=tidur.append,
            )
        assert tidur == [2, 4] and r.di_embed == r.jumlah_chunk > 0

    def test_retry_habis_melempar_error_kuota(self):
        tidur: list[float] = []
        with pytest.raises(LLMKuotaHabis):
            embed_dengan_retry(
                KuotaDulu(10),
                ["x"],
                task_type="RETRIEVAL_DOCUMENT",
                retry=2,
                jeda_detik=1,
                tidur=tidur.append,
            )
        assert tidur == [1, 2]

    def test_dimensi_embedding_salah_ditolak_sebelum_menulis(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        with Session(clean_db) as db, pytest.raises(LLMGagal, match="768"):
            ingest_dokumen(db, FakeLLM(dimensi=3), konfig_kecil(app_config), "doc1", tmp_path)
        assert hitung(clean_db) == 0

    def test_dokumen_tidak_terdaftar_dan_berkas_tidak_ada(self, clean_db, app_config, tmp_path):
        with Session(clean_db) as db:
            with pytest.raises(DokumenTidakTerdaftar, match="belum terdaftar"):
                ingest_dokumen(db, FakeLLM(), app_config, "hantu", tmp_path)
            daftar_dokumen(clean_db)
            with pytest.raises(BerkasTidakAda, match="Unduh manual"):
                ingest_dokumen(db, FakeLLM(), app_config, "doc1", tmp_path)

    def test_html_diingest_tanpa_halaman(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db, "faq")
        (tmp_path / "faq.html").write_text(
            f"<html><body><script>x=1</script><p>{banyak_kalimat(10)}</p></body></html>",
            encoding="utf-8",
        )
        with Session(clean_db) as db:
            r = ingest_dokumen(db, FakeLLM(), konfig_kecil(app_config), "faq", tmp_path)
        assert r.jumlah_chunk > 1
        with clean_db.connect() as c:
            assert c.execute(text("SELECT DISTINCT halaman FROM rag_chunks")).scalars().all() == [
                None
            ]

    def test_guard_token_chunk(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, self.HAL)
        with Session(clean_db) as db, pytest.raises(ChunkTerlaluBesar):
            ingest_dokumen(
                db, FakeLLM(), konfig_kecil(app_config, maks_token_chunk=5), "doc1", tmp_path
            )
        assert hitung(clean_db) == 0

    def test_ganti_model_embedding_memicu_embed_ulang(self, clean_db, app_config, tmp_path):
        """Chunk bermodel lain dianggap berubah -> di-embed ulang (vektor beda model tak boleh tercampur)."""
        cfg = konfig_kecil(app_config)
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, [self.HAL[0]])
        with Session(clean_db) as db:
            r1 = ingest_dokumen(db, FakeLLM(), cfg, "doc1", tmp_path)
            db.execute(text("UPDATE rag_chunks SET embedding_model = 'model-lama'"))
            db.commit()
            r2 = ingest_dokumen(db, FakeLLM(), cfg, "doc1", tmp_path)
        assert r2.di_embed == r1.jumlah_chunk
        with clean_db.connect() as c:
            assert c.execute(
                text("SELECT DISTINCT embedding_model FROM rag_chunks")
            ).scalars().all() == ["gemini-embedding-001"]


# ============================================================== retrieve (DB)


def unit(indeks: int, dimensi: int = 768) -> list[float]:
    v = [0.0] * dimensi
    v[indeks] = 1.0
    return v


def campur(a: list[float], b: list[float], bobot_a: float) -> list[float]:
    return l2_normalisasi([bobot_a * x + (1 - bobot_a) * y for x, y in zip(a, b, strict=True)])


@pytest.mark.db
class TestRetrieve:
    def _isi(self, engine: Engine) -> None:
        daftar_dokumen(engine, "d1")
        daftar_dokumen(engine, "d2")
        with Session(engine) as db:
            data = [
                ("d1", 0, "Aturan pilihan SNBP dua prodi.", 12, unit(0), "gemini-embedding-001"),
                ("d1", 1, "Syarat SNBT lulusan tiga tahun.", 13, unit(1), "gemini-embedding-001"),
                ("d2", 0, "Jadwal pendaftaran dan biaya.", None, unit(2), "gemini-embedding-001"),
                ("d2", 1, "Chunk model lama yang harus diabaikan.", 1, unit(1), "model-lama"),
            ]
            for dok, urutan, teks, hal, vek, model in data:
                db.add(
                    m.RagChunk(
                        dokumen_id=dok,
                        urutan=urutan,
                        teks=teks,
                        halaman=hal,
                        embedding=vek,
                        embedding_model=model,
                        sumber_url=URL,
                        tahun_siklus=2026,
                    )
                )
            db.commit()

    def test_urutan_skor_dan_metadata(self, clean_db):
        self._isi(clean_db)
        query = campur(unit(1), unit(0), 0.9)  # dekat chunk SNBT, lalu SNBP
        with Session(clean_db) as db:
            hasil = cari(db, query, top_k=3, embedding_model="gemini-embedding-001")
        assert [h.teks for h in hasil] == [
            "Syarat SNBT lulusan tiga tahun.",
            "Aturan pilihan SNBP dua prodi.",
            "Jadwal pendaftaran dan biaya.",
        ]
        skor = [h.skor for h in hasil]
        assert skor == sorted(skor, reverse=True)
        assert skor[0] == pytest.approx(
            sum(a * b for a, b in zip(query, unit(1), strict=True)), abs=1e-5
        )  # = dot
        assert skor[2] == pytest.approx(0.0, abs=1e-5)
        top = hasil[0]
        assert (top.dokumen_id, top.judul, top.halaman, top.url, top.tahun_siklus) == (
            "d1",
            "Dokumen d1",
            13,
            URL,
            2026,
        )

    def test_top_k_dan_filter_model(self, clean_db):
        self._isi(clean_db)
        with Session(clean_db) as db:
            semua = cari(db, unit(1), top_k=10, embedding_model="gemini-embedding-001")
            satu = cari(db, unit(1), top_k=1, embedding_model="gemini-embedding-001")
            lama = cari(db, unit(1), top_k=10, embedding_model="model-lama")
        assert len(semua) == 3 and "model lama" not in " ".join(
            h.teks for h in semua
        )  # model lain tak tercampur
        assert len(satu) == 1 and satu[0].skor == pytest.approx(1.0, abs=1e-6)
        assert [h.teks for h in lama] == ["Chunk model lama yang harus diabaikan."]

    def test_ambang(self, clean_db):
        self._isi(clean_db)
        with Session(clean_db) as db:
            hasil = cari(
                db, campur(unit(1), unit(0), 0.8), top_k=3, embedding_model="gemini-embedding-001"
            )
        # kosinus 0,8*e1 + 0,2*e0 (dinormalisasi): ke chunk SNBT 0,970 dan ke chunk SNBP 0,243
        assert [round(h.skor, 3) for h in hasil[:2]] == [0.970, 0.243]
        assert [h.dokumen_id for h in di_atas_ambang(hasil, 0.55)] == ["d1"]
        assert len(di_atas_ambang(hasil, 0.2)) == 2 and len(di_atas_ambang(hasil, 0.99)) == 0
        assert di_atas_ambang(hasil, -1.0) == hasil

    def test_tabel_kosong(self, clean_db):
        with Session(clean_db) as db:
            assert cari(db, unit(0), top_k=4, embedding_model="gemini-embedding-001") == []


# ============================================================== unggah multipart (admin)

KUNCI = "kunci-admin-rag"


@pytest.mark.db
class TestUnggah:
    def _client(self, engine, app_config, tmp_path, llm=None):
        app = create_app(
            make_settings(admin_key=KUNCI, dokumen_dir=str(tmp_path)),
            konfig_kecil(app_config),
            engine,
            llm_client=llm or FakeLLM(),
        )
        return TestClient(app), app

    def _kirim(self, c, dokumen_id="doc1", isi=None, proses=False, kunci=KUNCI):
        isi = isi if isi is not None else buat_pdf([paragraf("unggah")])
        return c.post(
            f"/api/v1/admin/dokumen/{dokumen_id}/berkas",
            params={"proses": str(proses).lower()},
            files={"berkas": ("apa-saja.pdf", isi, "application/pdf")},
            headers={"X-Admin-Key": kunci} if kunci else {},
        )

    def test_wajib_admin_key(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path)
        assert self._kirim(c, kunci=None).status_code == 401
        assert self._kirim(c, kunci="salah").status_code == 401
        assert list(tmp_path.iterdir()) == []

    def test_dokumen_tidak_terdaftar_atau_id_berbahaya(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path)
        for ident in ("hantu", "..", "a..b%2F..%2Fx", ".rahasia"):
            assert self._kirim(c, ident).status_code == 404, ident
        assert list(tmp_path.iterdir()) == []

    def test_bukan_pdf_dan_terlalu_besar(self, clean_db, app_config, tmp_path, monkeypatch):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path)
        r = self._kirim(c, isi=b"<html>bukan pdf</html>")
        assert r.status_code == 422 and r.json()["error"]["kode"] == "bukan_pdf"
        monkeypatch.setattr("app.api.v1.admin.MAKS_UNGGAH_BYTE", 50)
        r = self._kirim(c, isi=buat_pdf([paragraf("besar")]))
        assert r.status_code == 413 and r.json()["error"]["kode"] == "berkas_terlalu_besar"
        assert list(tmp_path.iterdir()) == []

    def test_unggah_menulis_berkas_apa_adanya(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path)
        isi = buat_pdf([paragraf("simpan")])
        r = self._kirim(c, isi=isi)
        assert r.status_code == 200
        assert r.json() == {
            "dokumen_id": "doc1",
            "berkas": "doc1.pdf",
            "ukuran_byte": len(isi),
            "diterima": 1,
            "error": [],
            "proses": None,
        }
        assert (tmp_path / "doc1.pdf").read_bytes() == isi  # nama berkas dari ID, bukan dari klien
        assert not list(tmp_path.glob("*.tmp"))
        assert hitung(clean_db) == 0  # tanpa proses=true tidak ada embedding

    def test_unggah_dengan_proses(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        fake = FakeLLM()
        c, _ = self._client(clean_db, app_config, tmp_path, llm=fake)
        r = self._kirim(c, isi=buat_pdf([paragraf("proses"), paragraf("lagi")]), proses=True)
        assert r.status_code == 200
        proses = r.json()["proses"]
        assert proses["jumlah_chunk"] > 2 and proses["di_embed"] == proses["jumlah_chunk"]
        assert hitung(clean_db) == proses["jumlah_chunk"] and r.json()["error"] == []

    def test_proses_gagal_berkas_tetap_tersimpan(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path, llm=FakeLLM(gagal_embed=LLMGagal("x")))
        r = self._kirim(c, proses=True)
        assert r.status_code == 200 and r.json()["proses"] is None
        assert "LLMGagal" in r.json()["error"][0]["pesan"] and (tmp_path / "doc1.pdf").exists()
        assert hitung(clean_db) == 0

    def test_pdf_tanpa_teks_dilaporkan(self, clean_db, app_config, tmp_path):
        daftar_dokumen(clean_db)
        c, _ = self._client(clean_db, app_config, tmp_path)
        r = self._kirim(c, isi=buat_pdf(["", ""]), proses=True)
        assert r.status_code == 200 and "scan" in r.json()["error"][0]["pesan"]


# ============================================================== skrip CLI


@pytest.mark.db
class TestSkrip:
    def test_dry_run_mencetak_ringkasan_chunk(self, clean_db, tmp_path, capsys):
        daftar_dokumen(clean_db)
        tulis_pdf(tmp_path, [paragraf("a"), paragraf("b")])
        url = clean_db.url.render_as_string(hide_password=False)
        kode = ingest_docs.main(["--dry-run", "--dir", str(tmp_path), "--database-url", url])
        out = capsys.readouterr().out
        assert kode == 0 and re.search(r"\[DRY\]\s+doc1: \d+ chunk", out) and "halaman 2" in out
        assert hitung(clean_db) == 0  # dry-run tidak menulis

    def test_berkas_hilang_dilaporkan_dengan_kode_keluar_1(self, clean_db, tmp_path, capsys):
        daftar_dokumen(clean_db)
        url = clean_db.url.render_as_string(hide_password=False)
        kode = ingest_docs.main(["--dry-run", "--dir", str(tmp_path), "--database-url", url])
        assert kode == 1 and "Unduh manual" in capsys.readouterr().out

    def test_tanpa_api_key_menolak_kecuali_dry_run(self, monkeypatch, capsys):
        from app.core import config

        monkeypatch.setattr(config, "get_settings", lambda: make_settings(gemini_api_key=""))
        monkeypatch.setattr(ingest_docs, "get_settings", lambda: make_settings(gemini_api_key=""))
        assert ingest_docs.main([]) == 2
        assert "GEMINI_API_KEY" in capsys.readouterr().err
