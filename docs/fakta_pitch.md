# Fakta untuk pitch (angka yang bisa dipertanggungjawabkan)

Semua angka di bawah bisa diperiksa ulang dengan perintah yang disebutkan. Tidak ada angka yang
tidak punya sumber. Ditulis 15 Oktober 2026 untuk submit hackathon.

## 1. Mesin aturan (deterministik)

| Angka | Sumber cara memeriksa |
|---|---|
| Gate **33 dari 33** kasus uji sesuai | `uv run python -m scripts.run_golden_set` (`config/golden/gate.json`, 13 syarat, kasus tepi) — terakhir jalan 15 Okt 2026 |
| Persona demo **20 dari 20** ekspektasi sesuai (4 gate + 16 penilaian kategori) | perintah yang sama; persona di `config/personas/` — terakhir jalan 15 Okt 2026 |
| Suite tes **978 tes** | `uv run pytest` (PostgreSQL kontainer). Terakhir hijau 978/978 pada 15 Okt 2026 (tag `v1.2-submit`, sebelum edit pemilik data). Saat ini 23 gagal + 2 error pengumpulan, semuanya `PersonaError` dari format tanggal verifikasi di `config/personas/rani.json` (kode tidak berubah sejak terakhir hijau) |
| Katalog: 10 PTN, 185 prodi, 10 rumpun | `data/seed/ptn.csv`, `data/seed/prodi.csv` |
| **31 prodi** (semuanya UI, 9 dari 10 rumpun) punya `daya_tampung` + `peminat_tahun_lalu`; sisanya tanpa data acuan sehingga penilaiannya `belum_ada_acuan`, bukan ditebak | `scripts.check_verified --detail` |

Catatan wajib: harapan gate dan persona **ditulis tim dari pembacaan syarat resmi**. Verifikasi
manusia: 0 dari 33 kasus `gate.json`; persona Rani **sudah ditandatangani pemilik data**
(`hasil_terverifikasi: true`, `diverifikasi_oleh: Rakhis-Yudha`, tanggal tertulis
"10-Oktober-2026", berdasar `reports/verifikasi_rani.md`: 35 cocok, 0 tidak cocok), tiga persona
lain masih `false`. **Perhatian**: tanggal tertulis bukan format YYYY-MM-DD sehingga validasi
persona gagal saat ini. Jadi 33/33 dan 20/20 adalah **kunci regresi** (mesin tidak berubah
perilaku), bukan bukti kebenaran yang dinilai independen.

## 2. RAG (tanya-jawab dokumen resmi)

Knowledge base: **4 dokumen ter-ingest, 103 chunk** (`snpmb-paparan-2026` 20, `unej-panduan-snbp-2026` 40,
`unej-panduan-snbt-2026` 39, `snpmb-sipers-2026` 4). Dokumen kelima (`snpmb-faq`, halaman web) belum
diunduh; ingest sekarang melewatinya dengan pesan `[LEWATI]`, bukan error. Cek: `SELECT dokumen_id,
count(*) FROM rag_chunks GROUP BY 1`.

Golden set: **23 pertanyaan** (13 dalam cakupan, 6 di luar cakupan, 4 keputusan).

**Skor proksi otomatis** (kecocokan sumber, halaman, dan angka kunci — BUKAN akurasi jawaban):

| Kelompok | Angka akhir 15 Okt 2026 | Berkas |
|---|---|---|
| Dalam cakupan | **11 dari 13 (84,6%)** | `reports/golden_rag_20261015-095036.csv` |
| Di luar cakupan (menolak dengan jujur) | **6 dari 6** | idem |
| Keputusan (dijawab mesin aturan) | **4 dari 4** | idem |
| Jatuh ke teks cadangan | **0** | idem |

Run ulang hari yang sama dengan cache LLM dikosongkan (`reports/golden_rag_20261015-120118.csv`)
mendapat skor proksi yang sama (11/13, 6/6, 4/4, 0 fallback). Empat belas dari 23 jawaban berubah
redaksionalnya; status lulus **proksi** tiap baris tidak berubah — tetapi penilaian manual berubah
pada dua baris (lihat tabel di bawah). Dua baris dalam cakupan yang gagal proksi dinilai **benar**
oleh manusia di kedua berkas: baris 5 (halaman kutipan beda dari rujukan) dan baris 14 (jawaban
30% PTNBH benar; proksi gagal karena rujukan golden memuat tambahan 40% BLU yang tidak ditanyakan).

**Nilai manual pemilik data** (dihitung dari berkas, `nilai_manual`). Penilai adalah pemilik data
dengan draf bantuan (bukan independen); 23 pertanyaan (sampel kecil).

Berkas 095036:

| Tipe | benar | sebagian | salah |
|---|---|---|---|
| Dalam cakupan | 13 | 0 | 0 |
| Di luar cakupan | 6 | 0 | 0 |
| Keputusan | 4 | 0 | 0 |
| **Jumlah** | **23** | **0** | **0** |

Berkas 120118 (kedua berkas kini terisi penuh):

| Tipe | benar | sebagian | salah |
|---|---|---|---|
| Dalam cakupan | 11 | 2 (baris 3 dan 8) | 0 |
| Di luar cakupan | 6 | 0 | 0 |
| Keputusan | 4 | 0 | 0 |
| **Jumlah** | **21** | **2** | **0** |

