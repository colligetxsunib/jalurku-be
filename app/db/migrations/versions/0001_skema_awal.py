"""skema awal

Revision ID: 0001
Revises:
Create Date: 2026-10-13 15:34:00.963574
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "dokumen_sumber",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("judul", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("jenis", sa.String(length=64), nullable=False),
        sa.Column("tahun_siklus", sa.Integer(), nullable=False),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dokumen_sumber")),
    )
    op.create_table(
        "ketentuan",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("jalur", sa.String(length=8), nullable=False),
        sa.Column("tahun_siklus", sa.Integer(), nullable=False),
        sa.Column("nilai", sa.Text(), nullable=False),
        sa.Column("nilai_terstruktur", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("keterangan", sa.Text(), nullable=True),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.CheckConstraint("jalur in ('SNBP','SNBT','ALL')", name=op.f("ck_ketentuan_jalur_valid")),
        sa.PrimaryKeyConstraint("key", "jalur", "tahun_siklus", name=op.f("pk_ketentuan")),
    )
    op.create_table(
        "llm_cache",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("respons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ttl_detik", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash", name=op.f("pk_llm_cache")),
    )
    op.create_table(
        "profesi",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("rumpun", sa.String(length=100), nullable=False),
        sa.Column("nama", sa.String(length=200), nullable=False),
        sa.Column("deskripsi", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profesi")),
    )
    op.create_index(op.f("ix_profesi_rumpun"), "profesi", ["rumpun"], unique=False)
    op.create_table(
        "ptn",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("nama", sa.String(length=200), nullable=False),
        sa.Column("provinsi", sa.String(length=64), nullable=False),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ptn")),
    )
    op.create_table(
        "rules_jalur",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("jalur", sa.String(length=8), nullable=False),
        sa.Column("tahun_siklus", sa.Integer(), nullable=False),
        sa.Column("syarat", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "dokumen_wajib",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.CheckConstraint("jalur in ('SNBP','SNBT')", name=op.f("ck_rules_jalur_jalur_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules_jalur")),
        sa.UniqueConstraint("jalur", "tahun_siklus", name="uq_rules_jalur_siklus"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_table(
        "prodi",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("ptn_id", sa.String(length=32), nullable=False),
        sa.Column("nama", sa.String(length=200), nullable=False),
        sa.Column("rumpun", sa.String(length=100), nullable=False),
        sa.Column("akreditasi", sa.String(length=16), nullable=True),
        sa.Column("jenjang", sa.String(length=8), nullable=False),
        sa.Column("program", sa.String(length=16), nullable=False),
        sa.Column("mapel_penentu", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tag_minat", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("jalur_dibuka", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.CheckConstraint("jenjang in ('S1','D3','D4')", name=op.f("ck_prodi_jenjang_valid")),
        sa.CheckConstraint("program in ('akademik','vokasi')", name=op.f("ck_prodi_program_valid")),
        sa.ForeignKeyConstraint(["ptn_id"], ["ptn.id"], name=op.f("fk_prodi_ptn_id_ptn")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prodi")),
    )
    op.create_index(op.f("ix_prodi_ptn_id"), "prodi", ["ptn_id"], unique=False)
    op.create_index(op.f("ix_prodi_rumpun"), "prodi", ["rumpun"], unique=False)
    op.create_table(
        "profiles",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("tahun_lulus", sa.Integer(), nullable=True),
        sa.Column("provinsi", sa.String(length=64), nullable=True),
        sa.Column("jenjang_sekolah", sa.String(length=16), nullable=True),
        sa.Column("akreditasi_sekolah", sa.String(length=32), nullable=True),
        sa.Column("nilai_rapor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("minat", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("skor_tryout", sa.Float(), nullable=True),
        sa.Column("peringkat_sekolah", sa.Integer(), nullable=True),
        sa.Column("jumlah_siswa_angkatan", sa.Integer(), nullable=True),
        sa.Column("alumni_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("punya_nilai_tka", sa.Boolean(), nullable=True),
        sa.Column("sekolah_punya_npsn", sa.Boolean(), nullable=True),
        sa.Column("sekolah_kurikulum_nasional", sa.Boolean(), nullable=True),
        sa.Column("pakai_erapor", sa.Boolean(), nullable=True),
        sa.Column("rapor_lengkap_di_pdss", sa.Boolean(), nullable=True),
        sa.Column("wni_punya_nik", sa.Boolean(), nullable=True),
        sa.Column("lulus_snbp_3_tahun_terakhir", sa.Boolean(), nullable=True),
        sa.Column("sudah_ikut_utbk_tahun_siklus", sa.Boolean(), nullable=True),
        sa.Column("paket_c_usia_per_1_juli", sa.Integer(), nullable=True),
        sa.Column(
            "konfirmasi_syarat_prodi", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_profiles_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_profiles")),
    )
    op.create_table(
        "query_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("pertanyaan", sa.Text(), nullable=False),
        sa.Column("yakin", sa.Boolean(), nullable=False),
        sa.Column(
            "sumber_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_query_logs_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_logs")),
    )
    op.create_index(op.f("ix_query_logs_session_id"), "query_logs", ["session_id"], unique=False)
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dokumen_id", sa.String(length=64), nullable=False),
        sa.Column("urutan", sa.Integer(), nullable=False),
        sa.Column("teks", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("halaman", sa.Integer(), nullable=True),
        sa.Column("sumber_url", sa.Text(), nullable=False),
        sa.Column("tahun_siklus", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dokumen_id"],
            ["dokumen_sumber.id"],
            name=op.f("fk_rag_chunks_dokumen_id_dokumen_sumber"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rag_chunks")),
        sa.UniqueConstraint("dokumen_id", "urutan", name="uq_rag_chunks_dokumen_urutan"),
    )
    op.create_index(op.f("ix_rag_chunks_dokumen_id"), "rag_chunks", ["dokumen_id"], unique=False)
    op.create_table(
        "strategies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("jalur", sa.String(length=8), nullable=False),
        sa.Column("pilihan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hasil_evaluasi", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("jalur in ('SNBP','SNBT')", name=op.f("ck_strategies_jalur_valid")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_strategies_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
    )
    op.create_index(
        "ix_strategies_session_created",
        "strategies",
        ["session_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "acuan_skor",
        sa.Column("prodi_id", sa.String(length=64), nullable=False),
        sa.Column("jalur", sa.String(length=8), nullable=False),
        sa.Column("tahun", sa.Integer(), nullable=False),
        sa.Column("rendah", sa.Float(), nullable=False),
        sa.Column("tinggi", sa.Float(), nullable=False),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.CheckConstraint("jalur in ('SNBP','SNBT')", name=op.f("ck_acuan_skor_jalur_valid")),
        sa.CheckConstraint("rendah <= tinggi", name=op.f("ck_acuan_skor_rentang_valid")),
        sa.ForeignKeyConstraint(
            ["prodi_id"],
            ["prodi.id"],
            name=op.f("fk_acuan_skor_prodi_id_prodi"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("prodi_id", "jalur", "tahun", name=op.f("pk_acuan_skor")),
    )
    op.create_table(
        "prodi_jalur",
        sa.Column("prodi_id", sa.String(length=64), nullable=False),
        sa.Column("jalur", sa.String(length=8), nullable=False),
        sa.Column("tahun_siklus", sa.Integer(), nullable=False),
        sa.Column("daya_tampung", sa.Integer(), nullable=True),
        sa.Column("peminat", sa.Integer(), nullable=True),
        sa.Column("tahun_peminat", sa.Integer(), nullable=True),
        sa.Column("sumber_url", sa.Text(), nullable=True),
        sa.Column("terakhir_diverifikasi", sa.Date(), nullable=True),
        sa.CheckConstraint("jalur in ('SNBP','SNBT')", name=op.f("ck_prodi_jalur_jalur_valid")),
        sa.CheckConstraint(
            "daya_tampung is null or daya_tampung > 0",
            name=op.f("ck_prodi_jalur_daya_tampung_positif"),
        ),
        sa.CheckConstraint(
            "peminat is null or peminat >= 0", name=op.f("ck_prodi_jalur_peminat_valid")
        ),
        sa.ForeignKeyConstraint(
            ["prodi_id"],
            ["prodi.id"],
            name=op.f("fk_prodi_jalur_prodi_id_prodi"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("prodi_id", "jalur", "tahun_siklus", name=op.f("pk_prodi_jalur")),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("prodi_jalur")
    op.drop_table("acuan_skor")
    op.drop_index("ix_strategies_session_created", table_name="strategies")
    op.drop_table("strategies")
    op.drop_index(op.f("ix_rag_chunks_dokumen_id"), table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index(op.f("ix_query_logs_session_id"), table_name="query_logs")
    op.drop_table("query_logs")
    op.drop_table("profiles")
    op.drop_index(op.f("ix_prodi_rumpun"), table_name="prodi")
    op.drop_index(op.f("ix_prodi_ptn_id"), table_name="prodi")
    op.drop_table("prodi")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("rules_jalur")
    op.drop_table("ptn")
    op.drop_index(op.f("ix_profesi_rumpun"), table_name="profesi")
    op.drop_table("profesi")
    op.drop_table("llm_cache")
    op.drop_table("ketentuan")
    op.drop_table("dokumen_sumber")
    # ### end Alembic commands ###
