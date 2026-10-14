"""Task 7: penilaian reach/match/safe (domain murni): faktor, tier, pita, matriks 3x3, SNBT."""

from __future__ import annotations

import json
import statistics
from itertools import product
from pathlib import Path

import pytest

from app.core.config import ROOT_DIR, ConfigError, load_app_config
from app.domain.assess_common import (
    BasisPita,
    Keketatan,
    buat_basis_pita,
    hitung_faktor,
    persentil,
    pita_dari_rasio,
    skor_siswa,
    tentukan_tier,
    tier_dari_skor,
)
from app.domain.assess_snbt import AcuanSkor, nilai_dengan_acuan, nilai_snbt

TIERS = ("lemah", "sedang", "kuat")
PITAS = ("rendah", "sedang", "tinggi")


@pytest.fixture(scope="module")
def cfg_app():
    return load_app_config(ROOT_DIR / "config" / "app.yaml")


@pytest.fixture()
def cfg(cfg_app):
    """Konfigurasi SNBT dengan pita TETAP (5 dan 15) supaya rasio uji mudah dihitung."""
    snbt = cfg_app.snbt
    pita = snbt.pita_keketatan.model_copy(update={"metode": "tetap"})
    return snbt.model_copy(update={"pita_keketatan": pita})


def rapor_rata(nilai: float, semester: int = 5) -> dict:
    return {f"semester_{i}": {"matematika": nilai, "bahasa": nilai} for i in range(1, semester + 1)}


def profil(rapor: float = 85, peringkat=(10, 100), **lain) -> dict:
    p = {
        "nilai_rapor": rapor_rata(rapor),
        "peringkat_sekolah": peringkat[0] if peringkat else None,
        "jumlah_siswa_angkatan": peringkat[1] if peringkat else None,
    }
    p.update(lain)
    return p


BASIS_TETAP = BasisPita("tetap", True, (5.0, 15.0))


def nilai(p, kek, cfg, cfg_app, basis=None, acuan=None):
    """Basis pita dibangun dari config (seperti service), kecuali diberikan eksplisit."""
    if basis is None:
        basis = buat_basis_pita(cfg.pita_keketatan, [], "semua")
    return nilai_snbt(
        p,
        acuan=acuan,
        keketatan=kek,
        basis_pita=basis,
        cfg=cfg,
        teks_catatan=cfg_app.teks.catatan_sel,
        tahun_siklus=2026,
    )


# ---------------------------- faktor siswa ----------------------------


def test_faktor_rapor_rata_sem1_sampai_5_tanpa_semester_6():
    p = {"nilai_rapor": {**rapor_rata(80), "semester_6": {"matematika": 0}}}
    f = hitung_faktor(p, 20)
    assert f.nilai["rapor"] == pytest.approx(0.80)  # semester_6 tidak dihitung


def test_faktor_tren_naik_turun_datar():
    naik = {"nilai_rapor": {f"semester_{i}": {"a": 70 + 5 * i} for i in range(1, 6)}}
    assert hitung_faktor(naik, 20).nilai["tren"] > 0.5
    turun = {"nilai_rapor": {f"semester_{i}": {"a": 90 - 5 * i} for i in range(1, 6)}}
    assert hitung_faktor(turun, 20).nilai["tren"] < 0.5
    assert hitung_faktor({"nilai_rapor": rapor_rata(80)}, 20).nilai["tren"] == pytest.approx(0.5)


def test_faktor_tren_dijepit_0_sampai_1():
    drastis = {
        "nilai_rapor": {
            "semester_1": {"a": 10},
            "semester_2": {"a": 10},
            "semester_3": {"a": 100},
            "semester_4": {"a": 100},
        }
    }
    assert hitung_faktor(drastis, 20).nilai["tren"] == 1.0


def test_faktor_tren_butuh_dua_semester():
    f = hitung_faktor({"nilai_rapor": {"semester_1": {"a": 80}}}, 20)
    assert "tren" not in f.nilai and "tren" in f.tidak_diketahui


def test_faktor_peringkat_1_adalah_satu_dan_terakhir_hampir_nol():
    assert hitung_faktor(profil(peringkat=(1, 100)), 20).nilai["peringkat"] == 1.0
    assert hitung_faktor(profil(peringkat=(100, 100)), 20).nilai["peringkat"] == pytest.approx(0.01)
    f = hitung_faktor(profil(peringkat=None), 20)
    assert "peringkat" in f.tidak_diketahui and "peringkat" not in f.nilai


