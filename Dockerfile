FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    PATH="/srv/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.8.22

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY app ./app
COPY config ./config
COPY data/seed ./data/seed
COPY data/riasec ./data/riasec
COPY data/draft ./data/draft
COPY scripts ./scripts

RUN useradd --system --uid 10001 --no-create-home appuser \
    && mkdir -p /srv/data/dokumen && chown -R appuser /srv/data
USER appuser

EXPOSE 8000
# Migrasi dijalankan sebelum server naik. IP klien dibaca aplikasi dari X-Forwarded-For hanya
# bila proxy ada di rate_limit.proxy_tepercaya (config/app.yaml), jadi uvicorn tidak ikut mengubah.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:build_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers --no-server-header"]
