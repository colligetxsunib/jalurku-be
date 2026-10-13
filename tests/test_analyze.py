"""Task 7: POST /analyze (gate + penilaian SNBT): FR-T1 sampai T5, FR-S4 (override tanpa simpan)."""

from __future__ import annotations

import ast
import statistics
import time

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR
from app.db import models as m
from app.ingest.csv_io import baca_csv
from app.ingest.service import ingest
from tests.helpers import analyze, masuk, muat_persona, put_profil

pytestmark = pytest.mark.db

IK = "ui-ilmu-komputer"


def satu(r, indeks: int = 0) -> dict:
    assert r.status_code == 200, r.text
    return r.json()["hasil"][indeks]


def snapshot(engine: Engine, tabel: str = "profiles") -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(f"SELECT * FROM {tabel} ORDER BY 1"))]


def rasio_ui_snbt() -> list[float]:
    """Rasio peminat/daya tampung semua prodi UI berdata, dihitung mandiri dari CSV."""
    hasil = []
    for b in baca_csv(ROOT_DIR / "data" / "seed" / "prodi.csv"):
        if b["daya_tampung"] and b["peminat_tahun_lalu"]:
            hasil.append(int(b["peminat_tahun_lalu"]) / int(b["daya_tampung"]))
    return hasil


# ---------------------------- bentuk respons & kasus utama ----------------------------


def test_wajib_token(app_seed):
    r = app_seed.post("/api/v1/analyze", json={"targets": [{"prodi_id": IK, "jalur": ["SNBT"]}]})
    assert r.status_code == 401


def test_rani_snbt_gate_lolos_lalu_penilaian_indikatif(app_seed):
    h = muat_persona(app_seed, "rani")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))

    assert (hasil["prodi_id"], hasil["jalur"]) == (IK, "SNBT")
    assert hasil["gate"]["status"] == "lolos"
    statuses = {s["id"]: s["status"] for s in hasil["gate"]["syarat"]}
    assert statuses["SNBT-02"] == "tidak_berlaku" and statuses["SNBT-01"] == "lolos"

    p = hasil["penilaian"]
    assert (
        p["metode"] == "matriks_keketatan" and p["indikatif"] is True and p["label"] == "indikatif"
    )
    assert p["kategori"] in ("reach", "match", "safe")
    assert p["keyakinan"] == "rendah"  # tier dari rapor hanya proksi
    assert p["tier"]["sumber"] == "proksi_rapor"
    assert "bukan skor UTBK" in p["tier"]["peringatan"]
    assert p["pita"]["catatan_relatif"] == "relatif terhadap prodi yang ada di data"
    assert p["sel"]["kategori"] == p["kategori"]
    assert hasil["data_kurang"] == []
    assert hasil["prodi"] == {
        "nama": "Ilmu Komputer",
        "ptn_id": "ui",
        "ptn_nama": "Universitas Indonesia",
        "ptn_provinsi": "Jawa Barat",
        "jenjang": "S1",
        "program": "akademik",
    }


def test_batas_pita_dihitung_dari_sebaran_data_seed(app_seed):
    h = muat_persona(app_seed, "rani")
    basis = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))["penilaian"]["pita"][
        "basis"
    ]
    rasio = sorted(rasio_ui_snbt())
    q = statistics.quantiles(rasio, n=100, method="inclusive")
    assert basis["metode"] == "persentil" and basis["n_prodi"] == len(rasio) == 31
    assert basis["persentil"] == [33, 67]
    assert basis["batas_rasio"] == [pytest.approx(q[32], abs=0.01), pytest.approx(q[66], abs=0.01)]


def test_pita_dan_kategori_konsisten_dengan_rasio_prodi(app_seed):
    h = muat_persona(app_seed, "rani")
    p = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))["penilaian"]
    assert p["pita"]["rasio"] == pytest.approx(2132 / 75, abs=0.01)
    assert (p["pita"]["daya_tampung"], p["pita"]["peminat"], p["pita"]["tahun_peminat"]) == (
        75,
        2132,
        2025,
    )
    batas = p["pita"]["basis"]["batas_rasio"]
    harapan_pita = (
        "rendah"
        if p["pita"]["rasio"] < batas[0]
        else "sedang"
        if p["pita"]["rasio"] < batas[1]
        else "tinggi"
    )
    assert p["pita"]["nilai"] == harapan_pita
    assert any(
        "acuan siklus sebelumnya" in c for c in p["catatan"]
    )  # peminat 2025 untuk siklus 2026


def test_gate_gagal_penilaian_null_dan_tidak_meminta_data(app_seed):
    h = muat_persona(app_seed, "budi")  # lulus 2023
    hasil = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert hasil["gate"]["status"] == "tidak_memenuhi_syarat"
    gagal = [s for s in hasil["gate"]["syarat"] if s["status"] == "gagal"]
    assert [s["id"] for s in gagal] == ["SNBT-01"] and "lulusan lebih lama" in gagal[0]["alasan"]
    assert hasil["penilaian"] is None  # kategori peluang tidak dihitung
    assert hasil["data_kurang"] == []


