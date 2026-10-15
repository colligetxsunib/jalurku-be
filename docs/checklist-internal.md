# Checklist internal

> Dokumen kerja internal tim (dipindah verbatim dari README bagian 15 per 15 Okt 2026).
> Centang, nama berkas, dan penugasan siapa-mengisi-apa hanya berlaku untuk tim inti.
> Calon kontributor luar mulai dari README bagian Kontribusi.

---

## 15. Yang perlu dikerjakan selanjutnya

### A. Tim data (tidak butuh kode)

Status per 15 Oktober 2026. Item bercentang sudah selesai.

**Sudah selesai**

- [x] **Tanggal verifikasi** di `rule_gate.csv`, `config_ketentuan.csv`, `dokumen_wajib.csv`, dan `ptn.csv` (2026-10-14), sudah di-ingest dan `scripts.check_verified` lulus untuk tabel kritis.
- [x] **Kelompok pita SNBT** diubah ke `program`; `harapan.penilaian` Rani dan Dimas diperbarui (perubahan di 7.2).
- [x] **Kalibrasi**: diputuskan memakai nilai bawaan dengan label "indikatif, belum dikalibrasi", dicatat sebagai keterbatasan di PRD v1.1. `skala_skor_tryout` dinonaktifkan.
- [x] **Data keketatan**: SNBP, sembilan PTN lain, dan `acuan_skor_snbt.csv` sengaja dikosongkan. Hasilnya `belum_ada_acuan`, demo hanya UI.
- [x] **Golden set RAG** 23 baris (`golden_set.csv`), skrip pengisi halaman dari PDF sudah ada dan sudah dijalankan.
- [x] **Catatan "demo memakai data fiktif"** dikirim backend lewat field `pemberitahuan`.
- [x] **Catat perubahan PRD v1.1** (log perubahan, kontrak, keterbatasan) di PRD bagian 18.
- [x] **Unduh PDF** dokumen resmi: 4 dari 5 sudah ada di `data/dokumen/`.
- [x] **Tanggal verifikasi `prodi.csv` dan `dokumen_rag_metadata.csv`** (15 Okt 2026): `prodi.csv` 31 baris (semuanya UI yang berdata keketatan) bertanggal 2026-10-15, 154 baris lain sengaja kosong karena tanpa data acuan; `dokumen_rag_metadata.csv` 4 dari 5 bertanggal 2026-10-15, `snpmb-faq` sengaja kosong karena PDF-nya tidak pernah diunduh dan tidak ada di basis RAG. `scripts.check_verified`: tabel kritis OK (`rules_jalur` 2/2, `ketentuan` 22/22, `acuan_skor` 0/0), katalog OK (154 prodi tanpa data hanya INFO). Catatan: `dokumen_sumber` terbaca 5/5 karena skrip membaca DB yang di-ingest sebelum CSV diubah; ingest ulang akan menyelaraskan ke 4/5. Catatan 2: skrip saat ini berhenti di bagian persona karena format tanggal di `rani.json` (lihat item Rani di bawah).
- [x] **Verifikasi persona Rani** oleh pemilik data: `hasil_terverifikasi: true`, `diverifikasi_oleh: Rakhis-Yudha`, tanggal tertulis "10-Oktober-2026" di `config/personas/rani.json`. Lembar verifikasi `reports/verifikasi_rani.md` (35 cocok, 0 tidak cocok) menjadi dasar penandatanganan. **Perhatian**: tanggal tertulis bukan format YYYY-MM-DD sehingga validasi persona gagal — `scripts.check_verified` berhenti di bagian persona dan suite tes saat ini 23 gagal + 2 error pengumpulan (semuanya `PersonaError` dari string tanggal ini). Pemilik data perlu menulis ulang tanggalnya format YYYY-MM-DD. Persona Dimas, Budi, Sinta dan `config/golden/gate.json` (0/33) tetap `false` (keputusan pemilik data).

