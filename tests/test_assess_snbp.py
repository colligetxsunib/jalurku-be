"""Task 8: penilaian SNBP (indikatif + keyakinan) dan integrasinya di /analyze."""

from __future__ import annotations

import json
from itertools import product

import pytest
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, load_app_config
from app.domain.assess_common import Keketatan, buat_basis_pita
from app.domain.assess_snbp import nilai_snbp, status_alumni
from app.ingest.service import ingest
from tests.helpers import analyze, muat_persona, put_profil

TIERS = ("lemah", "sedang", "kuat")
PITAS = ("rendah", "sedang", "tinggi")
RAPOR_TIER = {"lemah": 50, "sedang": 70, "kuat": 90}
RASIO_PITA = {"rendah": 2.0, "sedang": 10.0, "tinggi": 40.0}


@pytest.fixture(scope="module")
def cfg_app():
    return load_app_config(ROOT_DIR / "config" / "app.yaml")


def hitung(cfg_app, profil, kek, *, prodi="ui-ilmu-komputer", ptn="ui", cfg=None):
    cfg = cfg or cfg_app.snbp
    return nilai_snbp(
        profil,
        prodi_id=prodi,
        ptn_id=ptn,
        keketatan=kek,
        basis_pita=buat_basis_pita(cfg.pita_keketatan, [], "semua"),
        cfg=cfg,
        teks_catatan=cfg_app.teks.catatan_sel,
        tahun_siklus=2026,
    )


def rapor_saja(tier: str, **lain) -> dict:
    return {"nilai_rapor": {"semester_1": {"a": RAPOR_TIER[tier]}}, **lain}


# ---------------------------- domain ----------------------------


@pytest.mark.parametrize("tier,pita", list(product(TIERS, PITAS)))
def test_sembilan_sel_matriks_snbp(cfg_app, tier, pita):
    kek = Keketatan(daya_tampung=10, peminat=int(RASIO_PITA[pita] * 10), tahun_peminat=2025)
    h = hitung(cfg_app, rapor_saja(tier), kek)
    sel = getattr(getattr(cfg_app.snbp.matriks, tier), pita)
    assert (h.tier.nilai, h.pita["nilai"]) == (tier, pita)
    assert h.kategori == sel.kategori
    assert h.sel["catatan"] == (cfg_app.teks.catatan_sel[sel.catatan] if sel.catatan else None)
    if sel.catatan:
        assert cfg_app.teks.catatan_sel[sel.catatan] in h.catatan
    assert h.metode == "matriks_keketatan" and h.indikatif is True and h.label == "indikatif"


def test_tabel_awal_snbp_sama_dengan_prd(cfg_app):
    m = cfg_app.snbp.matriks
    assert m.kuat.rendah.kategori == "safe" and m.kuat.sedang.kategori == "match"
    assert m.lemah.tinggi.kategori == "reach" and m.sedang.rendah.kategori == "match"
    assert (
        m.kuat.tinggi.catatan
        == m.sedang.sedang.catatan
        == m.lemah.rendah.catatan
        == "batas_match_reach"
    )


def test_tier_snbp_dari_rapor_bukan_proksi_utbk(cfg_app):
    h = hitung(cfg_app, rapor_saja("kuat"), Keketatan(10, 100))
    assert h.tier.sumber == "rapor" and h.tier.peringatan is None
    assert "UTBK" not in h.alasan and "dari rapor semester 1-5" in h.alasan


def test_snbp_mengabaikan_skor_tryout(cfg_app):
    a = hitung(cfg_app, rapor_saja("sedang", skor_tryout=100), Keketatan(10, 100))
    b = hitung(cfg_app, rapor_saja("sedang", skor_tryout=950), Keketatan(10, 100))
    assert a.kategori == b.kategori and a.tier.skor == b.tier.skor


# ---- keyakinan dari rekam jejak alumni ----


