"""Task 12: infrastruktur LLM: klien, cache, antrean, fallback, PII, pagar keluaran. Tanpa jaringan."""

from __future__ import annotations

import ast
import logging
import math
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from google.genai import errors as gerrors
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import batasi_llm
from app.core.config import ROOT_DIR, AppConfig, Batas
from app.llm import cache
from app.llm.client import GeminiClient, NullClient, l2_normalisasi, petakan_error
from app.llm.errors import (
    LLMGagal,
    LLMKuotaHabis,
    LLMLayananSibuk,
    LLMModelTidakAda,
    LLMTidakDikonfigurasi,
    LLMTimeout,
)
from app.llm.fallback_texts import penjelasan_dari_hasil
from app.llm.guard import angka_tidak_dikenal, keluaran_aman
from app.llm.pii import normalisasi_pertanyaan, saring_pii
from app.llm.prompts import (
    SISTEM_JELASKAN,
    SISTEM_RAG,
    ChunkKonteks,
    JawabanRAG,
    prompt_jelaskan,
    prompt_rag,
)
from app.llm.service import LLMService, buat_client
from app.main import create_app
from app.services.querylog import PANJANG_MAKS, catat
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.helpers import analyze, masuk, muat_persona

# ============================================================== PII (tanpa DB)


@pytest.mark.parametrize(
    "teks,jenis",
    [
        ("hubungi aku di rani.s+osn@gmail.com ya", "email"),
        ("wa 081234567890 ya", "telepon"),
        ("telp +62 812-3456-7890", "telepon"),
        ("nomorku 0812 3456 7890", "telepon"),
        ("62812.3456.7890", "telepon"),
        ("NIK 3201123456780001 aku", "angka_panjang"),
        ("NISN: 0051234567", "angka_panjang"),
        ("nik 3201 1234 5678 0001", "angka_panjang"),
    ],
)
def test_pii_disaring(teks, jenis):
    h = saring_pii(teks)
    assert h.ada and jenis in h.ditemukan
    for fragmen in (
        "@gmail",
        "081234567890",
        "3456 7890",
        "3201123456780001",
        "0051234567",
        "5678 0001",
    ):
        assert fragmen not in h.teks
    assert any(p in h.teks for p in ("[email]", "[telepon]", "[angka]"))


@pytest.mark.parametrize(
    "teks",
    [
        "skor tryout 620",
        "aku lulus tahun 2026, bisa ikut SNBT 2026?",
        "peringkat 12 dari 300 siswa",
        "biaya UTBK Rp1.500.000",
        "kuota 45 persen untuk akreditasi A",
        "nilai 85 dan 90 dan 78",
        "SNBP 2026 butuh dokumen apa saja?",
    ],
)
def test_teks_wajar_tidak_diubah(teks):
    h = saring_pii(teks)
    assert h.teks == teks and not h.ada


def test_pii_idempoten_dan_campuran():
    h = saring_pii("email a@b.co telp 081234567890 nik 3201123456780001")
    assert set(h.ditemukan) == {"email", "telepon", "angka_panjang"}
    assert saring_pii(h.teks).teks == h.teks and not saring_pii(h.teks).ada


def test_normalisasi_pertanyaan_kanonik():
    a = normalisasi_pertanyaan("Apa syarat SNBT?")
    assert a == normalisasi_pertanyaan("  apa   SYARAT snbt ")
    assert a == normalisasi_pertanyaan("Apa syarat, SNBT!!")
    assert a != normalisasi_pertanyaan("Apa syarat SNBP?")


# ============================================================== pagar keluaran


