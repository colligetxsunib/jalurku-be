"""Layanan tes minat RIASEC: muat instrumen, simpan hasil ke profil.minat, dan baca penanda keyakinan.

Jawaban mentah TIDAK disimpan di mana pun. Yang tersimpan hanya skor turunan: di `profiles.minat`
(dipakai /explore) dan ringkasan kualitas di `riasec_hasil`. Keduanya terikat sesi (CASCADE), jadi
tidak pernah lebih lama dari TTL sesi.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import AppConfig, ConfigError
from app.db import models as m
from app.domain.riasec import Butir, HasilRiasec, Instrumen

log = logging.getLogger("jalurku.riasec")

NAMA_INSTRUMEN = "instrumen_v1.json"
NAMA_CONTOH = "instrumen_contoh.json"


def _galat(path: Path, pesan: str) -> ConfigError:
    return ConfigError(f"Instrumen RIASEC tidak valid ({path.name}): {pesan}")


def parse_instrumen(data: Mapping[str, Any], dimensi_config: list[str], path: Path) -> Instrumen:
    """Validasi ketat; kesalahan = ConfigError (aplikasi gagal start, bukan jalan dengan data rusak)."""
    try:
        skala = data["skala"]
        s_min, s_maks = skala["min"], skala["maks"]
        dimensi = tuple(data["dimensi"])
        butir_mentah = list(data["item"])
        versi, sumber = str(data["versi_instrumen"]).strip(), str(data["sumber"]).strip()
    except (KeyError, TypeError) as exc:
        raise _galat(path, f"kunci wajib hilang atau salah bentuk: {exc}") from exc
    if not versi or not sumber:
        raise _galat(path, "versi_instrumen dan sumber wajib diisi")
    if not (isinstance(s_min, int) and isinstance(s_maks, int)) or isinstance(s_min, bool):
        raise _galat(path, "skala.min dan skala.maks harus bilangan bulat")
    if s_min >= s_maks:
        raise _galat(path, "skala.min harus lebih kecil dari skala.maks")
    if set(dimensi) != set(dimensi_config) or len(dimensi) != len(set(dimensi)):
        raise _galat(path, f"dimensi harus tepat sama dengan minat.dimensi: {dimensi_config}")

    butir: list[Butir] = []
    ids: set[str] = set()
    for i, b in enumerate(butir_mentah):
        try:
            bid, teks, dim = str(b["id"]).strip(), str(b["teks"]).strip(), b["dimensi"]
        except (KeyError, TypeError) as exc:
            raise _galat(path, f"item[{i}] salah bentuk (butuh id, teks, dimensi)") from exc
        if not bid or not teks:
            raise _galat(path, f"item[{i}] id dan teks tidak boleh kosong")
        if bid in ids:
            raise _galat(path, f"id butir ganda: {bid}")
        if dim not in dimensi:
            raise _galat(path, f"item {bid}: dimensi '{dim}' tidak dikenal")
        ids.add(bid)
        butir.append(Butir(bid, teks, dim))
    kosong = [d for d in dimensi if not any(b.dimensi == d for b in butir)]
    if kosong:
        raise _galat(path, f"dimensi tanpa butir: {', '.join(kosong)}")
    label = {str(k): str(v) for k, v in (skala.get("label") or {}).items()}
    return Instrumen(
        versi_instrumen=versi,
        sumber=sumber,
        skala_min=s_min,
        skala_maks=s_maks,
        skala_label=label,
        dimensi=dimensi,
        item=tuple(butir),
        contoh=bool(data.get("contoh", False)),
    )


def muat_instrumen(folder: str | Path, config: AppConfig) -> Instrumen:
    """instrumen_v1.json bila ada; selain itu berkas contoh (diberi label contoh)."""
    folder = Path(folder)
    utama, contoh = folder / NAMA_INSTRUMEN, folder / NAMA_CONTOH
    if utama.is_file():
        path, paksa_contoh = utama, False
    elif contoh.is_file():
        path, paksa_contoh = contoh, True
        log.warning(
            "%s belum ada; memakai instrumen contoh (bukan instrumen final)", NAMA_INSTRUMEN
        )
    else:
        raise ConfigError(f"Instrumen RIASEC tidak ditemukan di {folder} ({NAMA_INSTRUMEN})")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _galat(path, f"tidak bisa dibaca sebagai JSON: {type(exc).__name__}") from exc
    instr = parse_instrumen(data, config.minat.dimensi, path)
    if paksa_contoh and not instr.contoh:
        instr = replace(instr, contoh=True)
    return instr


def simpan_hasil(
    db: Session, session_id: uuid.UUID, instr: Instrumen, hasil: HasilRiasec, profil_minat: dict
) -> None:
    """Tulis ringkasan kualitas. `profil_minat` = skor yang dipetakan ke profiles.minat."""
    baris = db.get(m.RiasecHasil, session_id)
    if baris is None:
        baris = m.RiasecHasil(session_id=session_id)
        db.add(baris)
    baris.versi_instrumen = instr.versi_instrumen
    baris.instrumen_contoh = instr.contoh
    baris.skor_norm = dict(profil_minat)
    baris.keyakinan = hasil.keyakinan
    baris.alasan = list(hasil.alasan)
    baris.terjawab = hasil.terjawab
    baris.total_item = hasil.total_item
    db.commit()


def sumber_minat(db: Session, session_id: uuid.UUID, minat: Mapping[str, Any] | None) -> dict:
    """Asal vektor minat profil, untuk menandai hasil /explore.

    `riasec` hanya bila minat profil saat ini masih sama dengan skor hasil tes terakhir; bila
    pengguna mengubahnya lewat PUT /profile, ia dianggap `manual` (keyakinan tes tidak berlaku).
    """
    aktif = {d: v for d, v in (minat or {}).items() if v is not None}
    if not aktif:
        return {"sumber": "belum_diisi", "keyakinan": None, "alasan": []}
    baris = db.get(m.RiasecHasil, session_id)
    if baris is not None and _sama(aktif, baris.skor_norm):
        return {
            "sumber": "riasec",
            "keyakinan": baris.keyakinan,
            "alasan": list(baris.alasan or []),
            "versi_instrumen": baris.versi_instrumen,
            "instrumen_contoh": baris.instrumen_contoh,
        }
    return {"sumber": "manual", "keyakinan": None, "alasan": []}


def _sama(a: Mapping[str, float], b: Mapping[str, float]) -> bool:
    return set(a) == set(b) and all(abs(a[k] - b[k]) < 1e-9 for k in a)