def test_faktor_tanpa_rapor():
    f = hitung_faktor({}, 20)
    assert "rapor" not in f.nilai
    assert skor_siswa(f, None) is None  # type: ignore[arg-type]


def test_skor_siswa_bobot_dinormalisasi_ulang_atas_faktor_yang_ada(cfg_app):
    bobot = cfg_app.snbt.tier_siswa.bobot  # rapor .5, tren .2, peringkat .3
    hanya_rapor = hitung_faktor({"nilai_rapor": {"semester_1": {"a": 80}}}, 20)
    assert skor_siswa(hanya_rapor, bobot) == pytest.approx(0.80)  # bukan 0.8 * 0.5
    penuh = hitung_faktor(profil(rapor=80, peringkat=(1, 100)), 20)
    harapan = (0.5 * 0.80 + 0.2 * 0.5 + 0.3 * 1.0) / 1.0
    assert skor_siswa(penuh, bobot) == pytest.approx(harapan)


@pytest.mark.parametrize(
    "skor,tier",
    [
        (0.0, "lemah"),
        (0.5999, "lemah"),
        (0.60, "sedang"),
        (0.7999, "sedang"),
        (0.80, "kuat"),
        (1.0, "kuat"),
    ],
)
def test_batas_tier_inklusif_ke_kelompok_atas(skor, tier):
    assert tier_dari_skor(skor, 0.60, 0.80) == tier


# ---------------------------- pita keketatan ----------------------------


def test_persentil_sama_dengan_statistics_inclusive():
    data = sorted(
        [
            17.4,
            19.2,
            20.4,
            21.0,
            21.5,
            23.7,
            25.9,
            27.7,
            28.4,
            30.2,
            30.9,
            34.3,
            35.4,
            37.0,
            54.8,
            71.2,
        ]
    )
    q = statistics.quantiles(data, n=100, method="inclusive")
    assert persentil(data, 33) == pytest.approx(q[32])
    assert persentil(data, 67) == pytest.approx(q[66])
    assert persentil([5.0], 50) == 5.0
    assert persentil([1, 2, 3, 4, 5], 0) == 1 and persentil([1, 2, 3, 4, 5], 100) == 5
    with pytest.raises(ValueError):
        persentil([], 50)


def test_basis_pita_tetap_dan_persentil(cfg_app):
    pita = cfg_app.snbt.pita_keketatan
    tetap = buat_basis_pita(pita.model_copy(update={"metode": "tetap"}), [])
    assert tetap.cukup and tetap.batas == (5, 15) and tetap.n_prodi is None

    data = [float(x) for x in range(10, 20)]  # 10 prodi
    persen = buat_basis_pita(pita, data, "semua")
    assert persen.cukup and persen.n_prodi == 10 and persen.persentil == (33, 67)
    assert persen.batas == (pytest.approx(persentil(data, 33)), pytest.approx(persentil(data, 67)))

    kurang = buat_basis_pita(pita, data[:3], "semua")  # min_sampel 8
    assert not kurang.cukup and kurang.batas is None and kurang.n_prodi == 3


def test_pita_dari_rasio_batas_inklusif_ke_pita_atas():
    b = BasisPita("tetap", True, (5.0, 15.0))
    assert [pita_dari_rasio(x, b) for x in (0, 4.99, 5, 14.99, 15, 99)] == [
        "rendah",
        "rendah",
        "sedang",
        "sedang",
        "tinggi",
        "tinggi",
    ]


def test_keketatan_rasio():
    assert Keketatan(75, 2132).rasio == pytest.approx(28.4267, abs=1e-3)
    assert Keketatan(0, 100).rasio is None
    assert Keketatan(None, 100).rasio is None
    assert Keketatan(50, None).rasio is None


# ---------------------------- matriks: ke-9 sel ----------------------------

# profil yang menghasilkan tier tertentu (rapor saja diketahui, bobot dinormalisasi ulang)
RAPOR_TIER = {"lemah": 50, "sedang": 70, "kuat": 90}
RASIO_PITA = {"rendah": 2.0, "sedang": 10.0, "tinggi": 40.0}