@pytest.mark.parametrize(
    "alumni_info,harapan",
    [
        (None, "rendah"),
        ({}, "rendah"),
        ({"ui-ilmu-komputer": "tidak_tahu"}, "rendah"),
        ({"ui": "tidak_tahu"}, "rendah"),
        ({"ui-ilmu-komputer": "ya"}, "sedang"),
        ({"ui-ilmu-komputer": "tidak"}, "sedang"),
        ({"ui": "ya"}, "sedang"),  # entri PTN berlaku bila entri prodi tidak ada
        ({"ui": "tidak_tahu", "ui-ilmu-komputer": "ya"}, "sedang"),  # entri prodi didahulukan
        ({"ugm": "ya"}, "rendah"),  # alumni PTN lain tidak relevan
    ],
)
def test_keyakinan_dari_alumni(cfg_app, alumni_info, harapan):
    h = hitung(cfg_app, rapor_saja("kuat", alumni_info=alumni_info), Keketatan(10, 20))
    assert h.keyakinan == harapan
    assert ("alumni" in h.faktor_tidak_diketahui) == (harapan == "rendah")
    if harapan == "rendah":
        assert any(
            "alumni sekolahmu tidak diketahui" in c for c in h.catatan
        )  # ditampilkan ke siswa


def test_alumni_tidak_mengubah_kategori_hanya_keyakinan(cfg_app):
    kek = Keketatan(10, 100)  # pita sedang
    hasil = {
        a: hitung(cfg_app, rapor_saja("kuat", alumni_info={"ui-ilmu-komputer": a}), kek)
        for a in ("ya", "tidak", "tidak_tahu")
    }
    assert len({h.kategori for h in hasil.values()}) == 1
    assert len({json.dumps(h.sel, sort_keys=True) for h in hasil.values()}) == 1
    assert [hasil[a].keyakinan for a in ("ya", "tidak", "tidak_tahu")] == [
        "sedang",
        "sedang",
        "rendah",
    ]


@pytest.mark.parametrize(
    "info,hasil",
    [
        (None, "kosong"),
        ({"x": "ya"}, "kosong"),
        ({"p": "ya"}, "ya"),
        ({"t": "tidak"}, "tidak"),
        ({"p": "mungkin"}, "kosong"),
        ({"p": "tidak_tahu", "t": "ya"}, "tidak_tahu"),
    ],
)
def test_status_alumni(info, hasil):
    assert status_alumni(info, "p", "t") == hasil


def test_akreditasi_hanya_konteks_tidak_mengubah_tier(cfg_app):
    kek = Keketatan(10, 100)
    a = hitung(cfg_app, rapor_saja("sedang", akreditasi_sekolah="A"), kek)
    c = hitung(cfg_app, rapor_saja("sedang", akreditasi_sekolah="C"), kek)
    assert (a.tier.nilai, a.tier.skor, a.kategori) == (c.tier.nilai, c.tier.skor, c.kategori)
    assert any("Akreditasi sekolah (A)" in x for x in a.catatan)


# ---- data kurang / belum ada acuan ----


def test_tanpa_data_keketatan_belum_ada_acuan_tier_tetap_tampil(cfg_app):
    h = hitung(cfg_app, rapor_saja("kuat"), None)
    assert h.kategori == "belum_ada_acuan" and h.keyakinan is None
    assert h.tier is not None and h.tier.nilai == "kuat"  # faktor siswa tetap terlihat
    assert "tidak menebak" in h.alasan and h.data_kurang == ()


def test_rapor_wajib_tanpa_rapor_data_kurang(cfg_app):
    h = hitung(cfg_app, {"peringkat_sekolah": 1, "jumlah_siswa_angkatan": 10}, Keketatan(10, 100))
    assert h.kategori == "data_kurang" and [d.field for d in h.data_kurang] == ["nilai_rapor"]


def test_faktor_opsional_tak_diketahui_dilaporkan_dan_bobot_dinormalisasi(cfg_app):
    h = hitung(cfg_app, {"nilai_rapor": {"semester_1": {"a": 90}}}, Keketatan(10, 20))
    assert set(h.tier.faktor_tidak_diketahui) == {"tren", "peringkat"}
    assert h.tier.skor == pytest.approx(0.90)  # hanya rapor yang diketahui -> bobot 100%
    assert {"tren", "peringkat", "alumni"} <= set(h.faktor_tidak_diketahui)


def test_ubah_config_snbp_mengubah_hasil_tanpa_ubah_kode(cfg_app):
    p, kek = rapor_saja("kuat"), Keketatan(10, 20)  # kuat x rendah
    assert hitung(cfg_app, p, kek).kategori == "safe"
    sel = cfg_app.snbp.matriks.kuat.rendah.model_copy(update={"kategori": "match"})
    matriks = cfg_app.snbp.matriks.model_copy(
        update={"kuat": cfg_app.snbp.matriks.kuat.model_copy(update={"rendah": sel})}
    )
    cfg = cfg_app.snbp.model_copy(update={"matriks": matriks})
    assert hitung(cfg_app, p, kek, cfg=cfg).kategori == "match"
    bobot = cfg_app.snbp.tier_siswa.bobot.model_copy(
        update={"rapor": 0.0, "tren": 0.0, "peringkat": 1.0}
    )
    cfg2 = cfg_app.snbp.model_copy(
        update={"tier_siswa": cfg_app.snbp.tier_siswa.model_copy(update={"bobot": bobot})}
    )
    p2 = {**p, "peringkat_sekolah": 100, "jumlah_siswa_angkatan": 100}  # peringkat terakhir
    assert hitung(cfg_app, p2, kek, cfg=cfg2).tier.nilai == "lemah"


