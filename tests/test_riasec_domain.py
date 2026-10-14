"""Skoring tes minat RIASEC (app.domain.riasec): fungsi murni, deterministik, tanpa DB/LLM.

Tidak bertanda `db`: berjalan tanpa PostgreSQL maupun dependensi web.
"""

from __future__ import annotations

from app.domain.riasec import (
    ItemRiasec,
    SkalaLikert,
    hitung,
    id_tak_dikenal,
    jawaban_di_luar_skala,
    validasi_instrumen,
)

DIMENSI = ["realistis", "investigatif", "artistik", "sosial", "enterprising", "konvensional"]
SKALA = SkalaLikert(min=0, maks=4)


def instrumen(n_per_dimensi: int = 2) -> list[ItemRiasec]:
    huruf = {"realistis": "r", "investigatif": "i", "artistik": "a", "sosial": "s",
             "enterprising": "e", "konvensional": "c"}
    return [
        ItemRiasec(id=f"{huruf[d]}{k}", dimensi=d, teks=f"aktivitas {d} {k}")
        for d in DIMENSI
        for k in range(1, n_per_dimensi + 1)
    ]


# ----------------------------------------------------------------- validasi instrumen


def test_instrumen_valid_tidak_ada_galat():
    assert validasi_instrumen(instrumen(), DIMENSI) == []


def test_instrumen_dimensi_tanpa_item_terdeteksi():
    item = [i for i in instrumen() if i.dimensi != "konvensional"]
    galat = validasi_instrumen(item, DIMENSI)
    assert any("konvensional" in g for g in galat)


def test_instrumen_dimensi_asing_dan_id_duplikat_terdeteksi():
    item = [
        ItemRiasec(id="x1", dimensi="misteri", teks="t"),
        ItemRiasec(id="x1", dimensi="realistis", teks="t"),
    ]
    galat = validasi_instrumen(item, DIMENSI)
    assert any("duplikat" in g for g in galat) and any("tak dikenal" in g for g in galat)


# ----------------------------------------------------------------- skoring


def test_skor_normalisasi_dan_holland_code_dari_hitungan_manual():
    item = instrumen(2)  # 2 item per dimensi, skor maks per dimensi = 2 * 4 = 8
    jawaban = {
        "r1": 4, "r2": 4,   # realistis = 8/8 = 1.0
        "i1": 2, "i2": 2,   # investigatif = 4/8 = 0.5
        "a1": 0, "a2": 0,   # artistik = 0
        "s1": 1, "s2": 1,   # sosial = 2/8 = 0.25
        "e1": 3, "e2": 3,   # enterprising = 6/8 = 0.75
        "c1": 4, "c2": 2,   # konvensional = 6/8 = 0.75
    }
    h = hitung(jawaban, item, SKALA, DIMENSI)
    assert h.skor_norm == {
        "realistis": 1.0, "investigatif": 0.5, "artistik": 0.0,
        "sosial": 0.25, "enterprising": 0.75, "konvensional": 0.75,
    }
    assert h.skor_mentah["realistis"] == 8 and h.skor_mentah["artistik"] == 0
    # Tiga teratas: realistis(1.0), lalu enterprising & konvensional(0.75) -> tie-break alfabet
    assert h.dimensi_teratas == ["realistis", "enterprising", "konvensional"]
    assert h.holland_code == "REC"
    assert h.terjawab == 12 and h.total_item == 12


def test_tes_parsial_normalisasi_hanya_item_terjawab():
    item = instrumen(2)
    # Hanya 1 dari 2 item realistis dijawab -> maks = 1 * 4, bukan 2 * 4
    h = hitung({"r1": 4}, item, SKALA, DIMENSI)
    assert h.skor_norm["realistis"] == 1.0  # 4/4
    assert h.skor_norm["investigatif"] == 0.0  # tak terjawab -> 0
    assert h.terjawab == 1


def test_deterministik_urutan_jawaban_tidak_berpengaruh():
    item = instrumen(2)
    j1 = {"r1": 1, "i1": 2, "a1": 3}
    j2 = {"a1": 3, "r1": 1, "i1": 2}
    assert hitung(j1, item, SKALA, DIMENSI) == hitung(j2, item, SKALA, DIMENSI)


def test_tanpa_jawaban_vektor_nol():
    h = hitung({}, instrumen(2), SKALA, DIMENSI)
    assert set(h.skor_norm.values()) == {0.0} and h.terjawab == 0


# ----------------------------------------------------------------- validasi jawaban


def test_deteksi_id_tak_dikenal_dan_nilai_di_luar_skala():
    item = instrumen(2)
    jawaban = {"r1": 4, "zz9": 2, "i1": 7}
    assert id_tak_dikenal(jawaban, item) == ["zz9"]
    assert jawaban_di_luar_skala(jawaban, SKALA) == ["i1"]