def test_pagar_angka_dan_persen():
    fakta = {"skor": 0.83, "rasio": 28.43, "gap": 40.0, "tahun": 2025, "n_prodi": 31}
    assert keluaran_aman("Rasio 28,43 dari 31 prodi, gap 40 poin, data 2025.", fakta) == (
        True,
        None,
    )
    ok, alasan = keluaran_aman("Peluangmu 80%.", fakta)
    assert not ok and "persentase" in alasan
    ok, alasan = keluaran_aman("Ada 99 prodi pembanding.", fakta)
    assert not ok and "99" in alasan
    assert not keluaran_aman("Kemungkinan diterima tinggi.", fakta)[0]
    assert angka_tidak_dikenal("620 dan 41", {"a": 620}) == ["41"]


# ============================================================== prompt


def test_prompt_rag_memberi_nomor_dan_membungkus_data():
    p = prompt_rag(
        "Berapa pilihan SNBP?",
        [
            ChunkKonteks(1, "Paparan SNPMB", 12, "Dua prodi."),
            ChunkKonteks(2, "FAQ", None, "Lainnya."),
        ],
    )
    assert "<konteks>" in p and "<pertanyaan>" in p
    assert "[1] Paparan SNPMB, halaman 12" in p and "[2] FAQ\n" in p
    assert "HANYA" in SISTEM_RAG and "mengarang" in SISTEM_RAG
    assert "persentase" in SISTEM_RAG and "DATA" in SISTEM_RAG  # pertahanan prompt injection
    assert JawabanRAG.model_json_schema()["required"] == ["jawaban", "cukup_informasi"]


def test_prompt_jelaskan_hanya_dari_fakta():
    p = prompt_jelaskan("Kenapa reach?", {"kategori": "reach", "gap": 40})
    assert '"gap": 40' in p and "<fakta>" in p
    assert "jangan menambah angka" in SISTEM_JELASKAN.lower()


# ============================================================== GeminiClient (SDK palsu)


class SDKPalsu:
    def __init__(self, *, embed=None, generate=None, gagal: Exception | None = None):
        self.panggilan: list[tuple] = []
        self._embed, self._generate, self._gagal = embed, generate, gagal
        self.models = SimpleNamespace(
            embed_content=self._embed_content, generate_content=self._generate_content
        )

    def _embed_content(self, *, model, contents, config):
        self.panggilan.append(("embed", model, list(contents), config))
        if self._gagal:
            raise self._gagal
        vec = self._embed if self._embed is not None else [3.0, 4.0] + [0.0] * 766
        return SimpleNamespace(embeddings=[SimpleNamespace(values=list(vec)) for _ in contents])

    def _generate_content(self, *, model, contents, config):
        self.panggilan.append(("generate", model, contents, config))
        if self._gagal:
            raise self._gagal
        return SimpleNamespace(text=self._generate)


def gemini(sdk) -> GeminiClient:
    return GeminiClient(
        "kunci-palsu",
        model="gemini-uji",
        embedding_model="gemini-embedding-001",
        dimensi=768,
        timeout_detik=5,
        sdk_client=sdk,
    )


def test_embedding_dikirim_dengan_task_type_dimensi_dan_dinormalisasi_l2():
    sdk = SDKPalsu()
    hasil = gemini(sdk).embed(["Apa syarat SNBT?"], task_type="RETRIEVAL_QUERY")
    jenis, model, isi, config = sdk.panggilan[0]
    assert (jenis, model, isi) == ("embed", "gemini-embedding-001", ["Apa syarat SNBT?"])
    assert config.task_type == "RETRIEVAL_QUERY" and config.output_dimensionality == 768
    assert len(hasil) == 1 and len(hasil[0]) == 768
    assert math.sqrt(sum(x * x for x in hasil[0])) == pytest.approx(1.0)
    assert hasil[0][:2] == pytest.approx([0.6, 0.8])  # (3,4) -> (0.6, 0.8)


def test_embedding_dimensi_salah_ditolak():
    with pytest.raises(LLMGagal, match="768"):
        gemini(SDKPalsu(embed=[1.0, 2.0, 3.0])).embed(["x"], task_type="RETRIEVAL_DOCUMENT")