def test_tidak_ada_persentase_peluang(cfg_app):
    d = hitung(cfg_app, rapor_saja("kuat"), Keketatan(10, 100)).ke_dict()
    teks = json.dumps(d).lower().replace("bukan peluang", "")
    assert "persentase" not in teks and "peluang" not in teks and "%" not in teks


# ---------------------------- API: /analyze jalur SNBP ----------------------------

IK, AKUN = "ui-ilmu-komputer", "ui-akuntansi"


def isi_keketatan_snbp(engine):
    """Tambah data SNBP (rasio 10 dan 40) untuk dua prodi UI. Data SNBT dipertahankan."""
    dasar = {
        "ptn_id": "ui",
        "rumpun_": "",
        "jenjang": "Sarjana",
        "program": "akademik",
        "jalur_dibuka": "SNBP|SNBT",
        "sumber_url": "https://contoh.id/data",
    }
    baris = [
        {
            **dasar,
            "prodi_id": IK,
            "nama": "Ilmu Komputer",
            "rumpun": "Teknologi Informasi",
            "daya_tampung_snbp": "30",
            "peminat_snbp": "300",
            "daya_tampung_snbt": "75",
            "peminat_snbt": "2132",
        },
        {
            **dasar,
            "prodi_id": AKUN,
            "nama": "Akuntansi",
            "rumpun": "Ekonomi dan Bisnis",
            "daya_tampung_snbp": "20",
            "peminat_snbp": "800",
            "daya_tampung_snbt": "90",
            "peminat_snbt": "2720",
        },
    ]
    for b in baris:
        b.pop("rumpun_")
    with Session(engine) as db:
        hasil = ingest(db, "katalog", baris)
        assert hasil.ok, hasil.error