Temuan manual run 120118: baris 3 turun benar→sebagian (kalimat batas umur 25 tahun terbaca
berlaku untuk semua lulusan, padahal rujukan hanya Paket C — cek teksnya di panduan, bisa naik ke
benar); baris 8 turun benar→sebagian (kasus 3 pilihan hilang pada run ini; run sebelumnya
lengkap).

Lembar verifikasi halaman untuk 13 pertanyaan dalam cakupan: `reports/lembar_verifikasi.csv`
(6 `ditemukan`, 7 `perkiraan`, 0 `tidak ditemukan`; kolom `halaman` di `golden_set.csv` sendiri sengaja
tidak diisi otomatis).

## 3. Cakupan dan status verifikasi data

- **10 PTN** di katalog, namun **hanya UI** yang punya data keketatan SNBT (31 prodi: daya tampung +
  peminat tahun lalu, 9 dari 10 rumpun). Prodi lain tidak ditebak: kategori `belum_ada_acuan`.
- `prodi.csv`: 31 baris UI bertanggal **2026-10-15**, 154 baris lain sengaja kosong (tanpa data acuan).
- `dokumen_rag_metadata.csv`: 4 dari 5 bertanggal **2026-10-15**; `snpmb-faq` sengaja kosong (berkasnya
  tidak pernah diunduh, tidak ada di basis RAG). Catatan: `scripts.check_verified` membaca DB, bukan
  CSV — DB masih memuat tanggal ingest lama sehingga `dokumen_sumber` terbaca 5/5; ingest ulang akan
  menyelaraskan ke 4/5.
- `acuan_skor_snbt.csv` sengaja **kosong** (skala skor tryout dinonaktifkan): skor SNBT hanya jadi
  penanda, tidak jadi acuan.
- Data eksplorasi (tag minat, mapel penentu, contoh profesi) kini memakai **draf** di `data/draft/`
  yang diturunkan mekanis dari klasifikasi rumpun, berlabel "draf, belum terverifikasi", dan dipakai
  hanya bila data resmi kosong.
- Semua angka kalibrasi (bobot kategori reach/match/safe, ambang skor RAG, ambang cek kualitas tes
  minat) adalah **nilai awal yang belum dikalibrasi** di `config/app.yaml`.

## 4. Catatan wajib kalau angka dipakai di depan juri

1. **Penilai adalah pemilik data dengan draf bantuan, bukan independen.** Harapan golden (gate,
   persona, dan RAG) ditulis oleh tim yang sama yang menulis mesinnya; penilaian manual jawaban
   RAG juga oleh pemilik data.
2. **Sampel kecil:** 23 pertanyaan golden; sebagian besar baris menguji hal yang sempit.
3. **Butir golden disusun tim dari sumber yang sama** dengan knowledge base (dokumen SNPMB resmi), jadi
   kecocokan sumber dan halaman bukan bukti retrivel yang luas.
4. **Baris bertipe keputusan dan di luar cakupan hanya mengukur pengalihan dan penolakan** (jawaban
   `mesin_aturan`, `yakin=false`), bukan kebenaran keputusan. Kebenaran keputusan dibuktikan terpisah
   oleh 33 kasus gate.
5. **Sitasi tingkat halaman belum andal:** skor proksi memeriksa halaman, tetapi 7 dari 13 halaman
   dalam cakupan baru berstatus "perkiraan" dan baris 5 gagal karena alasan halaman.
6. **LLM tidak deterministik:** jawaban bisa berbeda antar-run; skor bisa bergerak beberapa titik.

## 5. Keterbatasan yang jujur (jangan disembunyikan)

- **Kategori reach/match/safe adalah heuristik**, label di setiap respons: "indikatif, belum
  dikalibrasi". Tidak ada persentase peluang diterima.
- **Tidak ada acuan skor SNBT** (`acuan_skor` kosong); prodi tanpa daya tampung/peminat selalu
  `belum_ada_acuan`.
- **SNBP tanpa data keketatan:** penilaian SNBP hanya gate + matriks, bukan peringkat peluang.
- **Penolakan di luar cakupan bergantung instruksi LLM dan sitasi**, bukan pada ambang skor.
  Keputusan 15 Okt 2026: `rag.ambang_skor` (0,55) **tidak disetel** (rentang skor dalam/luar cakupan
  tumpang tindih: 0,75–0,81 vs 0,65–0,76; menyetel dengan golden hanya overfit pada 23 pertanyaan).
- **Instrumen tes minat RIASEC belum divalidasi psikometrik** dan bukan tes psikologi; butir orisinal
  tim, menunggu review guru BK (`reports/butir_riasec_review.csv`).
- **Belum ada backtest** kategori dengan data tahun lalu.
- **Konfirmasi hukum data anak (UU PDP) belum dilakukan** — syarat sebelum peluncuran nyata; sampai itu
  setiap respons membawa pemberitahuan "demo memakai data fiktif".
- **Verifikasi manusia**: persona Rani sudah ditandatangani pemilik data (dengan catatan format
  tanggal, lihat bagian 1); tanggal `terakhir_diverifikasi` `prodi.csv` (31 baris UI) dan
  `dokumen_rag_metadata.csv` (4/5) sudah terisi 2026-10-15; `nilai_manual` kedua berkas golden
  terisi penuh; halaman golden masih menunggu (lembar `reports/lembar_verifikasi.csv`).
