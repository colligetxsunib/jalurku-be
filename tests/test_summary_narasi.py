"""Task 16: narasi LLM opsional di POST /summary. Angka dan status tetap dari mesin aturan."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import AppConfig, Batas
from app.domain.ringkasan import KALIMAT_PENUTUP, fakta_narasi, narasi_template
from app.ingest.service import ingest_direktori
from app.llm.errors import LLMGagal, LLMKuotaHabis
from app.llm.guard import kategori_tidak_sesuai, narasi_aman
from app.llm.prompts import SISTEM_NARASI
from app.llm.service import LLMService
from app.main import create_app
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.helpers import SEED_DIR, analyze, muat_persona

IK, AKUN = "ui-ilmu-komputer", "ui-akuntansi"


# ------------------------------------------------------------------ pembantu


def fakta_dari_prompt(prompt: str) -> dict:
    isi = prompt.split("<fakta>\n", 1)[1].split("\n</fakta>", 1)[0]
    return json.loads(isi)


def narasi_sesuai_fakta(prompt, system, skema) -> str:
    """Balasan LLM yang patuh: hanya memakai nama, kategori, dan angka dari <fakta>."""
    f = fakta_dari_prompt(prompt)
    bagian = f["jalur"][0]
    p1, p2 = bagian["pilihan"][0], bagian["pilihan"][1]
    return (
        f"Strategi {bagian['jalur']} kamu berisi {bagian['jumlah_pilihan']} pilihan. "
        f"{p1['prodi']} berkategori {p1['kategori']}. "
        f"{p2['prodi']} berkategori {p2['kategori']}. "
        "Kategori ini indikatif, bukan jaminan."
    )


def balasan_kategori_salah(prompt, system, skema) -> str:
    """Menyebut kategori yang bukan milik prodi tersebut."""
    f = fakta_dari_prompt(prompt)
    p1 = f["jalur"][0]["pilihan"][0]
    salah = next(k for k in ("reach", "match", "safe") if k != p1["kategori"])
    return f"{p1['prodi']} berkategori {salah}."


def simpan(c, h, jalur, pilihan) -> str:
    body = {"jalur": jalur, "pilihan": [{"prodi_id": p} for p in pilihan], "simpan": True}
    r = c.post("/api/v1/strategy", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["strategy_id"]


def ringkas(c, h, **body):
    r = c.post("/api/v1/summary", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def bangun(clean_db: Engine, app_config: AppConfig):
    """Pabrik klien ter-seed dengan FakeLLM tertentu (dan config opsional)."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    with ExitStack() as tumpukan:

        def buat(llm: FakeLLM, config: AppConfig | None = None) -> TestClient:
            app = create_app(make_settings(), config or app_config, clean_db, llm_client=llm)
            return tumpukan.enter_context(TestClient(app, raise_server_exceptions=False))

        yield buat


def siapkan(c, pilihan=(IK, AKUN)):
    h = muat_persona(c, "rani")
    sid = simpan(c, h, "SNBT", list(pilihan))
    return h, sid


# ------------------------------------------------------------------ narasi LLM dipakai


@pytest.mark.db
def test_narasi_llm_dipakai_bila_lolos_pagar(bangun):
    llm = FakeLLM(balasan=narasi_sesuai_fakta)
    c = bangun(llm)
    h, _ = siapkan(c)
    d = ringkas(c, h)

    assert d["narasi_fallback"] is False
    assert d["narasi"].startswith("Strategi SNBT kamu berisi 2 pilihan.")
    assert d["narasi"].endswith(KALIMAT_PENUTUP)  # label indikatif selalu dari kode, bukan LLM
    assert llm.panggilan_generate == 1
    assert llm.system_terakhir == SISTEM_NARASI


@pytest.mark.db
def test_data_terstruktur_tidak_berubah_oleh_narasi_llm(bangun):
    c = bangun(FakeLLM(balasan=narasi_sesuai_fakta))
    h, _ = siapkan(c)
    d = ringkas(c, h)
    a = analyze(c, h, [{"prodi_id": p, "jalur": ["SNBT"]} for p in (IK, AKUN)]).json()["hasil"]
    for pil, hasil in zip(d["pilihan_akhir"], a, strict=True):
        assert pil["kategori"] == hasil["penilaian"]["kategori"]
        assert pil["alasan"] == hasil["penilaian"]["alasan"]
        assert pil["status_gate"] == hasil["gate"]["status"]


