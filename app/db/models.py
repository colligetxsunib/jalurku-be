"""Model DB (PRD bagian 10 + perubahan v1.1).

Aturan integritas:
- Semua tabel ber-session_id memakai ON DELETE CASCADE (FR-A4).
- `rag_chunks.embedding` bertipe vector(768) dan dikunci di migrasi pertama.
- Data resmi bersiklus: kunci memuat `tahun_siklus` agar siklus baru tidak menimpa yang lama.
- `terakhir_diverifikasi` boleh NULL (belum diverifikasi manusia). Tidak pernah diisi otomatis.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 768  # DIKUNCI. Mengganti berarti migrasi kolom + re-embed semua chunk.

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> Any:
    return func.now()


class Sesi(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Profil(Base):
    __tablename__ = "profiles"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    tahun_lulus: Mapped[int | None] = mapped_column(Integer)
    provinsi: Mapped[str | None] = mapped_column(String(64))  # provinsi sekolah asal
    jenjang_sekolah: Mapped[str | None] = mapped_column(String(16))  # SMA/SMK/MA/Paket C
    akreditasi_sekolah: Mapped[str | None] = mapped_column(String(32))
    nilai_rapor: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # {"semester_1": {"matematika": 85}}
    minat: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))  # {dimensi: 0..1}
    skor_tryout: Mapped[float | None] = mapped_column(Float)
    peringkat_sekolah: Mapped[int | None] = mapped_column(Integer)
    jumlah_siswa_angkatan: Mapped[int | None] = mapped_column(Integer)
    alumni_info: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # {prodi/PTN: ya|tidak|tidak_tahu}
    punya_nilai_tka: Mapped[bool | None] = mapped_column(Boolean)
    sekolah_punya_npsn: Mapped[bool | None] = mapped_column(Boolean)
    sekolah_kurikulum_nasional: Mapped[bool | None] = mapped_column(Boolean)
    pakai_erapor: Mapped[bool | None] = mapped_column(Boolean)
    rapor_lengkap_di_pdss: Mapped[bool | None] = mapped_column(Boolean)
    wni_punya_nik: Mapped[bool | None] = mapped_column(Boolean)  # boolean saja, bukan NIK
    lulus_snbp_3_tahun_terakhir: Mapped[bool | None] = mapped_column(Boolean)
    sudah_ikut_utbk_tahun_siklus: Mapped[bool | None] = mapped_column(Boolean)
    paket_c_usia_per_1_juli: Mapped[int | None] = mapped_column(Integer)
    konfirmasi_syarat_prodi: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True)
    )  # {prodi_id: bool}
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), onupdate=_now(), nullable=False
    )


class Ptn(Base):
    __tablename__ = "ptn"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    provinsi: Mapped[str] = mapped_column(String(64), nullable=False)
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)


class Prodi(Base):
    __tablename__ = "prodi"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ptn_id: Mapped[str] = mapped_column(ForeignKey("ptn.id"), nullable=False, index=True)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    rumpun: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    akreditasi: Mapped[str | None] = mapped_column(String(16))
    jenjang: Mapped[str] = mapped_column(String(8), nullable=False)  # S1 / D3 / D4
    program: Mapped[str] = mapped_column(String(16), nullable=False)  # akademik / vokasi
    mapel_penentu: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    tag_minat: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    # ["SNBP", "SNBT"]; NULL = tidak diketahui
    jalur_dibuka: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("jenjang in ('S1','D3','D4')", name="jenjang_valid"),
        CheckConstraint("program in ('akademik','vokasi')", name="program_valid"),
    )


class ProdiJalur(Base):
    """Data keketatan per prodi per jalur (daya tampung dan peminat)."""

    __tablename__ = "prodi_jalur"

    prodi_id: Mapped[str] = mapped_column(
        ForeignKey("prodi.id", ondelete="CASCADE"), primary_key=True
    )
    jalur: Mapped[str] = mapped_column(String(8), primary_key=True)
    tahun_siklus: Mapped[int] = mapped_column(Integer, primary_key=True)
    daya_tampung: Mapped[int | None] = mapped_column(Integer)
    peminat: Mapped[int | None] = mapped_column(Integer)
    tahun_peminat: Mapped[int | None] = mapped_column(Integer)
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("jalur in ('SNBP','SNBT')", name="jalur_valid"),
        CheckConstraint("daya_tampung is null or daya_tampung > 0", name="daya_tampung_positif"),
        CheckConstraint("peminat is null or peminat >= 0", name="peminat_valid"),
    )


class AcuanSkor(Base):
    __tablename__ = "acuan_skor"

    prodi_id: Mapped[str] = mapped_column(
        ForeignKey("prodi.id", ondelete="CASCADE"), primary_key=True
    )
    jalur: Mapped[str] = mapped_column(String(8), primary_key=True)
    tahun: Mapped[int] = mapped_column(Integer, primary_key=True)
    rendah: Mapped[float] = mapped_column(Float, nullable=False)
    tinggi: Mapped[float] = mapped_column(Float, nullable=False)
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("jalur in ('SNBP','SNBT')", name="jalur_valid"),
        CheckConstraint("rendah <= tinggi", name="rentang_valid"),
    )


class RulesJalur(Base):
    __tablename__ = "rules_jalur"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # mis. "SNBT-2026"
    jalur: Mapped[str] = mapped_column(String(8), nullable=False)
    tahun_siklus: Mapped[int] = mapped_column(Integer, nullable=False)
    syarat: Mapped[list] = mapped_column(JSONB, nullable=False)
    dokumen_wajib: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("jalur", "tahun_siklus", name="uq_rules_jalur_siklus"),
        CheckConstraint("jalur in ('SNBP','SNBT')", name="jalur_valid"),
    )


class Ketentuan(Base):
    """Ketentuan resmi SNPMB per siklus (isi config_ketentuan.csv)."""

    __tablename__ = "ketentuan"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    jalur: Mapped[str] = mapped_column(String(8), primary_key=True)  # SNBP / SNBT / ALL
    tahun_siklus: Mapped[int] = mapped_column(Integer, primary_key=True)
    nilai: Mapped[str] = mapped_column(Text, nullable=False)
    nilai_terstruktur: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    keterangan: Mapped[str | None] = mapped_column(Text)
    sumber_url: Mapped[str | None] = mapped_column(Text)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (CheckConstraint("jalur in ('SNBP','SNBT','ALL')", name="jalur_valid"),)


class Profesi(Base):
    __tablename__ = "profesi"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rumpun: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    deskripsi: Mapped[str | None] = mapped_column(Text)


class DokumenSumber(Base):
    __tablename__ = "dokumen_sumber"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    judul: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    jenis: Mapped[str] = mapped_column(String(64), nullable=False)
    tahun_siklus: Mapped[int] = mapped_column(Integer, nullable=False)
    terakhir_diverifikasi: Mapped[date | None] = mapped_column(Date)


class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dokumen_id: Mapped[str] = mapped_column(
        ForeignKey("dokumen_sumber.id", ondelete="CASCADE"), nullable=False, index=True
    )
    urutan: Mapped[int] = mapped_column(Integer, nullable=False)
    teks: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    halaman: Mapped[int | None] = mapped_column(Integer)
    sumber_url: Mapped[str] = mapped_column(Text, nullable=False)
    tahun_siklus: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("dokumen_id", "urutan", name="uq_rag_chunks_dokumen_urutan"),
    )


class Strategi(Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    jalur: Mapped[str] = mapped_column(String(8), nullable=False)
    pilihan: Mapped[list] = mapped_column(JSONB, nullable=False)
    hasil_evaluasi: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), nullable=False
    )

    __table_args__ = (CheckConstraint("jalur in ('SNBP','SNBT')", name="jalur_valid"),)


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pertanyaan: Mapped[str] = mapped_column(Text, nullable=False)  # sudah melewati penyaring PII
    yakin: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sumber_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), nullable=False
    )


class RiasecHasil(Base):
    """Hasil tes minat terakhir per sesi. Hanya skor turunan: jawaban mentah TIDAK disimpan.

    Ikut terhapus bersama sesi (CASCADE), jadi tidak pernah lebih lama dari TTL sesi.
    """

    __tablename__ = "riasec_hasil"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    versi_instrumen: Mapped[str] = mapped_column(String(64), nullable=False)
    instrumen_contoh: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skor_norm: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {dimensi: 0..1}
    keyakinan: Mapped[str] = mapped_column(String(8), nullable=False)  # sedang | rendah
    alasan: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    terjawab: Mapped[int] = mapped_column(Integer, nullable=False)
    total_item: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), nullable=False
    )

    __table_args__ = (CheckConstraint("keyakinan in ('sedang','rendah')", name="keyakinan_valid"),)


class LlmCache(Base):
    """Cache respons LLM dan embedding pertanyaan. Kunci = hash input bebas PII."""

    __tablename__ = "llm_cache"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    respons: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now(), nullable=False
    )
    ttl_detik: Mapped[int] = mapped_column(Integer, nullable=False)


Index("ix_strategies_session_created", Strategi.session_id, Strategi.created_at.desc())