def test_data_kurang_penilaian_null_dan_pertanyaan_dikembalikan(app_seed):
    h = muat_persona(app_seed, "sinta")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert hasil["gate"]["status"] == "data_kurang" and hasil["penilaian"] is None
    fields = {d["field"] for d in hasil["data_kurang"]}
    assert fields == {
        "wni_punya_nik",
        "lulus_snbp_3_tahun_terakhir",
        "sudah_ikut_utbk_tahun_siklus",
    }
    assert all(d["pertanyaan"].endswith("?") for d in hasil["data_kurang"])


def test_prodi_tanpa_data_belum_ada_acuan(app_seed):
    h = muat_persona(app_seed, "rani")
    for prodi in ("ui-dkv", "ugm-ilmu-komputer"):  # DKV UI kosong; PTN lain kosong
        p = satu(analyze(app_seed, h, [{"prodi_id": prodi, "jalur": ["SNBT"]}]))["penilaian"]
        assert p["kategori"] == "belum_ada_acuan"
        assert p["pita"] is None and p["sel"] is None
        assert "tidak menebak" in p["alasan"]


def test_vokasi_ui_dinilai_dan_membawa_jenjang(app_seed):
    h = muat_persona(app_seed, "rani")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": "ui-v-akuntansi-d3", "jalur": ["SNBT"]}]))
    assert hasil["prodi"]["jenjang"] == "D3" and hasil["prodi"]["program"] == "vokasi"
    assert hasil["penilaian"]["kategori"] in ("reach", "match", "safe")


def test_batas_tahun_lulus_lewat_api(app_seed):
    """Kasus tepi PRD: lulusan tepat di batas lolos; satu tahun lewat gugur dan penilaian null."""
    h = muat_persona(app_seed, "rani")
    di_batas = satu(
        analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], {"tahun_lulus": 2024})
    )
    assert di_batas["gate"]["status"] == "lolos" and di_batas["penilaian"] is not None
    lewat = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], {"tahun_lulus": 2023}))
    assert lewat["gate"]["status"] == "tidak_memenuhi_syarat" and lewat["penilaian"] is None


def test_banyak_target_urutan_dedupe_dan_jalur_snbp(app_seed):
    h = muat_persona(app_seed, "rani")
    r = analyze(
        app_seed,
        h,
        [
            {"prodi_id": "ui-akuntansi", "jalur": ["SNBT", "SNBP"]},
            {"prodi_id": IK, "jalur": ["SNBT"]},
            {"prodi_id": "ui-akuntansi", "jalur": ["SNBT"]},  # duplikat dilewati
        ],
    )
    assert r.status_code == 200
    urutan = [(x["prodi_id"], x["jalur"]) for x in r.json()["hasil"]]
    assert urutan == [("ui-akuntansi", "SNBT"), ("ui-akuntansi", "SNBP"), (IK, "SNBT")]


def test_snbp_target_mengikutsertakan_syarat_per_prodi(app_seed):
    h = muat_persona(app_seed, "dimas")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": "ui-teknik-industri", "jalur": ["SNBP"]}]))
    ids = [s["id"] for s in hasil["gate"]["syarat"]]
    assert "SNBP-08" in ids and hasil["gate"]["status"] == "lolos"  # Dimas sudah mengonfirmasi
    h2 = muat_persona(app_seed, "rani")  # Rani belum mengonfirmasi syarat prodi
    kurang = satu(analyze(app_seed, h2, [{"prodi_id": "ui-teknik-industri", "jalur": ["SNBP"]}]))
    assert kurang["gate"]["status"] == "data_kurang"
    assert [d["field"] for d in kurang["data_kurang"]] == [
        "konfirmasi_syarat_prodi.ui-teknik-industri"
    ]
    assert "Teknik Industri" in kurang["data_kurang"][0]["pertanyaan"]


def test_jalur_tidak_tercatat_dibuka_hanya_catatan_info(app_seed):
    h = muat_persona(app_seed, "dimas")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": "ui-teknik-industri", "jalur": ["SNBP"]}]))
    assert any("SNBP" in c and "belum mencatat" in c for c in hasil["catatan"])
    assert hasil["gate"]["status"] == "lolos"  # informasional: tidak memblokir


