"""Task 4: mesin gate. Golden set gate (PRD 14) + batas tiap syarat + kemurnian modul domain."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.core.config import ROOT_DIR
from app.domain.expr import bandingkan, parse_nilai, validasi_syarat
from app.domain.fields import Target
from app.domain.gate import Rules, evaluasi_gate
from app.domain.ketentuan import Ketentuan, KetentuanHilang, RuleError
from app.ingest.csv_io import baca_csv
from app.ingest.rules import rules_dari_baris

SEED = ROOT_DIR / "data" / "seed"
PERSONA_DIR = ROOT_DIR / "config" / "personas"


@pytest.fixture(scope="module")
def ketentuan() -> Ketentuan:
    return Ketentuan.dari_baris(baca_csv(SEED / "config_ketentuan.csv"))


@pytest.fixture(scope="module")
def rules() -> dict[str, Rules]:
    daftar, galat = rules_dari_baris(baca_csv(SEED / "rule_gate.csv"))
    assert galat == []
    return {r.jalur: r for r in daftar}


def profil_lolos(**ubah) -> dict:
    """Profil dasar yang memenuhi SEMUA syarat SNBP dan SNBT siklus 2026."""
    dasar = {
        "tahun_lulus": 2026,
        "jenjang_sekolah": "SMA",
        "akreditasi_sekolah": "A",
        "pakai_erapor": True,
        "peringkat_sekolah": 10,
        "jumlah_siswa_angkatan": 100,
        "sekolah_punya_npsn": True,
        "sekolah_kurikulum_nasional": True,
        "punya_nilai_tka": True,
        "rapor_lengkap_di_pdss": True,
        "wni_punya_nik": True,
        "lulus_snbp_3_tahun_terakhir": False,
        "sudah_ikut_utbk_tahun_siklus": False,
    }
    dasar.update(ubah)
    return dasar


def status_syarat(hasil, sid: str) -> str:
    return next(s.status for s in hasil.syarat if s.id == sid)


# ---------- data nyata dari CSV ----------


def test_rule_gate_csv_terbaca_penuh(rules):
    assert set(rules) == {"SNBP", "SNBT"}
    assert [s.id for s in rules["SNBP"].syarat] == [f"SNBP-0{i}" for i in range(1, 9)]
    assert [s.id for s in rules["SNBT"].syarat] == [f"SNBT-0{i}" for i in range(1, 6)]
    # tanggal verifikasi sengaja kosong di CSV dan tidak pernah diisi otomatis
    assert rules["SNBP"].terakhir_diverifikasi is None
    assert rules["SNBT"].terakhir_diverifikasi is None


# ---------- 5 kasus uji minimum (PRD bagian 14) ----------


def test_kasus1_lulusan_tepat_di_batas_lolos(rules, ketentuan):
    h = evaluasi_gate(rules["SNBT"], profil_lolos(tahun_lulus=2024), ketentuan)  # 2026 - 2
    assert status_syarat(h, "SNBT-01") == "lolos"
    assert h.status == "lolos"


def test_kasus2_satu_tahun_lewat_batas_tidak_memenuhi_syarat(rules, ketentuan):
    h = evaluasi_gate(rules["SNBT"], profil_lolos(tahun_lulus=2023), ketentuan)
    assert status_syarat(h, "SNBT-01") == "gagal"
    assert h.status == "tidak_memenuhi_syarat"
    gagal = next(s for s in h.syarat if s.id == "SNBT-01")
    assert "lulusan lebih lama" in gagal.alasan


def test_kasus3_data_belum_lengkap_snbp_data_kurang(rules, ketentuan):
    h = evaluasi_gate(rules["SNBP"], profil_lolos(rapor_lengkap_di_pdss=None), ketentuan)
    assert h.status == "data_kurang"
    assert [d.field for d in h.data_kurang] == ["rapor_lengkap_di_pdss"]
    assert "PDSS" in h.data_kurang[0].pertanyaan


def test_kasus4_gagal_mengalahkan_data_kurang(rules, ketentuan):
    h = evaluasi_gate(
        rules["SNBP"], profil_lolos(tahun_lulus=2025, punya_nilai_tka=None), ketentuan
    )
    assert status_syarat(h, "SNBP-01") == "gagal"
    assert status_syarat(h, "SNBP-06") == "data_kurang"  # tetap tercatat per syarat
    assert h.status == "tidak_memenuhi_syarat"
    assert h.data_kurang == ()  # yang sudah pasti gugur tidak diminta mengisi data tambahan


def test_kasus5_semua_terpenuhi_lolos(rules, ketentuan):
    assert evaluasi_gate(rules["SNBP"], profil_lolos(), ketentuan).status == "lolos"
    assert evaluasi_gate(rules["SNBT"], profil_lolos(), ketentuan).status == "lolos"


# ---------- batas tiap syarat ----------


@pytest.mark.parametrize(
    "tahun,harapan", [(2026, "lolos"), (2025, "gagal"), (2023, "gagal"), (2027, "gagal")]
)
def test_snbp01_tahun_lulus_harus_sama_dengan_siklus(rules, ketentuan, tahun, harapan):
    h = evaluasi_gate(rules["SNBP"], profil_lolos(tahun_lulus=tahun), ketentuan)
    assert status_syarat(h, "SNBP-01") == harapan


@pytest.mark.parametrize(
    "jenjang,harapan",
    [("SMA", "lolos"), ("SMK", "lolos"), ("MA", "lolos"), ("Paket C", "gagal")],
)
def test_snbp02_jenjang(rules, ketentuan, jenjang, harapan):
    h = evaluasi_gate(rules["SNBP"], profil_lolos(jenjang_sekolah=jenjang), ketentuan)
    assert status_syarat(h, "SNBP-02") == harapan


@pytest.mark.parametrize(
    "sid,field",
    [
        ("SNBP-03", "sekolah_punya_npsn"),
        ("SNBP-04", "sekolah_kurikulum_nasional"),
        ("SNBP-06", "punya_nilai_tka"),
        ("SNBP-07", "rapor_lengkap_di_pdss"),
    ],
)
@pytest.mark.parametrize(
    "nilai,harapan", [(True, "lolos"), (False, "gagal"), (None, "data_kurang")]
)
def test_snbp_syarat_boolean(rules, ketentuan, sid, field, nilai, harapan):
    h = evaluasi_gate(rules["SNBP"], profil_lolos(**{field: nilai}), ketentuan)
    assert status_syarat(h, sid) == harapan


@pytest.mark.parametrize(
    "akreditasi,erapor,peringkat,jumlah,harapan",
    [
        ("A", True, 45, 100, "lolos"),  # kuota 40 + 5 = 45%, tepat di batas
        ("A", True, 46, 100, "gagal"),
        ("A", False, 40, 100, "lolos"),
        ("A", False, 41, 100, "gagal"),
        ("B", False, 25, 100, "lolos"),  # 25,0 <= 25
        ("B", False, 26, 100, "gagal"),
        ("B", True, 30, 100, "lolos"),  # 25 + 5
        ("C", False, 5, 100, "lolos"),
        ("C", False, 6, 100, "gagal"),
        ("tidak_terakreditasi", True, 10, 100, "lolos"),  # kelompok 'C dan lainnya': 5 + 5
        ("tidak_terakreditasi", True, 11, 100, "gagal"),
        ("B", False, 30, 120, "lolos"),  # 25,0 persis dari 30/120
        ("A", False, 1, 3, "lolos"),  # 33,33 <= 40
        ("B", False, 1, 3, "gagal"),  # 33,33 > 25
        ("B", True, 29, 97, "lolos"),  # 29*100/97 = 29,897 <= 30
        ("B", True, 30, 97, "gagal"),  # 30*100/97 = 30,928 > 30
    ],
)
def test_snbp05_kuota_sekolah(rules, ketentuan, akreditasi, erapor, peringkat, jumlah, harapan):
    p = profil_lolos(
        akreditasi_sekolah=akreditasi,
        pakai_erapor=erapor,
        peringkat_sekolah=peringkat,
        jumlah_siswa_angkatan=jumlah,
    )
    assert status_syarat(evaluasi_gate(rules["SNBP"], p, ketentuan), "SNBP-05") == harapan


@pytest.mark.parametrize(
    "ubah,diminta",
    [
        ({"peringkat_sekolah": None}, ["peringkat_sekolah"]),
        ({"jumlah_siswa_angkatan": None}, ["jumlah_siswa_angkatan"]),
        ({"akreditasi_sekolah": None}, ["akreditasi_sekolah"]),
        ({"pakai_erapor": None}, ["pakai_erapor"]),
        (
            {"peringkat_sekolah": None, "akreditasi_sekolah": None},
            ["peringkat_sekolah", "akreditasi_sekolah"],
        ),
    ],
)
def test_snbp05_data_kurang_menyebut_field_profil_bukan_turunan(rules, ketentuan, ubah, diminta):
    h = evaluasi_gate(rules["SNBP"], profil_lolos(**ubah), ketentuan)
    assert status_syarat(h, "SNBP-05") == "data_kurang"
    assert sorted(d.field for d in h.data_kurang) == sorted(diminta)


def test_snbp08_per_target(rules, ketentuan):
    target = Target("ui-dkv", "Desain Komunikasi Visual")
    # tanpa target, syarat per-prodi dilewati (7 syarat saja)
    tanpa = evaluasi_gate(rules["SNBP"], profil_lolos(), ketentuan)
    assert "SNBP-08" not in [s.id for s in tanpa.syarat]

    kurang = evaluasi_gate(rules["SNBP"], profil_lolos(), ketentuan, target)
    assert kurang.status == "data_kurang"
    assert kurang.data_kurang[0].field == "konfirmasi_syarat_prodi.ui-dkv"
    assert "Desain Komunikasi Visual" in kurang.data_kurang[0].pertanyaan

    ya = evaluasi_gate(
        rules["SNBP"], profil_lolos(konfirmasi_syarat_prodi={"ui-dkv": True}), ketentuan, target
    )
    assert ya.status == "lolos"
    tidak = evaluasi_gate(
        rules["SNBP"], profil_lolos(konfirmasi_syarat_prodi={"ui-dkv": False}), ketentuan, target
    )
    assert status_syarat(tidak, "SNBP-08") == "gagal"


@pytest.mark.parametrize(
    "tahun,harapan", [(2026, "lolos"), (2025, "lolos"), (2024, "lolos"), (2023, "gagal")]
)
def test_snbt01_batas_tahun_lulus(rules, ketentuan, tahun, harapan):
    h = evaluasi_gate(rules["SNBT"], profil_lolos(tahun_lulus=tahun), ketentuan)
    assert status_syarat(h, "SNBT-01") == harapan


@pytest.mark.parametrize(
    "jenjang,usia,harapan",
    [
        ("SMA", None, "tidak_berlaku"),  # null = bukan Paket C, syarat dilewati
        ("SMK", 30, "tidak_berlaku"),
        ("Paket C", 25, "lolos"),  # tepat di batas
        ("Paket C", 26, "gagal"),
        ("Paket C", None, "data_kurang"),
        (None, None, "data_kurang"),  # jenjang belum diketahui: jangan menebak
    ],
)
def test_snbt02_usia_paket_c(rules, ketentuan, jenjang, usia, harapan):
    p = profil_lolos(jenjang_sekolah=jenjang, paket_c_usia_per_1_juli=usia)
    assert status_syarat(evaluasi_gate(rules["SNBT"], p, ketentuan), "SNBT-02") == harapan


def test_snbt02_tidak_berlaku_dihitung_lolos(rules, ketentuan):
    h = evaluasi_gate(rules["SNBT"], profil_lolos(jenjang_sekolah="SMA"), ketentuan)
    assert status_syarat(h, "SNBT-02") == "tidak_berlaku"
    assert h.status == "lolos"


@pytest.mark.parametrize(
    "sid,field,nilai_lolos",
    [
        ("SNBT-03", "wni_punya_nik", True),
        ("SNBT-04", "lulus_snbp_3_tahun_terakhir", False),  # syarat: == false
        ("SNBT-05", "sudah_ikut_utbk_tahun_siklus", False),
    ],
)
def test_snbt_syarat_boolean(rules, ketentuan, sid, field, nilai_lolos):
    assert (
        status_syarat(
            evaluasi_gate(rules["SNBT"], profil_lolos(**{field: nilai_lolos}), ketentuan), sid
        )
        == "lolos"
    )
    assert (
        status_syarat(
            evaluasi_gate(rules["SNBT"], profil_lolos(**{field: not nilai_lolos}), ketentuan), sid
        )
        == "gagal"
    )
    assert (
        status_syarat(evaluasi_gate(rules["SNBT"], profil_lolos(**{field: None}), ketentuan), sid)
        == "data_kurang"
    )


def test_tahun_siklus_dari_rule_bukan_jam_server(rules, ketentuan):
    """Rule siklus 2027 memakai tahun 2027 walau jam server berbeda: tidak ada `now()` di gate."""
    from dataclasses import replace

    r2027 = replace(rules["SNBT"], tahun_siklus=2027)
    ketentuan_2027 = Ketentuan(
        {**ketentuan.item, **{(k, j, 2027): v for (k, j, _), v in ketentuan.item.items()}}
    )
    assert (
        status_syarat(
            evaluasi_gate(r2027, profil_lolos(tahun_lulus=2025), ketentuan_2027), "SNBT-01"
        )
        == "lolos"
    )
    assert (
        status_syarat(
            evaluasi_gate(r2027, profil_lolos(tahun_lulus=2024), ketentuan_2027), "SNBT-01"
        )
        == "gagal"
    )


def test_deterministik(rules, ketentuan):
    p = profil_lolos(punya_nilai_tka=None, tahun_lulus=2025)
    assert evaluasi_gate(rules["SNBP"], p, ketentuan) == evaluasi_gate(rules["SNBP"], p, ketentuan)


def test_ketentuan_hilang_adalah_error_data_bukan_gagal(rules):
    kosong = Ketentuan({})
    with pytest.raises(KetentuanHilang):
        evaluasi_gate(rules["SNBP"], profil_lolos(), kosong)


# ---------- evaluator ekspresi ----------


def test_parse_nilai():
    assert parse_nilai("tahun_siklus-2").offset == -2
    assert parse_nilai("tahun_siklus + 1").offset == 1
    assert parse_nilai("tahun_siklus").offset == 0
    assert parse_nilai("SMA|SMK|MA", "in").item == ("SMA", "SMK", "MA")
    assert parse_nilai("SMA", "in").item == ("SMA",)
    assert parse_nilai("true").nilai is True
    assert parse_nilai("25").nilai == 25
    assert parse_nilai("2.5").nilai == 2.5
    fn = parse_nilai("config:kuota_sekolah_persen(akreditasi_sekolah, pakai_erapor)")
    assert (fn.nama, fn.argumen) == ("kuota_sekolah_persen", ("akreditasi_sekolah", "pakai_erapor"))


def test_tidak_ada_eval_kode_berbahaya_hanya_jadi_string():
    # Sisi kanan tak dikenal diperlakukan sebagai string literal, tidak pernah dieksekusi.
    expr = parse_nilai("__import__('os').system('echo bahaya')")
    assert expr.nilai == "__import__('os').system('echo bahaya')"
    with pytest.raises(RuleError):
        parse_nilai("config:__import__(x)")


@pytest.mark.parametrize(
    "field,op,nilai,potongan_pesan",
    [
        ("tidak_ada", "==", "1", "tidak terdaftar"),
        ("tahun_lulus", "~=", "1", "tidak diizinkan"),
        ("tahun_lulus", "eval", "1", "tidak diizinkan"),
        ("jenjang_sekolah", "in", "SMA", None),  # 'in' dengan satu nilai diterima
        ("tahun_lulus", ">=", "abc", "numerik"),
        ("jenjang_sekolah", "<=", "5", "numerik"),
        ("tahun_lulus", ">=", "config:tidak_ada(x)", "tidak dikenal"),
        (
            "persentil_peringkat_sekolah",
            "<=",
            "config:kuota_sekolah_persen(akreditasi_sekolah)",
            "argumen",
        ),
        (
            "persentil_peringkat_sekolah",
            "<=",
            "config:kuota_sekolah_persen(a,b)",
            "bukan field profil",
        ),
        ("punya_nilai_tka", "==", "ya", "true/false"),
        ("tahun_lulus", "==", "A|B", "hanya untuk operator 'in'"),
    ],
)
def test_validasi_syarat(field, op, nilai, potongan_pesan):
    galat = validasi_syarat(field, op, nilai)
    if potongan_pesan is None:
        assert galat == []
    else:
        assert any(potongan_pesan in g for g in galat), galat


def test_bandingkan_menolak_tipe_campur():
    with pytest.raises(RuleError):
        bandingkan("==", True, 1)  # bool vs angka tidak boleh sama
    with pytest.raises(RuleError):
        bandingkan(">=", "2026", 2024)
    assert bandingkan("exists", 0, None) is True
    assert bandingkan("exists", None, None) is False
    assert bandingkan("!=", "a", "b") is True


# ---------- parser rule dari CSV ----------


def test_rules_dari_baris_mengumpulkan_error_per_baris():
    baris = [
        {
            "jalur": "SNBT",
            "tahun_siklus": "2026",
            "syarat_id": "A",
            "field": "tahun_lulus",
            "op": ">=",
            "nilai": "tahun_siklus-2",
            "alasan_gagal": "x",
        },
        {
            "jalur": "SNBT",
            "tahun_siklus": "2026",
            "syarat_id": "B",
            "field": "field_gaib",
            "op": "==",
            "nilai": "1",
            "alasan_gagal": "x",
        },
        {
            "jalur": "XYZ",
            "tahun_siklus": "2026",
            "syarat_id": "C",
            "field": "tahun_lulus",
            "op": "==",
            "nilai": "1",
            "alasan_gagal": "x",
        },
        {
            "jalur": "SNBT",
            "tahun_siklus": "2026",
            "syarat_id": "A",
            "field": "tahun_lulus",
            "op": ">=",
            "nilai": "1",
            "alasan_gagal": "x",
        },
        {
            "jalur": "SNBT",
            "tahun_siklus": "2026",
            "syarat_id": "D",
            "field": "tahun_lulus",
            "op": ">=",
            "nilai": "1",
            "alasan_gagal": "",
        },
        {
            "jalur": "SNBT",
            "tahun_siklus": "2026",
            "syarat_id": "E",
            "field": "tahun_lulus",
            "op": ">=",
            "nilai": "1",
            "alasan_gagal": "x",
            "terakhir_diverifikasi": "bukan-tanggal",
        },
    ]
    hasil, galat = rules_dari_baris(baris)
    assert [r.jalur for r in hasil] == ["SNBT"] and len(hasil[0].syarat) == 1
    assert [g.baris for g in galat] == [2, 3, 4, 5, 6]
    assert "tidak terdaftar" in galat[0].pesan
    assert "duplikat" in galat[2].pesan


def test_terakhir_diverifikasi_aturan_semua_syarat():
    dasar = {
        "jalur": "SNBT",
        "tahun_siklus": "2026",
        "field": "tahun_lulus",
        "op": ">=",
        "nilai": "1",
        "alasan_gagal": "x",
    }
    sebagian, _ = rules_dari_baris(
        [
            {**dasar, "syarat_id": "A", "terakhir_diverifikasi": "2026-10-13"},
            {**dasar, "syarat_id": "B", "terakhir_diverifikasi": ""},
        ]
    )
    assert sebagian[0].terakhir_diverifikasi is None  # satu belum diverifikasi -> rule belum
    semua, _ = rules_dari_baris(
        [
            {**dasar, "syarat_id": "A", "terakhir_diverifikasi": "2026-10-13"},
            {**dasar, "syarat_id": "B", "terakhir_diverifikasi": "2026-10-12"},
        ]
    )
    assert str(semua[0].terakhir_diverifikasi) == "2026-10-12"


# ---------- persona ----------


def _persona() -> list[Path]:
    return sorted(PERSONA_DIR.glob("*.json"))


@pytest.mark.parametrize("path", _persona(), ids=lambda p: p.stem)
def test_persona_gate_sesuai_harapan(path, rules, ketentuan):
    persona = json.loads(path.read_text(encoding="utf-8"))
    assert persona["fiktif"] is True
    assert persona["profil"].get("provinsi") == "Jawa Barat"  # sama dengan provinsi UI (sementara)
    for jalur, harapan in persona["harapan"]["gate"].items():
        h = evaluasi_gate(rules[jalur], persona["profil"], ketentuan)
        assert h.status == harapan, f"{path.stem} {jalur}"


def test_persona_tanpa_data_identitas():
    terlarang = {"nama", "email", "telepon", "kontak", "nik", "nisn", "alamat"}
    for path in _persona():
        persona = json.loads(path.read_text(encoding="utf-8"))
        assert not (terlarang & set(persona["profil"])), path.stem


# ---------- kemurnian modul domain (PRD 8.5) ----------


def test_modul_domain_tidak_mengimpor_llm_db_atau_web():
    terlarang = ("app.llm", "app.rag", "google", "sqlalchemy", "fastapi", "httpx", "requests")
    for berkas in (ROOT_DIR / "app" / "domain").glob("*.py"):
        pohon = ast.parse(berkas.read_text(encoding="utf-8"))
        for node in ast.walk(pohon):
            if isinstance(node, ast.Import):
                nama = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                nama = [node.module or ""]
            else:
                continue
            for n in nama:
                assert not n.startswith(terlarang), f"{berkas.name} meng-import {n}"
