"""Golden set gate (PRD bagian 14): kasus tepi dan syarat resmi harus 100% sesuai harapan.

Harapan ada di config/golden/gate.json, ditulis dari pembacaan syarat resmi (bukan dari keluaran
mesin). Tes ini mengunci perilaku; kebenaran terhadap panduan resmi tetap perlu verifikasi manusia.
"""

from __future__ import annotations

import csv
import json

import pytest

from app.evaluasi import golden
from app.evaluasi.golden import KasusGate, jalankan_kasus_gate, muat_kasus_gate
from app.services import persona as modul_persona
from tests.helpers import SEED_DIR

KASUS = muat_kasus_gate()


def test_semua_kasus_gate_sesuai_harapan(app_seed):
    hasil = jalankan_kasus_gate(app_seed, KASUS)
    assert len(hasil) == len(KASUS)
    beda = [f"{h.id}: {h.detail}" for h in hasil if not h.ok]
    assert not beda, "Kasus gate tidak sesuai:\n" + "\n".join(beda)
    assert golden.ringkas_gate(hasil)["persen"] == 100.0


def test_kasus_berkas_valid_dan_unik():
    ids = [k.id for k in KASUS]
    assert len(ids) == len(set(ids)) >= 30


def test_lima_kasus_minimum_prd_ada():
    """PRD 14: batas tahun, satu tahun lewat, data_kurang rapor, gagal+data_kurang, semua terpenuhi."""
    peta = {k.id: k for k in KASUS}
    assert peta["GT-01"].harapan.gate == "lolos"  # tepat di batas
    assert (
        peta["GT-02"].harapan.gate == "tidak_memenuhi_syarat"
        and peta["GT-02"].harapan.penilaian == "null"
    )
    assert peta["GS-13"].harapan.gate == "data_kurang" and peta["GS-13"].jalur == "SNBP"
    assert peta["GT-03"].harapan.gate == "tidak_memenuhi_syarat"
    assert set(peta["GT-03"].harapan.syarat.values()) == {"gagal", "data_kurang"}
    assert peta["GT-05"].harapan.gate == "lolos" and peta["GT-05"].harapan.penilaian == "ada"


def test_setiap_syarat_resmi_punya_kasus_uji():
    """Tiap syarat di rule_gate.csv dirujuk setidaknya satu kasus (cakupan aturan)."""
    with (SEED_DIR / "rule_gate.csv").open(encoding="utf-8", newline="") as f:
        syarat = {r["syarat_id"] for r in csv.DictReader(f)}
    dirujuk = {sid for k in KASUS for sid in k.harapan.syarat}
    assert syarat <= dirujuk, f"syarat tanpa kasus uji: {sorted(syarat - dirujuk)}"


def test_kasus_merujuk_persona_prodi_dan_syarat_yang_ada():
    with (SEED_DIR / "prodi.csv").open(encoding="utf-8", newline="") as f:
        prodi = {r["prodi_id"] for r in csv.DictReader(f)}
    with (SEED_DIR / "rule_gate.csv").open(encoding="utf-8", newline="") as f:
        syarat = {(r["jalur"], r["syarat_id"]) for r in csv.DictReader(f)}
    tersedia = {p.id for p in modul_persona.muat_semua()}
    for k in KASUS:
        assert k.dasar in tersedia, k.id
        assert k.prodi_id in prodi, k.id
        for sid in k.harapan.syarat:
            assert (k.jalur, sid) in syarat, (k.id, sid)


def test_tanggal_verifikasi_tidak_pernah_terisi_otomatis():
    """Berkas yang dikirim tidak boleh terverifikasi tanpa penanggung jawab (diisi manusia)."""
    for k in KASUS:
        assert k.terverifikasi == bool(k.diverifikasi_oleh), k.id


def test_pelari_mendeteksi_harapan_yang_salah(app_seed):
    """Pelari tidak boleh lolos buta: harapan yang sengaja dibalik harus dilaporkan beda."""
    asli = next(k for k in KASUS if k.id == "GT-02")
    salah = KasusGate.model_validate(
        {**asli.model_dump(mode="json"), "harapan": {"gate": "lolos", "penilaian": "ada"}}
    )
    salah_syarat = KasusGate.model_validate(
        {
            **asli.model_dump(mode="json"),
            "harapan": {**asli.harapan.model_dump(), "syarat": {"SNBT-01": "lolos"}},
        }
    )
    hasil = jalankan_kasus_gate(app_seed, [salah, salah_syarat])
    assert [h.ok for h in hasil] == [False, False]
    assert "gate tidak_memenuhi_syarat (harapan lolos)" in hasil[0].detail
    assert "penilaian null (harapan ada)" in hasil[0].detail
    assert "SNBT-01 gagal (harapan lolos)" in hasil[1].detail


def test_pelari_melaporkan_prodi_tidak_ada_tanpa_melempar(app_seed):
    k = KasusGate.model_validate(
        {**KASUS[0].model_dump(mode="json"), "id": "X", "prodi_id": "tidak-ada"}
    )
    (h,) = jalankan_kasus_gate(app_seed, [k])
    assert not h.ok and "404" in h.detail


def test_pelari_menghapus_sesi_sementara(app_seed, clean_db):
    from sqlalchemy import text

    jalankan_kasus_gate(app_seed, KASUS[:3])
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sessions")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM profiles")).scalar() == 0


@pytest.mark.parametrize(
    "ubah, pesan",
    [
        ({"id": "GT-01"}, "id kasus ganda"),
        ({"override": {"nik": "1"}}, "override tidak valid"),
        ({"diverifikasi_oleh": "Tim Data"}, "harus diisi bersamaan"),
    ],
)
def test_berkas_golden_tidak_valid_ditolak(tmp_path, ubah, pesan):
    mentah = json.loads(golden.GOLDEN_GATE.read_text(encoding="utf-8"))
    mentah["kasus"][1] = {**mentah["kasus"][1], **ubah}
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(mentah), encoding="utf-8")
    with pytest.raises(golden.GoldenError, match=pesan):
        muat_kasus_gate(path)