def test_generate_mengirim_system_dan_skema_json():
    sdk = SDKPalsu(generate='{"jawaban": "ok"}')
    out = gemini(sdk).generate(
        "halo", system="aturan", json_schema=JawabanRAG, max_output_tokens=256
    )
    assert out == '{"jawaban": "ok"}'
    _, model, isi, config = sdk.panggilan[0]
    assert (model, isi) == ("gemini-uji", "halo")
    assert config.system_instruction == "aturan" and config.response_mime_type == "application/json"
    assert config.max_output_tokens == 256


def test_generate_tanpa_skema_teks_biasa_dan_respons_kosong_gagal():
    sdk = SDKPalsu(generate="Teks bebas")
    assert gemini(sdk).generate("halo") == "Teks bebas"
    assert sdk.panggilan[0][3].response_mime_type is None
    with pytest.raises(LLMGagal, match="kosong"):
        gemini(SDKPalsu(generate="   ")).generate("halo")


@pytest.mark.parametrize(
    "galat,tipe",
    [
        (gerrors.ClientError(429, {"error": {"message": "quota"}}), LLMKuotaHabis),
        (gerrors.ClientError(404, {"error": {"message": "model not found"}}), LLMModelTidakAda),
        (gerrors.ClientError(403, {"error": {"message": "key"}}), LLMGagal),
        (gerrors.ServerError(503, {"error": {"message": "down"}}), LLMGagal),
        (gerrors.ServerError(504, {"error": {"message": "slow"}}), LLMTimeout),
        (httpx.ReadTimeout("lambat"), LLMTimeout),
        (RuntimeError("isi prompt rahasia"), LLMGagal),
    ],
)
def test_pemetaan_error_penyedia(galat, tipe):
    with pytest.raises(tipe) as info:
        gemini(SDKPalsu(gagal=galat)).generate("pertanyaan-sangat-rahasia")
    assert "rahasia" not in str(info.value) and "kunci-palsu" not in str(info.value)
    assert (
        info.value.__suppress_context__
    )  # error asli (mungkin memuat isi permintaan) tidak ikut terbawa


def test_petakan_error_langsung():
    assert isinstance(petakan_error(TimeoutError()), LLMTimeout)


def test_null_client_dan_pemilihan_klien(app_config):
    with pytest.raises(LLMTidakDikonfigurasi):
        NullClient().embed(["x"], task_type="RETRIEVAL_QUERY")
    with pytest.raises(LLMTidakDikonfigurasi):
        NullClient().generate("x")
    assert isinstance(buat_client(make_settings(gemini_api_key=""), app_config), NullClient)
    assert isinstance(buat_client(make_settings(gemini_api_key="k"), app_config), GeminiClient)


class SDKPerModel:
    """generate_content gagal/berhasil sesuai nama model; mencatat urutan model yang dicoba."""

    def __init__(self, hasil: dict):
        self.hasil, self.dicoba = hasil, []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, *, model, contents, config):
        self.dicoba.append(model)
        h = self.hasil[model]
        if isinstance(h, list):  # urutan hasil per panggilan ke model yang sama
            h = h.pop(0) if len(h) > 1 else h[0]
        if isinstance(h, Exception):
            raise h
        return SimpleNamespace(text=h)


E404 = gerrors.ClientError(404, {"error": {"message": "x"}})
E429 = gerrors.ClientError(429, {"error": {"message": "x"}})
E503 = gerrors.ServerError(503, {"error": {"message": "x"}})
E504 = gerrors.ServerError(504, {"error": {"message": "x"}})
ETIMEOUT = httpx.ReadTimeout("lambat")


def gemini_cadangan(sdk, cadangan) -> GeminiClient:
    return GeminiClient(
        "kunci-palsu",
        model="utama",
        embedding_model="gemini-embedding-001",
        dimensi=768,
        timeout_detik=5,
        model_cadangan=cadangan,
        jeda_ulang_503_detik=0,
        sdk_client=sdk,
    )