@pytest.mark.parametrize("tier,pita", list(product(TIERS, PITAS)))
def test_sembilan_sel_matriks_sesuai_config(cfg, cfg_app, tier, pita):
    p = {"nilai_rapor": {"semester_1": {"a": RAPOR_TIER[tier]}}}
    kek = Keketatan(daya_tampung=10, peminat=int(RASIO_PITA[pita] * 10), tahun_peminat=2025)
    h = nilai(p, kek, cfg, cfg_app)
    sel = getattr(getattr(cfg.matriks, tier), pita)
    assert h.tier.nilai == tier and h.pita["nilai"] == pita
    assert h.kategori == sel.kategori
    assert h.sel == {
        "tier": tier,
        "pita": pita,
        "kategori": sel.kategori,
        "catatan": cfg_app.teks.catatan_sel.get(sel.catatan) if sel.catatan else None,
    }
    if sel.catatan:
        assert cfg_app.teks.catatan_sel[sel.catatan] in h.catatan


def test_tabel_awal_sesuai_prd_8_2(cfg_app):
    """Nilai awal dari PRD (placeholder). Bila tim data mengubah config, perbarui tes ini sengaja."""
    harapan = {
        ("kuat", "rendah"): "safe",
        ("kuat", "sedang"): "match",
        ("kuat", "tinggi"): "reach",
        ("sedang", "rendah"): "match",
        ("sedang", "sedang"): "reach",
        ("sedang", "tinggi"): "reach",
        ("lemah", "rendah"): "reach",
        ("lemah", "sedang"): "reach",
        ("lemah", "tinggi"): "reach",
    }
    for (t, p), kat in harapan.items():
        assert getattr(getattr(cfg_app.snbt.matriks, t), p).kategori == kat
    sel_batas = {(t, p) for t, p in harapan if getattr(getattr(cfg_app.snbt.matriks, t), p).catatan}
    assert sel_batas == {("kuat", "tinggi"), ("sedang", "sedang"), ("lemah", "rendah")}


def test_ubah_config_mengubah_hasil_tanpa_ubah_kode(cfg, cfg_app):
    p = {"nilai_rapor": {"semester_1": {"a": 90}}}  # kuat
    kek = Keketatan(10, 20)  # rasio 2 -> rendah
    awal = nilai(p, kek, cfg, cfg_app)
    assert awal.kategori == "safe"

    sel_baru = cfg.matriks.kuat.rendah.model_copy(update={"kategori": "reach"})
    matriks = cfg.matriks.model_copy(
        update={"kuat": cfg.matriks.kuat.model_copy(update={"rendah": sel_baru})}
    )
    assert nilai(p, kek, cfg.model_copy(update={"matriks": matriks}), cfg_app).kategori == "reach"

    batas = cfg.tier_siswa.batas.model_copy(update={"sedang_kuat": 0.95})
    cfg_batas = cfg.model_copy(
        update={"tier_siswa": cfg.tier_siswa.model_copy(update={"batas": batas})}
    )
    assert nilai(p, kek, cfg_batas, cfg_app).tier.nilai == "sedang"  # 0.90 < 0.95

    pita = cfg.pita_keketatan.model_copy(
        update={"batas": cfg.pita_keketatan.batas.model_copy(update={"rendah_sedang": 1.5})}
    )
    cfg_pita = cfg.model_copy(update={"pita_keketatan": pita})
    assert nilai(p, kek, cfg_pita, cfg_app).pita["nilai"] == "sedang"  # rasio 2 >= 1.5


def test_hasil_selalu_berlabel_indikatif_dan_tanpa_persentase_peluang(cfg, cfg_app):
    h = nilai(profil(), Keketatan(10, 40), cfg, cfg_app)
    d = h.ke_dict()
    assert (
        d["indikatif"] is True
        and d["label"] == "indikatif, belum dikalibrasi"
        and d["keyakinan"] in ("rendah", "sedang")
    )
    teks = json.dumps(d).lower()
    for terlarang in ("peluang", "probabilitas", "persentase", "%"):
        assert terlarang not in teks.replace("bukan peluang", ""), terlarang


# ---------------------------- SNBT: proksi, data kurang, belum ada acuan ----------------------------