**Masih terbuka**
- [ ] **Cek halaman golden RAG**: 13 pertanyaan dalam cakupan sudah disiapkan lembar kerjanya di `reports/lembar_verifikasi.csv` (dokumen, halaman, kutipan pendek, status). Hasil pencarian otomatis: 6 `ditemukan`, 7 `perkiraan`, 0 `tidak ditemukan`. Periksa kutipan tiap baris, lalu isi kolom `halaman` di `data/seed/golden_set.csv` secara manual (jangan otomatis).
- [ ] **PDF `snpmb-faq`** (halaman web) belum ada di `data/dokumen/`.
- [ ] **Cek provinsi UI** di daftar resmi SNPMB. Provinsi tetap Jawa Barat sampai pemilik data memberi kabar. Bila berubah (mis. DKI Jakarta), ganti `provinsi` pada keempat persona.
- [ ] **Data eksplorasi resmi**: `tag_minat` dan `mapel_penentu` per prodi, serta `profesi.csv`. Saat ini `/explore` memakai **draf** di `data/draft/` (dibuat `scripts.buat_draf_eksplorasi`, berlabel "draf, belum terverifikasi", tanpa tanggal verifikasi). Verifikasi dan pindahkan ke CSV utama; data resmi otomatis didahulukan.
- [ ] **Review butir RIASEC** oleh pemilik data dan guru BK: `data/riasec/instrumen_v1.json` sudah
  berisi 36 butir orisinal tim (draf), lembar kerjanya di `reports/butir_riasec_review.csv`. Validasi
  psikometrik belum dilakukan. Setelah butir diubah, jalankan `scripts.build_api_collection`.
- [ ] **Konfirmasi hukum** soal data anak (UU PDP) dan persetujuan orang tua/wali. Belum dikerjakan; **syarat sebelum peluncuran nyata**.

### B. Backend dan AI

Status dicek 15 Oktober 2026 dengan panggilan Gemini nyata.

- [x] **`GEMINI_API_KEY`, model, dan kuota**: kunci dikonfirmasi pemilik. `scripts.check_gemini` lulus untuk embedding (`gemini-embedding-001`, 768 dimensi), model utama, dan model cadangan.
- [x] **Model generatif dan rantai cadangan** (15 Okt 2026): `LLM_MODEL=gemini-flash-lite-latest`, `LLM_MODEL_FALLBACK=gemini-3.1-flash-lite`, `timeout_detik: 10`. Rantai: model utama, ulangi sekali bila 503, model cadangan, lalu teks template. Fallback menangani 404, 429, 503, dan timeout; error lain (kredensial, 400) langsung ke template. Respons API tidak pernah 5xx karena LLM gagal. Alasan: `gemini-3.1-flash-lite` terukur tidak stabil (1,5 sampai 17 detik, 503, 504), sedangkan `gemini-flash-lite-latest` 8 dari 8 berhasil dalam 1 sampai 2,5 detik. Nama `-latest` adalah alias yang bisa berpindah versi.
- [x] **Ingest dokumen RAG sungguhan**: 4 dari 5 dokumen masuk (103 chunk). `snpmb-faq` sekarang opsional: bila berkasnya belum ada, ingest melewatinya (`[LEWATI]`) tanpa error.
- [x] **Ambang skor RAG: keputusan diambil — tidak disetel** (tetap 0,55 di `config/app.yaml`). Skor pertanyaan dalam cakupan (0,75 sampai 0,81) tumpang tindih dengan di luar cakupan (0,65 sampai 0,76), jadi ambang bukan pemisah dan 0,55 hampir tidak pernah menolak. Pemisahan bergantung pada instruksi LLM dan sitasi (PRD bagian 18). Keputusan ini dicatat sebagai keterbatasan.
- [x] **Golden RAG angka akhir** (`scripts.run_golden_set --rag`, 15 Okt 2026, 23 pertanyaan, cache dikosongkan, file `reports/golden_rag_20261015-095036.csv`): dalam cakupan **11 dari 13** lulus proksi otomatis (84,6 persen), di luar cakupan 6 dari 6, keputusan mesin aturan 4 dari 4, fallback 0. Sebelum perubahan prompt: 9 dari 13, 5 dari 6, 4 dari 4. Ini skor proksi, **bukan akurasi**. Dua yang gagal proksi dinilai **benar** oleh manusia di kedua berkas: baris 5 (halaman kutipan beda dari rujukan) dan baris 14 (jawaban 30% PTNBH benar; proksi gagal karena rujukan golden memuat tambahan 40% BLU yang tidak ditanyakan). Hasil bervariasi antar-run karena LLM tidak deterministik. Run ulang hari yang sama (`reports/golden_rag_20261015-120118.csv`) mendapat skor proksi yang sama (11/13, 6/6, 4/4, 0 fallback); 14 dari 23 jawaban berubah redaksionalnya, status lulus **proksi** tiap baris tidak berubah — tetapi penilaian manual berubah pada baris 3 dan 8 (benar→sebagian, lihat item `nilai_manual`).
- [x] **Isi `nilai_manual`** di kedua berkas golden (`095036` dan `120118`): 095036 → 13+6+4 **benar**; 120118 → dalam cakupan 11 benar + 2 sebagian (baris 3 dan 8), luar cakupan 6 benar, keputusan 4 benar. Penilai adalah pemilik data dengan draf bantuan (bukan independen); 23 pertanyaan (sampel kecil). Temuan manual run 120118: baris 3 turun benar→sebagian (kalimat batas umur 25 tahun terbaca berlaku untuk semua lulusan, padahal rujukan hanya Paket C — cek teksnya di panduan, bisa naik ke benar); baris 8 turun benar→sebagian (kasus 3 pilihan hilang pada run ini; run sebelumnya lengkap). Laporkan metrik apa adanya di pitch. Skor proksi bukan akurasi.
- [x] **Uji ketersediaan terhadap API nyata**: `/query` (7 jawaban jatuh ke template saat timeout dan 503 nyata, tanpa 5xx), dan narasi `/summary` (utama normal: narasi LLM; utama 404 lalu cadangan: narasi LLM; semua model gagal: narasi template, HTTP 200). Respons 429 nyata belum teramati sebagai respons API.
- [ ] **Uji kualitas kategori** secara mundur (backtest) dengan data tahun lalu bila tersedia. Sampai saat itu kategori hanya boleh dikomunikasikan sebagai heuristik.