@pytest.mark.parametrize("galat", [E404, E429, E504, ETIMEOUT])
def test_model_utama_404_429_atau_timeout_dicoba_cadangan_berurutan(galat):
    sdk = SDKPerModel({"utama": galat, "c1": E429, "c2": "dari c2"})
    assert gemini_cadangan(sdk, ["c1", "c2"]).generate("halo") == "dari c2"
    assert sdk.dicoba == ["utama", "c1", "c2"]  # timeout/404/429 tidak diulang, langsung pindah


def test_503_diulang_sekali_pada_model_yang_sama_lalu_berhasil():
    sdk = SDKPerModel({"utama": [E503, "pulih"], "c1": "tidak dipakai"})
    assert gemini_cadangan(sdk, ["c1"]).generate("halo") == "pulih"
    assert sdk.dicoba == ["utama", "utama"]


def test_503_dua_kali_pindah_ke_cadangan_dan_cadangan_juga_diulang_sekali():
    sdk = SDKPerModel({"utama": E503, "c1": [E503, "dari c1"]})
    assert gemini_cadangan(sdk, ["c1"]).generate("halo") == "dari c1"
    assert sdk.dicoba == ["utama", "utama", "c1", "c1"]  # maksimal dua percobaan per model


def test_semua_model_503_melempar_layanan_sibuk_untuk_template():
    sdk = SDKPerModel({"utama": E503, "c1": E503})
    with pytest.raises(LLMLayananSibuk):
        gemini_cadangan(sdk, ["c1"]).generate("halo")
    assert sdk.dicoba == ["utama", "utama", "c1", "c1"]


def test_semua_model_timeout_melempar_timeout_untuk_template():
    sdk = SDKPerModel({"utama": ETIMEOUT, "c1": E504})
    with pytest.raises(LLMTimeout):
        gemini_cadangan(sdk, ["c1"]).generate("halo")
    assert sdk.dicoba == ["utama", "c1"]


def test_rantai_campuran_404_lalu_503_lalu_sukses():
    sdk = SDKPerModel({"utama": E404, "c1": [E503, E503], "c2": "akhirnya"})
    assert gemini_cadangan(sdk, ["c1", "c2"]).generate("halo") == "akhirnya"
    assert sdk.dicoba == ["utama", "c1", "c1", "c2"]


def test_cadangan_tidak_dicoba_bila_utama_berhasil_dan_duplikat_diabaikan():
    sdk = SDKPerModel({"utama": "ok", "c1": "tidak dipakai"})
    assert gemini_cadangan(sdk, ["utama", "c1", "c1"]).generate("halo") == "ok"
    assert sdk.dicoba == ["utama"]


@pytest.mark.parametrize(
    "galat",
    [
        gerrors.ServerError(500, {"error": {"message": "x"}}),
        gerrors.ClientError(403, {"error": {"message": "x"}}),
        gerrors.ClientError(400, {"error": {"message": "x"}}),
        RuntimeError("tak terduga"),
    ],
)
def test_error_selain_404_429_503_timeout_tidak_dicoba_ke_cadangan(galat):
    sdk = SDKPerModel({"utama": galat, "c1": "ok"})
    with pytest.raises(LLMGagal):
        gemini_cadangan(sdk, ["c1"]).generate("halo")
    assert sdk.dicoba == ["utama"]  # kredensial/permintaan salah: model lain tidak menolong


def test_semua_model_gagal_melempar_error_terakhir_dan_404_diingat():
    sdk = SDKPerModel({"utama": E404, "c1": E429})
    klien = gemini_cadangan(sdk, ["c1"])
    with pytest.raises(LLMKuotaHabis):
        klien.generate("halo")
    with pytest.raises(LLMKuotaHabis):
        klien.generate("halo")
    assert sdk.dicoba == ["utama", "c1", "c1"]  # utama 404 tidak dicoba lagi
    sdk2 = SDKPerModel({"utama": E404})
    klien2 = gemini_cadangan(sdk2, [])
    with pytest.raises(LLMModelTidakAda):
        klien2.generate("halo")
    with pytest.raises(LLMModelTidakAda):  # semua model sudah ditandai 404
        klien2.generate("halo")
    assert sdk2.dicoba == ["utama"]


