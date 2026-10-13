"""Task 18: skor kecocokan eksplorasi jurusan (fungsi murni, PRD 8.3)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domain.match import (
    alasan_template,
    dimensi_teratas,
    gabung_kecocokan,
    kemiripan_cosine,
    kesesuaian_nilai,
    mapel_terbaik,
)

# ------------------------------------------------------------------ cosine


def test_cosine_identik_orthogonal_dan_sebagian():
    a = {"realistis": 1.0, "investigatif": 1.0}
    assert kemiripan_cosine(a, a) == pytest.approx(1.0)
    assert kemiripan_cosine({"artistik": 1.0}, {"realistis": 1.0}) == 0.0
    # (1*1) / (sqrt(2) * 1)
    assert kemiripan_cosine(a, {"realistis": 1.0}) == pytest.approx(2**-0.5)


def test_cosine_tak_bergantung_skala():
    assert kemiripan_cosine({"a": 1, "b": 2}, {"a": 10, "b": 20}) == pytest.approx(1.0)


def test_cosine_vektor_nol_tidak_dihitung():
    assert kemiripan_cosine({}, {"a": 1}) is None
    assert kemiripan_cosine({"a": 0.0}, {"a": 1}) is None
    assert kemiripan_cosine({"a": 1}, {"a": 0.0}) is None


def test_cosine_simetris_dan_dalam_rentang():
    a, b = {"a": 0.3, "b": 0.9, "c": 0.1}, {"a": 0.7, "c": 0.4, "d": 1.0}
    assert kemiripan_cosine(a, b) == pytest.approx(kemiripan_cosine(b, a))
    assert 0.0 <= kemiripan_cosine(a, b) <= 1.0


# ------------------------------------------------------------------ nilai


def test_kesesuaian_nilai_rata_tertimbang():
    s = kesesuaian_nilai({"matematika": 90, "fisika": 60}, {"matematika": 1.0, "fisika": 0.5})
    assert s.skor == pytest.approx((1.0 * 90 + 0.5 * 60) / 1.5 / 100)
    assert s.kosong == [] and s.dipakai == {"fisika": 60, "matematika": 90}


def test_mapel_kosong_dikeluarkan_dan_ditandai_bukan_dianggap_nol():
    s = kesesuaian_nilai({"matematika": 80}, {"matematika": 1.0, "fisika": 1.0, "kimia": 0.5})
    assert s.skor == pytest.approx(0.8)  # hanya matematika yang dihitung
    assert s.kosong == ["fisika", "kimia"]


def test_tanpa_mapel_relevan_skor_none():
    s = kesesuaian_nilai({"biologi": 90}, {"matematika": 1.0})
    assert s.skor is None and s.kosong == ["matematika"] and s.dipakai == {}


def test_nilai_di_luar_rentang_dijepit_ke_0_1():
    assert kesesuaian_nilai({"a": 150}, {"a": 1}).skor == 1.0
    assert kesesuaian_nilai({"a": -5}, {"a": 1}).skor == 0.0


# ------------------------------------------------------------------ penggabungan


def test_gabung_bobot_awal_setengah_setengah():
    skor, bobot = gabung_kecocokan(0.8, 0.6, 0.5, 0.5)
    assert skor == pytest.approx(0.7) and bobot == {"minat": 0.5, "nilai": 0.5}


def test_gabung_komponen_kosong_dinormalisasi():
    skor, bobot = gabung_kecocokan(None, 0.6, 0.5, 0.5)
    assert skor == pytest.approx(0.6) and bobot == {"nilai": 1.0}
    skor, bobot = gabung_kecocokan(0.9, None, 0.3, 0.7)
    assert skor == pytest.approx(0.9) and bobot == {"minat": 1.0}


def test_gabung_semua_kosong_atau_bobot_nol():
    assert gabung_kecocokan(None, None, 0.5, 0.5) == (None, {})
    assert gabung_kecocokan(0.5, 0.5, 0.0, 0.0) == (None, {})
    assert gabung_kecocokan(0.9, 0.1, 1.0, 0.0) == (pytest.approx(0.9), {"minat": 1.0})


def test_gabung_bobot_tidak_harus_berjumlah_satu():
    skor, bobot = gabung_kecocokan(1.0, 0.0, 3.0, 1.0)
    assert skor == pytest.approx(0.75) and bobot == {"minat": 0.75, "nilai": 0.25}


# ------------------------------------------------------------------ alasan template


def test_dimensi_teratas_urut_sumbangan_lalu_nama():
    siswa = {"realistis": 0.6, "investigatif": 0.85, "artistik": 0.3}
    rumpun = {"realistis": 0.9, "investigatif": 0.8, "artistik": 0.0, "sosial": 1.0}
    assert dimensi_teratas(siswa, rumpun) == ["investigatif", "realistis"]  # .68 > .54; artistik 0
    assert dimensi_teratas(siswa, rumpun, n=1) == ["investigatif"]
    # imbang -> urut nama
    assert dimensi_teratas({"b": 1, "a": 1}, {"a": 1, "b": 1}) == ["a", "b"]


def test_mapel_terbaik_bobot_kali_nilai():
    assert mapel_terbaik({"matematika": 80, "fisika": 95}, {"matematika": 1.0, "fisika": 0.5}) == (
        "matematika",
        80,
    )
    assert mapel_terbaik({}, {}) is None


def test_alasan_lengkap():
    t = alasan_template(
        dimensi=["investigatif", "realistis"],
        terbaik=("bahasa_indonesia", 87.4),
        mapel_kosong=[],
        minat_diisi=True,
    )
    assert (
        t == "Cocok karena minatmu pada investigatif dan realistis serta nilai bahasa indonesia 87."
    )


def test_alasan_menandai_data_yang_belum_diisi():
    t = alasan_template(
        dimensi=["sosial"], terbaik=None, mapel_kosong=["biologi", "kimia"], minat_diisi=True
    )
    assert (
        "minatmu pada sosial" in t and "Nilai belum diisi untuk mapel relevan: biologi, kimia." in t
    )
    t = alasan_template(dimensi=[], terbaik=("matematika", 90), mapel_kosong=[], minat_diisi=False)
    assert "nilai matematika 90" in t and "Minat belum diisi" in t


def test_alasan_tanpa_klaim_peluang():
    t = alasan_template(dimensi=["a"], terbaik=("x", 50), mapel_kosong=[], minat_diisi=True)
    assert "%" not in t and "peluang" not in t.lower()


# ------------------------------------------------------------------ kemurnian modul


def test_modul_match_murni_tanpa_io_atau_framework():
    sumber = Path("app/domain/match.py").read_text(encoding="utf-8")
    impor = {
        n.module.split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(ast.parse(sumber))
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
        if not (isinstance(n, ast.ImportFrom) and n.module is None)
    }
    assert impor <= {"__future__", "collections", "dataclasses", "math"}, impor
