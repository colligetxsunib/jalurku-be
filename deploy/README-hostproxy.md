# Deploy JalurKu di belakang proxy host

Panduan ini untuk server yang HTTPS-nya ditangani sendiri oleh pemilik server (nginx di host +
certbot yang sudah ada; port 80/443 dipakai situs lain yang harus tetap hidup). Docker HANYA
menjalankan `db` (pgvector) dan `api`. Tidak ada nginx atau certbot di dalam compose.

Berkas terkait: `deploy/docker-compose.hostproxy.yml`, `deploy/.env.hostproxy.example`,
`deploy/deploy-hostproxy.sh`, `deploy/nginx-host.conf.example`.

## a. Prasyarat

- Docker + plugin `docker compose` di server.
- Subdomain API (mis. `jalurku-api.domainmu.com`) dengan record A ke IP server.
- Port 80/443 terbuka; situs lain di host tidak terganggu (kita hanya menambah satu vhost).

## b. Clone dan isi env

```bash
git clone <repo> jalurku && cd jalurku
git checkout <tag-atau-branch-rilis>
cp deploy/.env.hostproxy.example deploy/.env.prod
```

Isi `deploy/.env.prod` (tanpa tanda kutip; berkas ini tidak masuk repo): `POSTGRES_PASSWORD`
(alfanumerik ≥16, mis. `openssl rand -hex 24`), `GEMINI_API_KEY`, `LLM_MODEL` /
`LLM_MODEL_FALLBACK` / `EMBED_MODEL`, `ADMIN_KEY` baru (bukan kunci smoke/development),
`CORS_ORIGINS` ke origin frontend, `REQUIRE_VERIFIED=true`, `APP_HOST_PORT` (bawaan 8000),
`DOKUMEN_DIR` (bawaan `/srv/jalurku/dokumen`), dan `TRUSTED_PROXIES` (bawaan `172.31.0.0/24` —
lihat catatan di bawah).

Tentang `TRUSTED_PROXIES`: port api hanya dibuka di 127.0.0.1, sehingga koneksi dari nginx host
terlihat di dalam kontainer berasal dari IP gateway jaringan Docker, bukan IP pengunjung. Aplikasi
membaca IP asli dari header `X-Forwarded-For` hanya bila IP langsungnya ada di daftar ini
(`app/core/rate_limit.py`, env `TRUSTED_PROXIES` menimpa `rate_limit.proxy_tepercaya`). Nilai
`172.31.0.0/24` cocok dengan subnet `networks.internal` di compose; bila subnet diganti, ganti
juga nilai ini. Tanpa pengaturan ini semua pengunjung berbagi satu jatah rate limit (satu IP
gateway) — uji langkah h akan menangkapnya.

## c. Folder PDF dan izin

```bash
sudo mkdir -p /srv/jalurku/dokumen
sudo chown -R 10001:10001 /srv/jalurku/dokumen
```

Kontainer api berjalan sebagai pengguna `appuser` uid 10001 (`Dockerfile`), dan folder host di-mount
ke `/srv/data/dokumen` di kontainer. Tanpa `chown` ini kontainer tidak bisa membaca PDF (dan tidak
bisa menulis bila endpoint admin unggah dipakai). Alternatif tanpa `chown`: `chmod -R a+rX`
(akses baca saja) atau `a+rwX` (baca-tulis) pada folder itu.

Unggah 4 PDF (nama file persis `dokumen_id` + `.pdf`):

```bash
scp snpmb-paparan-2026.pdf unej-panduan-snbp-2026.pdf \
    unej-panduan-snbt-2026.pdf snpmb-sipers-2026.pdf \
    pengguna@server:/srv/jalurku/dokumen/
```

(`snpmb-faq` adalah halaman web dan sengaja tidak ada berkasnya; ingest melewatinya.)

## d. Naikkan stack lalu ingest dokumen

```bash
bash deploy/deploy-hostproxy.sh
```

