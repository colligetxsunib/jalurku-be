#!/usr/bin/env bash
# Deploy / upgrade JalurKu di belakang proxy host (Docker + plugin compose).
#
#   deploy/deploy-hostproxy.sh                 build + naikkan db dan api, seed, smoke test internal
#   deploy/deploy-hostproxy.sh --tanpa-smoke   lewati smoke test
#
# Hanya db dan api. TIDAK menyentuh nginx host dan TIDAK menerbitkan sertifikat: HTTPS milik
# pemilik server (lihat deploy/nginx-host.conf.example dan deploy/README-hostproxy.md).
# Sebelum pertama kali: salin deploy/.env.hostproxy.example ke deploy/.env.prod dan isi.
# Folder PDF (DOKUMEN_DIR) dibuat manual sebelum menjalankan skrip ini.
set -euo pipefail

SKRIP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SKRIP_DIR/.env.prod}"
COMPOSE_FILE="$SKRIP_DIR/docker-compose.hostproxy.yml"

info() { printf '\033[1;34m[jalurku]\033[0m %s\n' "$*"; }
gagal() { printf '\033[1;31m[jalurku] GAGAL:\033[0m %s\n' "$*" >&2; exit 1; }
peringat() { printf '\033[1;33m[jalurku] PERINGATAN:\033[0m %s\n' "$*" >&2; }

SMOKE=1
for arg in "$@"; do
  case "$arg" in
    --tanpa-smoke) SMOKE=0 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) gagal "argumen tidak dikenal: $arg" ;;
  esac
done

# Baca satu kunci dari berkas env tanpa meng-source-nya.
nilai_env() {
  local kunci="$1" baris
  baris="$(grep -E "^${kunci}=" "$ENV_FILE" | tail -n 1 || true)"
  printf '%s' "${baris#*=}"
}

dc() {
  docker compose --project-directory "$SKRIP_DIR" \
    --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

command -v docker >/dev/null 2>&1 || gagal "docker tidak ditemukan"
docker compose version >/dev/null 2>&1 || gagal "plugin 'docker compose' tidak ditemukan"
[ -f "$ENV_FILE" ] || gagal "$ENV_FILE tidak ada. Salin dari deploy/.env.hostproxy.example lalu isi."
[ -n "$(nilai_env POSTGRES_PASSWORD)" ] || gagal "POSTGRES_PASSWORD kosong di $ENV_FILE"
[ "$(nilai_env REQUIRE_VERIFIED)" = "true" ] \
  || peringat "REQUIRE_VERIFIED belum true. Nyalakan sebelum rekam video dan submit."
[ -n "$(nilai_env GEMINI_API_KEY)" ] \
  || peringat "GEMINI_API_KEY kosong. /query dan narasi memakai fallback."
[ -n "$(nilai_env TRUSTED_PROXIES)" ] \
  || peringat "TRUSTED_PROXIES kosong: semua pengunjung berbagi satu jatah rate limit (IP gateway Docker)."
dc config -q || gagal "docker-compose.hostproxy.yml tidak valid dengan $ENV_FILE"

PORT="$(nilai_env APP_HOST_PORT)"; PORT="${PORT:-8000}"

info "Build image dan naikkan db + api (tanpa nginx)..."
dc up -d --build --remove-orphans db api

info "Menunggu api sehat (migrasi dijalankan saat start)..."
api_id="$(dc ps -q api)"
[ -n "$api_id" ] || gagal "kontainer api tidak ditemukan"
status=""
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$api_id")"
  [ "$status" = "healthy" ] && break
  [ "$status" = "unhealthy" ] && { dc logs --tail 50 api; gagal "api unhealthy"; }
  sleep 3
done
[ "$status" = "healthy" ] || { dc logs --tail 50 api; gagal "api belum sehat setelah 180 detik"; }

info "Memuat data seed (idempoten, perintah yang sama dengan deploy.sh --seed)..."
dc exec -T api python -m scripts.ingest

info "Cek kesiapan verifikasi..."
dc exec -T api python -m scripts.check_verified || peringat "check_verified menemukan yang belum siap (lihat di atas)."

if [ "$SMOKE" = "1" ]; then
  info "Smoke test internal (langsung ke api di 127.0.0.1, tanpa nginx host)..."
  admin_key="$(nilai_env ADMIN_KEY)"
  if [ -n "$admin_key" ]; then
    dc exec -T api python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --prod --admin-key "$admin_key"
  else
    dc exec -T api python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --prod
  fi
fi

info "Cek dari host (port loopback)..."
curl -fsS "http://127.0.0.1:$PORT/api/v1/health" >/dev/null \
  || gagal "http://127.0.0.1:$PORT/api/v1/health tidak menjawab"

info "Selesai. Ringkasan:"
info "  api  -> http://127.0.0.1:$PORT (HANYA loopback; publik lewat nginx host)"
info "  db   -> tidak dipublish ke host"
info "Langkah berikutnya (di host/server):"
info "  1. Isi folder PDF lalu ingest dokumen: lihat deploy/README-hostproxy.md langkah d."
info "  2. Pasang server block nginx host, nginx -t, reload, lalu certbot."
info "  3. check_gemini, siapkan_demo --hangatkan, lalu smoke test dari luar:"
info "     python -m scripts.smoke_test --base-url https://DOMAIN --prod --lewat-proxy"
