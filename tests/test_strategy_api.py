"""Task 10: POST /strategy (komposisi per jalur, aturan resmi 2026, swap, what-if tanpa simpan)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app
from tests.conftest import make_settings
from tests.helpers import analyze, masuk, muat_persona

pytestmark = pytest.mark.db

SARJANA = ["ui-ilmu-komputer", "ui-akuntansi", "ui-hukum", "ui-psikologi"]
SHORTLIST_VOKASI = ["ui-v-akuntansi-d3", "ui-v-fisioterapi"]


def strategi(c, h, jalur="SNBT", pilihan=(), shortlist=(), **lain):
    body = {
        "jalur": jalur,
        "pilihan": [{"prodi_id": p} for p in pilihan],
        "shortlist": list(shortlist),
        **lain,
    }
    return c.post("/api/v1/strategy", json=body, headers=h)


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def temuan(d: dict, kode: str) -> dict | None:
    return next((t for t in d["temuan"] if t["kode"] == kode), None)


def snapshot(engine: Engine, tabel: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(f"SELECT * FROM {tabel} ORDER BY 1"))]


# ---------------------------- SNBT: aturan resmi 2026 ----------------------------


def test_tiga_sarjana_melanggar_aturan_vokasi_dengan_saran_swap_dari_shortlist(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:3], SHORTLIST_VOKASI))

    assert d["jalur"] == "SNBT" and d["batas_pilihan"] == 4
    vokasi = temuan(d, "butuh_vokasi")
    assert vokasi["tingkat"] == "pelanggaran" and "Sarjana maksimal 2" in vokasi["pesan"]
    assert d["temuan"][0]["kode"] == "butuh_vokasi"  # pelanggaran paling atas

    saran = vokasi["saran_swap"]
    assert 1 <= len(saran) <= 3
    assert all(s["ganti"] in SARJANA[:3] and s["dengan"] in SHORTLIST_VOKASI for s in saran)
    assert saran[0] == {
        "ganti": "ui-ilmu-komputer",
        "dengan": "ui-v-fisioterapi",  # vokasi match; D3 Akuntansi (reach) tidak lebih baik
        "alasan": saran[0]["alasan"],
    }
    assert "memperbaiki" in saran[0]["alasan"]

    # semua di UI -> peringatan satu PTN; swap vokasi UI tidak memperbaikinya
    assert (
        temuan(d, "satu_ptn")["tingkat"] == "peringatan"
        and temuan(d, "satu_ptn")["saran_swap"] == []
    )
    k = d["komposisi"]
    assert (k["jumlah"], k["akademik"], k["vokasi"]) == (3, 3, 0)
    assert k["reach"] + k["match"] + k["safe"] == 3


def test_komposisi_sah_dua_sarjana_satu_vokasi_tanpa_pelanggaran(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", [SARJANA[0], SARJANA[1], "ui-v-akuntansi-d3"]))
    assert not [t for t in d["temuan"] if t["tingkat"] == "pelanggaran"]
    assert (d["komposisi"]["akademik"], d["komposisi"]["vokasi"], d["komposisi"]["d3"]) == (2, 1, 1)


def test_empat_sarjana_melanggar_dan_menyebut_komposisi_yang_sah(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA, SHORTLIST_VOKASI))
    t = temuan(d, "butuh_vokasi")
    assert t["tingkat"] == "pelanggaran"
    assert "2 akademik + 2 vokasi (minimal 1 D3)" in t["pesan"]
    assert t["saran_swap"] == []  # satu swap tidak cukup untuk 4 pilihan, pesan memandu langkahnya


def test_satu_atau_dua_pilihan_snbt_bebas_termasuk_dua_sarjana(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:2]))
    assert not [t for t in d["temuan"] if t["tingkat"] == "pelanggaran"]


def test_lima_pilihan_snbt_melebihi_batas(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", [*SARJANA, "ui-v-akuntansi-d3"]))
    t = temuan(d, "melebihi_batas_pilihan")
    assert t["tingkat"] == "pelanggaran" and "maksimal 4" in t["pesan"]
    assert temuan(d, "butuh_vokasi") is None  # komposisi tak diperiksa bila jumlah sudah melanggar


# ---------------------------- SNBP: 2 pilihan + aturan provinsi ----------------------------


def test_snbp_dua_pilihan_di_provinsi_sekolah_asal_sah(app_seed):
    h = muat_persona(app_seed, "dimas")
    d = ok(strategi(app_seed, h, "SNBP", ["ui-teknik-industri", "ui-teknik-elektro"]))
    assert d["batas_pilihan"] == 2
    assert not [t for t in d["temuan"] if t["tingkat"] == "pelanggaran"]
    # data keketatan SNBP belum ada: tidak dihitung, dilaporkan sendiri (bukan salah hitung)
    assert set(temuan(d, "pilihan_belum_ada_acuan")["prodi_ids"]) == {
        "ui-teknik-industri",
        "ui-teknik-elektro",
    }
    assert temuan(d, "evaluasi_rasio_dilewati") is not None
    assert temuan(d, "min_safe") is None


def test_snbp_tiga_pilihan_melebihi_batas(app_seed):
    h = muat_persona(app_seed, "dimas")
    d = ok(
        strategi(
            app_seed, h, "SNBP", ["ui-teknik-industri", "ui-teknik-elektro", "ui-teknik-mesin"]
        )
    )
    assert temuan(d, "melebihi_batas_pilihan")["tingkat"] == "pelanggaran"


def test_snbp_provinsi_sekolah_di_luar_pilihan_melanggar_lewat_whatif(app_seed):
    h = muat_persona(app_seed, "dimas")
    t = ["ui-teknik-industri", "ui-teknik-elektro"]
    d = ok(strategi(app_seed, h, "SNBP", t, override={"provinsi": "Bali"}))
    p = temuan(d, "provinsi_sekolah_asal")
    assert p["tingkat"] == "pelanggaran" and "Bali" in p["pesan"]
    # satu pilihan saja: provinsi mana pun boleh
    satu = ok(strategi(app_seed, h, "SNBP", t[:1], override={"provinsi": "Bali"}))
    assert temuan(satu, "provinsi_sekolah_asal") is None
    # dan profil tersimpan tetap Jawa Barat
    assert app_seed.get("/api/v1/profile", headers=h).json()["profil"]["provinsi"] == "Jawa Barat"


def test_snbp_provinsi_belum_diisi_meminta_data(app_seed):
    h = muat_persona(app_seed, "dimas")
    d = ok(
        strategi(
            app_seed,
            h,
            "SNBP",
            ["ui-teknik-industri", "ui-teknik-elektro"],
            override={"provinsi": None},
        )
    )
    t = temuan(d, "provinsi_sekolah_belum_diisi")
    assert t["tingkat"] == "peringatan" and t["data_kurang"] == ["provinsi"]


def test_snbp_pilihan_di_ptn_provinsi_lain_ditambah_ui_sah(app_seed):
    h = muat_persona(app_seed, "dimas")
    d = ok(strategi(app_seed, h, "SNBP", ["ui-teknik-industri", "ugm-teknik-industri"]))
    assert temuan(d, "provinsi_sekolah_asal") is None  # satu di Jawa Barat sudah cukup


# ---------------------------- hasil analisis, komposisi, informasi ----------------------------


def test_hasil_sama_dengan_analyze(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:2]))
    a = ok(analyze(app_seed, h, [{"prodi_id": p, "jalur": ["SNBT"]} for p in SARJANA[:2]]))
    assert d["hasil"] == a["hasil"]


def test_pilihan_tidak_memenuhi_syarat_dilaporkan_dan_tidak_dihitung(app_seed):
    h = muat_persona(app_seed, "budi")  # lulus 2023: gagal SNBT
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:2]))
    t = temuan(d, "pilihan_tidak_memenuhi_syarat")
    assert t["tingkat"] == "peringatan" and set(t["prodi_ids"]) == set(SARJANA[:2])
    assert d["komposisi"]["tidak_dinilai"] == 2 and d["komposisi"]["reach"] == 0


def test_pilihan_data_kurang_dilaporkan(app_seed):
    h = muat_persona(app_seed, "sinta")
    d = ok(strategi(app_seed, h, "SNBT", [SARJANA[0]]))
    assert temuan(d, "pilihan_data_kurang")["prodi_ids"] == [SARJANA[0]]


def test_prodi_tanpa_data_belum_ada_acuan_tidak_dihitung(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", ["ui-dkv", "ugm-hukum"]))
    assert set(temuan(d, "pilihan_belum_ada_acuan")["prodi_ids"]) == {"ui-dkv", "ugm-hukum"}
    assert d["komposisi"]["tidak_dinilai"] == 2


def test_blokir_lintas_jalur_dan_hanya_satu_jalur(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:1]))
    assert "tidak dapat mendaftar UTBK-SNBT" in temuan(d, "blokir_lintas_jalur")["pesan"]
    assert temuan(d, "blokir_lintas_jalur")["tingkat"] == "info"
    assert temuan(d, "hanya_satu_jalur") is not None
    # setelah strategi SNBP disimpan, info 'hanya satu jalur' hilang untuk SNBT
    ok(strategi(app_seed, h, "SNBP", ["ui-akuntansi"], simpan=True))
    assert temuan(ok(strategi(app_seed, h, "SNBT", SARJANA[:1])), "hanya_satu_jalur") is None


# ---------------------------- heuristik dari config ----------------------------


def test_semua_reach_memicu_peringatan_dan_config_mengubahnya(app_seed, clean_db, app_config):
    h = muat_persona(app_seed, "rani")
    dua_reach = ["ui-v-akuntansi-d3", "ui-v-hubungan-masyarakat"]  # rasio sangat tinggi -> reach
    d = ok(strategi(app_seed, h, "SNBT", dua_reach))
    assert [x["penilaian"]["kategori"] for x in d["hasil"]] == ["reach", "reach"]
    assert temuan(d, "min_safe")["tingkat"] == "peringatan"
    assert temuan(d, "maks_reach")["tingkat"] == "peringatan"

    # ubah konfigurasi saja (tanpa ubah kode): perilaku berubah
    longgar = app_config.strategi.model_copy(update={"min_safe": 0, "maks_rasio_reach": 1.0})
    cfg = app_config.model_copy(update={"strategi": longgar})
    with TestClient(create_app(make_settings(), cfg, clean_db)) as c:
        h2 = muat_persona(c, "rani")
        d2 = ok(strategi(c, h2, "SNBT", dua_reach))
    assert temuan(d2, "min_safe") is None and temuan(d2, "maks_reach") is None


def test_saran_swap_menyelamatkan_komposisi_reach_dari_shortlist(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(
        strategi(
            app_seed,
            h,
            "SNBT",
            ["ui-v-akuntansi-d3", "ui-v-hubungan-masyarakat"],
            shortlist=[
                "ui-teknik-elektro",
                "ui-v-fisioterapi",
            ],  # Teknik Elektro: safe di antara prodi akademik
        )
    )
    saran = temuan(d, "min_safe")["saran_swap"]
    assert saran, "harus ada saran swap bila shortlist punya kandidat safe"
    assert (
        saran[0]["dengan"] == "ui-teknik-elektro"
    )  # kandidat safe memperbaiki min_safe dan maks_reach
    assert {s["ganti"] for s in saran} <= {"ui-v-akuntansi-d3", "ui-v-hubungan-masyarakat"}


# ---------------------------- what-if & penyimpanan ----------------------------


def test_override_tidak_mengubah_baris_dan_simpan_dipaksa_false(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    sebelum = {
        t: snapshot(clean_db, t) for t in ("profiles", "strategies", "sessions", "query_logs")
    }
    d = ok(
        strategi(
            app_seed,
            h,
            "SNBT",
            SARJANA[:2],
            override={"skor_tryout": 650, "tahun_lulus": 2024},
            simpan=True,
        )
    )
    assert d["disimpan"] is False and d["strategy_id"] is None
    assert any("what-if" in c for c in d["catatan"])
    assert {t: snapshot(clean_db, t) for t in sebelum} == sebelum  # tidak ada baris yang berubah


def test_override_kosong_tetap_mode_whatif(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:1], override={}, simpan=True))
    assert d["disimpan"] is False
    assert snapshot(clean_db, "strategies") == []


def test_override_mengubah_hasil_komposisi(app_seed):
    h = muat_persona(app_seed, "rani")
    safe_dua = ["ui-teknik-elektro", "ui-teknik-mesin"]  # keduanya safe untuk Rani
    asli = ok(strategi(app_seed, h, "SNBT", safe_dua))
    jelek = {
        "nilai_rapor": {
            f"semester_{i}": dict.fromkeys(
                ("matematika", "fisika", "kimia", "biologi", "bahasa_indonesia", "bahasa_inggris"),
                40,
            )
            for i in range(1, 6)
        },
        "peringkat_sekolah": 290,
    }
    skenario = ok(strategi(app_seed, h, "SNBT", safe_dua, override=jelek))
    assert asli["komposisi"]["safe"] == 2 and skenario["komposisi"]["reach"] == 2
    assert temuan(skenario, "maks_reach") is not None and temuan(asli, "maks_reach") is None


def test_simpan_menyimpan_pilihan_aktif(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:2], simpan=True))
    assert d["disimpan"] is True and d["strategy_id"]
    with clean_db.connect() as conn:
        baris = conn.execute(
            text("SELECT id::text, jalur, pilihan, hasil_evaluasi FROM strategies")
        ).one()
    assert baris[0] == d["strategy_id"] and baris[1] == "SNBT"
    assert [p["prodi_id"] for p in baris[2]] == SARJANA[:2]
    assert baris[3]["komposisi"] == d["komposisi"] and baris[3]["komposisi"]["jumlah"] == 2
    assert [t["kode"] for t in baris[3]["temuan"]] == [t["kode"] for t in d["temuan"]]


def test_tanpa_simpan_tidak_menyimpan(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    d = ok(strategi(app_seed, h, "SNBT", SARJANA[:2]))
    assert d["disimpan"] is False and snapshot(clean_db, "strategies") == []


def test_strategi_terhapus_bersama_sesi(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    ok(strategi(app_seed, h, "SNBT", SARJANA[:2], simpan=True))
    assert app_seed.delete("/api/v1/session", headers=h).status_code == 204
    assert snapshot(clean_db, "strategies") == []


# ---------------------------- validasi permintaan & akses ----------------------------


def test_wajib_token(app_seed):
    r = app_seed.post(
        "/api/v1/strategy", json={"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi"}]}
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"jalur": "SNBT", "pilihan": []},
        {"jalur": "SNBT"},
        {"pilihan": [{"prodi_id": "ui-akuntansi"}]},
        {"jalur": "MANDIRI", "pilihan": [{"prodi_id": "ui-akuntansi"}]},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi"}, {"prodi_id": "ui-akuntansi"}]},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": f"p{i}"} for i in range(11)]},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi"}], "hasil_analisis": "palsu"},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi", "jalur": "SNBT"}]},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi"}], "shortlist": [""]},
        {"jalur": "SNBT", "pilihan": [{"prodi_id": "ui-akuntansi"}], "override": {"nama": "X"}},
    ],
)
def test_permintaan_tidak_valid_422(app_seed, body):
    h = muat_persona(app_seed, "rani")
    assert app_seed.post("/api/v1/strategy", json=body, headers=h).status_code == 422


def test_prodi_tidak_dikenal_di_pilihan_atau_shortlist_404(app_seed):
    h = muat_persona(app_seed, "rani")
    r = strategi(app_seed, h, "SNBT", ["ui-akuntansi", "hantu-1"], shortlist=["hantu-2"])
    assert r.status_code == 404
    assert r.json()["error"]["detail"]["prodi_id"] == ["hantu-1", "hantu-2"]


def test_deterministik_dan_cepat(app_seed):
    h = muat_persona(app_seed, "rani")
    args = (
        app_seed,
        h,
        "SNBT",
        SARJANA[:3],
        SHORTLIST_VOKASI + ["ui-hukum", "ui-manajemen", "ui-v-bisnis-kreatif"],
    )
    pertama = ok(strategi(*args))
    t0 = time.perf_counter()
    kedua = ok(strategi(*args))
    durasi = time.perf_counter() - t0
    assert pertama == kedua
    assert durasi < 1.0, f"/strategy {durasi:.2f}s melebihi target 1 detik"


def test_sesi_tanpa_profil_tetap_dievaluasi(app_seed):
    h = masuk(app_seed)
    d = ok(strategi(app_seed, h, "SNBT", ["ui-ilmu-komputer"]))
    assert temuan(d, "pilihan_data_kurang") is not None