def test_snbt_tier_proksi_rapor_berkeyakinan_rendah_dan_peringatan_jelas(cfg, cfg_app):
    h = nilai(profil(), Keketatan(10, 100), cfg, cfg_app)
    assert h.tier.sumber == "proksi_rapor"
    assert h.keyakinan == "rendah"
    assert "bukan skor UTBK" in h.tier.peringatan
    assert "bukan skor UTBK" in h.alasan
    assert any("bukan skor UTBK" in c for c in h.catatan)


def test_snbt_pita_persentil_menyebut_relatif_terhadap_data(cfg_app):
    cfg = cfg_app.snbt  # metode persentil
    basis = buat_basis_pita(cfg.pita_keketatan, [float(x) for x in range(10, 30)], "semua")
    h = nilai(profil(), Keketatan(10, 200), cfg, cfg_app, basis=basis)
    assert h.pita["catatan_relatif"] == "relatif terhadap prodi yang ada di data"
    assert h.pita["basis"]["metode"] == "persentil" and h.pita["basis"]["n_prodi"] == 20
    assert "relatif terhadap prodi yang ada di data" in h.alasan


def test_snbt_tanpa_data_keketatan_belum_ada_acuan_dan_tidak_meminta_data_siswa(cfg, cfg_app):
    for kek in (None, Keketatan(None, None), Keketatan(0, 100), Keketatan(50, None)):
        h = nilai({}, kek, cfg, cfg_app)  # profil kosong pun tidak diminta melengkapi
        assert h.kategori == "belum_ada_acuan"
        assert h.data_kurang == () and h.keyakinan is None
        assert "tidak menebak" in h.alasan


def test_snbt_sampel_pembanding_kurang_belum_ada_acuan(cfg_app):
    basis = buat_basis_pita(cfg_app.snbt.pita_keketatan, [10.0, 20.0, 30.0], "semua")
    h = nilai(profil(), Keketatan(10, 100), cfg_app.snbt, cfg_app, basis=basis)
    assert h.kategori == "belum_ada_acuan" and "terlalu sedikit" in h.alasan


def test_snbt_rapor_kosong_data_kurang_nilai_rapor(cfg, cfg_app):
    h = nilai(
        {"peringkat_sekolah": 1, "jumlah_siswa_angkatan": 10}, Keketatan(10, 100), cfg, cfg_app
    )
    assert h.kategori == "data_kurang"
    assert [d.field for d in h.data_kurang] == ["nilai_rapor"]
    assert h.pita is not None  # pita tetap ditampilkan


def test_snbt_faktor_tidak_diketahui_dilaporkan(cfg, cfg_app):
    h = nilai({"nilai_rapor": {"semester_1": {"a": 80}}}, Keketatan(10, 100), cfg, cfg_app)
    assert set(h.tier.faktor_tidak_diketahui) == {"tren", "peringkat"}
    assert any("tren" in c and "peringkat" in c for c in h.catatan)


def test_snbt_skor_tryout_tidak_memengaruhi_kategori_tanpa_skala(cfg, cfg_app):
    rendah = nilai(profil(skor_tryout=100), Keketatan(10, 100), cfg, cfg_app)
    tinggi = nilai(profil(skor_tryout=900), Keketatan(10, 100), cfg, cfg_app)
    assert rendah.kategori == tinggi.kategori and rendah.tier.sumber == "proksi_rapor"


def test_snbt_tier_pindah_ke_skor_tryout_bila_skala_ada(cfg, cfg_app):
    from app.core.config import BatasSkor, SkalaSkorTryoutConfig

    skala = SkalaSkorTryoutConfig(batas=BatasSkor(lemah_sedang=600, sedang_kuat=750))
    c = cfg.model_copy(update={"skala_skor_tryout": skala})
    kek = Keketatan(10, 20)  # pita rendah
    h = nilai(profil(rapor=95, skor_tryout=500), kek, c, cfg_app)  # rapor bagus, tryout lemah
    assert h.tier.sumber == "skor_tryout" and h.tier.nilai == "lemah" and h.keyakinan == "sedang"
    assert "dari skor tryout" in h.alasan and "proksi" not in h.alasan.lower().replace(
        "proksi_rapor", ""
    )
    assert h.kategori == c.matriks.lemah.rendah.kategori
    # tanpa skor tryout: kembali ke proksi rapor
    h2 = nilai(profil(rapor=95), kek, c, cfg_app)
    assert h2.tier.sumber == "proksi_rapor" and h2.keyakinan == "rendah"


