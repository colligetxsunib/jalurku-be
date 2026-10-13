#!/usr/bin/env bash
# Fungsi bersama deploy.sh dan init-cert.sh (di-source, bukan dijalankan langsung).

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$DEPLOY_DIR/.env.prod}"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"

info() { printf '\033[1;34m[jalurku]\033[0m %s\n' "$*"; }
gagal() { printf '\033[1;31m[jalurku] GAGAL:\033[0m %s\n' "$*" >&2; exit 1; }

# Git Bash di Windows: docker.exe butuh path gaya Windows. Di Linux/macOS (cygpath tidak ada) path
# dipakai apa adanya.
if command -v cygpath >/dev/null 2>&1; then
  jalur_docker() { cygpath -m "$1"; }
else
  jalur_docker() { printf '%s' "$1"; }
fi

dc() {
  docker compose --project-directory "$(jalur_docker "$DEPLOY_DIR")" \
    --env-file "$(jalur_docker "$ENV_FILE")" -f "$(jalur_docker "$COMPOSE_FILE")" "$@"
}

# Baca satu kunci dari berkas env tanpa meng-source-nya (nilai tidak dieksekusi sebagai shell).
nilai_env() {
  local kunci="$1" baris
  baris="$(grep -E "^${kunci}=" "$ENV_FILE" | tail -n 1 || true)"
  printf '%s' "${baris#*=}"
}

wajib_ada() {
  command -v docker >/dev/null 2>&1 || gagal "docker tidak ditemukan"
  docker compose version >/dev/null 2>&1 || gagal "plugin 'docker compose' tidak ditemukan"
  [ -f "$ENV_FILE" ] || gagal "$ENV_FILE tidak ada. Salin dari deploy/.env.prod.example lalu isi."
}

# Tolak konfigurasi yang jelas keliru sebelum apa pun dijalankan.
periksa_env() {
  local domain pw
  domain="$(nilai_env DOMAIN)"
  pw="$(nilai_env POSTGRES_PASSWORD)"
  [ -n "$domain" ] || gagal "DOMAIN kosong di $ENV_FILE"
  [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || gagal "DOMAIN tidak valid: $domain"
  [ -n "$pw" ] || gagal "POSTGRES_PASSWORD kosong (buat: openssl rand -hex 24)"
  [[ "$pw" =~ ^[A-Za-z0-9]+$ ]] || gagal "POSTGRES_PASSWORD hanya boleh huruf dan angka (dipakai di URL)"
  [ "${#pw}" -ge 16 ] || gagal "POSTGRES_PASSWORD terlalu pendek (minimal 16 karakter)"
  if [ "$(nilai_env REQUIRE_VERIFIED)" != "true" ]; then
    info "PERINGATAN: REQUIRE_VERIFIED belum true. Nyalakan sebelum rekam video dan submit."
  fi
  if [ -z "$(nilai_env GEMINI_API_KEY)" ]; then
    info "PERINGATAN: GEMINI_API_KEY kosong. /query dan narasi memakai fallback."
  fi
  dc config -q || gagal "docker-compose.prod.yml tidak valid dengan $ENV_FILE"
}