def test_deterministik_dan_cepat(app_seed):
    h = muat_persona(app_seed, "rani")
    targets = [
        {"prodi_id": p, "jalur": ["SNBT", "SNBP"]}
        for p in ("ui-ilmu-komputer", "ui-akuntansi", "ui-hukum", "ui-kedokteran")
    ]
    pertama = analyze(app_seed, h, targets)  # menghangatkan cache referensi
    t0 = time.perf_counter()
    kedua = analyze(app_seed, h, targets)
    durasi = time.perf_counter() - t0
    assert pertama.json() == kedua.json()
    assert durasi < 1.0, f"/analyze {durasi:.2f}s melebihi target 1 detik"


# ---------------------------- sumber & status verifikasi ----------------------------


def test_data_belum_diverifikasi_tetap_bertanda_di_respons(app_seed):
    h = muat_persona(app_seed, "rani")
    hasil = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert (
        hasil["status_verifikasi"] == "belum_diverifikasi"
        and hasil["terakhir_diverifikasi"] is None
    )
    jenis = {s["jenis"]: s for s in hasil["sumber_detail"]}
    assert set(jenis) == {"rules_gate", "keketatan"}
    assert all(s["status_verifikasi"] == "belum_diverifikasi" for s in jenis.values())
    assert any("files.snpmb.id" in u for u in hasil["sumber"])
    assert any("pintarly.id" in u for u in hasil["sumber"])  # sumber sekunder terlihat jelas


def test_terverifikasi_hanya_bila_semua_sumber_punya_tanggal(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    with Session(clean_db) as db:
        db.query(m.RulesJalur).filter_by(jalur="SNBT").update(
            {"terakhir_diverifikasi": "2026-10-12"}
        )
        db.commit()
    app_seed.app.state.refdata.invalidate()
    sebagian = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert sebagian["status_verifikasi"] == "belum_diverifikasi"  # data keketatan belum

    with Session(clean_db) as db:
        db.query(m.ProdiJalur).filter_by(prodi_id=IK).update(
            {"terakhir_diverifikasi": "2026-10-13"}
        )
        db.commit()
    penuh = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert penuh["status_verifikasi"] == "terverifikasi"
    assert penuh["terakhir_diverifikasi"] == "2026-10-12"  # tanggal terlama


# ---------------------------- acuan_skor otomatis aktif ----------------------------


def test_jalur_acuan_skor_aktif_bila_tabel_terisi(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    with Session(clean_db) as db:
        hasil = ingest(
            db,
            "acuan",
            [
                {
                    "prodi_id": IK,
                    "jalur": "SNBT",
                    "rendah": "660",
                    "tinggi": "720",
                    "tahun": "2025",
                    "sumber_url": "https://contoh.id/acuan",
                }
            ],
        )
        assert hasil.ok
    tanpa_skor = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))
    assert tanpa_skor["penilaian"]["kategori"] == "data_kurang"
    assert [d["field"] for d in tanpa_skor["data_kurang"]] == ["skor_tryout"]

    reach = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], {"skor_tryout": 620}))
    p = reach["penilaian"]
    assert (p["kategori"], p["gap"], p["metode"]) == ("reach", 40, "acuan_skor")
    assert p["acuan"] == {"rendah": 660, "tinggi": 720, "tahun": 2025}
    assert p["label"] == "acuan siklus sebelumnya" and p["indikatif"] is False
    assert {s["jenis"] for s in reach["sumber_detail"]} == {"rules_gate", "keketatan", "acuan_skor"}
    assert "https://contoh.id/acuan" in reach["sumber"]

    for skor, kategori in ((700, "match"), (720, "safe")):
        r = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], {"skor_tryout": skor}))
        assert r["penilaian"]["kategori"] == kategori


# ---------------------------- override (what-if) tidak menyimpan ----------------------------


def test_override_tidak_mengubah_baris_mana_pun_di_db(app_seed, clean_db):
    h = muat_persona(app_seed, "rani")
    sebelum = {
        t: snapshot(clean_db, t) for t in ("profiles", "sessions", "strategies", "query_logs")
    }
    override = {
        "skor_tryout": 650,
        "tahun_lulus": 2024,
        "nilai_rapor": {"semester_1": {"matematika": 10}, "semester_5": None},
        "peringkat_sekolah": 200,
        "minat": {"realistis": 0.1},
    }
    r = analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], override)
    assert r.status_code == 200, r.text
    sesudah = {t: snapshot(clean_db, t) for t in sebelum}
    assert sesudah == sebelum  # profil sebelum == sesudah, semua tabel sesi
    # dan GET /profile tetap menampilkan nilai asli
    asli = app_seed.get("/api/v1/profile", headers=h).json()["profil"]
    assert (
        asli["tahun_lulus"] == 2026
        and asli["peringkat_sekolah"] == 12
        and asli["skor_tryout"] is None
    )