def test_tentukan_tier_rapor_saja(cfg):
    # rapor 95 datar: tren netral 0.5 -> (0.5*0.95 + 0.2*0.5) / 0.7 = 0.82 -> kuat
    t = tentukan_tier({"nilai_rapor": rapor_rata(95)}, cfg, sumber_rapor="rapor")
    assert t.nilai == "kuat" and t.sumber == "rapor" and t.skor == pytest.approx(0.8214, abs=1e-3)
    # rapor 90 datar tanpa peringkat: 0.79 -> sedang (tren netral menarik rata-rata ke bawah)
    assert (
        tentukan_tier({"nilai_rapor": rapor_rata(90)}, cfg, sumber_rapor="rapor").nilai == "sedang"
    )
    assert tentukan_tier({}, cfg, sumber_rapor="rapor") is None


# ---------------------------- SNBT: jalur acuan_skor (PRD 8.2) ----------------------------

ACUAN = AcuanSkor(rendah=660, tinggi=720, tahun=2025)


@pytest.mark.parametrize(
    "skor,kategori,gap",
    [
        (720, "safe", None),
        (800, "safe", None),
        (719.9, "match", None),
        (660, "match", None),
        (659.9, "reach", pytest.approx(0.1)),
        (620, "reach", 40),
    ],
)
def test_acuan_skor_batas(skor, kategori, gap):
    h = nilai_dengan_acuan(skor, ACUAN, tahun_siklus=2026)
    assert h.kategori == kategori and h.gap == gap
    assert h.metode == "acuan_skor" and h.indikatif is False
    assert h.label == "acuan siklus sebelumnya"
    assert h.acuan == {"rendah": 660, "tinggi": 720, "tahun": 2025}


def test_acuan_skor_belum_ada_skor_data_kurang():
    h = nilai_dengan_acuan(None, ACUAN, tahun_siklus=2026)
    assert h.kategori == "data_kurang" and [d.field for d in h.data_kurang] == ["skor_tryout"]


def test_acuan_siklus_sama_tanpa_label_siklus_sebelumnya():
    assert nilai_dengan_acuan(700, AcuanSkor(660, 720, 2026), tahun_siklus=2026).label is None


def test_acuan_didahulukan_atas_matriks(cfg, cfg_app):
    h = nilai(profil(skor_tryout=620), Keketatan(10, 100), cfg, cfg_app, acuan=ACUAN)
    assert h.metode == "acuan_skor" and h.kategori == "reach" and h.gap == 40


# ---------------------------- validasi config saat startup ----------------------------


def _config_dengan(tmp_path: Path, ganti: str, jadi: str) -> Path:
    isi = (ROOT_DIR / "config" / "app.yaml").read_text(encoding="utf-8")
    assert ganti in isi, ganti
    p = tmp_path / "app.yaml"
    p.write_text(isi.replace(ganti, jadi, 1), encoding="utf-8")
    return p


def test_config_sel_matriks_kosong_gagal_start(tmp_path):
    p = _config_dengan(tmp_path, "      rendah: {kategori: safe}\n", "")
    with pytest.raises(ConfigError, match="snbp.matriks.kuat.rendah"):
        load_app_config(p)


def test_config_kategori_di_luar_himpunan_gagal_start(tmp_path):
    p = _config_dengan(tmp_path, "rendah: {kategori: safe}", "rendah: {kategori: aman}")
    with pytest.raises(ConfigError, match="kategori"):
        load_app_config(p)


def test_config_batas_tier_tidak_urut_gagal_start(tmp_path):
    p = _config_dengan(
        tmp_path,
        "batas: {lemah_sedang: 0.60, sedang_kuat: 0.80}",
        "batas: {lemah_sedang: 0.90, sedang_kuat: 0.80}",
    )
    with pytest.raises(ConfigError, match="lebih kecil"):
        load_app_config(p)


def test_config_persentil_tidak_urut_gagal_start(tmp_path):
    p = _config_dengan(
        tmp_path,
        "persentil: {rendah_sedang: 33, sedang_tinggi: 67}",
        "persentil: {rendah_sedang: 80, sedang_tinggi: 67}",
    )
    with pytest.raises(ConfigError, match="persentil"):
        load_app_config(p)
