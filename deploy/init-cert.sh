#!/usr/bin/env bash
# Terbitkan sertifikat Let's Encrypt pertama untuk DOMAIN, lalu pindahkan nginx ke mode HTTPS.
#
#   deploy/init-cert.sh              sertifikat sungguhan
#   STAGING=1 deploy/init-cert.sh    CA staging (uji alur; tidak dipercaya browser, batas rate longgar)
#
# Prasyarat: DNS A/AAAA DOMAIN sudah mengarah ke server ini, port 80 dan 443 terbuka di firewall,
# dan stack sudah jalan (deploy/deploy.sh). Pembaruan berikutnya otomatis (layanan certbot).
set -euo pipefail
# shellcheck source=deploy/_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

wajib_ada
periksa_env
DOMAIN="$(nilai_env DOMAIN)"
EMAIL="$(nilai_env ACME_EMAIL)"

case "$DOMAIN" in
  localhost|*.localhost|*.local) gagal "DOMAIN=$DOMAIN tidak bisa mendapat sertifikat publik" ;;
esac
[ -n "$EMAIL" ] || gagal "ACME_EMAIL kosong di $ENV_FILE"
[ "$(nilai_env HTTP_PORT)" = "" ] || [ "$(nilai_env HTTP_PORT)" = "80" ] \
  || gagal "Let's Encrypt membutuhkan port 80 asli; HTTP_PORT harus 80"

info "Memastikan nginx berjalan (melayani tantangan ACME di port 80)..."
dc up -d nginx

staging=()
if [ "${STAGING:-0}" = "1" ]; then
  staging=(--staging)
  info "Memakai CA STAGING (sertifikat tidak dipercaya browser)."
fi

info "Meminta sertifikat untuk $DOMAIN..."
dc run --rm --no-deps --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" \
  --agree-tos --no-eff-email --non-interactive \
  ${staging[@]+"${staging[@]}"}

info "Memindahkan nginx ke HTTPS..."
dc exec -T nginx sh /jalurku/entrypoint.sh muat-ulang

sleep 2
# Sertifikat sungguhan harus dipercaya klien (verifikasi aktif). Staging tidak dipercaya: pakai -k.
insecure=()
[ "${STAGING:-0}" = "1" ] && insecure=(-k)
curl -fsS ${insecure[@]+"${insecure[@]}"} "https://$DOMAIN/api/v1/health" >/dev/null \
  && info "HTTPS aktif: https://$DOMAIN/api/v1/health OK" \
  || gagal "sertifikat terbit tetapi https://$DOMAIN belum menjawab; cek: docker compose logs nginx"
if [ "${STAGING:-0}" = "1" ]; then
  info "Ini sertifikat staging. Untuk yang sungguhan: hapus volume certs lalu jalankan tanpa STAGING."
fi