def test_override_mengubah_hasil_dan_tier(app_seed):
    h = muat_persona(app_seed, "rani")
    asli = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}]))["penilaian"]
    jelek = {
        "nilai_rapor": {f"semester_{i}": {"matematika": 40, "fisika": 40} for i in range(1, 6)},
        "peringkat_sekolah": 290,
    }
    skenario = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], jelek))["penilaian"]
    assert asli["tier"]["nilai"] == "kuat" and skenario["tier"]["nilai"] == "lemah"
    assert skenario["kategori"] == "reach"


def test_override_diverifikasi_dengan_skema_sama(app_seed):
    h = muat_persona(app_seed, "rani")
    t = [{"prodi_id": IK, "jalur": ["SNBT"]}]
    for override, field in (
        ({"skor_tryout": "tinggi sekali"}, "override.skor_tryout"),
        ({"skor_tryout": 99999}, "skor_tryout"),
        (
            {"nilai_rapor": {"semester_1": {"matematika": 500}}},
            "override.nilai_rapor.semester_1.matematika",
        ),
        ({"nama": "Rani"}, "override.nama"),
        ({"tahun_lulus": 1990}, "tahun_lulus"),
    ):
        r = analyze(app_seed, h, t, override)
        assert r.status_code == 422, (override, r.text)
        assert field in [e["field"] for e in r.json()["error"]["detail"]["field"]]


def test_override_pada_sesi_tanpa_profil(app_seed):
    """What-if bisa dipakai tanpa menyimpan profil: override melengkapi data sementara."""
    h = masuk(app_seed)
    hasil = satu(analyze(app_seed, h, [{"prodi_id": IK, "jalur": ["SNBT"]}], {"tahun_lulus": 2026}))
    assert hasil["gate"]["status"] == "data_kurang"
    assert app_seed.get("/api/v1/profile", headers=h).json()["profil"]["tahun_lulus"] is None


# ---------------------------- validasi permintaan ----------------------------


def test_prodi_tidak_ada_404_dengan_daftar_lengkap(app_seed):
    h = muat_persona(app_seed, "rani")
    r = analyze(
        app_seed,
        h,
        [
            {"prodi_id": IK, "jalur": ["SNBT"]},
            {"prodi_id": "hantu-1", "jalur": ["SNBT"]},
            {"prodi_id": "hantu-2", "jalur": ["SNBP"]},
        ],
    )
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["kode"] == "prodi_tidak_ditemukan" and err["detail"]["prodi_id"] == [
        "hantu-1",
        "hantu-2",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"targets": []},
        {},
        {"targets": [{"prodi_id": IK, "jalur": []}]},
        {"targets": [{"prodi_id": IK, "jalur": ["MANDIRI"]}]},
        {"targets": [{"prodi_id": "", "jalur": ["SNBT"]}]},
        {"targets": [{"prodi_id": IK, "jalur": ["SNBT"]}], "hasil_analisis": "bohong"},
        {"targets": [{"prodi_id": IK, "jalur": ["SNBT"], "catatan": "x"}]},
    ],
)
def test_permintaan_tidak_valid_422(app_seed, body):
    h = muat_persona(app_seed, "rani")
    assert app_seed.post("/api/v1/analyze", json=body, headers=h).status_code == 422


# ---------------------------- keputusan tidak melibatkan LLM ----------------------------


def test_orkestrasi_analisis_tidak_mengimpor_llm():
    terlarang = ("app.llm", "app.rag", "google")
    for berkas in ("app/services/analisis.py", "app/api/v1/analyze.py"):
        pohon = ast.parse((ROOT_DIR / berkas).read_text(encoding="utf-8"))
        for node in ast.walk(pohon):
            nama = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            for n in nama:
                assert not n.startswith(terlarang), f"{berkas} meng-import {n}"


def test_put_profil_lalu_analyze_berurutan(app_seed):
    """Alur frontend: profil diisi bertahap, hasil analisis ikut berubah."""
    h = masuk(app_seed)
    put_profil(
        app_seed,
        h,
        tahun_lulus=2026,
        jenjang_sekolah="SMA",
        wni_punya_nik=True,
        lulus_snbp_3_tahun_terakhir=False,
        sudah_ikut_utbk_tahun_siklus=False,
    )
    t = [{"prodi_id": IK, "jalur": ["SNBT"]}]
    awal = satu(analyze(app_seed, h, t))
    assert awal["gate"]["status"] == "lolos"
    assert awal["penilaian"]["kategori"] == "data_kurang"  # gate lolos, rapor belum ada
    assert [d["field"] for d in awal["data_kurang"]] == ["nilai_rapor"]
    put_profil(app_seed, h, nilai_rapor={"semester_1": {"matematika": 90}})
    akhir = satu(analyze(app_seed, h, t))
    assert (
        akhir["penilaian"]["kategori"] in ("reach", "match", "safe") and akhir["data_kurang"] == []
    )
    assert "tren" in akhir["penilaian"]["tier"]["faktor_tidak_diketahui"]
