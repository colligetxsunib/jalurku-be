"""hasil tes minat RIASEC per sesi

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 10:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "riasec_hasil",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("versi_instrumen", sa.String(length=64), nullable=False),
        sa.Column("instrumen_contoh", sa.Boolean(), nullable=False),
        sa.Column("skor_norm", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("keyakinan", sa.String(length=8), nullable=False),
        sa.Column(
            "alasan",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("terjawab", sa.Integer(), nullable=False),
        sa.Column("total_item", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "keyakinan in ('sedang','rendah')", name=op.f("ck_riasec_hasil_keyakinan_valid")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_riasec_hasil_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_riasec_hasil")),
    )


def downgrade() -> None:
    op.drop_table("riasec_hasil")
