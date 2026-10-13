"""Inti penilaian reach/match/safe (PRD 8.2): tier siswa x pita keketatan -> matriks. Fungsi murni.

Ini HEURISTIK, bukan probabilitas. Tidak ada persentase peluang. Tidak ada LLM di sini.

Kesepakatan batas: nilai yang tepat sama dengan batas masuk kelompok yang LEBIH TINGGI
(skor == lemah_sedang -> sedang, skor == sedang_kuat -> kuat, rasio == rendah_sedang -> sedang, dst).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from math import floor
from statistics import fmean
from typing import Any

from app.core.config import BobotTier, JalurPenilaianConfig, PitaConfig
from app.domain.fields import pertanyaan_untuk
from app.domain.gate import DataKurang

SEMESTER_DIPAKAI = ("semester_1", "semester_2", "semester_3", "semester_4", "semester_5")
CATATAN_RELATIF = "relatif terhadap prodi yang ada di data"
PERINGATAN_PROKSI = "Proksi dari rapor, bukan skor UTBK. Seleksi SNBT berdasarkan skor UTBK."


def _klem(x: float, bawah: float = 0.0, atas: float = 1.0) -> float:
    return max(bawah, min(atas, x))


# ----------------------------------------------------------------------------- faktor & tier


@dataclass(frozen=True)
class FaktorSiswa:
    nilai: Mapping[str, float]  # faktor yang diketahui, masing-masing 0-1
    tidak_diketahui: tuple[str, ...]  # faktor opsional yang tidak bisa dihitung (tren, peringkat)


def hitung_faktor(profil: Mapping[str, Any], tren_skala_poin: float) -> FaktorSiswa:
    """Faktor milik siswa. `rapor` wajib (bila tak ada, tidak muncul di `nilai`)."""
    rapor = profil.get("nilai_rapor") or {}
    per_semester: dict[str, list[float]] = {}
    for sem in SEMESTER_DIPAKAI:
        nilai = [float(v) for v in (rapor.get(sem) or {}).values() if v is not None]
        if nilai:
            per_semester[sem] = nilai

    faktor: dict[str, float] = {}
    tidak_diketahui: list[str] = []

    semua = [v for vals in per_semester.values() for v in vals]
    if semua:
        faktor["rapor"] = _klem(fmean(semua) / 100)

    if len(per_semester) >= 2:
        rata = [fmean(per_semester[s]) for s in sorted(per_semester)]
        k = min(2, max(1, len(rata) // 2))
        delta = fmean(rata[-k:]) - fmean(rata[:k])
        faktor["tren"] = _klem(0.5 + delta / (2 * tren_skala_poin))
    else:
        tidak_diketahui.append("tren")

    peringkat, jumlah = profil.get("peringkat_sekolah"), profil.get("jumlah_siswa_angkatan")
    if peringkat is not None and jumlah is not None and 1 <= peringkat <= jumlah:
        faktor["peringkat"] = _klem((jumlah - peringkat + 1) / jumlah)  # peringkat 1 = 1.0
    else:
        tidak_diketahui.append("peringkat")
    return FaktorSiswa(faktor, tuple(tidak_diketahui))


def skor_siswa(faktor: FaktorSiswa, bobot: BobotTier) -> float | None:
    """Rata-rata tertimbang atas faktor yang diketahui; bobot dinormalisasi ulang. None bila rapor tak ada."""
    if "rapor" not in faktor.nilai:
        return None
    b = {"rapor": bobot.rapor, "tren": bobot.tren, "peringkat": bobot.peringkat}
    total = sum(b[f] for f in faktor.nilai)
    if total <= 0:
        return fmean(faktor.nilai.values())
    return sum(b[f] * v for f, v in faktor.nilai.items()) / total


def tier_dari_skor(skor: float, lemah_sedang: float, sedang_kuat: float) -> str:
    if skor < lemah_sedang:
        return "lemah"
    if skor < sedang_kuat:
        return "sedang"
    return "kuat"


@dataclass(frozen=True)
class TierSiswa:
    nilai: str  # lemah | sedang | kuat
    skor: float
    sumber: str  # rapor | proksi_rapor | skor_tryout
    faktor: Mapping[str, float] = field(default_factory=dict)
    faktor_tidak_diketahui: tuple[str, ...] = ()
    peringatan: str | None = None

    def ke_dict(self) -> dict[str, Any]:
        return {
            "nilai": self.nilai,
            "skor": round(self.skor, 3),
            "sumber": self.sumber,
            "faktor": {k: round(v, 3) for k, v in self.faktor.items()},
            "faktor_tidak_diketahui": list(self.faktor_tidak_diketahui),
            "peringatan": self.peringatan,
        }


def tentukan_tier(
    profil: Mapping[str, Any],
    cfg: JalurPenilaianConfig,
    *,
    sumber_rapor: str,
    peringatan_rapor: str | None = None,
    pakai_skor_tryout: bool = False,
) -> TierSiswa | None:
    """Tier siswa, atau None bila data tidak cukup (rapor tidak ada).

    Bila `pakai_skor_tryout` dan skala skor tryout ada di config dan siswa punya skor, tier berpindah
    ke skor tryout (menggantikan proksi rapor).
    """
    faktor = hitung_faktor(profil, cfg.tier_siswa.tren.skala_poin)
    skala = cfg.skala_skor_tryout
    skor_tryout = profil.get("skor_tryout")
    if pakai_skor_tryout and skala is not None and skor_tryout is not None:
        return TierSiswa(
            nilai=tier_dari_skor(skor_tryout, skala.batas.lemah_sedang, skala.batas.sedang_kuat),
            skor=float(skor_tryout),
            sumber="skor_tryout",
            faktor=faktor.nilai,
            faktor_tidak_diketahui=faktor.tidak_diketahui,
        )
    skor = skor_siswa(faktor, cfg.tier_siswa.bobot)
    if skor is None:
        return None
    b = cfg.tier_siswa.batas
    return TierSiswa(
        nilai=tier_dari_skor(skor, b.lemah_sedang, b.sedang_kuat),
        skor=skor,
        sumber=sumber_rapor,
        faktor=faktor.nilai,
        faktor_tidak_diketahui=faktor.tidak_diketahui,
        peringatan=peringatan_rapor,
    )


# ----------------------------------------------------------------------------- pita keketatan


def persentil(nilai_terurut: Sequence[float], p: float) -> float:
    """Persentil dengan interpolasi linear (sama dengan numpy default)."""
    n = len(nilai_terurut)
    if n == 0:
        raise ValueError("data kosong")
    if n == 1:
        return float(nilai_terurut[0])
    pos = (n - 1) * p / 100
    bawah = floor(pos)
    atas = min(bawah + 1, n - 1)
    return nilai_terurut[bawah] + (nilai_terurut[atas] - nilai_terurut[bawah]) * (pos - bawah)


@dataclass(frozen=True)
class BasisPita:
    metode: str  # tetap | persentil
    cukup: bool  # False = sampel pembanding kurang, pita tidak bisa dihitung
    batas: tuple[float, float] | None  # (rendah_sedang, sedang_tinggi) dalam satuan rasio
    n_prodi: int | None = None
    persentil: tuple[float, float] | None = None
    kelompok: str | None = None  # semua | program:<nama>

    def ke_dict(self) -> dict[str, Any]:
        return {
            "metode": self.metode,
            "n_prodi": self.n_prodi,
            "persentil": list(self.persentil) if self.persentil else None,
            "batas_rasio": [round(x, 2) for x in self.batas] if self.batas else None,
            "kelompok": self.kelompok,
        }


def buat_basis_pita(
    cfg: PitaConfig, rasio_pembanding: Sequence[float], kelompok: str | None = None
) -> BasisPita:
    if cfg.metode == "tetap":
        return BasisPita("tetap", True, (cfg.batas.rendah_sedang, cfg.batas.sedang_tinggi))
    pa, pb = cfg.persentil.rendah_sedang, cfg.persentil.sedang_tinggi
    data = sorted(rasio_pembanding)
    if len(data) < cfg.min_sampel:
        return BasisPita("persentil", False, None, len(data), (pa, pb), kelompok)
    return BasisPita(
        "persentil", True, (persentil(data, pa), persentil(data, pb)), len(data), (pa, pb), kelompok
    )


def pita_dari_rasio(rasio: float, basis: BasisPita) -> str:
    assert basis.batas is not None
    rendah_sedang, sedang_tinggi = basis.batas
    if rasio < rendah_sedang:
        return "rendah"
    if rasio < sedang_tinggi:
        return "sedang"
    return "tinggi"


@dataclass(frozen=True)
class Keketatan:
    """Data keketatan satu prodi pada satu jalur."""

    daya_tampung: int | None = None
    peminat: int | None = None
    tahun_peminat: int | None = None

    @property
    def rasio(self) -> float | None:
        if self.daya_tampung and self.peminat is not None and self.daya_tampung > 0:
            return self.peminat / self.daya_tampung
        return None


# ----------------------------------------------------------------------------- hasil penilaian


@dataclass(frozen=True)
class Penilaian:
    kategori: str  # reach | match | safe | belum_ada_acuan | data_kurang
    metode: str  # matriks_keketatan | acuan_skor
    indikatif: bool
    alasan: str
    label: str | None = None
    keyakinan: str | None = None  # rendah | sedang
    gap: float | None = None
    tier: TierSiswa | None = None
    pita: Mapping[str, Any] | None = None
    sel: Mapping[str, Any] | None = None
    acuan: Mapping[str, Any] | None = None
    catatan: tuple[str, ...] = ()
    data_kurang: tuple[DataKurang, ...] = ()
    # Semua faktor yang tidak diketahui (faktor tier + mis. rekam jejak alumni), ditampilkan ke siswa
    faktor_tidak_diketahui: tuple[str, ...] = ()

    def ke_dict(self) -> dict[str, Any]:
        return {
            "kategori": self.kategori,
            "metode": self.metode,
            "indikatif": self.indikatif,
            "label": self.label,
            "keyakinan": self.keyakinan,
            "alasan": self.alasan,
            "gap": self.gap,
            "faktor_tidak_diketahui": list(self.faktor_tidak_diketahui),
            "tier": self.tier.ke_dict() if self.tier else None,
            "pita": dict(self.pita) if self.pita else None,
            "sel": dict(self.sel) if self.sel else None,
            "acuan": dict(self.acuan) if self.acuan else None,
            "catatan": list(self.catatan),
        }


def _info_pita(nilai: str, k: Keketatan, basis: BasisPita) -> dict[str, Any]:
    info: dict[str, Any] = {
        "nilai": nilai,
        "rasio": round(k.rasio, 2) if k.rasio is not None else None,
        "daya_tampung": k.daya_tampung,
        "peminat": k.peminat,
        "tahun_peminat": k.tahun_peminat,
        "basis": basis.ke_dict(),
    }
    if basis.metode == "persentil":
        info["catatan_relatif"] = CATATAN_RELATIF
    return info


@dataclass(frozen=True)
class Keyakinan:
    nilai: str  # rendah | sedang
    catatan: tuple[str, ...] = ()
    tidak_diketahui: tuple[str, ...] = ()  # faktor non-tier yang tak diketahui (mis. alumni)


KeyakinanFn = Callable[[TierSiswa], Keyakinan]


def nilai_dengan_matriks(
    *,
    jalur: str,
    profil: Mapping[str, Any],
    keketatan: Keketatan | None,
    basis_pita: BasisPita,
    cfg: JalurPenilaianConfig,
    teks_catatan: Mapping[str, str],
    tahun_siklus: int,
    sumber_tier_rapor: str,
    peringatan_tier_rapor: str | None,
    pakai_skor_tryout: bool,
    keyakinan: KeyakinanFn,
    keterangan_sumber: Mapping[str, str],
) -> Penilaian:
    """Alur bersama SNBT/SNBP.

    Urutan keputusan: (1) tanpa data keketatan -> belum_ada_acuan (jangan menebak, jangan minta data
    siswa yang tak berguna); (2) tier tak bisa dihitung -> data_kurang; (3) kategori = matriks.
    """
    tier = tentukan_tier(
        profil,
        cfg,
        sumber_rapor=sumber_tier_rapor,
        peringatan_rapor=peringatan_tier_rapor,
        pakai_skor_tryout=pakai_skor_tryout,
    )
    catatan: list[str] = []

    rasio = keketatan.rasio if keketatan else None
    if keketatan is None or rasio is None:
        return Penilaian(
            kategori="belum_ada_acuan",
            metode="matriks_keketatan",
            indikatif=True,
            label="indikatif",
            alasan=(
                f"Belum ada data peminat dan daya tampung {jalur} untuk prodi ini, sehingga "
                "keketatan tidak bisa dihitung. Sistem tidak menebak."
            ),
            tier=tier,
            catatan=(),
        )
    if not basis_pita.cukup:
        return Penilaian(
            kategori="belum_ada_acuan",
            metode="matriks_keketatan",
            indikatif=True,
            label="indikatif",
            alasan=(
                f"Data pembanding {jalur} terlalu sedikit ({basis_pita.n_prodi} prodi, minimal "
                f"{cfg.pita_keketatan.min_sampel}) untuk menentukan pita keketatan."
            ),
            tier=tier,
            pita=_info_pita("belum_dihitung", keketatan, basis_pita),
        )
    pita = pita_dari_rasio(rasio, basis_pita)
    info_pita = _info_pita(pita, keketatan, basis_pita)

    if tier is None:
        return Penilaian(
            kategori="data_kurang",
            metode="matriks_keketatan",
            indikatif=True,
            label="indikatif",
            alasan="Nilai rapor belum diisi, sehingga tier siswa tidak bisa dihitung.",
            pita=info_pita,
            data_kurang=(DataKurang("nilai_rapor", pertanyaan_untuk("nilai_rapor")),),
        )

    sel_cfg = getattr(getattr(cfg.matriks, tier.nilai), pita)
    kategori = sel_cfg.kategori
    catatan_sel = teks_catatan.get(sel_cfg.catatan, sel_cfg.catatan) if sel_cfg.catatan else None
    yakin = keyakinan(tier)
    catatan.extend(yakin.catatan)
    if catatan_sel:
        catatan.append(catatan_sel)
    if keketatan.tahun_peminat is not None and keketatan.tahun_peminat < tahun_siklus:
        catatan.append(
            f"Data peminat tahun {keketatan.tahun_peminat} (acuan siklus sebelumnya). "
            "Cek ulang saat pendaftaran dibuka."
        )
    tidak_diketahui = tuple(dict.fromkeys(tier.faktor_tidak_diketahui + yakin.tidak_diketahui))
    if tidak_diketahui:
        catatan.append(
            "Faktor yang tidak diketahui dan tidak dihitung: " + ", ".join(tidak_diketahui)
        )

    relatif = (
        f", {CATATAN_RELATIF} ({basis_pita.n_prodi} prodi)"
        if basis_pita.metode == "persentil"
        else ""
    )
    alasan = (
        f"Tier siswa {tier.nilai} ({keterangan_sumber.get(tier.sumber, tier.sumber)}, "
        f"skor {tier.skor:.2f}) dan keketatan prodi "
        f"{pita} ({rasio:.1f} peminat per kursi{relatif}) menghasilkan kategori {kategori}. "
        "Ini heuristik indikatif, bukan peluang."
    )
    return Penilaian(
        kategori=kategori,
        metode="matriks_keketatan",
        indikatif=True,
        label="indikatif",
        keyakinan=yakin.nilai,
        alasan=alasan,
        tier=tier,
        pita=info_pita,
        sel={"tier": tier.nilai, "pita": pita, "kategori": kategori, "catatan": catatan_sel},
        catatan=tuple(catatan),
        faktor_tidak_diketahui=tidak_diketahui,
    )