def test_env_model_menimpa_yaml_dan_cadangan_diteruskan(app_config):
    from app.core.config import terapkan_env_model

    s = make_settings(
        llm_model=" m-baru ", embed_model="e-baru", llm_model_fallback="a, b ,m-baru,a"
    )
    cfg = terapkan_env_model(app_config, s)
    assert (cfg.llm.model, cfg.embedding.model) == ("m-baru", "e-baru")
    assert cfg.embedding.dimensi == app_config.embedding.dimensi
    assert s.llm_model_fallback_list == ["a", "b"]  # tanpa model utama dan duplikat
    assert terapkan_env_model(app_config, make_settings()) is app_config  # kosong = tidak berubah
    klien = buat_client(make_settings(gemini_api_key="k", llm_model_fallback="a,b"), app_config)
    assert klien._urutan_model == [app_config.llm.model, "a", "b"]


def test_create_app_menerapkan_env_model(app_config):
    app = create_app(make_settings(llm_model="m-baru"), app_config, llm_client=FakeLLM())
    assert app.state.config.llm.model == "m-baru"


def test_list_models_mengelompokkan_berdasarkan_aksi():
    from scripts.list_models import kelompokkan

    def model(nama, *aksi):
        return SimpleNamespace(name=f"models/{nama}", supported_actions=list(aksi))

    gen, emb = kelompokkan(
        [
            model("b-gen", "generateContent", "countTokens"),
            model("a-gen", "generateContent"),
            model("e1", "embedContent"),
            model("lain", "predict"),
        ]
    )
    assert [m.name for m in gen] == ["models/a-gen", "models/b-gen"]
    assert [m.name for m in emb] == ["models/e1"]


def test_l2_normalisasi_vektor_nol_ditolak():
    with pytest.raises(LLMGagal):
        l2_normalisasi([0.0, 0.0])


# ============================================================== layanan + cache + antrean (DB)


def layanan(app_config: AppConfig, klien, **llm_ubah) -> LLMService:
    cfg = app_config.model_copy(update={"llm": app_config.llm.model_copy(update=llm_ubah)})
    return LLMService(klien, cfg)


