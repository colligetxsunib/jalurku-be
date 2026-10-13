#!/bin/sh
# Entrypoint nginx JalurKu.
#   (tanpa argumen)  render konfigurasi lalu jalankan nginx di foreground
#   muat-ulang       render ulang + `nginx -s reload` (dipanggil deploy/init-cert.sh)
#
# Mode dipilih dari keberadaan sertifikat: ada -> https.conf.template, tidak ada -> http.conf.template.
# Saat berjalan, konfigurasi dirender ulang dan di-reload tiap RELOAD_INTERVAL_DETIK (default 6 jam)
# sehingga sertifikat baru/pembaruan certbot terbaca tanpa campur tangan. Bila konfigurasi hasil
# render tidak lolos `nginx -t`, konfigurasi lama dipertahankan.
set -eu

: "${DOMAIN:?DOMAIN wajib diisi (lihat deploy/.env.prod)}"
# DOMAIN masuk ke berkas konfigurasi: hanya karakter nama host yang diizinkan.
case "$DOMAIN" in
  "" | .* | -* | *[!A-Za-z0-9.-]*)
    echo "[jalurku-nginx] DOMAIN tidak valid: $DOMAIN" >&2
    exit 1
    ;;
esac

TEMPLATES=/jalurku/templates
CONF=/etc/nginx/conf.d/default.conf
LIVE="/etc/letsencrypt/live/$DOMAIN"
INTERVAL="${RELOAD_INTERVAL_DETIK:-21600}"

pilih_mode() {
  if [ -s "$LIVE/fullchain.pem" ] && [ -s "$LIVE/privkey.pem" ]; then
    echo https
  else
    echo http
  fi
}

render() {
  mode="$(pilih_mode)"
  # Hanya ${DOMAIN} yang diganti; variabel nginx ($host, $request_uri, ...) dibiarkan apa adanya.
  envsubst '${DOMAIN}' < "$TEMPLATES/$mode.conf.template" > "$CONF.baru"
  mv "$CONF.baru" "$CONF"
  echo "[jalurku-nginx] mode=$mode domain=$DOMAIN"
}

muat_ulang() {
  cp "$CONF" "$CONF.lama" 2>/dev/null || true
  render
  if nginx -t >/dev/null 2>&1; then
    nginx -s reload
    rm -f "$CONF.lama"
    return 0
  fi
  echo "[jalurku-nginx] konfigurasi baru tidak valid; konfigurasi lama dipertahankan" >&2
  nginx -t >&2 || true
  [ -f "$CONF.lama" ] && mv "$CONF.lama" "$CONF"
  return 1
}

case "${1:-start}" in
  muat-ulang)
    muat_ulang
    exit $?
    ;;
  start) ;;
  *)
    echo "Pemakaian: entrypoint.sh [muat-ulang]" >&2
    exit 2
    ;;
esac

render
nginx -t

(
  while :; do
    sleep "$INTERVAL"
    muat_ulang || true
  done
) &

exec nginx -g 'daemon off;'
