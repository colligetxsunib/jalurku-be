"""Task 10: evaluasi komposisi (domain murni): aturan keras, heuristik, saran swap."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.strategy import (
    AturanStrategi,
    Pilihan,
    evaluasi,
    hitung_komposisi,
    tambah_saran_swap,
)

KOMPOSISI_SNBT = {
    1: "bebas",
    2: "bebas",
    3: [
        {"akademik": 2, "vokasi": 1, "min_d3": 0},
        {"akademik": 1, "vokasi": 2, "min_d3": 0},
        {"akademik": 0, "vokasi": 3, "min_d3": 1},
    ],
    4: [
        {"akademik": 2, "vokasi": 2, "min_d3": 1},
        {"akademik": 1, "vokasi": 3, "min_d3": 1},
    ],
}


def aturan(jalur: str = "SNBT", **ubah) -> AturanStrategi:
    dasar = AturanStrategi(
        jalur=jalur,
        max_pilihan=4 if jalur == "SNBT" else 2,
        komposisi=KOMPOSISI_SNBT if jalur == "SNBT" else None,
        aturan_provinsi=jalur == "SNBP",
        blokir_lintas_jalur=True,
        min_pilihan_untuk_evaluasi=2,
        min_safe=1,
        maks_rasio_reach=0.5,
        peringatan_satu_ptn=True,
        peringatan_satu_jalur=True,
        maks_saran_swap=3,
    )
    return replace(dasar, **ubah)


def P(
    pid: str,
    *,
    ptn="ui",
    prov="Jawa Barat",
    program="akademik",
    jenjang=None,
    gate="lolos",
    kat="match",
):
    jenjang = jenjang or ("S1" if program == "akademik" else "D3")
    return Pilihan(pid, pid.upper(), ptn, ptn.upper(), prov, program, jenjang, gate, kat)


def nilai(pilihan, a=None, *, provinsi="Jawa Barat", lain=True):
    return evaluasi(pilihan, a or aturan(), provinsi_sekolah=provinsi, ada_strategi_jalur_lain=lain)


def kode(temuan, tingkat=None) -> list[str]:
    return [t.kode for t in temuan if tingkat is None or t.tingkat == tingkat]


# ---------------------------- batas jumlah pilihan (dari ketentuan, bukan hardcode) ----------------------------


@pytest.mark.parametrize(
    "jalur,jumlah,melebihi",
    [
        ("SNBP", 1, False),
        ("SNBP", 2, False),
        ("SNBP", 3, True),
        ("SNBT", 4, False),
        ("SNBT", 5, True),
    ],
)
def test_batas_jumlah_pilihan_per_jalur(jalur, jumlah, melebihi):
    pil = [
        P(f"p{i}", ptn=f"ptn{i}", prov="Jawa Barat", program="akademik" if i < 2 else "vokasi")
        for i in range(jumlah)
    ]
    t = nilai(pil, aturan(jalur))
    assert ("melebihi_batas_pilihan" in kode(t, "pelanggaran")) == melebihi


def test_batas_diambil_dari_aturan_bukan_konstanta():
    pil = [P("a", ptn="x"), P("b", ptn="y"), P("c", ptn="z", program="vokasi")]
    assert "melebihi_batas_pilihan" not in kode(nilai(pil, aturan("SNBT", max_pilihan=3)))
    assert "melebihi_batas_pilihan" in kode(nilai(pil, aturan("SNBT", max_pilihan=2)))


# ---------------------------- SNBP: aturan provinsi ----------------------------


def test_snbp_dua_pilihan_wajib_satu_di_provinsi_sekolah_asal():
    a = aturan("SNBP")
    di_jabar = [P("a", ptn="ui"), P("b", ptn="itb")]
    luar = [P("a", ptn="ugm", prov="DI Yogyakarta"), P("b", ptn="unair", prov="Jawa Timur")]
    campur = [P("a", ptn="ugm", prov="DI Yogyakarta"), P("b", ptn="ui")]
    assert "provinsi_sekolah_asal" not in kode(nilai(di_jabar, a))
    assert "provinsi_sekolah_asal" in kode(nilai(luar, a), "pelanggaran")
    assert "provinsi_sekolah_asal" not in kode(nilai(campur, a))


def test_snbp_satu_pilihan_boleh_di_provinsi_mana_pun():
    t = nilai([P("a", ptn="ugm", prov="DI Yogyakarta")], aturan("SNBP"))
    assert "provinsi_sekolah_asal" not in kode(t)


def test_snbp_provinsi_sekolah_belum_diisi_meminta_data_bukan_menebak():
    t = nilai([P("a"), P("b", ptn="itb")], aturan("SNBP"), provinsi=None)
    temuan = next(x for x in t if x.kode == "provinsi_sekolah_belum_diisi")
    assert temuan.tingkat == "peringatan" and temuan.data_kurang == ("provinsi",)
    assert "provinsi_sekolah_asal" not in kode(t)


def test_aturan_provinsi_nonaktif_bila_ketentuan_tidak_ada():
    luar = [P("a", ptn="ugm", prov="DI Yogyakarta"), P("b", ptn="unair", prov="Jawa Timur")]
    assert "provinsi_sekolah_asal" not in kode(nilai(luar, aturan("SNBP", aturan_provinsi=False)))


# ---------------------------- SNBT: komposisi akademik/vokasi/D3 ----------------------------


def A(i, **kw):
    return P(f"a{i}", ptn=f"ptn{i}", **kw)


def V(i, jenjang="D3", **kw):
    return P(f"v{i}", ptn=f"ptn{i + 10}", program="vokasi", jenjang=jenjang, **kw)


@pytest.mark.parametrize(
    "pilihan,sah",
    [
        ([A(1)], True),
        ([A(1), A(2)], True),  # 1-2 pilihan bebas, termasuk 2 Sarjana
        ([A(1), A(2), V(1)], True),  # 2 akademik + 1 vokasi
        ([A(1), V(1), V(2, "D4")], True),  # 1 akademik + 2 vokasi
        ([V(1), V(2, "D4"), V(3, "D4")], True),  # 3 vokasi dengan minimal 1 D3
        ([V(1, "D4"), V(2, "D4"), V(3, "D4")], False),  # 3 vokasi tanpa D3
        ([A(1), A(2), A(3)], False),  # semua Sarjana
        ([A(1), A(2), V(1), V(2, "D4")], True),  # 2 + 2 dengan 1 D3
        ([A(1), A(2), V(1, "D4"), V(2, "D4")], False),  # 2 + 2 tanpa D3
        ([A(1), V(1), V(2), V(3, "D4")], True),  # 1 + 3 dengan D3
        ([A(1), A(2), A(3), V(1)], False),  # 3 Sarjana: Sarjana maksimal 2
        ([A(1), A(2), A(3), A(4)], False),
        ([V(1), V(2), V(3), V(4)], False),  # 0 akademik + 4 vokasi tidak ada di daftar sah
    ],
)
def test_komposisi_snbt(pilihan, sah):
    t = nilai(pilihan)
    ada_pelanggaran = bool(
        {"butuh_vokasi", "komposisi_snbt_tidak_valid"} & set(kode(t, "pelanggaran"))
    )
    assert ada_pelanggaran == (not sah)


def test_semua_sarjana_memicu_butuh_vokasi_dengan_penjelasan():
    t = next(x for x in nilai([A(1), A(2), A(3)]) if x.kode == "butuh_vokasi")
    assert t.tingkat == "pelanggaran"
    assert "Sarjana maksimal 2" in t.pesan and "2 akademik + 1 vokasi" in t.pesan
    assert "0 akademik + 3 vokasi (minimal 1 D3)" in t.pesan


def test_komposisi_tidak_valid_menyebut_d3():
    t = next(
        x
        for x in nilai([A(1), A(2), V(1, "D4"), V(2, "D4")])
        if x.kode == "komposisi_snbt_tidak_valid"
    )
    assert "D3: 0" in t.pesan and "minimal 1 D3" in t.pesan


def test_komposisi_snbp_tidak_diperiksa():
    assert not {"butuh_vokasi", "komposisi_snbt_tidak_valid"} & set(
        kode(nilai([A(1), A(2)], aturan("SNBP")))
    )


def test_hitung_komposisi():
    k = hitung_komposisi(
        [
            A(1, kat="reach"),
            A(2, kat="safe"),
            V(1, kat="match"),
            V(2, "D4", gate="tidak_memenuhi_syarat", kat=None),
        ]
    )
    assert k == {
        "jumlah": 4,
        "reach": 1,
        "match": 1,
        "safe": 1,
        "tidak_dinilai": 1,
        "akademik": 2,
        "vokasi": 2,
        "d3": 1,
    }


# ---------------------------- heuristik: safe, reach, satu PTN ----------------------------


def test_min_safe_dan_maks_reach():
    t = nilai([A(1, kat="reach"), A(2, kat="match")])
    assert "min_safe" in kode(t, "peringatan") and "maks_reach" not in kode(
        t
    )  # 1/2 = 50% tidak > 50%
    t = nilai([A(1, kat="reach"), A(2, kat="reach")])
    assert {"min_safe", "maks_reach"} <= set(kode(t, "peringatan"))
    t = nilai([A(1, kat="reach"), A(2, kat="reach"), A(3, kat="safe")])
    assert "maks_reach" in kode(t) and "min_safe" not in kode(t)  # 2/3 > 50%
    assert not {"min_safe", "maks_reach"} & set(kode(nilai([A(1, kat="safe"), A(2, kat="match")])))


def test_rasio_hanya_bila_cukup_pilihan_yang_dinilai():
    t = nilai([A(1, kat="reach")])  # hanya 1 dinilai (< 2)
    assert not {"min_safe", "maks_reach"} & set(kode(t))
    assert "evaluasi_rasio_dilewati" in kode(t, "info")


def test_pilihan_tidak_dapat_dinilai_tidak_dihitung_tetapi_dilaporkan():
    t = nilai(
        [
            A(1, kat="safe"),
            A(2, gate="tidak_memenuhi_syarat", kat=None),
            A(3, gate="data_kurang", kat=None),
            A(4, kat="belum_ada_acuan"),
        ]
    )
    peta = {x.kode: x for x in t}
    assert peta["pilihan_tidak_memenuhi_syarat"].prodi_ids == ("a2",)
    assert peta["pilihan_tidak_memenuhi_syarat"].tingkat == "peringatan"
    assert (
        peta["pilihan_data_kurang"].prodi_ids == ("a3",)
        and peta["pilihan_data_kurang"].tingkat == "info"
    )
    assert peta["pilihan_belum_ada_acuan"].prodi_ids == ("a4",)
    # hanya 1 yang dapat dinilai -> rasio dilewati, bukan min_safe/maks_reach salah hitung
    assert "evaluasi_rasio_dilewati" in peta and "min_safe" not in peta


def test_satu_ptn():
    assert "satu_ptn" in kode(nilai([P("a"), P("b")]), "peringatan")
    assert "satu_ptn" not in kode(nilai([P("a"), P("b", ptn="itb")]))
    assert "satu_ptn" not in kode(nilai([P("a")]))  # satu pilihan bukan 'semua di satu PTN'
    assert "satu_ptn" not in kode(nilai([P("a"), P("b")], aturan(peringatan_satu_ptn=False)))


def test_informasi_blokir_lintas_jalur_dan_satu_jalur():
    t = nilai([P("a")], lain=False)
    assert {"blokir_lintas_jalur", "hanya_satu_jalur"} <= set(kode(t, "info"))
    t = nilai([P("a")], lain=True)
    assert "hanya_satu_jalur" not in kode(t) and "blokir_lintas_jalur" in kode(t)
    assert "blokir_lintas_jalur" not in kode(nilai([P("a")], aturan(blokir_lintas_jalur=False)))
    assert "hanya_satu_jalur" not in kode(
        nilai([P("a")], aturan(peringatan_satu_jalur=False), lain=False)
    )


def test_config_mengubah_perilaku():
    pil = [A(1, kat="reach"), A(2, kat="match")]
    assert "min_safe" in kode(nilai(pil))
    assert "min_safe" not in kode(nilai(pil, aturan(min_safe=0)))
    dua_reach = [A(1, kat="reach"), A(2, kat="reach"), A(3, kat="safe")]
    assert "maks_reach" in kode(nilai(dua_reach))
    assert "maks_reach" not in kode(nilai(dua_reach, aturan(maks_rasio_reach=0.7)))
    assert "evaluasi_rasio_dilewati" in kode(nilai(pil, aturan(min_pilihan_untuk_evaluasi=3)))


def test_urutan_temuan_pelanggaran_dulu():
    t = nilai([A(1, kat="reach"), A(2, kat="reach"), A(3, kat="reach")])
    tingkat = [x.tingkat for x in t]
    assert tingkat == sorted(tingkat, key={"pelanggaran": 0, "peringatan": 1, "info": 2}.get)
    assert t[0].kode == "butuh_vokasi"


def test_tidak_ada_pilihan_tidak_ada_temuan():
    assert nilai([]) == []


# ---------------------------- saran swap ----------------------------


def swap(pilihan, kandidat, a=None, **kw):
    a = a or aturan()
    temuan = nilai(pilihan, a, **kw)
    return tambah_saran_swap(
        temuan,
        pilihan,
        kandidat,
        a,
        provinsi_sekolah=kw.get("provinsi", "Jawa Barat"),
        ada_strategi_jalur_lain=kw.get("lain", True),
    )


def saran_untuk(temuan, kode_):
    return [(s.ganti, s.dengan) for t in temuan if t.kode == kode_ for s in t.saran_swap]


def test_swap_memperbaiki_butuh_vokasi_dari_shortlist():
    pil = [A(1, kat="match"), A(2, kat="safe"), A(3, kat="match")]
    kand = [V(1, kat="match")]
    t = swap(pil, kand)
    # a2 satu-satunya safe: menggantinya akan memunculkan min_safe, jadi tidak disarankan
    assert saran_untuk(t, "butuh_vokasi") == [("a1", "v1"), ("a3", "v1")]
    s = next(x for x in t if x.kode == "butuh_vokasi").saran_swap[0]
    assert "memperbaiki" in s.alasan and "komposisi belum memuat program vokasi" in s.alasan


def test_swap_hanya_dari_shortlist_dan_bukan_yang_sudah_dipilih():
    pil = [A(1), A(2), A(3)]
    assert saran_untuk(swap(pil, []), "butuh_vokasi") == []
    assert saran_untuk(swap(pil, [A(1)]), "butuh_vokasi") == []  # a1 sudah dipilih
    assert saran_untuk(swap(pil, [A(9)]), "butuh_vokasi") == []  # akademik: tidak memperbaiki


def test_swap_ditolak_bila_menimbulkan_masalah_baru():
    pil = [A(1, kat="match"), A(2, kat="safe"), A(3, kat="match")]
    gagal = V(
        1, gate="tidak_memenuhi_syarat", kat=None
    )  # memperbaiki komposisi tapi tak memenuhi syarat
    t = swap(pil, [gagal])
    assert saran_untuk(t, "butuh_vokasi") == []
    ok = V(2, kat="match")
    assert saran_untuk(swap(pil, [gagal, ok]), "butuh_vokasi") == [("a1", "v2"), ("a3", "v2")]


def test_swap_tidak_memutus_aturan_lain_yang_sudah_terpenuhi():
    pil = [A(1, kat="match"), A(2, kat="safe"), A(3, kat="match")]
    # tanpa a2 (satu-satunya safe) susunan itu memang akan melanggar min_safe
    tanpa_safe = [A(1, kat="match"), V(1, kat="match"), A(3, kat="match")]
    assert "min_safe" in kode(nilai(tanpa_safe))
    t = swap(pil, [V(1, kat="match")])
    assert ("a2", "v1") not in saran_untuk(t, "butuh_vokasi")
    # bila kandidat vokasinya safe, mengganti a2 aman dan ikut disarankan
    t2 = swap(pil, [V(1, kat="safe")])
    assert ("a2", "v1") in saran_untuk(t2, "butuh_vokasi")


def test_swap_memperbaiki_reach_berlebih_dengan_kandidat_safe():
    pil = [A(1, kat="reach"), A(2, kat="reach")]
    t = swap(pil, [A(3, kat="safe"), A(4, kat="match")])
    assert saran_untuk(t, "min_safe")[0] == ("a1", "a3")
    assert saran_untuk(t, "maks_reach")  # reach 2/2 berkurang jadi 1/2
    s = next(x for x in t if x.kode == "min_safe").saran_swap[0]
    assert "A3 berkategori safe" in s.alasan


def test_swap_mengganti_pilihan_yang_tidak_memenuhi_syarat():
    pil = [A(1, kat="safe"), A(2, gate="tidak_memenuhi_syarat", kat=None)]
    t = swap(pil, [A(3, kat="match")])
    assert saran_untuk(t, "pilihan_tidak_memenuhi_syarat") == [("a2", "a3")]


def test_swap_urutan_deterministik_dan_dibatasi():
    pil = [A(1, kat="reach"), A(2, kat="reach")]
    kand = [A(5, kat="safe"), A(4, kat="safe"), A(3, kat="safe")]
    pertama = swap(pil, kand)
    kedua = swap(pil, kand)
    assert pertama == kedua
    assert saran_untuk(pertama, "min_safe") == [
        ("a1", "a5"),
        ("a1", "a4"),
        ("a1", "a3"),
    ]  # maks 3, urutan shortlist
    satu = swap(pil, kand, aturan(maks_saran_swap=1))
    assert len(saran_untuk(satu, "min_safe")) == 1
    nol = swap(pil, kand, aturan(maks_saran_swap=0))
    assert all(t.saran_swap == () for t in nol)


def test_tanpa_masalah_tidak_ada_saran():
    t = swap([A(1, kat="safe"), A(2, kat="match")], [A(3, kat="safe")])
    assert all(x.saran_swap == () for x in t)


def test_jumlah_berlebih_tidak_bisa_diperbaiki_dengan_swap():
    pil = [A(i, kat="match", program="akademik" if i < 3 else "vokasi") for i in range(1, 6)]
    t = swap(pil, [V(9, kat="safe")], aturan(max_pilihan=4))
    assert saran_untuk(t, "melebihi_batas_pilihan") == []