@pytest.mark.db
def test_ringkasan_sama_dengan_dan_tanpa_llm_selain_narasi(bangun):
    """LLM hanya menyentuh `narasi` dan `narasi_fallback`; semua field lain identik."""
    # Urutan penting: kedua klien memakai DB yang sama, dan narasi sukses masuk cache LLM.
    tanpa = bangun(FakeLLM(gagal=LLMGagal("mati")))
    h2, _ = siapkan(tanpa)
    d_tmpl = ringkas(tanpa, h2)
    pakai = bangun(FakeLLM(balasan=narasi_sesuai_fakta))
    h1, _ = siapkan(pakai)
    d_llm = ringkas(pakai, h1)

    def inti(d):
        buang = {"narasi", "narasi_fallback", "dihasilkan_pada", "strategi"}
        return {k: v for k, v in d.items() if k not in buang}

    assert inti(d_llm) == inti(d_tmpl)
    assert d_llm["narasi_fallback"] is False and d_tmpl["narasi_fallback"] is True


@pytest.mark.db
def test_prompt_hanya_memuat_fakta_mesin_aturan_tanpa_data_profil(bangun):
    llm = FakeLLM(balasan=narasi_sesuai_fakta)
    c = bangun(llm)
    h, _ = siapkan(c)
    ringkas(c, h)
    prompt = llm.prompt_terakhir
    assert "<fakta>" in prompt and "Ilmu Komputer" in prompt and "SNBT" in prompt
    token = h["Authorization"].split()[1]
    for terlarang in (
        token,
        "nilai_rapor",
        "peringkat_sekolah",
        "Jawa Barat",
        "skor_tryout",
        "konfirmasi_syarat_prodi",
        "alumni",
    ):
        assert terlarang not in prompt, terlarang
    assert set(fakta_dari_prompt(prompt)) == {"tahun_siklus", "memuat_snbp_dan_snbt", "jalur"}


@pytest.mark.db
def test_narasi_di_cache_dan_tidak_memanggil_llm_lagi(bangun):
    llm = FakeLLM(balasan=narasi_sesuai_fakta)
    c = bangun(llm)
    h, _ = siapkan(c)
    pertama = ringkas(c, h)
    kedua = ringkas(c, h)
    assert llm.panggilan_generate == 1
    assert kedua["narasi"] == pertama["narasi"] and kedua["narasi_fallback"] is False


# ------------------------------------------------------------------ fallback ke template


@pytest.mark.db
@pytest.mark.parametrize(
    "balasan",
    [
        pytest.param(lambda p, s, k: "Peluang kamu diterima sekitar 80%.", id="persentase"),
        pytest.param(lambda p, s, k: "Ada 99 pilihan yang cocok untukmu.", id="angka_asing"),
        pytest.param(balasan_kategori_salah, id="kategori_salah"),
        pytest.param(lambda p, s, k: "<b>Strategi</b> kamu bagus.", id="markup"),
        pytest.param(lambda p, s, k: "   ", id="kosong"),
        pytest.param(lambda p, s, k: "Strategi bagus. " * 100, id="terlalu_panjang"),
    ],
)
def test_narasi_ditolak_pagar_memakai_template(bangun, balasan):
    c = bangun(FakeLLM(balasan=balasan))
    h, _ = siapkan(c)
    d = ringkas(c, h)
    assert d["narasi_fallback"] is True
    assert d["narasi"].startswith("Pilihan SNBT:") and d["narasi"].endswith(KALIMAT_PENUTUP)
    assert "80%" not in d["narasi"] and "99" not in d["narasi"]
    assert len(d["pilihan_akhir"]) == 2  # ringkasan tetap lengkap


@pytest.mark.db
@pytest.mark.parametrize("galat", [LLMGagal("x"), LLMKuotaHabis("x"), RuntimeError("tak terduga")])
def test_llm_gagal_ringkasan_tetap_lengkap(bangun, galat):
    c = bangun(FakeLLM(gagal=galat))
    h, _ = siapkan(c)
    d = ringkas(c, h)
    assert d["narasi_fallback"] is True and d["narasi"].startswith("Pilihan SNBT:")
    assert [p["prodi_id"] for p in d["pilihan_akhir"]] == [IK, AKUN]


