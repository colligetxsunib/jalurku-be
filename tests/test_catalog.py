"""Task 9: katalog PTN dan prodi (FR-C1, FR-C2)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db import models as m
from app.ingest.service import ingest
from tests.helpers import masuk

pytestmark = pytest.mark.db


@pytest.fixture()
def katalog(app_seed):
    h = masuk(app_seed)

    def ambil(path: str, **params):
        return app_seed.get(f"/api/v1/catalog{path}", params=params, headers=h)

    ambil.client = app_seed
    ambil.headers = h
    return ambil


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------- akses ----------------------------


@pytest.mark.parametrize("path", ["/ptn", "/prodi", "/prodi/ui-ilmu-komputer"])
def test_wajib_token(app_seed, path):
    assert app_seed.get(f"/api/v1/catalog{path}").status_code == 401


# ---------------------------- PTN ----------------------------


def test_daftar_ptn(katalog):
    d = ok(katalog("/ptn"))
    assert d["total"] == 10 and d["total_halaman"] == 1
    peta = {p["id"]: p for p in d["items"]}
    assert set(peta) == {"ui", "ugm", "itb", "unair", "ipb", "ub", "its", "unhas", "undip", "uns"}
    assert peta["ui"]["jumlah_prodi"] == 32 and peta["ugm"]["jumlah_prodi"] == 17
    assert peta["ui"]["provinsi"] == "Jawa Barat"
    assert [p["nama"] for p in d["items"]] == sorted(p["nama"] for p in d["items"])


def test_ptn_filter_provinsi_dan_nama(katalog):
    jatim = ok(katalog("/ptn", provinsi="jawa timur"))  # tidak peka huruf besar/kecil
    assert {p["id"] for p in jatim["items"]} == {"unair", "ub", "its"}
    assert [p["id"] for p in ok(katalog("/ptn", q="gadjah"))["items"]] == ["ugm"]
    assert ok(katalog("/ptn", q="tidak-ada"))["total"] == 0


def test_ptn_provinsi_tidak_baku_422(katalog):
    r = katalog("/ptn", provinsi="Narnia")
    assert r.status_code == 422
    assert r.json()["error"]["detail"]["field"][0]["field"] == "provinsi"


# ---------------------------- daftar prodi: paginasi ----------------------------


def test_paginasi_prodi(katalog):
    p1 = ok(katalog("/prodi", limit=20))
    assert (p1["total"], p1["page"], p1["limit"], p1["total_halaman"]) == (185, 1, 20, 10)
    assert len(p1["items"]) == 20
    p10 = ok(katalog("/prodi", limit=20, page=10))
    assert len(p10["items"]) == 5
    assert ok(katalog("/prodi", limit=20, page=11))["items"] == []
    # urutan stabil dan tanpa duplikat lintas halaman
    ids = [
        x["id"] for pg in range(1, 11) for x in ok(katalog("/prodi", limit=20, page=pg))["items"]
    ]
    assert len(ids) == len(set(ids)) == 185
    assert ids == [
        x["id"] for pg in range(1, 11) for x in ok(katalog("/prodi", limit=20, page=pg))["items"]
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"page": "a"},
        {"jalur": "MANDIRI"},
        {"program": "magister"},
        {"jenjang": "S2"},
    ],
)
def test_parameter_tidak_valid_422(katalog, params):
    assert katalog("/prodi", **params).status_code == 422


def test_item_daftar_prodi(katalog):
    item = ok(katalog("/prodi", q="Ilmu Komputer", ptn_id="ui"))["items"][0]
    assert item == {
        "id": "ui-ilmu-komputer",
        "nama": "Ilmu Komputer",
        "ptn": {"id": "ui", "nama": "Universitas Indonesia", "provinsi": "Jawa Barat"},
        "rumpun": "Teknologi Informasi",
        "jenjang": "S1",
        "program": "akademik",
        "akreditasi": None,
        "jalur_dibuka": ["SNBT"],
        "punya_data_keketatan": True,
        "status_verifikasi": "belum_diverifikasi",
    }


# ---------------------------- daftar prodi: filter ----------------------------


def test_filter_nama_tidak_peka_huruf_besar(katalog):
    d = ok(katalog("/prodi", q="TEKNIK", limit=100))
    assert d["total"] > 0 and all("teknik" in x["nama"].lower() for x in d["items"])
    assert ok(katalog("/prodi", q="teknik", limit=100))["total"] == d["total"]


def test_karakter_wildcard_pengguna_diperlakukan_sebagai_teks(katalog):
    assert ok(katalog("/prodi", q="%"))["total"] == 0
    assert ok(katalog("/prodi", q="_"))["total"] == 0
    assert ok(katalog("/prodi", q="Teknik_Sipil"))["total"] == 0  # '_' bukan wildcard


def test_filter_rumpun(katalog):
    d = ok(katalog("/prodi", rumpun="kesehatan", limit=100))
    assert d["total"] > 0 and all(x["rumpun"] == "Kesehatan" for x in d["items"])


def test_filter_provinsi(katalog):
    assert ok(katalog("/prodi", provinsi="Jawa Barat"))["total"] == 32 + 17 + 17  # UI + ITB + IPB
    assert ok(katalog("/prodi", provinsi="DI Yogyakarta"))["total"] == 17
    assert ok(katalog("/prodi", provinsi="Bali"))["total"] == 0


def test_filter_jalur_hanya_prodi_yang_tercatat_membuka_jalur_itu(katalog):
    assert ok(katalog("/prodi", jalur="SNBT"))["total"] == 31
    assert ok(katalog("/prodi", jalur="SNBP"))["total"] == 0  # seed belum mencatat SNBP


def test_filter_program_jenjang_dan_ptn(katalog):
    assert ok(katalog("/prodi", program="vokasi"))["total"] == 15
    assert ok(katalog("/prodi", jenjang="D3"))["total"] == 9
    assert ok(katalog("/prodi", jenjang="D4"))["total"] == 6
    assert ok(katalog("/prodi", ptn_id="ugm"))["total"] == 17
    d = ok(katalog("/prodi", program="vokasi", q="akuntansi"))
    assert [x["id"] for x in d["items"]] == ["ui-v-akuntansi-d3"]


def test_filter_digabung(katalog):
    d = ok(katalog("/prodi", provinsi="Jawa Barat", rumpun="Teknik", jalur="SNBT", limit=100))
    assert d["total"] > 0
    assert all(x["ptn"]["id"] == "ui" and x["rumpun"] == "Teknik" for x in d["items"])


# ---------------------------- detail prodi ----------------------------


def test_detail_prodi_dengan_data_keketatan_tanpa_acuan(katalog):
    d = ok(katalog("/prodi/ui-ilmu-komputer"))
    assert d["nama"] == "Ilmu Komputer" and d["ptn"]["nama"] == "Universitas Indonesia"
    assert d["jalur_dibuka"] == ["SNBT"]
    assert d["acuan"] is None and d["status_acuan"] == "belum_ada_acuan"  # bukan nilai tebakan
    snbt = d["keketatan"]["SNBT"]
    assert (snbt["daya_tampung"], snbt["peminat"], snbt["tahun_peminat"], snbt["tahun_siklus"]) == (
        75,
        2132,
        2025,
        2026,
    )
    assert snbt["rasio_peminat_per_kursi"] == pytest.approx(28.43, abs=0.01)
    assert (
        snbt["status_verifikasi"] == "belum_diverifikasi" and snbt["terakhir_diverifikasi"] is None
    )
    assert "pintarly.id" in snbt["sumber_url"]  # sumber sekunder terlihat jelas
    assert d["status_keketatan"] == "ada"
    assert (
        d["mapel_penentu"] is None and d["akreditasi"] is None
    )  # belum ada datanya: null, bukan tebakan


def test_detail_prodi_tanpa_data_apa_pun(katalog):
    for pid in ("ui-dkv", "ugm-hukum"):
        d = ok(katalog(f"/prodi/{pid}"))
        assert d["keketatan"] == {} and d["status_keketatan"] == "belum_ada_data"
        assert d["acuan"] is None and d["status_acuan"] == "belum_ada_acuan"
        assert d["jalur_dibuka"] is None and d["sumber_url"] is None


def test_detail_prodi_vokasi(katalog):
    d = ok(katalog("/prodi/ui-v-fisioterapi"))
    assert (d["jenjang"], d["program"], d["rumpun"]) == ("D4", "vokasi", "Kesehatan")


def test_detail_dengan_acuan_skor_berlabel_siklus_sebelumnya(app_seed, katalog):
    with Session(app_seed.app.state.engine) as db:
        assert ingest(
            db,
            "acuan",
            [
                {
                    "prodi_id": "ui-ilmu-komputer",
                    "jalur": "SNBT",
                    "rendah": "660",
                    "tinggi": "720",
                    "tahun": "2025",
                    "sumber_url": "https://contoh.id/a",
                    "terakhir_diverifikasi": "2026-10-12",
                }
            ],
        ).ok
    d = ok(katalog("/prodi/ui-ilmu-komputer"))
    assert d["status_acuan"] == "ada"
    assert d["acuan"]["SNBT"] == {
        "rendah": 660.0,
        "tinggi": 720.0,
        "tahun": 2025,
        "label": "acuan siklus sebelumnya",
        "sumber_url": "https://contoh.id/a",
        "terakhir_diverifikasi": "2026-10-12",
        "status_verifikasi": "terverifikasi",
    }


def test_detail_menampilkan_status_terverifikasi_setelah_diverifikasi(app_seed, katalog):
    with Session(app_seed.app.state.engine) as db:
        db.query(m.Prodi).filter_by(id="ui-ilmu-komputer").update(
            {"terakhir_diverifikasi": "2026-10-13"}
        )
        db.commit()
    d = ok(katalog("/prodi/ui-ilmu-komputer"))
    assert d["status_verifikasi"] == "terverifikasi" and d["terakhir_diverifikasi"] == "2026-10-13"


def test_detail_tidak_ada_404(katalog):
    r = katalog("/prodi/tidak-ada")
    assert r.status_code == 404
    assert r.json()["error"]["kode"] == "prodi_tidak_ditemukan"
    assert r.json()["error"]["detail"] == {"prodi_id": ["tidak-ada"]}
