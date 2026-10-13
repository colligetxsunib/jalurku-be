"""Task 6: profil (FR-P1 sampai P4, kriteria penerimaan 7.2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import models as m
from app.domain.profil import (
    PROFIL_FIELDS,
    AturanProfil,
    gabung_profil,
    profil_kosong,
    rapor_ada,
    validasi_profil,
)
from app.schemas.profile import ProfilePatch
from tests.helpers import PERSONA_DIR, masuk, persona
from tests.helpers import put_profil as put

ATURAN = AturanProfil(
    tahun_siklus=2026,
    tahun_lulus_mundur=15,
    tahun_lulus_maju=1,
    skor_tryout_min=0,
    skor_tryout_maks=1000,
    paket_c_usia_min=10,
    paket_c_usia_maks=70,
    dimensi_minat=("realistis", "investigatif"),
)


# ---------------------------- gabung_profil (murni) ----------------------------


def test_gabung_hanya_mengubah_field_yang_dikirim():
    dasar = {**profil_kosong(), "tahun_lulus": 2026, "provinsi": "Jawa Barat"}
    hasil = gabung_profil(dasar, {"provinsi": "Banten"})
    assert hasil["provinsi"] == "Banten"
    assert hasil["tahun_lulus"] == 2026  # tidak dikirim = tidak berubah


def test_gabung_null_eksplisit_menghapus_nilai():
    dasar = {**profil_kosong(), "tahun_lulus": 2026, "punya_nilai_tka": True}
    hasil = gabung_profil(dasar, {"tahun_lulus": None})
    assert hasil["tahun_lulus"] is None and hasil["punya_nilai_tka"] is True


def test_gabung_false_bukan_null():
    hasil = gabung_profil(profil_kosong(), {"punya_nilai_tka": False})
    assert hasil["punya_nilai_tka"] is False


def test_gabung_nilai_rapor_per_semester_dan_mapel():
    p = gabung_profil(
        profil_kosong(), {"nilai_rapor": {"semester_1": {"matematika": 85, "fisika": 80}}}
    )
    p = gabung_profil(p, {"nilai_rapor": {"semester_2": {"matematika": 70}}})
    assert p["nilai_rapor"] == {
        "semester_1": {"matematika": 85, "fisika": 80},
        "semester_2": {"matematika": 70},
    }
    p = gabung_profil(p, {"nilai_rapor": {"semester_1": {"fisika": None, "kimia": 75}}})
    assert p["nilai_rapor"]["semester_1"] == {"matematika": 85, "kimia": 75}
    p = gabung_profil(p, {"nilai_rapor": {"semester_2": None}})
    assert list(p["nilai_rapor"]) == ["semester_1"]
    p = gabung_profil(p, {"nilai_rapor": {"semester_1": {"matematika": None, "kimia": None}}})
    assert p["nilai_rapor"] is None  # semua kosong -> field kosong
    assert (
        gabung_profil(
            {**profil_kosong(), "nilai_rapor": {"semester_1": {"a": 1}}}, {"nilai_rapor": None}
        )["nilai_rapor"]
        is None
    )


def test_gabung_dict_dangkal():
    p = gabung_profil(profil_kosong(), {"minat": {"realistis": 0.5, "investigatif": 0.9}})
    p = gabung_profil(p, {"minat": {"realistis": None}})
    assert p["minat"] == {"investigatif": 0.9}
    assert gabung_profil(p, {"minat": {}})["minat"] == {"investigatif": 0.9}  # {} = tanpa perubahan


def test_gabung_tidak_mengubah_argumen_dan_menolak_field_asing():
    dasar = {**profil_kosong(), "nilai_rapor": {"semester_1": {"matematika": 80}}}
    gabung_profil(dasar, {"nilai_rapor": {"semester_1": {"matematika": 99}}})
    assert dasar["nilai_rapor"]["semester_1"]["matematika"] == 80
    with pytest.raises(ValueError, match="tidak dikenal"):
        gabung_profil(profil_kosong(), {"nama": "Budi"})


def test_rapor_ada():
    assert not rapor_ada(profil_kosong())
    assert not rapor_ada({"nilai_rapor": {"semester_1": {}}})
    assert rapor_ada({"nilai_rapor": {"semester_1": {"matematika": 80}}})


# ---------------------------- validasi lintas-field (murni) ----------------------------


@pytest.mark.parametrize(
    "ubah,field",
    [
        ({"tahun_lulus": 1990}, "tahun_lulus"),
        ({"tahun_lulus": 2028}, "tahun_lulus"),
        ({"peringkat_sekolah": 50, "jumlah_siswa_angkatan": 40}, "peringkat_sekolah"),
        ({"skor_tryout": 5000}, "skor_tryout"),
        ({"skor_tryout": -1}, "skor_tryout"),
        ({"paket_c_usia_per_1_juli": 5}, "paket_c_usia_per_1_juli"),
        ({"minat": {"astronomi": 0.5}}, "minat"),
    ],
)
def test_validasi_profil_menolak(ubah, field):
    galat = validasi_profil({**profil_kosong(), **ubah}, ATURAN)
    assert field in [f for f, _ in galat], galat


@pytest.mark.parametrize(
    "ubah",
    [
        {"tahun_lulus": 2026},
        {"tahun_lulus": 2027},  # satu tahun ke depan masih wajar
        {"tahun_lulus": 2011},  # batas bawah: 2026 - 15
        {"peringkat_sekolah": 40, "jumlah_siswa_angkatan": 40},
        {"skor_tryout": 0},
        {"skor_tryout": 1000},
        {"minat": {"realistis": 0.5}},
    ],
)
def test_validasi_profil_menerima_batas(ubah):
    assert validasi_profil({**profil_kosong(), **ubah}, ATURAN) == []


# ---------------------------- skema (statis) ----------------------------


def test_skema_tanpa_field_identitas():
    terlarang = {"nama", "email", "telepon", "kontak", "nik", "nisn", "alamat", "no_hp", "nomor_hp"}
    assert not (terlarang & set(ProfilePatch.model_fields))
    assert set(ProfilePatch.model_fields) == set(PROFIL_FIELDS)  # skema = daftar domain


@pytest.mark.parametrize("nama", sorted(p.stem for p in PERSONA_DIR.glob("*.json")))
def test_profil_persona_sah_menurut_skema(nama):
    ProfilePatch.model_validate(persona(nama)["profil"])


def test_provinsi_dinormalisasi():
    assert ProfilePatch(provinsi="jawa  barat").provinsi == "Jawa Barat"


# ---------------------------- API ----------------------------


def fields_error(r) -> list[str]:
    return [e["field"] for e in r.json()["error"]["detail"]["field"]]


@pytest.mark.db
class TestProfilAPI:
    def test_wajib_token(self, app_seed):
        assert app_seed.get("/api/v1/profile").status_code == 401
        assert app_seed.put("/api/v1/profile", json={}).status_code == 401

    def test_get_profil_baru_kosong_dengan_data_kurang(self, app_seed):
        h = masuk(app_seed)
        r = app_seed.get("/api/v1/profile", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert set(body["profil"]) == set(PROFIL_FIELDS)
        assert all(v is None for v in body["profil"].values())
        assert set(body["data_kurang"]) == {"SNBP", "SNBT"}
        assert {
            "tahun_lulus",
            "jenjang_sekolah",
            "punya_nilai_tka",
            "peringkat_sekolah",
            "jumlah_siswa_angkatan",
            "akreditasi_sekolah",
            "pakai_erapor",
            "nilai_rapor",
        } <= set(body["data_kurang"]["SNBP"])
        assert {
            "tahun_lulus",
            "wni_punya_nik",
            "lulus_snbp_3_tahun_terakhir",
            "sudah_ikut_utbk_tahun_siklus",
            "nilai_rapor",
        } <= set(body["data_kurang"]["SNBT"])
        # tiap field yang diminta punya pertanyaan untuk siswa
        semua = set(body["data_kurang"]["SNBP"]) | set(body["data_kurang"]["SNBT"])
        assert semua <= set(body["pertanyaan"])
        assert "TKA" in body["pertanyaan"]["punya_nilai_tka"]

    def test_put_parsial_hanya_mengubah_field_yang_dikirim(self, app_seed, clean_db):
        h = masuk(app_seed)
        r = put(app_seed, h, tahun_lulus=2026, provinsi="Jawa Barat", akreditasi_sekolah="A")
        assert r.status_code == 200
        r = put(app_seed, h, akreditasi_sekolah="B")  # hanya satu field
        profil = r.json()["profil"]
        assert (profil["tahun_lulus"], profil["provinsi"], profil["akreditasi_sekolah"]) == (
            2026,
            "Jawa Barat",
            "B",
        )
        sesi_id = app_seed.get("/api/v1/session", headers=h)
        assert sesi_id.status_code == 200
        with Session(clean_db) as db:
            baris = db.query(m.Profil).one()
            assert (baris.tahun_lulus, baris.provinsi, baris.akreditasi_sekolah) == (
                2026,
                "Jawa Barat",
                "B",
            )

    def test_put_null_eksplisit_menghapus_nilai(self, app_seed, clean_db):
        h = masuk(app_seed)
        put(app_seed, h, tahun_lulus=2026, punya_nilai_tka=True)
        r = put(app_seed, h, tahun_lulus=None)
        assert r.json()["profil"]["tahun_lulus"] is None
        assert r.json()["profil"]["punya_nilai_tka"] is True
        with Session(clean_db) as db:
            assert db.query(m.Profil).one().tahun_lulus is None

    def test_put_false_disimpan_sebagai_false(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, punya_nilai_tka=False)
        assert r.json()["profil"]["punya_nilai_tka"] is False

    def test_put_kosong_tidak_mengubah_apa_pun(self, app_seed):
        h = masuk(app_seed)
        put(app_seed, h, tahun_lulus=2026)
        r = put(app_seed, h)
        assert r.status_code == 200 and r.json()["profil"]["tahun_lulus"] == 2026

    def test_nilai_rapor_bertahap(self, app_seed):
        h = masuk(app_seed)
        put(app_seed, h, nilai_rapor={"semester_1": {"matematika": 85, "fisika": 80}})
        r = put(app_seed, h, nilai_rapor={"semester_2": {"matematika": 88}})
        assert r.json()["profil"]["nilai_rapor"] == {
            "semester_1": {"matematika": 85.0, "fisika": 80.0},
            "semester_2": {"matematika": 88.0},
        }
        r = put(app_seed, h, nilai_rapor=None)
        assert r.json()["profil"]["nilai_rapor"] is None

    @pytest.mark.parametrize(
        "body,field",
        [
            (
                {"nilai_rapor": {"semester_1": {"matematika": 150}}},
                "nilai_rapor.semester_1.matematika",
            ),
            (
                {"nilai_rapor": {"semester_1": {"matematika": -1}}},
                "nilai_rapor.semester_1.matematika",
            ),
            ({"nilai_rapor": {"semester_9": {"matematika": 80}}}, "nilai_rapor.semester_9"),
            (
                {"nilai_rapor": {"semester_1": {"Matematika Wajib": 80}}},
                "nilai_rapor.semester_1.Matematika Wajib",
            ),
            ({"provinsi": "Narnia"}, "provinsi"),
            ({"tahun_lulus": 1990}, "tahun_lulus"),
            ({"tahun_lulus": 2035}, "tahun_lulus"),
            ({"jenjang_sekolah": "Universitas"}, "jenjang_sekolah"),
            ({"akreditasi_sekolah": "Z"}, "akreditasi_sekolah"),
            ({"peringkat_sekolah": 0}, "peringkat_sekolah"),
            ({"peringkat_sekolah": 50, "jumlah_siswa_angkatan": 40}, "peringkat_sekolah"),
            ({"skor_tryout": 5000}, "skor_tryout"),
            ({"minat": {"astronomi": 0.5}}, "minat"),
            ({"minat": {"realistis": 1.5}}, "minat.realistis"),
            ({"alumni_info": {"ui-ilmu-komputer": "mungkin"}}, "alumni_info.ui-ilmu-komputer"),
            ({"konfirmasi_syarat_prodi": {"prodi-hantu": True}}, "konfirmasi_syarat_prodi"),
            ({"punya_nilai_tka": "mungkin"}, "punya_nilai_tka"),
        ],
    )
    def test_nilai_tidak_valid_422_per_field(self, app_seed, body, field):
        h = masuk(app_seed)
        r = put(app_seed, h, **body)
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["kode"] == "validasi_gagal"
        assert field in fields_error(r)

    @pytest.mark.parametrize(
        "field", ["nama", "email", "telepon", "nik", "nisn", "alamat", "kontak"]
    )
    def test_field_identitas_ditolak(self, app_seed, field):
        h = masuk(app_seed)
        r = put(app_seed, h, **{field: "rahasia"})
        assert r.status_code == 422
        assert field in fields_error(r)
        assert "rahasia" not in r.text  # nilai input tidak dipantulkan

    def test_gagal_validasi_tidak_menyimpan_apa_pun(self, app_seed, clean_db):
        h = masuk(app_seed)
        r = put(app_seed, h, tahun_lulus=2026, provinsi="Narnia")
        assert r.status_code == 422
        with Session(clean_db) as db:
            assert db.query(m.Profil).count() == 0

    def test_error_peringkat_hanya_bila_field_terkait_diubah(self, app_seed, clean_db):
        h = masuk(app_seed)
        put(app_seed, h, peringkat_sekolah=10, jumlah_siswa_angkatan=100)
        assert put(app_seed, h, jumlah_siswa_angkatan=5).status_code == 422  # 10 > 5
        assert put(app_seed, h, tahun_lulus=2026).status_code == 200

    def test_konfirmasi_prodi_valid(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, konfirmasi_syarat_prodi={"ui-dkv": True})
        assert r.status_code == 200
        assert r.json()["profil"]["konfirmasi_syarat_prodi"] == {"ui-dkv": True}

    def test_profil_antar_sesi_terpisah(self, app_seed):
        a, b = masuk(app_seed), masuk(app_seed)
        put(app_seed, a, tahun_lulus=2026)
        assert app_seed.get("/api/v1/profile", headers=b).json()["profil"]["tahun_lulus"] is None

    def test_hapus_sesi_menghapus_profil(self, app_seed, clean_db):
        h = masuk(app_seed)
        put(app_seed, h, tahun_lulus=2026)
        assert app_seed.delete("/api/v1/session", headers=h).status_code == 204
        with Session(clean_db) as db:
            assert db.query(m.Profil).count() == 0

    # --- data_kurang per jalur memakai gate nyata ---

    def test_persona_rani_lengkap_tidak_ada_data_kurang(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, **persona("rani")["profil"])
        assert r.status_code == 200, r.text
        assert r.json()["data_kurang"] == {"SNBP": [], "SNBT": []}
        assert r.json()["profil"]["peringkat_sekolah"] == 12
        assert r.json()["profil"]["alumni_info"] is None  # {} = tanpa isi

    def test_persona_dimas_lengkap(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, **persona("dimas")["profil"])
        assert r.json()["data_kurang"] == {"SNBP": [], "SNBT": []}
        assert r.json()["profil"]["konfirmasi_syarat_prodi"]["ui-teknik-industri"] is True

    def test_persona_budi_pasti_gugur_tidak_diminta_data_tambahan(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, **persona("budi")["profil"])
        assert r.status_code == 200, r.text
        assert r.json()["data_kurang"] == {"SNBP": [], "SNBT": []}

    def test_persona_sinta_data_kurang_menyusut_saat_diisi(self, app_seed):
        h = masuk(app_seed)
        r = put(app_seed, h, **persona("sinta")["profil"])
        kurang = r.json()["data_kurang"]
        assert "punya_nilai_tka" in kurang["SNBP"] and "nilai_rapor" in kurang["SNBP"]
        assert "tahun_lulus" not in kurang["SNBP"] and "sekolah_punya_npsn" not in kurang["SNBP"]
        assert set(kurang["SNBT"]) == {
            "wni_punya_nik",
            "lulus_snbp_3_tahun_terakhir",
            "sudah_ikut_utbk_tahun_siklus",
            "nilai_rapor",
        }

        r = put(
            app_seed,
            h,
            wni_punya_nik=True,
            lulus_snbp_3_tahun_terakhir=False,
            sudah_ikut_utbk_tahun_siklus=False,
        )
        assert r.json()["data_kurang"]["SNBT"] == ["nilai_rapor"]
        r = put(app_seed, h, nilai_rapor={"semester_1": {"matematika": 80}})
        assert r.json()["data_kurang"]["SNBT"] == []

    def test_paket_c_meminta_usia(self, app_seed):
        h = masuk(app_seed)
        base = {**persona("rani")["profil"], "jenjang_sekolah": "Paket C"}
        r = put(app_seed, h, **base)
        assert r.json()["data_kurang"]["SNBT"] == ["paket_c_usia_per_1_juli"]
        assert (
            r.json()["data_kurang"]["SNBP"] == []
        )  # SNBP-02: Paket C gagal -> tidak diminta data lagi


@pytest.mark.db
def test_503_bila_data_referensi_belum_dimuat(client: TestClient):
    h = masuk(client)  # DB kosong: tanpa ketentuan/rules
    r = client.get("/api/v1/profile", headers=h)
    assert r.status_code == 503
    assert r.json()["error"]["kode"] == "ketentuan_belum_dimuat"