@pytest.mark.db
def test_tanpa_kunci_api_llm_tidak_dipanggil(clean_db, app_config):
    """Tanpa GEMINI_API_KEY (NullClient): template dipakai tanpa upaya panggilan."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    app = create_app(make_settings(gemini_api_key=""), app_config, clean_db)
    assert app.state.llm.dikonfigurasi is False
    with TestClient(app, raise_server_exceptions=False) as c:
        h, _ = siapkan(c)
        assert ringkas(c, h)["narasi_fallback"] is True


@pytest.mark.db
def test_batas_llm_per_sesi_menurunkan_ke_template_bukan_429(bangun, app_config):
    rl = app_config.rate_limit.model_copy(update={"llm_per_sesi": Batas(maks=1, jendela_detik=60)})
    llm = FakeLLM(balasan=narasi_sesuai_fakta)
    c = bangun(llm, app_config.model_copy(update={"rate_limit": rl}))
    h = muat_persona(c, "rani")
    id1 = simpan(c, h, "SNBT", [IK, AKUN])
    id2 = simpan(c, h, "SNBT", [AKUN, IK])  # fakta berbeda -> cache meleset

    pertama = ringkas(c, h, strategy_id=id1)
    kedua = ringkas(c, h, strategy_id=id2)  # jatah LLM sesi habis

    assert pertama["narasi_fallback"] is False
    assert kedua["narasi_fallback"] is True and kedua["narasi"].startswith("Pilihan SNBT:")
    assert llm.panggilan_generate == 1
    # Cache hit tidak memakai jatah: id1 diulang tetap berhasil.
    assert ringkas(c, h, strategy_id=id1)["narasi_fallback"] is False


@pytest.mark.db
def test_ringkasan_dengan_narasi_llm_tidak_bocor_antar_sesi(bangun):
    """Cache narasi hanya berisi fakta mesin aturan, tapi strategi sesi lain tetap tidak terjangkau."""
    c = bangun(FakeLLM(balasan=narasi_sesuai_fakta))
    _, sid = siapkan(c)
    h2 = muat_persona(c, "dimas")
    r = c.post("/api/v1/summary", json={"strategy_id": sid}, headers=h2)
    assert r.status_code == 404


# ------------------------------------------------------------------ pagar & fakta (unit)

PILIHAN = [
    {"prodi": "Ilmu Komputer", "kategori": "reach"},
    {"prodi": "Akuntansi", "kategori": "match"},
]


def test_kategori_tidak_sesuai():
    assert kategori_tidak_sesuai("Ilmu Komputer berkategori reach.", PILIHAN) == []
    assert kategori_tidak_sesuai("ilmu komputer BERKATEGORI REACH.", PILIHAN) == []
    salah = kategori_tidak_sesuai("Ilmu Komputer berkategori safe. Akuntansi match.", PILIHAN)
    assert salah == ["Ilmu Komputer berkategori safe."]
    # Kalimat tanpa nama prodi tidak bisa dipetakan: tidak diperiksa.
    assert kategori_tidak_sesuai("Ada satu reach dan satu match.", PILIHAN) == []
    # Prodi yang tidak dinilai tidak boleh diberi kategori apa pun.
    assert kategori_tidak_sesuai(
        "Hukum berkategori safe.", [{"prodi": "Hukum", "kategori": "belum_dinilai"}]
    ) == ["Hukum berkategori safe."]


def test_kategori_nama_prodi_kembar_dilonggarkan():
    kembar = [
        {"prodi": "Akuntansi", "kategori": "reach"},
        {"prodi": "Akuntansi", "kategori": "safe"},
    ]
    assert kategori_tidak_sesuai("Akuntansi bisa reach atau safe.", kembar) == []
    assert kategori_tidak_sesuai("Akuntansi berkategori match.", kembar) != []


def test_narasi_aman_gabungan():
    fakta = {
        "tahun_siklus": 2026,
        "jalur": [{"jalur": "SNBT", "jumlah_pilihan": 2, "pilihan": PILIHAN}],
    }
    assert narasi_aman("Ilmu Komputer berkategori reach untuk 2 pilihan SNBT 2026.", fakta) == (
        True,
        None,
    )
    ok, alasan = narasi_aman("Ilmu Komputer berkategori safe.", fakta)
    assert not ok and "kategori" in alasan
    assert not narasi_aman("Peluang 80%.", fakta)[0]
    assert not narasi_aman("x" * 1300, fakta)[0]
    assert not narasi_aman("", fakta)[0]


def _bagian():
    return [
        {
            "jalur": "SNBT",
            "pelanggaran": 1,
            "peringatan": 2,
            "batas_pilihan": 4,
            "komposisi": {
                "jumlah": 2,
                "reach": 1,
                "match": 0,
                "safe": 0,
                "tidak_dinilai": 1,
                "akademik": 2,
                "vokasi": 0,
                "d3": 0,
            },
            "pilihan": [
                {
                    "nama": "Ilmu Komputer",
                    "ptn": "Universitas Indonesia",
                    "kategori": "reach",
                    "status": "lolos",
                    "keyakinan": "rendah",
                },
                {
                    "nama": "Hukum",
                    "ptn": "Universitas Indonesia",
                    "kategori": None,
                    "status": "data_kurang",
                    "keyakinan": None,
                },
            ],
        }
    ]


def test_fakta_narasi_hanya_hasil_mesin_aturan():
    f = fakta_narasi(_bagian(), 2026)
    assert f["tahun_siklus"] == 2026 and f["memuat_snbp_dan_snbt"] is False
    j = f["jalur"][0]
    assert j["jumlah_pilihan"] == 2 and j["batas_pilihan"] == 4
    assert j["komposisi"] == {"reach": 1, "match": 0, "safe": 0, "tidak_dinilai": 1}
    assert j["aturan_dilanggar"] == 1 and j["peringatan"] == 2
    assert j["pilihan"][1]["kategori"] == "belum_dinilai"
    assert j["pilihan"][0] == {
        "prodi": "Ilmu Komputer",
        "ptn": "Universitas Indonesia",
        "kategori": "reach",
        "status_syarat": "lolos",
        "keyakinan": "rendah",
    }


def test_template_dan_fakta_dari_bagian_yang_sama_tetap_konsisten():
    bagian = _bagian()
    t = narasi_template(bagian)
    assert t.startswith("Pilihan SNBT: Ilmu Komputer (Universitas Indonesia), kategori reach;")
    assert "Ada 1 aturan SNBT" in t and t.endswith(KALIMAT_PENUTUP)


# ------------------------------------------------------------------ LLMService.izin


@pytest.mark.db
def test_izin_dipanggil_hanya_saat_cache_meleset(clean_db, app_config):
    llm = FakeLLM(teks="Halo")
    layanan = LLMService(llm, app_config)
    panggilan: list[int] = []
    cache_key: dict[str, Callable] = {"k": 1}  # type: ignore[assignment]

    def izin_ya() -> bool:
        panggilan.append(1)
        return True

    with Session(clean_db) as db:
        g1 = layanan.generate(
            db, namespace="uji", system="s", prompt="p", kunci_cache=cache_key, izin=izin_ya
        )
        g2 = layanan.generate(
            db, namespace="uji", system="s", prompt="p", kunci_cache=cache_key, izin=izin_ya
        )
        db.commit()
    assert (g1.teks, g1.fallback, g1.dari_cache) == ("Halo", False, False)
    assert (g2.teks, g2.fallback, g2.dari_cache) == ("Halo", False, True)
    assert panggilan == [1] and llm.panggilan_generate == 1


@pytest.mark.db
def test_izin_ditolak_tidak_memanggil_llm(clean_db, app_config):
    llm = FakeLLM(teks="Halo")
    layanan = LLMService(llm, app_config)
    with Session(clean_db) as db:
        g = layanan.generate(
            db, namespace="uji2", system="s", prompt="p", kunci_cache={"k": 2}, izin=lambda: False
        )
    assert g.teks is None and g.fallback is True and g.alasan == "BatasSesi"
    assert llm.panggilan_generate == 0