@pytest.mark.db
class TestLLMService:
    def test_embedding_di_cache_per_pertanyaan_ternormalisasi(self, clean_db, app_config):
        fake = FakeLLM()
        svc = layanan(app_config, fake)
        with Session(clean_db) as db:
            a = svc.embed_pertanyaan(db, "Apa syarat SNBT?")
            b = svc.embed_pertanyaan(db, "  apa   SYARAT snbt ")
            c = svc.embed_pertanyaan(db, "Apa syarat SNBP?")
        assert fake.panggilan_embed == 2  # a (b dari cache) dan c
        assert (a.dari_cache, b.dari_cache, c.dari_cache) == (False, True, False)
        assert a.vektor == b.vektor and a.vektor != c.vektor and len(a.vektor) == 768
        assert fake.task_types == ["RETRIEVAL_QUERY", "RETRIEVAL_QUERY"]

    def test_embedding_gagal_menjadi_fallback_bukan_exception(self, clean_db, app_config):
        fake = FakeLLM(gagal_embed=LLMKuotaHabis("429"))
        with Session(clean_db) as db:
            h = layanan(app_config, fake).embed_pertanyaan(db, "pertanyaan")
        assert h.fallback and h.vektor is None and h.alasan == "LLMKuotaHabis"

    def test_hasil_gagal_tidak_di_cache(self, clean_db, app_config):
        fake = FakeLLM(gagal_embed=LLMTimeout("t"))
        svc = layanan(app_config, fake)
        with Session(clean_db) as db:
            svc.embed_pertanyaan(db, "sama")
            svc.embed_pertanyaan(db, "sama")
        assert fake.panggilan_embed == 2

    def test_generate_di_cache_untuk_masukan_sama(self, clean_db, app_config):
        fake = FakeLLM(teks="Penjelasan A")
        svc = layanan(app_config, fake)
        kw = dict(
            namespace="jelaskan",
            system="s",
            prompt="p",
            kunci_cache={"hasil": {"kategori": "reach"}},
        )
        with Session(clean_db) as db:
            h1 = svc.generate(db, **kw)
            h2 = svc.generate(db, **kw)
            h3 = svc.generate(db, **{**kw, "kunci_cache": {"hasil": {"kategori": "safe"}}})
        assert fake.panggilan_generate == 2
        assert (h1.teks, h1.dari_cache) == ("Penjelasan A", False)
        assert (h2.teks, h2.dari_cache) == ("Penjelasan A", True)
        assert h3.dari_cache is False and not h1.fallback

    def test_cache_dimatikan_dengan_ttl_nol(self, clean_db, app_config):
        fake = FakeLLM()
        svc = layanan(app_config, fake, cache_ttl_detik=0)
        kw = dict(namespace="n", system="s", prompt="p", kunci_cache={"x": 1})
        with Session(clean_db) as db:
            svc.generate(db, **kw)
            svc.generate(db, **kw)
        assert fake.panggilan_generate == 2

    def test_cache_kedaluwarsa_dihitung_ulang_dan_dibersihkan(self, clean_db, app_config):
        fake = FakeLLM()
        svc = layanan(app_config, fake, cache_ttl_detik=100)
        kw = dict(namespace="n", system="s", prompt="p", kunci_cache={"x": 1})
        with Session(clean_db) as db:
            svc.generate(db, **kw)
            db.execute(text("UPDATE llm_cache SET created_at = now() - interval '200 seconds'"))
            db.commit()
            svc.generate(db, **kw)
            assert fake.panggilan_generate == 2  # kedaluwarsa -> hitung ulang
            db.execute(text("UPDATE llm_cache SET created_at = now() - interval '200 seconds'"))
            cache.simpan(db, "kunci-baru", {"teks": "segar"}, 3600)
            db.commit()
        n = cache.hapus_kedaluwarsa(sessionmaker(bind=clean_db))
        assert n == 1
        with clean_db.connect() as conn:
            assert conn.execute(text("SELECT key_hash FROM llm_cache")).scalars().all() == [
                "kunci-baru"
            ]

    def test_kunci_cache_bergantung_pada_model_dan_namespace(self):
        a = cache.buat_kunci("jelaskan", "model-a", {"x": 1})
        assert a != cache.buat_kunci("jelaskan", "model-b", {"x": 1})
        assert a != cache.buat_kunci("narasi", "model-a", {"x": 1})
        assert a == cache.buat_kunci("jelaskan", "model-a", {"x": 1})
        assert cache.buat_kunci("n", "m", {"a": 1, "b": 2}) == cache.buat_kunci(
            "n", "m", {"b": 2, "a": 1}
        )

    @pytest.mark.parametrize(
        "galat,alasan",
        [
            (LLMKuotaHabis("429"), "LLMKuotaHabis"),
            (LLMTimeout("t"), "LLMTimeout"),
            (LLMGagal("x"), "LLMGagal"),
            (RuntimeError("tak terduga"), "LLMGagal"),
        ],
    )
    def test_kegagalan_generate_jadi_fallback(self, clean_db, app_config, galat, alasan):
        svc = layanan(app_config, FakeLLM(gagal=galat))
        with Session(clean_db) as db:
            h = svc.generate(db, namespace="n", system="s", prompt="p", kunci_cache={"x": 1})
        assert h.fallback and h.teks is None and h.alasan == alasan

    def test_tanpa_api_key_fallback(self, clean_db, app_config):
        svc = LLMService(NullClient(), app_config)
        with Session(clean_db) as db:
            h = svc.generate(db, namespace="n", system="s", prompt="p", kunci_cache={"x": 1})
            e = svc.embed_pertanyaan(db, "x")
        assert h.fallback and e.fallback and h.alasan == "LLMTidakDikonfigurasi"

    def test_pembatas_konkurensi_global(self, clean_db, app_config):
        fake = FakeLLM(jeda=0.12)
        svc = layanan(app_config, fake, maks_konkuren=2, timeout_detik=10)
        hasil = []

        def kerja(i: int):
            with Session(clean_db) as db:
                hasil.append(
                    svc.generate(db, namespace="n", system="s", prompt="p", kunci_cache={"i": i})
                )

        threads = [threading.Thread(target=kerja, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(hasil) == 6 and all(not h.fallback for h in hasil)
        assert fake.aktif_maks == 2  # tidak pernah lebih dari maks_konkuren

    def test_antrean_penuh_menjadi_fallback(self, clean_db, app_config):
        tahan, mulai = threading.Event(), threading.Event()

        def balas(prompt, system, skema):
            mulai.set()
            tahan.wait(5)
            return "lambat"

        svc = LLMService(
            FakeLLM(balasan=balas),
            app_config.model_copy(
                update={"llm": app_config.llm.model_copy(update={"maks_konkuren": 1})}
            ),
            tunggu_antrean_detik=0.05,
        )

        def pertama():
            with Session(clean_db) as db:
                svc.generate(db, namespace="n", system="s", prompt="p", kunci_cache={"i": 1})

        t = threading.Thread(target=pertama)
        t.start()
        assert mulai.wait(5)
        with Session(clean_db) as db:
            h = svc.generate(db, namespace="n", system="s", prompt="p", kunci_cache={"i": 2})
        tahan.set()
        t.join()
        assert h.fallback and h.alasan == "LLMAntreanPenuh"

    def test_log_tidak_memuat_isi_pertanyaan_atau_prompt(self, clean_db, app_config, caplog):
        svc = layanan(app_config, FakeLLM(gagal=LLMKuotaHabis("429"), gagal_embed=LLMTimeout("t")))
        with caplog.at_level(logging.DEBUG), Session(clean_db) as db:
            svc.embed_pertanyaan(db, "pertanyaan-rahasia-unik-123")
            svc.generate(
                db,
                namespace="n",
                system="s",
                prompt="prompt-rahasia-unik-456",
                kunci_cache={"x": 1},
            )
        assert "rahasia-unik" not in caplog.text
        assert "LLMKuotaHabis" in caplog.text or "LLMTimeout" in caplog.text


# ============================================================== wiring aplikasi


@pytest.mark.db
class TestWiring:
    def test_app_memakai_klien_injeksi_atau_null(self, clean_db, app_config):
        fake = FakeLLM()
        app = create_app(make_settings(), app_config, clean_db, llm_client=fake)
        assert app.state.llm._client is fake
        app2 = create_app(make_settings(gemini_api_key=""), app_config, clean_db)
        assert isinstance(app2.state.llm._client, NullClient)

    def test_satu_llmservice_per_proses(self, clean_db, app_config):
        app = create_app(make_settings(), app_config, clean_db, llm_client=FakeLLM())
        assert app.state.llm is app.state.llm

    def test_endpoint_llm_dibatasi_lebih_ketat_per_sesi(self, clean_db, app_config):
        rl = app_config.rate_limit.model_copy(
            update={"llm_per_sesi": Batas(maks=2, jendela_detik=60)}
        )
        cfg = app_config.model_copy(update={"rate_limit": rl})
        router = APIRouter()

        @router.get("/api/v1/_uji_llm")
        def uji(_=Depends(batasi_llm)):
            return {"ok": True}

        app = create_app(make_settings(), cfg, clean_db)
        app.include_router(router)
        with TestClient(app) as c:
            h = masuk(c)
            kode = [c.get("/api/v1/_uji_llm", headers=h).status_code for _ in range(3)]
            assert kode == [200, 200, 429]
            assert (
                c.get("/api/v1/session", headers=h).status_code == 200
            )  # endpoint non-LLM tidak ikut terblokir
            lain = masuk(c)
            assert c.get("/api/v1/_uji_llm", headers=lain).status_code == 200  # kuota per sesi

    def test_bersihkan_menghapus_cache_kedaluwarsa(self, clean_db, app_config):
        from app.main import bersihkan

        app = create_app(make_settings(), app_config, clean_db)
        with Session(clean_db) as db:
            cache.simpan(db, "lama", {"teks": "x"}, 10)
            db.execute(text("UPDATE llm_cache SET created_at = now() - interval '1 hour'"))
            cache.simpan(db, "baru", {"teks": "y"}, 3600)
            db.commit()
        bersihkan(app)
        with clean_db.connect() as conn:
            assert conn.execute(text("SELECT key_hash FROM llm_cache")).scalars().all() == ["baru"]


# ============================================================== query_logs + fallback teks


@pytest.mark.db
def test_query_log_menyaring_pii_dan_memotong(clean_db):
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.db import models as m

    sid = uuid.uuid4()
    with Session(clean_db) as db:
        db.add(
            m.Sesi(
                id=sid,
                token_hash="h" * 64,
                consent_at=datetime.now(UTC),
                consent_version="v1",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        tersimpan = catat(
            db, sid, "hubungi 081234567890 atau a@b.co " + "x" * 800, yakin=False, sumber_ids=[3, 5]
        )
    assert (
        "081234567890" not in tersimpan
        and "a@b.co" not in tersimpan
        and len(tersimpan) == PANJANG_MAKS
    )
    with Session(clean_db) as db:
        baris = db.query(m.QueryLog).one()
        assert baris.pertanyaan == tersimpan and baris.yakin is False and baris.sumber_ids == [3, 5]
        assert "[telepon]" in baris.pertanyaan and "[email]" in baris.pertanyaan


@pytest.mark.db
def test_penjelasan_fallback_dari_hasil_mesin_aturan(app_seed):
    t = [{"prodi_id": "ui-ilmu-komputer", "jalur": ["SNBT"]}]
    ok_ = analyze(app_seed, muat_persona(app_seed, "rani"), t).json()["hasil"][0]
    teks = penjelasan_dari_hasil(ok_)
    assert (
        "Ilmu Komputer" in teks
        and "syarat terpenuhi" in teks
        and ok_["penilaian"]["alasan"] in teks
    )

    gagal = analyze(app_seed, muat_persona(app_seed, "budi"), t).json()["hasil"][0]
    assert "belum memenuhi syarat" in penjelasan_dari_hasil(
        gagal
    ) and "lulusan lebih lama" in penjelasan_dari_hasil(gagal)

    kurang = analyze(app_seed, muat_persona(app_seed, "sinta"), t).json()["hasil"][0]
    assert "belum lengkap" in penjelasan_dari_hasil(kurang) and "NIK" in penjelasan_dari_hasil(
        kurang
    )


# ============================================================== struktur kode


def test_hanya_klien_yang_mengimpor_sdk_google():
    boleh = {"app/llm/client.py"}
    for berkas in (ROOT_DIR / "app").rglob("*.py"):
        rel = berkas.relative_to(ROOT_DIR).as_posix()
        for node in ast.walk(ast.parse(berkas.read_text(encoding="utf-8"))):
            nama = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            if any(n == "google" or n.startswith("google.") for n in nama):
                assert rel in boleh, f"{rel} meng-import SDK Google; hanya klien LLM yang boleh"
