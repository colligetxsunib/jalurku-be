#!/usr/bin/env bash
# Deploy / upgrade JalurKu di satu server (Docker + plugin compose).
#
#   deploy/deploy.sh                 build + naikkan stack, tunggu sehat, smoke test internal
#   deploy/deploy.sh --seed          sama, lalu muat data seed ke database (idempoten)
#   deploy/deploy.sh --tanpa-smoke   lewati smoke test
#
# Sebelum pertama kali: salin deploy/.env.prod.example ke deploy/.env.prod dan isi. Setelah stack
# naik, jalankan deploy/init-cert.sh sekali untuk HTTPS. Data seed memakai REQUIRE_VERIFIED dari
# .env.prod: bila true, baris tanpa terakhir_diverifikasi ditolak.
set -euo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

SEED=0
SMOKE=1
for arg in "$@"; do
  case "$arg" in
    --seed) SEED=1 ;;
    --tanpa-smoke) SMOKE=0 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) gagal "argumen tidak dikenal: $arg" ;;
  esac
done

wajib_ada
periksa_env
DOMAIN="$(nilai_env DOMAIN)"

info "Build image dan naikkan stack..."
dc up -d --build --remove-orphans

info "Menunggu api sehat (migrasi dijalankan saat start)..."
api_id="$(dc ps -q api)"
[ -n "$api_id" ] || gagal "kontainer api tidak ditemukan"
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$api_id")"
  [ "$status" = "healthy" ] && break
  [ "$status" = "unhealthy" ] && { dc logs --tail 50 api; gagal "api unhealthy"; }
  sleep 3
done
[ "$status" = "healthy" ] || { dc logs --tail 50 api; gagal "api belum sehat setelah 180 detik"; }

if [ "$SEED" = "1" ]; then
  info "Memuat data seed..."
  dc exec -T api python -m scripts.ingest
fi

if [ "$SMOKE" = "1" ]; then
  info "Smoke test internal (langsung ke api, tanpa nginx)..."
  admin_key="$(nilai_env ADMIN_KEY)"
  if [ -n "$admin_key" ]; then
    dc exec -T api python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --prod --admin-key "$admin_key"
  else
    dc exec -T api python -m scripts.smoke_test --base-url http://127.0.0.1:8000 --prod
  fi
fi

info "Cek lewat nginx..."
nginx_id="$(dc ps -q nginx)"
[ -n "$nginx_id" ] || gagal "kontainer nginx tidak ditemukan"
http_port="$(nilai_env HTTP_PORT)"; http_port="${http_port:-80}"
https_port="$(nilai_env HTTPS_PORT)"; https_port="${https_port:-443}"
mode="http"
if dc exec -T nginx test -s "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"; then mode="https"; fi
if [ "$mode" = "https" ]; then
  # -k: yang diperiksa hanya nginx -> api. Kepercayaan sertifikat diperiksa init-cert.sh dan smoke
  # test eksternal (sertifikat staging/self-signed tidak dipercaya, tetapi stack tetap sehat).
  curl -fsSk --resolve "$DOMAIN:$https_port:127.0.0.1" "https://$DOMAIN:$https_port/api/v1/health" >/dev/null \
    || gagal "https://$DOMAIN/api/v1/health tidak sehat"
  info "nginx mode HTTPS: OK"
else
  curl -fsS -H "Host: $DOMAIN" "http://127.0.0.1:$http_port/api/v1/health" >/dev/null \
    || gagal "nginx (mode HTTP) tidak meneruskan ke api"
  info "nginx mode HTTP: OK. BELUM terenkripsi; jalankan deploy/init-cert.sh untuk HTTPS."
fi

info "Selesai. Uji dari luar server:"
info "  python -m scripts.smoke_test --base-url ${mode}://$DOMAIN --prod --lewat-proxy"
