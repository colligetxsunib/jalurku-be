"""Task 5: ingest (konverter, FR-D2, transaksi, idempoten, admin endpoint)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, AppConfig
from app.db import models as m
from app.domain.gate import evaluasi_gate
from app.domain.provinsi import PROVINSI_BAKU, normalisasi_provinsi
from app.ingest.acuan import acuan_dari_baris
from app.ingest.csv_io import baca_csv
from app.ingest.dokumen import dokumen_dari_baris
from app.ingest.katalog import katalog_dari_baris
from app.ingest.ketentuan import ketentuan_dari_baris, parse_komposisi
from app.ingest.service import ingest, ingest_direktori
from app.ingest.umum import Kebijakan
from app.main import create_app
from app.services.refdata import muat_refdata
from tests.conftest import make_settings
from tests.helpers import SEED_DIR

SEED = SEED_DIR  # salinan netral tanpa tanggal verifikasi (lihat tests/helpers.py)
LONGGAR = Kebijakan(require_verified=False, hari_ini=date(2026, 10, 13))
KETAT = Kebijakan(require_verified=True, hari_ini=date(2026, 10, 13))


def baris(nama: str) -> list[dict[str, str]]:
    return baca_csv(SEED / nama)


# ---------------------------- provinsi ----------------------------


def test_daftar_provinsi_38_dan_normalisasi():
    assert len(PROVINSI_BAKU) == len(set(PROVINSI_BAKU)) == 38
    assert normalisasi_provinsi("  jawa   barat ") == "Jawa Barat"
    assert normalisasi_provinsi("DI Yogyakarta") == "DI Yogyakarta"
    assert normalisasi_provinsi("PERLU_VERIFIKASI (Jawa Barat atau DKI Jakarta)") is None
    assert normalisasi_provinsi(None) is None


# ---------------------------- komposisi SNBT ----------------------------


def test_parse_komposisi_dari_teks_csv_asli():
    tiga = parse_komposisi(
        "2 akademik+1 vokasi | 1 akademik+2 vokasi | 3 vokasi dengan minimal 1 D3", 3
    )
    assert tiga == [
        {"akademik": 2, "vokasi": 1, "min_d3": 0},
        {"akademik": 1, "vokasi": 2, "min_d3": 0},
        {"akademik": 0, "vokasi": 3, "min_d3": 1},
    ]
    empat = parse_komposisi("2 akademik+2 vokasi (min 1 D3) | 1 akademik+3 vokasi (min 1 D3)", 4)
    assert empat == [
        {"akademik": 2, "vokasi": 2, "min_d3": 1},
        {"akademik": 1, "vokasi": 3, "min_d3": 1},
    ]


@pytest.mark.parametrize(
    "teks,n,potongan",
    [
        ("2 akademik+2 vokasi", 3, "seharusnya 3"),
        ("3 vokasi dengan minimal 4 D3", 3, "melebihi jumlah vokasi"),
        ("campur aduk", 3, "tidak dapat dibaca"),
        ("", 3, "komposisi kosong"),
    ],
)
def test_parse_komposisi_error(teks, n, potongan):
    with pytest.raises(ValueError, match=potongan):
        parse_komposisi(teks, n)


# ---------------------------- konverter dari CSV asli ----------------------------


def test_ketentuan_csv_asli():
    item, galat = ketentuan_dari_baris(baris("config_ketentuan.csv"), LONGGAR)
    assert galat == [] and len(item) == 22
    peta = {(i["key"], i["jalur"]): i for i in item}
    assert peta[("komposisi_pilihan_1_2", "SNBT")]["nilai_terstruktur"] == "bebas"
    assert len(peta[("komposisi_pilihan_3", "SNBT")]["nilai_terstruktur"]) == 3
    assert peta[("max_pilihan_prodi", "SNBP")]["nilai"] == "2"
    assert peta[("max_pilihan_prodi", "SNBT")]["nilai"] == "4"
    assert all(i["terakhir_diverifikasi"] is None for i in item)  # tidak pernah diisi otomatis


def test_ketentuan_validasi():
    dasar = {
        "key": "max_pilihan_prodi",
        "jalur": "SNBP",
        "tahun_siklus": "2026",
        "nilai": "2",
        "sumber_url": "https://x.id/a.pdf",
    }
    _, g = ketentuan_dari_baris([{**dasar, "nilai": "dua"}], LONGGAR)
    assert "harus angka" in g[0].pesan
    _, g = ketentuan_dari_baris([{**dasar, "jalur": "XXX"}], LONGGAR)
    assert "jalur harus" in g[0].pesan
    _, g = ketentuan_dari_baris([{**dasar, "sumber_url": ""}], LONGGAR)
    assert "sumber_url wajib" in g[0].pesan
    _, g = ketentuan_dari_baris([dasar, dasar], LONGGAR)
    assert "duplikat" in g[0].pesan and g[0].baris == 2


def test_katalog_csv_asli():
    kat = katalog_dari_baris(baris("ptn.csv") + baris("prodi.csv"), LONGGAR, tahun_default=2026)
    assert kat.error == []
    assert len(kat.ptn) == 10 and len(kat.prodi) == 185
    assert next(p for p in kat.ptn if p["id"] == "ui")["provinsi"] == "Jawa Barat"
    # hanya prodi UI yang punya data keketatan: 16 Sarjana + 15 vokasi
    assert len(kat.prodi_jalur) == 31
    assert {j["jalur"] for j in kat.prodi_jalur} == {"SNBT"}
    assert all(j["tahun_siklus"] == 2026 and j["tahun_peminat"] == 2025 for j in kat.prodi_jalur)
    ik = next(p for p in kat.prodi if p["id"] == "ui-ilmu-komputer")
    assert (ik["jenjang"], ik["program"], ik["jalur_dibuka"]) == ("S1", "akademik", ["SNBT"])
    vokasi = {p["id"]: p for p in kat.prodi if p["program"] == "vokasi"}
    assert len(vokasi) == 15
    assert sum(1 for p in vokasi.values() if p["jenjang"] == "D3") == 9
    assert sum(1 for p in vokasi.values() if p["jenjang"] == "D4") == 6
    kosong = next(
        p for p in kat.prodi if p["id"] == "ui-dkv"
    )  # tanpa data: tidak ada baris keketatan
    assert kosong["jalur_dibuka"] is None and kosong["sumber_url"] is None
    assert not [j for j in kat.prodi_jalur if j["prodi_id"] == "ui-dkv"]


PTN_OK = {"ptn_id": "ui", "nama": "UI", "provinsi": "Jawa Barat"}


def _prodi(**ubah):
    dasar = {
        "prodi_id": "p1",
        "ptn_id": "ui",
        "nama": "X",
        "rumpun": "Teknik",
        "jenjang": "Sarjana",
        "program": "akademik",
    }
    dasar.update(ubah)
    return dasar


def test_katalog_provinsi_tidak_baku_ditolak_dan_error_berantai_diredam():
    kat = katalog_dari_baris(
        [{**PTN_OK, "provinsi": "PERLU_VERIFIKASI (Jawa Barat atau DKI Jakarta)"}, _prodi()],
        LONGGAR,
    )
    assert len(kat.error) == 1 and "bukan provinsi baku" in kat.error[0].pesan
    assert kat.ptn_ditolak == {"ui"}


@pytest.mark.parametrize(
    "ubah,potongan",
    [
        ({"jenjang": "Magister"}, "jenjang 'Magister' tidak dikenal"),
        ({"program": "vokasi"}, "tidak sesuai program"),
        ({"jenjang": "Diploma Tiga", "program": "akademik"}, "tidak sesuai program"),
        ({"jalur_dibuka": "SNBX"}, "jalur tidak dikenal"),
        (
            {"jalur_dibuka": "SNBP|SNBT", "daya_tampung": "50"},
            "hanya boleh diisi bila jalur_dibuka tepat satu",
        ),
        ({"daya_tampung": "50", "jalur_dibuka": "SNBT", "sumber_url": ""}, "sumber_url wajib"),
        ({"daya_tampung": "0", "jalur_dibuka": "SNBT", "sumber_url": "https://a.id"}, "harus >= 1"),
        (
            {"daya_tampung_snbp": "10", "jalur_dibuka": "SNBT", "sumber_url": "https://a.id"},
            "tidak ada di jalur_dibuka",
        ),
    ],
)
def test_katalog_prodi_validasi(ubah, potongan):
    kat = katalog_dari_baris([PTN_OK, _prodi(**ubah)], LONGGAR, tahun_default=2026)
    assert kat.error and potongan in kat.error[0].pesan, kat.error


def test_katalog_data_dua_jalur_lewat_kolom_per_jalur():
    kat = katalog_dari_baris(
        [
            PTN_OK,
            _prodi(
                jalur_dibuka="SNBP|SNBT",
                sumber_url="https://a.id",
                daya_tampung_snbp="30",
                peminat_snbp="300",
                daya_tampung_snbt="40",
                peminat_snbt="1200",
            ),
        ],
        LONGGAR,
        tahun_default=2026,
    )
    assert kat.error == []
    per = {j["jalur"]: (j["daya_tampung"], j["peminat"]) for j in kat.prodi_jalur}
    assert per == {"SNBP": (30, 300), "SNBT": (40, 1200)}


def test_katalog_duplikat():
    kat = katalog_dari_baris([PTN_OK, PTN_OK, _prodi(), _prodi()], LONGGAR)
    assert sorted(e.baris for e in kat.error) == [2, 4]


def test_acuan_dan_dokumen():
    item, g = acuan_dari_baris(
        [
            {
                "prodi_id": "p",
                "jalur": "SNBT",
                "rendah": "600",
                "tinggi": "700",
                "tahun": "2025",
                "sumber_url": "https://a.id",
            },
            {
                "prodi_id": "p",
                "jalur": "SNBT",
                "rendah": "700",
                "tinggi": "600",
                "tahun": "2024",
                "sumber_url": "https://a.id",
            },
        ],
        LONGGAR,
    )
    assert len(item) == 1 and "tidak boleh lebih besar" in g[0].pesan
    assert acuan_dari_baris(baris("acuan_skor_snbt.csv"), LONGGAR) == ([], [])  # CSV kosong = sah

    dok, g = dokumen_dari_baris(baris("dokumen_rag_metadata.csv"), LONGGAR)
    assert g == [] and len(dok) == 5
    assert {d["id"] for d in dok} >= {"snpmb-paparan-2026", "snpmb-faq"}
    assert all(d["terakhir_diverifikasi"] is None for d in dok)


# ---------------------------- kebijakan FR-D2 ----------------------------


def test_require_verified_menolak_tanpa_tanggal_dan_menerima_dengan_tanggal():
    dasar = {
        "key": "max_pilihan_prodi",
        "jalur": "SNBP",
        "tahun_siklus": "2026",
        "nilai": "2",
        "sumber_url": "https://x.id/a.pdf",
    }
    _, g = ketentuan_dari_baris([dasar], KETAT)
    assert "terakhir_diverifikasi wajib diisi" in g[0].pesan
    item, g = ketentuan_dari_baris([{**dasar, "terakhir_diverifikasi": "2026-10-13"}], KETAT)
    assert g == [] and item[0]["terakhir_diverifikasi"] == date(2026, 10, 13)


@pytest.mark.parametrize(
    "nilai,potongan",
    [("13-10-2026", "YYYY-MM-DD"), ("2027-01-01", "masa depan"), ("kemarin", "YYYY-MM-DD")],
)
def test_tanggal_verifikasi_tidak_valid(nilai, potongan):
    dasar = {
        "key": "max_pilihan_prodi",
        "jalur": "SNBP",
        "tahun_siklus": "2026",
        "nilai": "2",
        "sumber_url": "https://x.id/a.pdf",
        "terakhir_diverifikasi": nilai,
    }
    _, g = ketentuan_dari_baris([dasar], LONGGAR)
    assert potongan in g[0].pesan


# ---------------------------- database ----------------------------


def _hitung(engine: Engine, tabel: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"select count(*) from {tabel}")).scalar()


@pytest.mark.db
class TestIngestDB:
    def test_seed_lengkap_dan_idempoten(self, clean_db: Engine):
        for _ in range(2):  # ulang: tidak boleh menggandakan data
            with Session(clean_db) as db:
                hasil = ingest_direktori(db, SEED)
            assert all(h.ok for h in hasil), [e for h in hasil for e in h.error]
            assert {
                t: _hitung(clean_db, t)
                for t in (
                    "ptn",
                    "prodi",
                    "prodi_jalur",
                    "rules_jalur",
                    "ketentuan",
                    "dokumen_sumber",
                    "acuan_skor",
                )
            } == {
                "ptn": 10,
                "prodi": 185,
                "prodi_jalur": 31,
                "rules_jalur": 2,
                "ketentuan": 22,
                "dokumen_sumber": 5,
                "acuan_skor": 0,
            }

    def test_isi_db_sesuai_csv(self, clean_db: Engine):
        with Session(clean_db) as db:
            ingest_direktori(db, SEED)
        with Session(clean_db) as db:
            snbt = db.get(m.RulesJalur, "SNBT-2026")
            snbp = db.get(m.RulesJalur, "SNBP-2026")
            assert len(snbt.syarat) == 5 and len(snbp.syarat) == 8
            assert len(snbp.dokumen_wajib) == 5 and len(snbt.dokumen_wajib) == 8
            assert snbt.terakhir_diverifikasi is None  # belum diverifikasi manusia
            k4 = db.get(m.Ketentuan, ("komposisi_pilihan_4", "SNBT", 2026))
            assert k4.nilai_terstruktur[0] == {"akademik": 2, "vokasi": 2, "min_d3": 1}
            teks = db.get(m.Ketentuan, ("pemeringkatan_siswa", "SNBP", 2026))
            assert teks.nilai_terstruktur is None  # SQL NULL, bukan JSON null
            ui = db.get(m.Ptn, "ui")
            assert ui.provinsi == "Jawa Barat"
            vokasi = db.get(m.Prodi, "ui-v-hubungan-masyarakat")
            assert (vokasi.jenjang, vokasi.program) == ("D3", "vokasi")
            pj = db.get(m.ProdiJalur, ("ui-ilmu-komputer", "SNBT", 2026))
            assert (pj.daya_tampung, pj.peminat, pj.tahun_peminat) == (75, 2132, 2025)

    def test_batch_gagal_menyimpan_nol_baris(self, clean_db: Engine):
        payload = [
            {"ptn_id": "a", "nama": "A", "provinsi": "Jawa Barat"},
            {"ptn_id": "b", "nama": "B", "provinsi": "Provinsi Fiktif"},
        ]
        with Session(clean_db) as db:
            hasil = ingest(db, "katalog", payload)
        assert not hasil.ok and hasil.diterima == 0
        assert [e.baris for e in hasil.error] == [2]
        assert _hitung(clean_db, "ptn") == 0  # baris pertama yang valid pun tidak tersimpan

    def test_upsert_memperbarui_nilai(self, clean_db: Engine):
        ptn = {"ptn_id": "a", "nama": "A", "provinsi": "Jawa Barat"}
        with Session(clean_db) as db:
            ingest(db, "katalog", [ptn])
            ingest(db, "katalog", [{**ptn, "nama": "A Baru", "provinsi": "Banten"}])
        with Session(clean_db) as db:
            baris = db.get(m.Ptn, "a")
            assert (baris.nama, baris.provinsi) == ("A Baru", "Banten")
        assert _hitung(clean_db, "ptn") == 1

    def test_prodi_dengan_ptn_tak_dikenal_ditolak(self, clean_db: Engine):
        with Session(clean_db) as db:
            hasil = ingest(db, "katalog", [_prodi(ptn_id="hantu")])
        assert "tidak ada di katalog PTN" in hasil.error[0].pesan
        assert _hitung(clean_db, "prodi") == 0

    def test_require_verified_menolak_seed_tanpa_tanggal(self, clean_db: Engine):
        with Session(clean_db) as db:
            hasil = ingest_direktori(db, SEED, require_verified=True)
        # acuan dan profesi tidak punya berkas seed (payload kosong), jadi tidak ada yang ditolak
        assert all(not h.ok for h in hasil if h.tipe not in ("acuan", "profesi"))
        assert {h.tipe for h in hasil if h.ok} == {"acuan", "profesi"}
        assert "REQUIRE_VERIFIED" in hasil[0].error[0].pesan
        assert _hitung(clean_db, "ketentuan") == 0 and _hitung(clean_db, "prodi") == 0

    def test_dokumen_wajib_lama_dipertahankan_saat_syarat_diperbarui(self, clean_db: Engine):
        with Session(clean_db) as db:
            ingest_direktori(db, SEED, tipe=["ketentuan", "rules"])
            syarat_saja = [r for r in baris("rule_gate.csv") if r["jalur"] == "SNBT"]
            hasil = ingest(db, "rules", syarat_saja)
        assert hasil.ok
        with Session(clean_db) as db:
            assert len(db.get(m.RulesJalur, "SNBT-2026").dokumen_wajib) == 8

    def test_dokumen_wajib_tanpa_rules_ditolak(self, clean_db: Engine):
        with Session(clean_db) as db:
            hasil = ingest(
                db,
                "rules",
                [{"jalur": "SNBT", "nama_dokumen": "KTP", "sumber_url": "https://a.id"}],
            )
        assert "belum ada rules SNBT" in hasil.error[0].pesan

    def test_refdata_dari_db_menjalankan_gate_persona(self, clean_db: Engine):
        with Session(clean_db) as db:
            ingest_direktori(db, SEED)
            ref = muat_refdata(db)
        assert ref.tahun_siklus == 2026 and set(ref.rules) == {"SNBP", "SNBT"}
        import json

        budi = json.loads((ROOT_DIR / "config" / "personas" / "budi.json").read_text("utf-8"))
        h = evaluasi_gate(ref.rules["SNBT"], budi["profil"], ref.ketentuan)
        assert h.status == "tidak_memenuhi_syarat"
        rani = json.loads((ROOT_DIR / "config" / "personas" / "rani.json").read_text("utf-8"))
        assert evaluasi_gate(ref.rules["SNBP"], rani["profil"], ref.ketentuan).status == "lolos"


@pytest.mark.db
class TestAdminIngest:
    KUNCI = "kunci-admin-uji-123"

    def _client(self, engine: Engine, app_config: AppConfig, **settings) -> TestClient:
        return TestClient(create_app(make_settings(**settings), app_config, engine))

    def test_nonaktif_404_bila_admin_key_tidak_diset(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key="")
        r = c.post(
            "/api/v1/admin/ingest",
            json={"tipe": "katalog", "payload": []},
            headers={"X-Admin-Key": "apa-saja"},
        )
        assert r.status_code == 404

    @pytest.mark.parametrize("header", [{}, {"X-Admin-Key": "salah"}, {"X-Admin-Key": ""}])
    def test_tanpa_atau_salah_key_401(self, clean_db, app_config, header):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        r = c.post("/api/v1/admin/ingest", json={"tipe": "katalog", "payload": []}, headers=header)
        assert r.status_code == 401
        assert r.json()["error"]["kode"] == "admin_key_salah"

    def test_token_sesi_bukan_admin_key(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        token = c.post("/api/v1/session", json={"consent": True, "consent_version": "v1"}).json()[
            "token"
        ]
        r = c.post(
            "/api/v1/admin/ingest",
            json={"tipe": "katalog", "payload": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401

    def test_key_nonascii_tidak_membuat_500(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        r = c.post(
            "/api/v1/admin/ingest",
            json={"tipe": "katalog", "payload": []},
            headers={"X-Admin-Key": "kunci-é".encode("latin-1")},
        )
        assert r.status_code == 401

    def test_impor_berhasil_dan_idempoten(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        body = {"tipe": "katalog", "payload": [{"ptn_id": "a", "nama": "A", "provinsi": "Banten"}]}
        for _ in range(2):
            r = c.post("/api/v1/admin/ingest", json=body, headers={"X-Admin-Key": self.KUNCI})
            assert r.status_code == 200, r.text
            assert r.json() == {
                "tipe": "katalog",
                "diterima": 1,
                "error": [],
                "ringkasan": {"ptn": 1, "prodi": 0, "prodi_jalur": 0},
            }
        assert _hitung(clean_db, "ptn") == 1

    def test_impor_ditolak_422_dengan_error_per_baris(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        body = {
            "tipe": "katalog",
            "payload": [
                {"ptn_id": "a", "nama": "A", "provinsi": "Banten"},
                {"ptn_id": "b", "nama": "B", "provinsi": "Narnia"},
            ],
        }
        r = c.post("/api/v1/admin/ingest", json=body, headers={"X-Admin-Key": self.KUNCI})
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["kode"] == "impor_ditolak"
        assert err["detail"]["diterima"] == 0
        assert err["detail"]["error"][0]["baris"] == 2
        assert _hitung(clean_db, "ptn") == 0

    def test_tipe_tak_dikenal_dan_field_tambahan_ditolak(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI)
        h = {"X-Admin-Key": self.KUNCI}
        assert (
            c.post(
                "/api/v1/admin/ingest", json={"tipe": "lain", "payload": []}, headers=h
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/api/v1/admin/ingest", json={"tipe": "katalog", "payload": [], "x": 1}, headers=h
            ).status_code
            == 422
        )

    def test_require_verified_dari_settings(self, clean_db, app_config):
        c = self._client(clean_db, app_config, admin_key=self.KUNCI, require_verified=True)
        body = {"tipe": "katalog", "payload": [{"ptn_id": "a", "nama": "A", "provinsi": "Banten"}]}
        r = c.post("/api/v1/admin/ingest", json=body, headers={"X-Admin-Key": self.KUNCI})
        assert r.status_code == 422
        assert "REQUIRE_VERIFIED" in r.json()["error"]["detail"]["error"][0]["pesan"]
        body["payload"][0]["terakhir_diverifikasi"] = "2026-10-13"
        assert (
            c.post(
                "/api/v1/admin/ingest", json=body, headers={"X-Admin-Key": self.KUNCI}
            ).status_code
            == 200
        )

    def test_cache_refdata_dibuang_setelah_ingest(self, clean_db, app_config):
        app = create_app(make_settings(admin_key=self.KUNCI), app_config, clean_db)
        c = TestClient(app)
        with Session(clean_db) as db:
            ingest_direktori(db, SEED, tipe=["ketentuan", "rules"])
            assert app.state.refdata.get(db).tahun_siklus == 2026
            n_syarat = len(app.state.refdata.get(db).rules["SNBT"].syarat)
        assert n_syarat == 5
        payload = [r for r in baris("rule_gate.csv") if r["jalur"] == "SNBT"][:3]
        r = c.post(
            "/api/v1/admin/ingest",
            json={"tipe": "rules", "payload": payload},
            headers={"X-Admin-Key": self.KUNCI},
        )
        assert r.status_code == 200, r.text
        with Session(clean_db) as db:
            assert len(app.state.refdata.get(db).rules["SNBT"].syarat) == 3