### C. Deploy dan integrasi FE

Semua belum selesai. Urutan kerja yang disarankan di hari deploy:

- [ ] **VPS dan domain/subdomain** disiapkan; DNS menunjuk ke server; port 80/443 terbuka.
- [ ] **`.env` server** (jangan pakai berkas dev): `REQUIRE_VERIFIED=true`, `ADMIN_KEY` baru (bukan kunci smoke `kunci-smoke-uji-123`), `CORS_ORIGINS` ke origin frontend, kunci Gemini (`GEMINI_API_KEY`) dan nama model (`LLM_MODEL`, `LLM_MODEL_FALLBACK`, `EMBED_MODEL`) yang valid.
- [ ] **`compose up`, migrasi, dan ingest di server**: `alembic upgrade head`, `scripts.ingest`, `scripts.ingest_docs`; pastikan 103 chunk masuk (`SELECT count(*) FROM rag_chunks`).
- [ ] **`scripts.check_gemini` di hari deploy** (nama model bisa dihentikan penyedia; `-latest` bisa berpindah versi).
- [ ] **`siapkan_demo --hangatkan` di server** untuk sesi demo 72 jam dan cache LLM hangat sebelum rekaman.
- [ ] **Smoke test terhadap URL publik** (`scripts.smoke_container`/`smoke_test`): semua endpoint 200/201/204 sesuai harapan, `/docs` mati di produksi, admin 401 tanpa kunci dan 404 bila `ADMIN_KEY` kosong.
- [ ] **Konfirmasi dengan tim FE** soal field respons RIASEC yang dibaca dashboard: `holland_code`, `dimensi_teratas`, `skor_norm`, `keyakinan`, `alasan_keyakinan`, `min_terjawab`, `pernyataan`, `instrumen_contoh` (kontrak di `app/schemas/riasec.py`; tambahan satu-satunya adalah `min_terjawab`).
- [ ] **Deploy ke VPS**, jalankan `init-cert.sh` (coba `STAGING=1` dulu), lalu `smoke_test` dari luar server.
- [ ] **Ekspor halaman statis persona** (`scripts.export_persona_static`) dan salin `data/demo_statis/` ke server.
- [ ] Atur firewall (hanya 80/443), pencadangan volume `dbdata`, dan pemantauan log.
- [ ] Bila trafik tumbuh melebihi satu proses: pindahkan rate limiter dan batas konkurensi LLM ke penyimpanan bersama (mis. Redis) sebelum menambah worker.

### D. Frontend dan integrasi

- [ ] Integrasi alur A dan B sesuai diagram di 3.1, tombol "Muat persona demo" (`POST /session` lalu `PUT /profile` dari `config/personas`), indikator pemuatan untuk `/query` dan `/summary`.
- [ ] Tampilkan **matriks kecocokan x kelayakan** dari `/explore`, label `indikatif` dan `keyakinan` pada setiap kategori, serta `status_verifikasi` per hasil.
- [ ] Teks consent dan catatan "prototipe, jangan isi data pribadi nyata" ada di frontend. Backend hanya mencatat `consent_at` dan `consent_version`.
- [ ] Halaman ringkasan siap cetak (ekspor PDF cukup dari halaman web).

### E. Roadmap (di luar MVP)

Timeline personal, mentor matching, draf email/esai, jalur Mandiri dan beasiswa, pengecekan pembaruan aturan otomatis, dan LLM untuk mengubah cerita minat bebas menjadi profil terstruktur.