@pytest.mark.db
class TestAnalyzeSNBP:
    def _rani(self, app_seed):
        h = muat_persona(app_seed, "rani")
        put_profil(app_seed, h, konfirmasi_syarat_prodi={IK: True, AKUN: True})
        return h

    def test_tanpa_data_snbp_di_seed_belum_ada_acuan_dengan_tier(self, app_seed):
        h = muat_persona(app_seed, "dimas")
        hasil = analyze(
            app_seed, h, [{"prodi_id": "ui-teknik-industri", "jalur": ["SNBP"]}]
        ).json()["hasil"][0]
        assert hasil["gate"]["status"] == "lolos"
        p = hasil["penilaian"]
        assert p["kategori"] == "belum_ada_acuan" and p["keyakinan"] is None
        assert p["tier"]["sumber"] == "rapor" and p["tier"]["nilai"] in TIERS
        assert p["pita"] is None
        assert hasil["data_kurang"] == []  # tidak meminta data siswa yang tak berguna

    def test_snbp_dengan_data_keketatan(self, app_seed, clean_db):
        isi_keketatan_snbp(clean_db)
        h = self._rani(app_seed)
        r = analyze(
            app_seed,
            h,
            [{"prodi_id": IK, "jalur": ["SNBP"]}, {"prodi_id": AKUN, "jalur": ["SNBP"]}],
        )
        ik, akun = r.json()["hasil"]
        p = ik["penilaian"]
        assert (
            p["metode"] == "matriks_keketatan"
            and p["label"] == "indikatif"
            and p["indikatif"] is True
        )
        assert p["tier"]["nilai"] == "kuat" and p["tier"]["sumber"] == "rapor"
        assert p["pita"]["nilai"] == "sedang" and p["pita"]["rasio"] == 10.0
        assert p["pita"]["basis"]["metode"] == "tetap" and "catatan_relatif" not in p["pita"]
        assert p["kategori"] == "match" and p["sel"] == {
            "tier": "kuat",
            "pita": "sedang",
            "kategori": "match",
            "catatan": None,
        }
        # kuat x tinggi = reach dengan catatan 'batas match/reach'
        assert (
            akun["penilaian"]["pita"]["nilai"] == "tinggi"
            and akun["penilaian"]["kategori"] == "reach"
        )
        assert "batas antara match dan reach" in akun["penilaian"]["sel"]["catatan"]
        assert {s["jenis"] for s in ik["sumber_detail"]} == {"rules_gate", "keketatan"}

    def test_keyakinan_rendah_tanpa_alumni_lalu_sedang_bila_diisi(self, app_seed, clean_db):
        isi_keketatan_snbp(clean_db)
        h = self._rani(app_seed)
        t = [{"prodi_id": IK, "jalur": ["SNBP"]}]
        awal = analyze(app_seed, h, t).json()["hasil"][0]["penilaian"]
        assert awal["keyakinan"] == "rendah" and "alumni" in awal["faktor_tidak_diketahui"]
        put_profil(app_seed, h, alumni_info={IK: "ya"})
        akhir = analyze(app_seed, h, t).json()["hasil"][0]["penilaian"]
        assert akhir["keyakinan"] == "sedang" and "alumni" not in akhir["faktor_tidak_diketahui"]
        assert akhir["kategori"] == awal["kategori"]  # alumni tidak mengubah kategori

    def test_snbp_dan_snbt_satu_prodi_memakai_data_masing_masing(self, app_seed, clean_db):
        isi_keketatan_snbp(clean_db)
        h = self._rani(app_seed)
        r = analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBP", "SNBT"]}]).json()["hasil"]
        snbp, snbt = r
        assert snbp["jalur"] == "SNBP" and snbt["jalur"] == "SNBT"
        assert snbp["penilaian"]["pita"]["daya_tampung"] == 30
        assert snbt["penilaian"]["pita"]["daya_tampung"] == 75
        assert snbt["penilaian"]["tier"]["sumber"] == "proksi_rapor"  # SNBT proksi, SNBP rapor
        assert snbt["penilaian"]["keyakinan"] == "rendah"
        assert snbp["catatan"] == []  # jalur_dibuka kini memuat SNBP

    def test_override_what_if_snbp_mengubah_tier_tanpa_menyimpan(self, app_seed, clean_db):
        isi_keketatan_snbp(clean_db)
        h = self._rani(app_seed)
        t = [{"prodi_id": IK, "jalur": ["SNBP"]}]
        jelek = {
            # override digabung per mapel, jadi semua mapel Rani ditimpa
            "nilai_rapor": {
                f"semester_{i}": dict.fromkeys(
                    (
                        "matematika",
                        "fisika",
                        "kimia",
                        "biologi",
                        "bahasa_indonesia",
                        "bahasa_inggris",
                    ),
                    45,
                )
                for i in range(1, 6)
            },
            "peringkat_sekolah": 130,  # 43,3% masih di dalam kuota 45% (A + e-Rapor): gate lolos
        }
        p = analyze(app_seed, h, t, jelek).json()["hasil"][0]["penilaian"]
        assert p["tier"]["nilai"] == "lemah" and p["kategori"] == "reach"
        asli = analyze(app_seed, h, t).json()["hasil"][0]["penilaian"]
        assert asli["tier"]["nilai"] == "kuat"  # profil tersimpan tidak berubah

    def test_gate_snbp_gagal_tidak_menilai(self, app_seed, clean_db):
        isi_keketatan_snbp(clean_db)
        h = muat_persona(app_seed, "budi")
        hasil = analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBP"]}]).json()["hasil"][0]
        assert hasil["gate"]["status"] == "tidak_memenuhi_syarat" and hasil["penilaian"] is None

    def test_sampel_pembanding_kurang_pada_metode_persentil(self, app_seed, clean_db, app_config):
        """SNBP berpersentil dengan data < min_sampel -> belum_ada_acuan, bukan tebakan."""
        from fastapi.testclient import TestClient

        from app.main import create_app
        from tests.conftest import make_settings

        isi_keketatan_snbp(clean_db)
        pita = app_config.snbp.pita_keketatan.model_copy(update={"metode": "persentil"})
        cfg = app_config.model_copy(
            update={"snbp": app_config.snbp.model_copy(update={"pita_keketatan": pita})}
        )
        with TestClient(create_app(make_settings(), cfg, clean_db)) as c:
            h = self._rani(c)
            p = analyze(c, h, [{"prodi_id": IK, "jalur": ["SNBP"]}]).json()["hasil"][0]["penilaian"]
        assert p["kategori"] == "belum_ada_acuan" and "terlalu sedikit" in p["alasan"]