Skrip ini: build image, naikkan `db` + `api`, tunggu `api` sehat (migrasi jalan saat start), muat
data seed (idempoten, perintah yang sama dengan `deploy.sh --seed`), jalankan
`scripts.check_verified`, lalu smoke test internal ke `127.0.0.1:${APP_HOST_PORT}`. Tidak menyentuh
nginx host dan tidak menerbitkan sertifikat.

Ingest dokumen RAG (butuh `GEMINI_API_KEY`):

```bash
docker compose --project-directory deploy --env-file deploy/.env.prod \
  -f deploy/docker-compose.hostproxy.yml exec api python -m scripts.ingest_docs
```

Harus 4 dokumen dan 103 chunk. Cek: `SELECT count(*) FROM rag_chunks;` harus `103`.

## e. Pasang nginx host lalu certbot

Backup konfigurasi nginx host dulu. Salin `deploy/nginx-host.conf.example` menjadi vhost baru,
ganti `server_name` dan samakan `proxy_pass` dengan `APP_HOST_PORT`, lalu:

```bash
nginx -t && systemctl reload nginx
certbot --nginx -d jalurku-api.domainmu.com
```

## f. Cek model, hangatkan demo

```bash
python -m scripts.list_models        # cari nama model yang valid hari itu
python -m scripts.check_gemini       # cek kunci + model utama/cadangan + embedding
python -m scripts.siapkan_demo --base-url http://127.0.0.1:8000 --hangatkan
```

`siapkan_demo` butuh `DATABASE_URL` yang sama dengan server (jalankan di dalam kontainer `api`
atau dari mesin yang menjangkau DB). Opsi `--hangatkan` membuat sesi demo 72 jam dan menghangatkan
cache LLM untuk rekaman.

## g. Smoke test dari luar

```bash
python -m scripts.smoke_test --base-url https://jalurku-api.domainmu.com --prod --lewat-proxy
```

Semua pemeriksaan harus lulus. Catatan: cek "header keamanan nginx" (`--lewat-proxy`) menuntut
`X-Content-Type-Options: nosniff` dan `Cache-Control: no-store` dari vhost host — contoh vhost
menyediakannya sebagai baris opsional (berpagar). Bila host tidak memasangnya, jalankan smoke
tanpa `--lewat-proxy` (semua pemeriksaan endpoint tetap jalan).

## h. Uji pembatas laju dari dua perangkat berbeda

Dari satu perangkat, kirim 21 kali `POST /session` beruntun (batas `buat_sesi_per_ip`: 20 per
60 detik): permintaan ke-21 harus `429`, dan perangkat lain pada saat yang sama harus tetap `201`.
Bila perangkat lain ikut `429`, IP klien tidak terbaca benar — periksa `TRUSTED_PROXIES` dan header
`X-Forwarded-For` di vhost host.

## i. Backup dan rollback

- Backup DB berkala: `pg_dump` dari kontainer `db` (nama kontainer ikut nama proyek compose).
- Rollback: hapus symlink vhost (`sites-enabled`), `nginx -t && systemctl reload nginx`; hentikan
  stack dengan `docker compose ... down` **tanpa `-v`**.
- Peringatan: jangan hapus volume `dbdata` dan jangan hapus folder PDF (`DOKUMEN_DIR`).

## j. Pemecahan masalah

- **Port 8000 terpakai**: isi `APP_HOST_PORT` lain di `deploy/.env.prod`, naikkan ulang stack,
  dan samakan `proxy_pass` di vhost host.
- **CORS salah**: origin frontend harus persis (termasuk skema) di `CORS_ORIGINS`; error terlihat
  sebagai kegagalan preflight di browser, bukan di smoke test.
- **`REQUIRE_VERIFIED` menolak start**: API sengaja tidak naik bila tabel kritis memuat baris
  tanpa `terakhir_diverifikasi`. Lihat log kontainer api, isi tanggal yang kurang, ingest ulang.
- **502 dari nginx**: api belum sehat / `APP_HOST_PORT` tidak cocok dengan `proxy_pass`; cek
  `docker compose ... ps` dan `logs api`. Pastikan hanya path `/api/` yang diteruskan.
