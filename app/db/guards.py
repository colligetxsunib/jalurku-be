"""Guard startup: vektor dari model/dimensi berbeda tidak boleh pernah tercampur (PRD bagian 10)."""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.core.config import AppConfig, ConfigError


def check_embedding_consistency(engine: Engine, config: AppConfig) -> None:
    """Bandingkan config dengan dimensi kolom `rag_chunks.embedding` dan `embedding_model` chunk.

    Melempar ConfigError bila tidak cocok sehingga aplikasi gagal start.
    Error koneksi (OperationalError) dibiarkan naik; pemanggil memutuskan.
    """
    with engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('rag_chunks')")).scalar() is None:
            raise ConfigError("Tabel rag_chunks belum ada. Jalankan: alembic upgrade head")

        dimensi_kolom = conn.execute(
            text(
                "SELECT a.atttypmod FROM pg_attribute a "
                "WHERE a.attrelid = 'rag_chunks'::regclass AND a.attname = 'embedding'"
            )
        ).scalar()
        if dimensi_kolom != config.embedding.dimensi:
            raise ConfigError(
                f"Dimensi embedding di config ({config.embedding.dimensi}) tidak sama dengan kolom "
                f"rag_chunks.embedding ({dimensi_kolom}). Mengganti dimensi butuh migrasi kolom "
                "dan re-embed semua chunk."
            )

        model_ada = (
            conn.execute(text("SELECT DISTINCT embedding_model FROM rag_chunks")).scalars().all()
        )
        asing = sorted(m for m in model_ada if m != config.embedding.model)
        if asing:
            raise ConfigError(
                f"Model embedding di config ({config.embedding.model}) tidak sama dengan chunk yang "
                f"sudah ada ({', '.join(asing)}). Re-embed semua chunk sebelum mengganti model."
            )
