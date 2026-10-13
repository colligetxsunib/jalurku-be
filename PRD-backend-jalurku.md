# PRD Backend — JalurKu

| | |
|---|---|
| **Versi** | 1.0 (baseline, **dibekukan 13 Oktober 2026**; disusun dari "PRD Backend JalurKu v0.2") |
| **Status** | Dibekukan untuk implementasi. Scope hackathon dipotong untuk 3 hari |
| **Deadline** | 16 Oktober 2026 |
| **Stack backend** | Python 3.11+, FastAPI, Pydantic, PostgreSQL + pgvector, Gemini via Google AI Studio API |
| **Nama produk** | "JalurKu" (sementara). Berkas asli berjudul "PathWise". |

**Cara membaca dokumen ini**

- Isi berasal dari PRD v0.2. ID kebutuhan (FR-xx) dipertahankan agar mudah ditelusuri.
- **[Usulan]** menandai tambahan penyusun untuk menutup celah di v0.2. Dengan pembekuan 13 Oktober, semua [Usulan] **dianggap disetujui**, kecuali yang masih tercantum di daftar terbuka (bagian 17).
- **[Diputuskan]** menandai keputusan tim pada 13 Oktober 2026 yang menggantikan teks v0.2 atau usulan sebelumnya.
- Aturan resmi SNPMB (batas tahun lulus, jumlah pilihan, syarat sekolah SNBP) **belum diverifikasi** di dokumen ini. Semua angka aturan, bobot, ambang, dan isi matriks hanya contoh atau placeholder sampai diverifikasi tim data.
- Temuan ketidakkonsistenan di v0.2 ada di **Lampiran A**.

### Aturan setelah pembekuan

| Dibekukan (ubah hanya jika memblokir implementasi, dan catat di Log Perubahan, bagian 18) | Bebas diubah tanpa revisi PRD |
|---|---|
| Kontrak API (bagian 11) dan skema DB (bagian 10) | Isi `config/` dan data: rule gate, bobot, ambang, pita keketatan, isi matriks SNBP, katalog, acuan skor, dokumen RAG |
| Struktur konfigurasi (nama dan bentuk kunci) | Teks template penjelasan dan teks fallback |
| Prinsip 8.1 dan 8.5 (keputusan oleh mesin aturan, bukan LLM) | Urutan prioritas dalam urutan pemotongan (bagian 16), selama "yang tidak boleh dipotong" tetap |

Tidak ada fitur baru setelah pembekuan. Ide baru masuk backlog roadmap.

---

## 1. Ringkasan

JalurKu adalah web app yang membantu siswa SMA kelas akhir menentukan jurusan, memilih jalur (SNBP/SNBT), dan merencanakan langkah menuju kuliah sesuai minat dan kemampuan. Nilai jualnya bukan chatbot, melainkan **keputusan yang bisa dipertanggungjawabkan**:

- rekomendasi jurusan berbasis minat + nilai,
- pengecekan syarat jalur yang deterministik,
- penilaian reach/match/safe yang transparan,
- simulator strategi pilihan prodi dengan skenario what-if.

Dokumen ini mendefinisikan kebutuhan **sistem backend** untuk MVP hackathon.

## 2. Latar Belakang dan Masalah

- Siswa bingung memilih jurusan dan tidak tahu apakah pilihannya realistis.
- Informasi jalur (SNBP/SNBT) tersebar di banyak dokumen dan berubah tiap siklus.
- Alat yang ada terpisah: tes minat berhenti di minat, situs kampus berhenti di data umum, chatbot berhenti di Q&A. Tidak ada yang menyambungkan **minat → jurusan → kelayakan → strategi**.

## 3. Tujuan dan Non-Tujuan

### Tujuan MVP

1. Siswa menyelesaikan alur dari profil sampai ringkasan strategi dalam ± 10 menit.
2. Setiap rekomendasi dan status kelayakan disertai alasan dan sumber yang bisa diperiksa.
3. Keputusan (lolos/tidak lolos syarat, kategori) dihasilkan **logika deterministik, bukan LLM**.
4. AI menjelaskan dan menjawab pertanyaan berbasis dokumen resmi dengan sitasi, dan jujur saat tidak yakin.
5. Sistem bisa dievaluasi: ada golden set dan metrik akurasi yang bisa ditunjukkan ke juri.

### Non-tujuan (tidak dibangun di MVP)

- Timeline personal, mentor matching, draft email/esai (roadmap).
- Jalur mandiri dan beasiswa (hanya SNBP dan SNBT).
- Prediksi peluang dalam bentuk persentase.
- Fine-tuning model, LLM lokal di VPS, agent multi-turn.
- Integrasi dengan sistem resmi SNPMB atau kampus.
- Aplikasi mobile native (web mobile-first saja).
- Login email/password dan akun pengguna (MVP memakai sesi tamu).

## 4. Pengguna dan Skenario

**Pengguna utama:** siswa SMA/SMK/MA kelas 12 yang akan mendaftar kuliah lewat SNBP atau SNBT.
**Pengguna sekunder (di luar MVP):** guru BK pendamping.

| Skenario | Alur |
|---|---|
| **A. Belum punya target** | Rani mengisi profil dan minat → memilih "belum punya target" → mendapat 5 rekomendasi jurusan beserta alasan → memilih 3 → sistem menganalisis kelayakan jalur dan kategori reach/match/safe per prodi → ia menyusun 4 pilihan di simulator → mendapat ringkasan strategi. |
| **B. Sudah punya target** | Dimas langsung memilih 3 prodi tujuan → sistem mengecek syarat jalur, menampilkan gap, dan memberi saran komposisi pilihan. |
| **Tepi** | Lulusan melebihi batas tahun yang diizinkan SNBT → sistem menyatakan jalur tidak memenuhi syarat beserta alasannya dan **tidak menghitung kategori peluang**. |

## 5. Lingkup MVP

| Modul | Status | Endpoint utama |
|---|---|---|
| Sesi tamu (login → roadmap) | Wajib | `POST/GET/DELETE /session` |
| Profil siswa (nilai, sekolah, minat) | Wajib | `GET/PUT /profile` |
| Katalog PTN dan prodi | Wajib | `GET /catalog/*` |
| Analisis target: gate + penilaian | Wajib | `POST /analyze` |
| Penilaian reach/match/safe SNBP | Wajib, berlabel **indikatif** + tingkat keyakinan | `POST /analyze` |
| Simulator strategi + what-if | Wajib | `POST /strategy` |
| Ringkasan strategi | Wajib | `POST /summary` |
| AI kontekstual + RAG bersitasi | Wajib | `POST /query` |
| Eksplorasi jurusan | Versi sangat sederhana, tanpa LLM; dilewati jika waktu habis | `POST /explore` |
| Timeline, mentor, draft | Roadmap | — |

**Cakupan data MVP**

- **10 PTN:** UI, UGM, ITB, UNAIR, IPB, Brawijaya, ITS, UNHAS, UNDIP, UNS.
- **17 prodi:** Teknologi Informasi/Ilmu Komputer, Akuntansi, Hukum, Kedokteran Umum, Komunikasi, Desain Komunikasi Visual, Psikologi, Manajemen, Hubungan Internasional, Teknik Sipil, Teknik Industri, Teknik Mesin, Teknik Kimia, Arsitektur, Teknik Lingkungan, Kedokteran Gigi, Teknik Elektro.
- **Jalur:** SNBP dan SNBT.
- **Kedalaman:** katalog ringan untuk semua. Data acuan mendalam hanya untuk subset sekitar 4–5 PTN × 5–6 prodi. Sisanya tampil `belum_ada_acuan`.
- **Bahasa antarmuka dan jawaban:** Indonesia saja.

## 6. Alur Produk dan Peran Backend

Prinsip: **target dulu, jalur belakangan.** Jalur yang tersedia adalah hasil analisis dari target, bukan halaman terpisah.

| # | Langkah | Tanggung jawab backend | Endpoint |
|---|---|---|---|
| 1 | Landing dan consent | Catat persetujuan sebelum data diproses | `POST /session` |
| 2 | Sesi tamu | Buat token sesi otomatis | `POST /session` |
| 3 | Profil | Simpan parsial, validasi, kembalikan `data_kurang` | `PUT /profile` |
| 4 | Percabangan target | Sudah punya target (1–4 PTN + prodi) atau mode eksplorasi → shortlist | `GET /catalog/*`, `POST /explore` |
| 5 | Analisis target | Gate lalu penilaian per prodi per jalur | `POST /analyze` |
| 6 | Strategi pilihan | Evaluasi komposisi, saran swap, what-if | `POST /strategy` |
| 7 | Ringkasan strategi | Dokumen akhir yang siap cetak | `POST /summary` |
| 4–7 | AI kontekstual ("Kenapa?", pertanyaan balik, Q&A bebas) | RAG bersitasi | `POST /query` |

---

## 7. Kebutuhan Fungsional

### 7.1 Sesi Tamu (tanpa login)

| ID | Kebutuhan |
|---|---|
| FR-A1 | Saat siswa mulai, server membuat sesi anonim dan mengembalikan token acak berumur pendek. Tidak ada email atau password. |
| FR-A2 | Profil dan hasil disimpan dengan kunci id sesi, dihapus otomatis setelah masa berlaku sesi habis (contoh: 24 jam). |
| FR-A3 | Consent dicatat dengan timestamp pada sesi **sebelum** data apa pun diproses. |
| FR-A4 | "Hapus data saya" menghapus sesi dan seluruh data turunannya. |
| FR-A5 | Rate limiting per sesi dan per IP. |

**Kriteria penerimaan**

- `POST /session` tanpa `consent: true` ditolak, dan tidak ada baris sesi yang dibuat.
- Endpoint selain `/session` (POST) dan `/health` menolak token tidak valid atau kedaluwarsa dengan 401.
- Setelah `DELETE /session`, tidak ada baris di `profiles`, `strategies`, atau `query_logs` dengan `session_id` tersebut (cek via FK cascade).
- Sesi kedaluwarsa dibersihkan otomatis. **[Usulan]** pembersihan lewat tugas latar berkala, ditambah pengecekan `expires_at` pada setiap request.
- Token dibuat dengan generator acak kriptografis (≥ 256 bit). **[Usulan]** hanya hash token yang disimpan di DB.
- Roadmap: login email/password (argon2/bcrypt, JWT). **Tidak ada JWT di MVP.**

### 7.2 Profil

| ID | Kebutuhan |
|---|---|
| FR-P1 | Simpan dan perbarui profil secara parsial (boleh belum lengkap). |
| FR-P2 | Validasi rentang nilai (mis. 0–100), provinsi dari daftar baku, tahun lulus masuk akal. |
| FR-P3 | Kembalikan daftar `data_kurang` yang dibutuhkan untuk analisis tertentu. |
| FR-P4 | Kumpulkan data seminimal mungkin. Tidak ada data identitas sensitif di luar yang dibutuhkan logika. |

**Kriteria penerimaan**

- `PUT /profile` dengan sebagian field hanya mengubah field itu. Field yang tidak dikirim tidak berubah, dan `null` eksplisit menghapus nilai.
- Nilai di luar rentang menghasilkan 422 dengan detail per field.
- Respons menyertakan `data_kurang` per jalur, mis. `{"SNBT": ["skor_tryout"], "SNBP": ["peringkat_kelas"]}`.
- Tidak ada field nama, kontak, NIK, atau NISN di skema profil.

### 7.3 Katalog

| ID | Kebutuhan |
|---|---|
| FR-C1 | Daftar dan pencarian PTN dan prodi (filter nama, rumpun, provinsi, jalur yang dibuka). |
| FR-C2 | Detail prodi: akreditasi, daya tampung, jalur dibuka, mapel penentu, acuan tahun lalu, sumber. |

**Kriteria penerimaan**

- Prodi tanpa data acuan mengembalikan `acuan: null` dan `status_acuan: "belum_ada_acuan"`, bukan nilai tebakan.
- **[Usulan]** Ada `GET /catalog/prodi/{id}` untuk FR-C2 (belum ada di tabel API v0.2) dan paginasi (`page`, `limit`) pada endpoint daftar.

### 7.3b Eksplorasi Jurusan

| ID | Kebutuhan |
|---|---|
| FR-E1 | Terima profil minat dan nilai, kembalikan 5 jurusan/rumpun dengan skor kecocokan, alasan, dan contoh profesi. |
| FR-E2 | Skor kecocokan dihitung deterministik (lihat 8.3). Penjelasan dari template. LLM opsional jika ada waktu. |
| FR-E3 | Dari shortlist jurusan, kembalikan PTN yang membuka jurusan itu. |

**Kriteria penerimaan**

- Dengan input yang sama, urutan dan skor selalu sama (deterministik).
- Tiap rekomendasi memuat komponen skor (minat, nilai), alasan, dan ≥ 1 contoh profesi.
- Fitur ini berfungsi penuh **tanpa** memanggil LLM.

### 7.4 Analisis Target

| ID | Kebutuhan |
|---|---|
| FR-T1 | Untuk tiap target (PTN + prodi) dan jalur, jalankan gate (syarat mutlak) dengan keluaran per syarat: `lolos`, `gagal`, atau `data_kurang`. |
| FR-T2 | Jika ada syarat `gagal`, jalur dinyatakan tidak memenuhi syarat, alasan ditampilkan, penilaian **tidak dijalankan**. |
| FR-T3 | Jika ada `data_kurang`, kembalikan daftar pertanyaan yang perlu dijawab dan **jangan menebak**. |
| FR-T4 | Untuk yang lolos gate, jalankan penilaian: kategori reach/match/safe, gap, dan alasan (8.2). |
| FR-T5 | Setiap hasil menyertakan `sumber` dan `terakhir_diverifikasi`. |

**Kriteria penerimaan**

- Hasil gate sama untuk input yang sama dan tidak bergantung pada LLM atau jaringan.
- Kasus tepi di batas (mis. tahun lulus tepat di batas) diuji dan sesuai operator rule (`>=` berarti lolos di batas).
- Respons memuat `label` ("acuan siklus sebelumnya") bila data acuan berasal dari siklus sebelumnya.

### 7.5 Strategi Pilihan

| ID | Kebutuhan |
|---|---|
| FR-S1 | Terima daftar pilihan prodi. Batas jumlah pilihan mengikuti panduan resmi terbaru, **dikonfigurasi, bukan di-hardcode**. |
| FR-S2 | Evaluasi komposisi dengan aturan yang dapat dikonfigurasi (mis. minimal satu safe, maksimal setengah pilihan reach). |
| FR-S3 | Beri saran swap dari shortlist siswa bila komposisi tidak seimbang. |
| FR-S4 | What-if: terima override profil (nilai mapel, skor tryout) atau pergantian pilihan, hitung ulang seluruh hasil **tanpa menyimpan perubahan**. |

**Kriteria penerimaan**

- Request dengan `override` tidak mengubah baris mana pun di DB (diuji dengan membandingkan profil sebelum dan sesudah).
- Mengubah file konfigurasi (batas pilihan, rasio reach) mengubah perilaku tanpa perubahan kode.
- Setiap temuan komposisi berisi kode, tingkat (info/peringatan), pesan, dan saran swap bila relevan.

### 7.6 Ringkasan Strategi

| ID | Kebutuhan |
|---|---|
| FR-R1 | Hasilkan satu dokumen ringkas: pilihan akhir, alasan, gap, fokus persiapan, syarat/dokumen utama dengan sumber, dan catatan "acuan siklus sebelumnya". |
| FR-R2 | **[Diputuskan]** Ringkasan dapat dicetak atau disimpan sebagai PDF lewat halaman web siap cetak (cetak dari browser; tidak perlu pembuatan PDF di server). **Tidak ada tautan yang bisa dibagikan**: bentrok dengan TTL sesi 24 jam dan privasi data anak. |

**Kriteria penerimaan**

- Tidak ada endpoint yang mengembalikan ringkasan tanpa token sesi yang valid. Tidak ada token atau URL publik untuk berbagi ringkasan.
- **[Diputuskan]** Bila juri membutuhkan tautan: satu halaman statis hasil ekspor **persona fiktif** (dibuat offline oleh skrip dari data persona), disajikan sebagai file statis oleh reverse proxy, **terpisah dari data pengguna** (tanpa akses ke DB atau sesi).
- Seluruh angka dan status di ringkasan berasal dari mesin aturan. LLM hanya boleh menyusun narasi.
- Bila LLM gagal, ringkasan tetap lengkap dengan teks template.
- **[Usulan]** "Fokus persiapan" diturunkan deterministik dari gap (mapel/skor yang paling jauh dari acuan).
- **[Usulan]** "Dokumen utama" diambil dari data terkurasi (`rules_jalur.dokumen_wajib`), bukan dari RAG, agar konsisten dan tidak halusinasi.

### 7.7 AI Kontekstual dan RAG

| ID | Kebutuhan |
|---|---|
| FR-Q1 | **[Diputuskan]** Endpoint query menerima pertanyaan, `mode` (`tanya` atau `jelaskan`), dan **hanya identifier konteks** (`prodi_id`, `jalur`, serta `override` terstruktur untuk what-if). Ringkasan profil dan hasil analisis **dibangun server dari data sesi dan mesin aturan**, bukan dikirim klien. |
| FR-Q2 | Pipeline dua langkah: retrieve potongan dokumen resmi, lalu generate jawaban **hanya** dari konteks yang diambil. |
| FR-Q3 | Jawaban wajib menyertakan `sumber[]`. Jika skor retrieval di bawah ambang atau konteks tidak memuat jawaban, kembalikan `yakin: false` dan arahkan ke sumber resmi atau guru BK. Tidak boleh mengarang. |
| FR-Q4 | Respons menyertakan `data_dibutuhkan[]` (pertanyaan balik untuk melengkapi profil) dan `saran_pertanyaan[]`. |
| FR-Q5 | Pertanyaan yang meminta keputusan ("aku lolos nggak?") dijawab dengan merujuk hasil mesin aturan, bukan opini LLM. |

**Kriteria penerimaan**

- Jika skor retrieval tertinggi < ambang, respons `yakin: false` dikembalikan **tanpa memanggil LLM** (hemat kuota dan mencegah halusinasi). **[Usulan]**
- `sumber[]` dibangun server dari metadata chunk yang dipakai (judul, url, halaman), **bukan** dari teks keluaran LLM. **[Usulan]**
- **[Diputuskan]** Konteks profil dan hasil analisis dibangun **di server dari id**, tidak memuat PII. Skema request `/query` memakai `extra="forbid"`: body yang menyertakan field konteks bebas (mis. `hasil_analisis`, teks profil) ditolak 422. Ini harus punya tes otomatis.
- `override` boleh dikirim klien hanya sebagai **data terstruktur** yang divalidasi skema sama dengan `/analyze` (mis. `skor_tryout` bertipe angka dalam rentang), supaya "Kenapa?" pada hasil what-if menjelaskan angka yang sama dengan yang dilihat siswa. Server tetap menghitung ulang hasilnya sendiri.
- Mode `jelaskan` mewajibkan `prodi_id` dan `jalur`; penjelasan hanya boleh merujuk hasil mesin aturan untuk pasangan itu.
- Pertanyaan bertipe keputusan dideteksi (aturan kata kunci sederhana) dan dijawab dari hasil `/analyze`. **[Usulan]**
- Pertanyaan di-embed dengan `task_type=RETRIEVAL_QUERY` pada saat request (satu panggilan embedding per `/query`; hasilnya di-cache per pertanyaan ternormalisasi). Bila API embedding gagal, respons `yakin: false` dengan `fallback: true`, bukan error 5xx.

### 7.8 Admin dan Kurasi Data (internal)

| ID | Kebutuhan |
|---|---|
| FR-D1 | Skrip/endpoint internal untuk memuat data rule, katalog, dan dokumen RAG. |
| FR-D2 | Validasi skema saat impor: tiap rule dan dokumen wajib punya `sumber_url`, `terakhir_diverifikasi`, `tahun_siklus`. |

**Kriteria penerimaan**

- Impor yang melanggar FR-D2 ditolak dengan daftar error per baris. **[Usulan]** satu batch berjalan dalam satu transaksi (semua berhasil atau tidak sama sekali).
- **[Usulan]** Impor bersifat idempoten (upsert berdasarkan id).
- **[Diputuskan]** `/admin/ingest` dilindungi header `X-Admin-Key` yang dibandingkan dengan `ADMIN_KEY` dari environment variable (perbandingan waktu-konstan), bukan token sesi. Tanpa key atau key salah → 401. Jika `ADMIN_KEY` tidak diset, endpoint nonaktif (404).

---

## 8. Logika Inti

### 8.1 Tahap 1 — Gate (syarat mutlak)

Pencocokan aturan, bukan komputasi berat. Setiap jalur punya daftar syarat yang disimpan sebagai **data** (bukan kode). Contoh jenis syarat: batas tahun lulus SNBT; kelengkapan rapor semester 1–5 dan kelayakan sekolah untuk SNBP. Nilai pastinya wajib diverifikasi ke panduan resmi SNPMB siklus terkait.

Contoh bentuk rule (nilai hanya ilustrasi):

```json
{
  "jalur": "SNBT",
  "syarat": [
    {"id": "tahun_lulus", "field": "tahun_lulus", "op": ">=",
     "nilai": "tahun_ini - 3",
     "alasan_gagal": "Lulusan lebih dari batas tahun yang diizinkan tidak bisa ikut SNBT"}
  ],
  "dokumen_wajib": [{"nama": "...", "sumber_url": "..."}],
  "sumber_url": "url-panduan",
  "terakhir_diverifikasi": "YYYY-MM-DD",
  "tahun_siklus": 2026
}
```

**Resolusi status per syarat → status jalur**

| Kondisi | Status gate |
|---|---|
| Ada ≥ 1 syarat `gagal` (walau ada syarat lain `data_kurang`) | `tidak_memenuhi_syarat`: jalur gugur, penilaian tidak dijalankan |
| Tidak ada `gagal`, ada ≥ 1 `data_kurang` | `data_kurang`: kembalikan pertanyaan, jangan menebak |
| Semua `lolos` | `lolos`: lanjut ke 8.2 |

Catatan: `gagal` mengalahkan `data_kurang`, jadi siswa yang sudah pasti gugur tidak diminta mengisi data tambahan.

**[Usulan]** Operator rule dibatasi whitelist (`>=`, `<=`, `==`, `in`, `exists`, dst.). Rule dievaluasi dengan evaluator sendiri, **tanpa `eval()`**. Variabel dinamis seperti `tahun_ini` diambil dari konfigurasi (`tahun_acuan_pendaftaran`), bukan dari jam server. Lihat Lampiran A #10.

### 8.2 Tahap 2 — Penilaian reach/match/safe

Hanya untuk jalur yang lolos gate. Ini **heuristik, bukan probabilitas**. Tidak ada persentase peluang.

**Nilai `kategori` yang mungkin:** `reach`, `match`, `safe`, `belum_ada_acuan`, `data_kurang`.

#### SNBT

- Input: skor siswa (dari input tryout atau slider skenario) dan acuan prodi `{rendah, tinggi}` dari data tahun lalu.
- `skor >= tinggi` → **safe**
- `rendah <= skor < tinggi` → **match**
- `skor < rendah` → **reach**, `gap = rendah - skor`
- Skor belum ada → `data_kurang` (minta input).
- Prodi tanpa data acuan → `belum_ada_acuan` (jangan menebak).

#### SNBP (indikatif + tingkat keyakinan)

- Kategori tetap diberikan, **selalu berlabel "indikatif"** dan disertai `keyakinan` ∈ {`rendah`, `sedang`}. Tidak ada acuan nilai resmi, dan hasil dipengaruhi kuota sekolah serta rekam jejak alumni (bobot persis: cek panduan terbaru).
- Jika data alumni tidak ada → `keyakinan` otomatis `rendah` dan faktor yang tidak diketahui ditampilkan ke siswa.

**[Diputuskan] Model matriks 3×3.** Rumus margin dari draf sebelumnya dibuang: `skor_siswa` (dari rapor) dan `kebutuhan_prodi` (rasio peminat/daya tampung) berbeda jenis, sehingga selisihnya sulit dijelaskan dan ambangnya tidak punya dasar. Gantinya, dua sumbu dipisah lalu dipetakan lewat matriks yang berada di config, sehingga isinya bisa diubah tim data tanpa menyentuh kode.

1. **Tier siswa** (`lemah` / `sedang` / `kuat`): dari `skor_siswa`, rata-rata tertimbang faktor milik siswa yang **diketahui** (bobot dinormalisasi ulang atas faktor yang ada). Faktor yang dipakai: rapor (rata-rata sem 1–5 / 100), tren rapor, dan peringkat kelas (persentil), masing-masing dinormalisasi ke 0–1. Faktor yang tidak diketahui masuk `faktor_tidak_diketahui`. `f_rapor` wajib ada; bila tidak ada → `data_kurang`. Semua faktor berjenis sama (performa siswa), jadi dapat dirata-ratakan.
2. **Pita keketatan** (`rendah` / `sedang` / `tinggi`): dari `rasio = peminat_tahun_lalu / daya_tampung`, dipetakan lewat dua batas di config. Bila salah satu data tidak ada → `belum_ada_acuan` (tidak menebak).
3. **Kategori** = `matriks[tier][pita]`.
4. **Keyakinan**: `rendah` bila data alumni kosong atau `tidak_tahu`; selain itu `sedang`. Data alumni **tidak** ikut menentukan sel matriks, hanya keyakinan dan catatan yang ditampilkan.
5. **Output** memuat tier, pita, sel matriks yang terpakai, nilai tiap faktor siswa, `faktor_tidak_diketahui`, dan `catatan` sel, supaya alasan bisa dibaca juri.
6. **Akreditasi sekolah** tidak ikut menghitung tier. Ia dipakai di gate bila rule SNBP mensyaratkannya dan ditampilkan sebagai konteks. Jika tim data ingin memasukkannya ke tier, cukup tambahkan faktor dan bobot di config.

Isi awal matriks (placeholder, **bukan klaim akurasi**). Tiga sel yang di draf berupa "match/reach" harus menjadi **satu** kategori karena API mengembalikan satu nilai dan aturan komposisi 8.4 menghitungnya. Nilai awalnya diambil yang lebih berhati-hati (`reach`) dan keraguannya dipindahkan ke `catatan` yang ditampilkan ke siswa.

| | Keketatan rendah | Keketatan sedang | Keketatan tinggi |
|---|---|---|---|
| **Siswa kuat** | safe | match | reach\* |
| **Siswa sedang** | match | reach\* | reach |
| **Siswa lemah** | reach\* | reach | reach |

\* sel ber-`catatan` "berada di batas antara match dan reach".

```yaml
# config/app.yaml (nilai = placeholder, diisi dan dikalibrasi tim data)
snbp:
  tier_siswa:
    bobot: {rapor: 0.5, tren: 0.2, peringkat: 0.3}
    batas: {lemah_sedang: 0.60, sedang_kuat: 0.80}     # skor_siswa 0–1
  pita_keketatan:
    batas: {rendah_sedang: 5, sedang_tinggi: 15}       # rasio peminat/daya tampung
  matriks:                                             # baris = tier, kolom = pita
    kuat:   {rendah: {kategori: safe},  sedang: {kategori: match},
             tinggi: {kategori: reach, catatan: batas_match_reach}}
    sedang: {rendah: {kategori: match},
             sedang: {kategori: reach, catatan: batas_match_reach},
             tinggi: {kategori: reach}}
    lemah:  {rendah: {kategori: reach, catatan: batas_match_reach},
             sedang: {kategori: reach}, tinggi: {kategori: reach}}
```

**Kriteria penerimaan**

- Ke-9 sel matriks punya tes: input yang jatuh di sel itu menghasilkan kategori dan catatan sesuai config.
- Mengubah isi sel, bobot, atau batas pita di config mengubah hasil **tanpa perubahan kode**.
- Tidak ada kombinasi tier × pita yang tidak punya sel (validasi config saat startup: gagal cepat bila ada sel kosong atau kategori di luar {safe, match, reach}).
- Hasil selalu memuat label `indikatif` dan `keyakinan`. Tidak ada persentase.

### 8.3 Skor Kecocokan (eksplorasi jurusan)

Dua sumbu dipisah: **kecocokan** (minat dan kemampuan) dan **kelayakan** (hasil gate + penilaian).

```
kecocokan = w1 * kemiripan_minat + w2 * kesesuaian_nilai      # awal: w1 = 0.5, w2 = 0.5 (config)
```

- `kemiripan_minat`: kemiripan vektor minat siswa dengan tag minat tiap rumpun/prodi. **[Usulan]** cosine similarity atas himpunan dimensi minat tetap (jumlah dimensi sama dengan hasil 6–8 pertanyaan cepat, dan sama dengan `prodi.tag_minat`).
- `kesesuaian_nilai`: rata-rata tertimbang nilai mapel relevan, dinormalisasi ke 0–1. **[Usulan]** mapel yang belum diisi dikeluarkan dari perhitungan dan ditandai.
- Hasil ditampilkan sebagai **matriks kecocokan × kelayakan**, bukan satu angka tunggal.
- Kelayakan memakai mesin yang sama dengan 8.1–8.2 bila data cukup. Bila tidak, `data_kurang`.
- Penjelasan dibuat dari template, mis. "Cocok karena minatmu pada {dimensi_teratas} dan nilai {mapel} {nilai}".

### 8.4 Evaluasi Komposisi Strategi

Parameter awal (dari konfigurasi): minimal satu safe, maksimal 50% reach, peringatan jika semua pilihan di satu PTN atau satu jalur. Keluaran: daftar temuan beserta saran swap.

**[Usulan] aturan agar tidak ambigu**

- Evaluasi dilakukan **per jalur** (SNBP dan SNBT adalah daftar pilihan terpisah dengan batas berbeda). Batas jumlah pilihan disimpan per jalur di konfigurasi.
- Pilihan berstatus `tidak_memenuhi_syarat`, `data_kurang`, atau `belum_ada_acuan` **tidak dihitung** dalam rasio, tetapi dilaporkan sebagai temuan tersendiri.
- Aturan rasio hanya diterapkan jika jumlah pilihan yang dapat dinilai ≥ `min_pilihan_untuk_evaluasi` (config). Di bawah itu, hanya temuan informatif.
- Saran swap hanya diambil dari shortlist siswa dan harus memperbaiki setidaknya satu temuan tanpa menimbulkan pelanggaran baru.

### 8.5 Peran LLM

| LLM boleh | LLM tidak boleh |
|---|---|
| Menjelaskan hasil mesin aturan | Memutuskan kelolosan syarat |
| Mengubah cerita minat bebas jadi profil minat terstruktur | Menentukan kategori reach/match/safe |
| Menjawab Q&A berbasis RAG | Menentukan deadline atau jadwal |

**[Usulan]** Modul domain (`gate`, `assess`, `match`, `strategy`) berupa fungsi murni yang **tidak meng-import** klien LLM. Dengan begitu aturan "LLM tidak memutuskan" dijamin oleh struktur kode.

---

## 9. Arsitektur

```
Frontend (web mobile-first)
        │  REST JSON · Authorization: Bearer <token sesi>
        ▼
Reverse proxy HTTPS (mis. Caddy/Nginx)
        ▼
FastAPI  (/api/v1)
  ├─ Sesi tamu · Profile · Catalog
  ├─ Rules engine (gate) · Scoring (assess, match)   ← deterministik, tanpa LLM
  ├─ Strategy evaluator
  ├─ RAG service (retrieve → generate)
  └─ LLM client (Gemini API: cache + antrean + fallback)
        ▼
PostgreSQL + pgvector  (relasional + embedding)
```

### Keputusan teknis

| Area | Keputusan |
|---|---|
| Bahasa/framework | Python 3.11+, FastAPI, Pydantic untuk validasi |
| Database | PostgreSQL + pgvector (satu DB). Alternatif cepat: ChromaDB lokal bila pgvector menyulitkan |
| LLM | Gemini via Google AI Studio API. Kunci API dibuat di AI Studio (langganan Google tidak otomatis termasuk API) |
| Embedding | **[Diputuskan, dikunci]** Gemini embedding API, model `gemini-embedding-001`, `output_dimensionality=768`. Dokumen di-embed dengan `task_type=RETRIEVAL_DOCUMENT`, pertanyaan dengan `RETRIEVAL_QUERY`. Vektor dinormalisasi L2 di sisi aplikasi (model ini tidak menormalisasi dimensi selain 3072), jarak = cosine. Tidak ada model embedding yang dijalankan di VPS. **Tidak boleh diganti di tengah jalan**: mengganti model atau dimensi berarti migrasi kolom dan re-embed semua chunk |
| Chunking | ± 500–1000 karakter, overlap 100–200. Metadata: sumber, halaman, tahun siklus. Jauh di bawah batas input model (2.048 token), skrip ingest tetap menolak chunk yang melebihinya |
| Konfigurasi | Bobot, ambang retrieval, batas jumlah pilihan, TTL sesi, rate limit di file konfigurasi, bukan di kode |
| Deployment | VPS ± 2 vCPU / 2–4 GB RAM, Docker Compose (api, db, proxy), HTTPS. **Deploy paling lambat hari ke-2.** Siapkan fallback demo terekam |

### [Usulan] Struktur proyek

```
app/
  main.py
  api/v1/            # session, profile, catalog, explore, analyze, strategy, summary, query, admin
  core/              # config, security (token), rate_limit, errors
  domain/            # gate.py, assess_snbt.py, assess_snbp.py, match.py, strategy.py  (fungsi murni)
  rag/               # ingest.py, retrieve.py, generate.py
  llm/               # client.py, cache.py, prompts.py, fallback_texts.py
  db/                # models.py, session.py, migrations/
  schemas/           # model Pydantic request/response
config/              # app.yaml, rules/*.json, personas/*.json (persona fiktif + hasil terverifikasi)
scripts/             # ingest.py, seed_personas.py, run_golden_set.py, export_persona_static.py
tests/               # golden_gate/, golden_rag/
docker-compose.yml
```

### Environment variable (tidak boleh masuk repositori)

`GEMINI_API_KEY`, `DATABASE_URL`, `ADMIN_KEY`, `CORS_ORIGINS`, `SESSION_TTL_HOURS`.

---

## 10. Model Data

Entitas dari v0.2. Kolom bertanda **[Usulan]** adalah tambahan agar kebutuhan di bagian 7–8 bisa dipenuhi.

| Entitas | Field utama |
|---|---|
| `sessions` | id, consent_at, created_at, expires_at, **[Usulan]** token_hash, consent_version |
| `profiles` | session_id, tahun_lulus, provinsi, akreditasi_sekolah, nilai_rapor (JSON per mapel), minat (JSON), skor_tryout (opsional), **[Usulan]** jenis_sekolah (SMA/SMK/MA), nilai_rapor **per semester** (untuk tren dan kelengkapan sem 1–5), peringkat_kelas + jumlah_siswa, alumni_info (JSON: prodi/PTN → ya/tidak/tidak_tahu) |
| `ptn` | id, nama, provinsi |
| `prodi` | id, ptn_id, nama, rumpun, akreditasi, daya_tampung, peminat_tahun_lalu, mapel_penentu, tag_minat, jalur_dibuka |
| `acuan_skor` | prodi_id, jalur, rendah, tinggi, tahun, sumber_url, terakhir_diverifikasi |
| `rules_jalur` | id, jalur, syarat (JSON), sumber_url, terakhir_diverifikasi, tahun_siklus, **[Usulan]** dokumen_wajib (JSON) |
| `profesi` | id, rumpun, nama, deskripsi |
| `rag_chunks` | id, dokumen_id, teks, embedding `vector(768)`, **[Diputuskan]** embedding_model, halaman, sumber_url, tahun_siklus |
| **[Usulan]** `dokumen_sumber` | id, judul, url, jenis, tahun_siklus, terakhir_diverifikasi (rujukan `rag_chunks.dokumen_id`) |
| `strategies` | id, session_id, pilihan (JSON), hasil_evaluasi (JSON), created_at |
| `query_logs` | id, session_id, pertanyaan, yakin, sumber_ids, created_at |
| **[Usulan]** `llm_cache` | key_hash, respons, created_at, ttl (kunci = hash dari template + input deterministik yang bebas PII). Juga dipakai untuk cache embedding pertanyaan ternormalisasi |

**Aturan integritas**

- Semua tabel ber-`session_id` memakai `ON DELETE CASCADE`, sehingga `DELETE /session` dan pembersihan kedaluwarsa menghapus data turunan secara otomatis (FR-A4).
- **[Diputuskan]** Kolom `embedding` bertipe `vector(768)` dan dikunci di migrasi pertama. Model dan dimensi juga dicatat di `config/app.yaml`. **Saat startup, aplikasi membandingkan config dengan dimensi kolom dan `embedding_model` pada chunk yang ada; bila tidak cocok, aplikasi gagal start** agar vektor dari model berbeda tidak pernah tercampur.
- **[Usulan]** Dengan jumlah chunk MVP yang kecil (ratusan sampai ribuan), pencarian vektor eksak tanpa indeks ANN sudah cukup cepat.
- **[Usulan]** `query_logs.pertanyaan` melewati penyaring PII sederhana (nomor telepon, email, deret angka panjang) sebelum disimpan atau dikirim ke LLM.
- Aturan, katalog, dan acuan **berversi dengan `tahun_siklus`**, sehingga data siklus baru tidak menimpa data lama.

---

## 11. Spesifikasi API

Prefix: `/api/v1`. Autentikasi: header `Authorization: Bearer <token>`. Semua endpoint kecuali `POST /session` dan `GET /health` memerlukan token sesi.

| Endpoint | Fungsi |
|---|---|
| `POST /session` | Buat sesi tamu, catat consent, kembalikan token |
| `GET /session` | Status sesi dan sisa masa berlaku |
| `DELETE /session` | Hapus sesi dan seluruh data |
| `GET /health` | Cek layanan hidup (monitoring VPS) |
| `GET /profile`, `PUT /profile` | Baca dan perbarui profil (parsial) |
| `GET /catalog/ptn`, `GET /catalog/prodi` | Daftar dan pencarian |
| `GET /catalog/prodi/{id}` **[Usulan]** | Detail prodi (FR-C2) |
| `POST /explore` | Rekomendasi jurusan dari minat dan nilai |
| `POST /analyze` | Gate + penilaian per target |
| `POST /strategy` | Evaluasi komposisi + what-if |
| `POST /summary` | Ringkasan strategi |
| `POST /query` | RAG dengan konteks |
| `POST /admin/ingest` | Impor data dan dokumen (internal; **[Diputuskan]** header `X-Admin-Key`, bukan token sesi) |

### POST /session

```json
// Request
{"consent": true, "consent_version": "2026-10-13"}

// Response 201
{"token": "…", "expires_at": "2026-10-14T10:00:00Z", "sisa_detik": 86400}
```

Tanpa `consent: true` → 400 `consent_diperlukan`.

### PUT /profile (parsial)

```json
// Request (contoh sebagian)
{"tahun_lulus": 2026, "provinsi": "Jawa Barat", "akreditasi_sekolah": "A",
 "nilai_rapor": {"semester_1": {"matematika": 85, "fisika": 80}}}

// Response 200
{"profil": {"…": "…"},
 "data_kurang": {"SNBT": ["skor_tryout"], "SNBP": ["peringkat_kelas"]}}
```

### POST /explore

```json
// Request
{"top_n": 5}

// Response (ringkas)
{"rekomendasi": [{
  "rumpun": "…",
  "skor_kecocokan": 0.78,
  "komponen": {"minat": 0.82, "nilai": 0.74},
  "alasan": "…",
  "contoh_profesi": ["…"],
  "prodi_ids": ["…"],
  "kelayakan": null
}]}
```

### POST /analyze

Request:

```json
{
  "targets": [{"prodi_id": "ui-ti", "jalur": ["SNBP", "SNBT"]}],
  "override": {"skor_tryout": 620}
}
```

Response (angka hanya ilustrasi format, bukan data nyata):

```json
{
  "hasil": [{
    "prodi_id": "ui-ti",
    "jalur": "SNBT",
    "gate": {"status": "lolos", "syarat": []},
    "penilaian": {
      "kategori": "reach",
      "gap": 40,
      "alasan": "Skor 620 di bawah rentang acuan tahun lalu",
      "acuan": {"rendah": 660, "tinggi": 720, "tahun": 2026},
      "label": "acuan siklus sebelumnya"
    },
    "sumber": ["url"],
    "terakhir_diverifikasi": "YYYY-MM-DD",
    "data_kurang": []
  }]
}
```

Contoh gate gagal (penilaian tidak dijalankan):

```json
{
  "prodi_id": "ui-ti", "jalur": "SNBT",
  "gate": {"status": "tidak_memenuhi_syarat",
           "syarat": [{"id": "tahun_lulus", "status": "gagal", "alasan": "…"}]},
  "penilaian": null,
  "sumber": ["url"], "terakhir_diverifikasi": "YYYY-MM-DD", "data_kurang": []
}
```

Contoh `data_kurang` **[Usulan]**: `[{"field": "skor_tryout", "pertanyaan": "Berapa estimasi skor tryout UTBK kamu?"}]`.

### POST /strategy **[Usulan: bentuk request/response]**

```json
// Request
{
  "jalur": "SNBT",
  "pilihan": [{"prodi_id": "ui-ti"}, {"prodi_id": "unair-ti"}],
  "shortlist": ["undip-ti", "ub-ti"],
  "override": {"skor_tryout": 650},
  "simpan": false
}

// Response (ringkas)
{
  "hasil": [ /* bentuk sama seperti /analyze */ ],
  "komposisi": {"jumlah": 2, "reach": 1, "match": 1, "safe": 0},
  "temuan": [{
    "kode": "min_safe", "tingkat": "peringatan",
    "pesan": "Belum ada pilihan safe",
    "saran_swap": [{"ganti": "ui-ti", "dengan": "undip-ti", "alasan": "…"}]
  }]
}
```

- Jika `override` ada, `simpan` dipaksa `false` (what-if tidak pernah menyimpan).
- `simpan: true` menyimpan pilihan aktif ke `strategies` untuk dipakai `/summary`.

### POST /summary

- Request: `{}` memakai strategi tersimpan terbaru, atau `{"strategy_id": "…"}`. **[Usulan]**
- Response memuat: `pilihan_akhir`, `alasan`, `gap`, `fokus_persiapan`, `dokumen_syarat` (dengan sumber), `catatan` ("acuan siklus sebelumnya"), `dihasilkan_pada`, dan `narasi_fallback: true|false`.

### POST /query

```json
// Request: tanya
{
  "pertanyaan": "SNBP butuh dokumen apa saja?",
  "konteks": {"prodi_id": "ui-ti", "jalur": "SNBP"},
  "mode": "tanya"
}

// Request: jelaskan (tombol "Kenapa?"), termasuk hasil what-if
{
  "pertanyaan": "Kenapa hasilnya reach?",
  "konteks": {"prodi_id": "ui-ti", "jalur": "SNBT", "override": {"skor_tryout": 620}},
  "mode": "jelaskan"
}

// Response
{
  "jawaban": "...",
  "sumber": [{"judul": "...", "url": "...", "halaman": 12}],
  "yakin": true,
  "data_dibutuhkan": [],
  "saran_pertanyaan": ["Kapan jadwal pendaftarannya?"]
}
```

- **[Diputuskan]** `mode`: `"tanya"` (Q&A bebas; `konteks` opsional) atau `"jelaskan"` (tombol "Kenapa?"; `konteks.prodi_id` dan `konteks.jalur` wajib). Satu endpoint, tanpa `/explain` terpisah.
- **[Diputuskan]** `konteks` hanya berisi `prodi_id`, `jalur`, dan `override` terstruktur. Server membangun sendiri ringkasan profil dan hasil analisis dari sesi. Field lain di body → 422 (`extra="forbid"`).
- Saat `yakin: false`, `sumber` berisi tautan sumber resmi terkait (bila ada) dan jawaban mengarahkan ke sumber resmi atau guru BK.
- Fallback LLM gagal: `jawaban` memakai teks cadangan, `yakin: false`, dan field `fallback: true`.

### POST /admin/ingest **[Usulan: bentuk request]**

```json
{"tipe": "rules | katalog | acuan | dokumen", "payload": [ /* item */ ]}
```

Dokumen PDF diunggah lewat multipart. Respons: jumlah item diterima, daftar error per baris. Header `X-Admin-Key` wajib (lihat 7.8).

### Format error standar

```json
{"error": {"kode": "…", "pesan": "…", "detail": {}}}
```

| Status | Pemakaian |
|---|---|
| 400 | Permintaan salah secara bisnis (mis. `consent_diperlukan`) |
| 401 | Token tidak ada, tidak valid, atau sesi kedaluwarsa |
| 404 | Sumber daya tidak ditemukan |
| 422 | Validasi skema/field gagal. **[Usulan]** bungkus respons default FastAPI ke format standar di atas |
| 429 | Rate limit. **[Usulan]** sertakan header `Retry-After` |
| 503 | Dependensi mati dan tidak ada fallback |

---

## 12. Data dan Kurasi

- **Sumber utama:** panduan resmi SNPMB (SNBP/SNBT), PDDikti, situs resmi kampus, data publik tahun lalu.
- Setiap rule, acuan, dan dokumen **wajib** punya `sumber_url`, `terakhir_diverifikasi`, `tahun_siklus`.
- **Verifikasi silang** oleh satu anggota tim sebelum data dipakai.
- Siklus berikutnya kemungkinan belum sepenuhnya rilis. Gunakan data siklus 2026 dengan label jelas **"acuan siklus sebelumnya, cek ulang saat dibuka"**.
- Data acuan skor tidak semuanya resmi atau lengkap. Jika tidak ada, tampilkan `belum_ada_acuan`.
- Hormati lisensi dan kutip sumber. Dokumen RAG disimpan dengan metadata asal.
- **Pembaruan aturan:** halaman dan PDF dari domain resmi (portal SNPMB dan situs resmi PTN) di-ingest ke RAG secara manual terjadwal. **Rule gate tetap diisi dan diverifikasi manusia**, LLM hanya membantu membaca. Setiap jawaban menampilkan tombol "Buka sumber resmi". Fitur "cek pembaruan" otomatis masuk roadmap.
- Cek dulu apakah daftar daya tampung dan peminat bisa diunduh dari portal resmi agar tidak diketik manual.

## 13. Kebutuhan Non-Fungsional

### Akurasi dan kejujuran

- Tidak ada persentase peluang. Semua kategori berlabel heuristik beserta alasan.
- Jawaban RAG tanpa sumber memadai wajib `yakin: false`.

### Privasi (UU PDP)

- Data siswa mencakup anak di bawah umur: minimalkan data, consent eksplisit, jelaskan lokasi penyimpanan.
- **Jangan kirim data identitas** (nama, kontak) ke penyedia LLM. Kirim hanya ringkasan profil terstruktur yang diperlukan.
- Tombol "hapus data saya" menghapus sesi dan seluruh data turunannya.
- Jangan pakai data siswa asli untuk demo tanpa persetujuan. Gunakan persona fiktif.
- Cek ketentuan penggunaan data pada free tier Gemini API **sebelum** memproses data siswa nyata.
- **[Diputuskan] Data anak dan persetujuan orang tua/wali.** UU PDP mengatur data anak secara khusus, dan umumnya melibatkan persetujuan orang tua/wali. Tim bukan penasihat hukum, jadi hal ini **harus dikonfirmasi ke ahli sebelum peluncuran nyata** dan tidak boleh diabaikan. Langkah untuk hackathon:
  1. Demo hanya memakai persona fiktif.
  2. UI menampilkan catatan bahwa produk ini masih prototipe dan tidak untuk data pribadi nyata. Frontend memuat teks consent, backend hanya mencatat `consent_at` dan `consent_version`.
  3. Proposal mencantumkan konfirmasi hukum dan alur persetujuan orang tua/wali sebagai **syarat sebelum peluncuran nyata**.
- **[Usulan]** Log aplikasi tidak mencatat body request, token, atau teks pertanyaan mentah.

### Keamanan

- Token sesi acak berumur pendek, rate limiting, validasi input, CORS terbatas.
- Secret (API key LLM, admin key) di environment variable, bukan di repositori.
- **[Usulan]** Rate limit memakai penyimpanan in-memory (cukup untuk satu instance) dengan batas lebih ketat untuk endpoint yang memanggil LLM. Jika di belakang reverse proxy, IP klien dibaca dari `X-Forwarded-For` hanya dari proxy tepercaya.

### Performa

| Endpoint | Target |
|---|---|
| Deterministik (`/analyze`, `/strategy`) | < 1 detik pada data MVP |
| Memanggil LLM (`/query`, narasi `/summary`) | < ± 8 detik, frontend menampilkan indikator pemuatan |

- Cache hasil penjelasan yang berulang. Free tier Gemini punya batas permintaan per menit yang rendah dan berbeda per model, jadi **cache dan antrean sederhana wajib**.
- **[Usulan]** Pembatas konkurensi global (semaphore) untuk panggilan LLM, karena kuota berlaku per API key, bukan per sesi.
- Pemakaian API per `/query`: 1 panggilan embedding (pertanyaan) + maksimal 1 panggilan generate. Embedding dokumen hanya terjadi saat ingest, tetapi embedding pertanyaan terjadi saat runtime, jadi batasnya tetap dicek di AI Studio (lihat bagian 17 #7).

### Keandalan demo

- Persona demo tetap dengan hasil yang sudah diverifikasi manual.
- **Fallback:** jika LLM atau internet gagal, hasil deterministik tetap tampil dan penjelasan memakai teks cadangan.
- Siapkan video demo terekam.
- **[Usulan]** `GET /health` memeriksa koneksi DB saja (tidak memanggil LLM agar tidak membuang kuota).
- **[Diputuskan]** Tombol **"Muat persona demo"** di frontend membuat **sesi baru** (`POST /session`, lalu `PUT /profile` dengan data persona), sehingga demo tidak mati saat TTL habis. Consent tetap eksplisit lewat landing seperti biasa, dan UI menandai data sebagai fiktif. Data persona dan hasil terverifikasinya disimpan di `config/personas/*.json` sebagai satu sumber kebenaran (dipakai skrip seed, tes golden, dan frontend).

## 14. Evaluasi dan Metrik

| Metrik | Cara ukur | Target awal |
|---|---|---|
| Akurasi gate | 3–5 profil uji dan kasus tepi vs hasil verifikasi manual | 100% pada set uji |
| Akurasi RAG | Golden set 20 pertanyaan dengan jawaban dan sumber benar | Dilaporkan apa adanya, target awal 85% |
| Kejujuran RAG | % pertanyaan di luar cakupan yang dijawab `yakin: false` | Setinggi mungkin, dilaporkan |
| Kualitas kategori | Uji mundur sederhana dengan data tahun lalu bila memungkinkan | Dilaporkan, bukan klaim |
| Waktu penyelesaian alur | Uji ke 3–5 siswa atau guru BK | ± 10 menit |

Target bersifat awal dan disesuaikan setelah ada hasil nyata. Tampilkan batas akurasi secara terbuka di pitch.

**[Diputuskan] Batasan uji pengguna.** Metrik "waktu penyelesaian alur" melibatkan siswa atau guru BK. Karena keputusan privasi di bagian 13 (hanya data fiktif sebelum konfirmasi hukum), peserta uji diminta **mengisi data contoh/fiktif**, bukan data diri atau rapor asli. Pilihan lain yang lebih aman: uji dengan guru BK (dewasa) memakai persona. Hasil uji dilaporkan sebagai uji coba kecil, bukan klaim.

**[Usulan] Kasus uji gate minimum**

1. Lulusan tepat di batas tahun → lolos.
2. Lulusan satu tahun melewati batas → `tidak_memenuhi_syarat`, penilaian `null`.
3. Rapor semester tidak lengkap → `data_kurang` (SNBP).
4. Satu syarat `gagal` bersamaan dengan satu `data_kurang` → `tidak_memenuhi_syarat`.
5. Semua syarat terpenuhi → `lolos` lalu penilaian dijalankan.

**[Usulan]** Golden set RAG mencakup ≥ 5 pertanyaan di luar cakupan (untuk mengukur kejujuran) dan ≥ 3 pertanyaan bertipe keputusan (harus dijawab dari mesin aturan).

## 15. Risiko dan Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Data acuan skor tidak lengkap atau tidak resmi | Kategori menyesatkan | Cakupan sempit, label sumber, `belum_ada_acuan` |
| Aturan jalur berubah antar siklus | Gate salah | Rule berupa data berversi, tanggal verifikasi, verifikasi manual |
| LLM berhalusinasi | Informasi salah ke siswa | Hanya jawab dari konteks, sitasi wajib, ambang retrieval, fallback ke sumber resmi |
| Kategori dianggap kepastian | Keputusan keliru | Label heuristik, tanpa persentase, banyak penjelasan |
| Scope terlalu lebar untuk 3 orang (backend + AI dipegang satu peran) | Tidak selesai | Prioritas MVP ketat, eksplorasi boleh disederhanakan, lihat urutan pemotongan di 16 |
| Kebocoran data anak | Risiko hukum dan etika | Minimalisasi data, tanpa PII ke LLM, hapus data, cascade delete |
| Kegagalan demo live | Penilaian turun | Persona tetap, fallback deterministik, video cadangan |
| Biaya/latensi API LLM | Demo lambat | Cache, prompt ringkas, batasi panggilan |
| Waktu hanya 3 hari | Fitur tidak selesai atau demo gagal | Scope dipotong, deploy hari ke-2, hari terakhir tanpa fitur baru |
| Batas permintaan free tier Gemini | Respons lambat atau gagal | Cache, antrean sederhana, teks fallback, cek batas di AI Studio, siapkan opsi billing |
| Data alumni sekolah tidak tersedia (SNBP) | Kategori SNBP kurang akurat | Label indikatif, keyakinan rendah bila data kosong, tampilkan faktor tidak diketahui |
| **[Usulan]** Input teks bebas memuat PII | Data pribadi terkirim ke LLM atau tersimpan di log | Penyaring PII sederhana, peringatan di UI, tidak mencatat teks mentah |
| **[Diputuskan]** Persetujuan orang tua/wali untuk data anak belum dikonfirmasi ahli | Produk tidak boleh dirilis ke siswa nyata | Hackathon: persona fiktif saja, catatan di UI, syarat peluncuran di proposal. Uji pengguna memakai data contoh |
| **[Diputuskan]** Kuota embedding free tier belum terverifikasi (embedding pertanyaan terjadi saat runtime) | `/query` gagal saat demo atau uji | Cache embedding pertanyaan, pra-embed `saran_pertanyaan`, fallback `yakin: false`, cek batas di AI Studio hari 1 |

## 16. Rencana Kerja Backend (Tim 3 Orang)

**Peran**

- **Backend dan AI:** sesi, rules engine, scoring, strategi, RAG, API.
- **Frontend dan UX:** alur web mobile-first, simulator, halaman ringkasan.
- **Data, riset, pitch:** kurasi rule dan katalog, dokumen RAG, golden set, proposal, video.

| Tanggal | Pekerjaan backend | **[Usulan]** Kriteria selesai hari itu |
|---|---|---|
| **13 Okt** | Skeleton FastAPI dan skema DB, sesi tamu, rules engine gate + `/analyze` (SNBT dulu, lalu SNBP). Bersama anggota data: kunci skema rule dan subset PTN/prodi | `POST /session` dan `/analyze` SNBT berjalan lokal dengan 1 rule nyata dan 1 prodi |
| **14 Okt** | `/strategy`, `/summary`, ingest RAG + `/query` bersitasi, muat data, **deploy ke VPS** (Docker Compose, HTTPS) | API dapat diakses lewat HTTPS publik. `/query` mengembalikan sitasi dan `yakin: false` |
| **15 Okt** | Integrasi frontend, perbaikan bug, golden set 20 pertanyaan, rekam video dengan persona tetap, finalisasi proposal. `/explore` versi sederhana **hanya jika ada waktu** | Persona demo berjalan end-to-end. Metrik golden set tercatat |
| **16 Okt** | Hanya submit dan penanganan darurat. **Tanpa fitur baru** | Submit |

Proposal dan video dikerjakan paralel sejak awal, bukan di hari terakhir. Rekam video setelah alur demo dikunci.

**[Usulan] Urutan pemotongan bila waktu habis** (dari yang pertama dikorbankan):

1. Ekspor PDF (cukup halaman web siap cetak).
2. `/explore` (bila dipotong, Skenario A turun ke penelusuran katalog dengan filter rumpun).
3. LLM untuk mengubah cerita minat bebas jadi profil terstruktur (cukup kuesioner 6–8 pertanyaan).
4. Narasi LLM di `/summary` (cukup template).

Yang **tidak boleh dipotong**: gate, penilaian SNBT, sesi + consent + hapus data, `/query` bersitasi dengan `yakin: false`, dan deploy.

## 17. Keputusan dan Pertanyaan Terbuka

**Sudah diputuskan (v0.2):** deadline 16 Oktober 2026; LLM Gemini via Google AI Studio API; 10 PTN × 17 prodi; bahasa Indonesia saja; hosting VPS; SNBP berkategori indikatif dengan tingkat keyakinan; login ditunda ke roadmap dan diganti sesi tamu.

**Diputuskan 13 Oktober 2026 (menutup pertanyaan terbuka sebelumnya):**

| Topik | Keputusan | Lokasi |
|---|---|---|
| Embedding | Gemini API, `gemini-embedding-001`, 768 dimensi, dikunci; tidak ada model lokal di VPS | 9, 10 |
| Ringkasan | Cukup cetak/PDF. Tanpa tautan yang bisa dibagikan. Halaman statis hanya untuk persona fiktif, terpisah dari data pengguna | 7.6 |
| Consent < 18 tahun | Konfirmasi ahli sebelum peluncuran nyata. Hackathon: persona fiktif, catatan di UI, syarat di proposal | 13 |
| Tombol "Kenapa?" | `/query` dengan `mode: "jelaskan"`. Konteks dibangun server dari id, bukan teks klien | 7.7, 11 |
| Admin ingest | Header `X-Admin-Key` (`ADMIN_KEY`) | 7.8 |
| Persona demo | Tombol "Muat persona demo" membuat sesi baru | 13 |
| Penilaian SNBP | Matriks 3×3 (tier siswa × pita keketatan) di config, menggantikan rumus margin | 8.2 |
| Lampiran A | Semua usulan diikuti, dengan perubahan di #5, #6, #13, #14, #16 | Lampiran A |

**Masih terbuka.** Semua butir di bawah adalah **data atau nilai config** dan tidak memblokir penulisan kode, kecuali yang ditandai.

| # | Pertanyaan terbuka | Pemilik | Memblokir kode? |
|---|---|---|---|
| 1 | Subset PTN × prodi untuk data acuan mendalam | Data | Tidak (isi seed) |
| 2 | Aturan resmi terbaru: batas tahun lulus, jumlah pilihan per jalur, ketentuan sekolah SNBP, diverifikasi ke panduan SNPMB | Data | Tidak (isi `config/rules`) |
| 3 | Spesifikasi VPS, domain, dan HTTPS untuk demo | Backend | **Ya, untuk deploy hari ke-2** |
| 4 | Isi matriks SNBP: batas tier siswa, batas pita rasio, bobot faktor, dan keputusan akhir 3 sel "batas match/reach" (nilai awal `reach` + catatan) | Data | Tidak (isi config) |
| 5 | Konfirmasi: akreditasi sekolah tidak ikut menghitung tier SNBP (hanya gate dan konteks) | Data | Tidak |
| 6 | Himpunan dimensi minat untuk kuesioner dan `tag_minat` | Data + Frontend | Sebagian: menentukan skema `profiles.minat` |
| 7 | Cek di AI Studio: ketersediaan dan batas free tier untuk `gemini-embedding-001` dan model generatif yang dipakai (belum diverifikasi di dokumen ini). Tentukan nama model generatif | Backend | Tidak, tapi cek **hari 1** |
| 8 | Definisi `tahun_ini` pada rule (tahun siklus pendaftaran, disimpan sebagai `tahun_acuan_pendaftaran`) | Data | Tidak (isi config) |
| 9 | Konfirmasi hukum UU PDP untuk data anak dan alur persetujuan orang tua/wali | Tim | Tidak (syarat peluncuran nyata, bukan hackathon) |

---

## 18. Log Perubahan

| Tanggal | Versi | Perubahan |
|---|---|---|
| 13 Okt 2026 | 0.2 | PRD sumber (draft awal tim) |
| 13 Okt 2026 | 0.3 | Penyusunan ulang, ID FR dipertahankan; kriteria penerimaan, spesifikasi API, dan Lampiran A ditambahkan |
| 13 Okt 2026 | 1.0 | **Pembekuan.** Keputusan embedding, ringkasan cetak/PDF, consent anak, `/query` mode `jelaskan` dengan konteks dari server, `X-Admin-Key`, persona demo, dan matriks SNBP 3×3 dimasukkan. Rumus margin SNBP dihapus |

---

## Lampiran A — Temuan di PRD v0.2 dan Usulan Penyelesaian

**Status per 13 Oktober 2026:** seluruh usulan di bawah diikuti. Empat butir diputuskan berbeda atau lebih ketat dari usulan awal: **#5** (model embedding dipilih dan dikunci), **#6** (cetak/PDF saja, tautan berumur pendek ditolak), **#13** (konteks `/query` hanya dari id), dan **#14** (rumus margin diganti matriks 3×3). **#16** diputuskan sebagai tombol "Muat persona demo" yang membuat sesi baru.

| # | Temuan | Dampak | Usulan |
|---|---|---|---|
| 1 | Berkas berjudul "PathWise", isi menyebut "JalurKu" (nama sementara) | Penamaan repo, UI, dan dokumen tidak konsisten | Pilih satu nama. Pakai nama netral untuk kode (`backend`) agar ganti nama murah |
| 2 | JWT disebut di bagian Keamanan dan roadmap, padahal MVP tanpa login | Salah paham arsitektur | Token sesi acak opaque. JWT hanya saat login diaktifkan |
| 3 | Risiko menyebut "hapus akun", FR-A4 menyebut "hapus data saya" | Istilah berbeda untuk fungsi yang sama | Samakan menjadi "hapus data saya" |
| 4 | `/admin/ingest` tunduk pada aturan "semua endpoint butuh token sesi" | Admin tidak punya sesi, jadi endpoint tak bisa dipakai atau malah terbuka | `X-Admin-Key`, atau CLI saja |
| 5 | Embedding "model multibahasa kecil di CPU" bertentangan dengan "tidak ada model yang dijalankan sendiri di VPS" | Beban RAM di VPS 2 GB dan dimensi vektor tak bisa dikunci | **Diputuskan:** Gemini API, `gemini-embedding-001`, 768 dimensi, dikunci (bagian 9 dan 10) |
| 6 | Ringkasan "bisa dibagikan" sementara data hilang dalam 24 jam dan tanpa akun | Tautan mati atau memaksa data publik | **Diputuskan:** cetak/PDF saja. Halaman statis hanya untuk persona fiktif (7.6) |
| 7 | Skenario utama A bergantung pada `/explore`, tetapi modul itu opsional. Bagian 5 menyebut "tanpa LLM", sedangkan 8.5 menyebut LLM untuk cerita minat bebas | Alur utama bisa putus saat dipotong | Kuesioner terstruktur saja di MVP. Sediakan fallback penelusuran katalog |
| 8 | Skema `profiles` tidak memuat data yang dipakai SNBP (nilai per semester, peringkat, alumni, jenis sekolah) | Gate dan penilaian SNBP tak bisa dihitung | Tambahkan field (bagian 10) |
| 9 | FR-S1 menyebut satu batas jumlah pilihan, padahal SNBP dan SNBT berbeda. Skenario "4 pilihan" mencampur jalur | Evaluasi komposisi ambigu | Evaluasi per jalur, batas per jalur di config (8.4) |
| 10 | Contoh rule `tahun_ini - 3` tidak mendefinisikan `tahun_ini`, sementara data yang dipakai bersiklus 2026 | Gate bisa salah satu tahun | Ambil dari config `tahun_acuan_pendaftaran` |
| 11 | Tombol "Kenapa?" tanpa endpoint | Frontend tidak punya kontrak | `/query` dengan `mode: "jelaskan"` |
| 12 | Status 400 dan 422 sama-sama dipakai tanpa pembeda | Klien bingung menangani error | Definisikan pemakaian masing-masing (bagian 11) |
| 13 | `query_logs` menyimpan pertanyaan bebas, dan konteks dikirim klien | Potensi PII tersimpan dan terkirim ke LLM, dan konteks bisa dimanipulasi klien | Penyaring PII. **Diputuskan:** konteks dibangun di server dari id, `extra="forbid"` + tes otomatis (7.7) |
| 14 | Rumus penilaian SNBP belum didefinisikan (hanya daftar faktor) | Tidak bisa dikodekan atau diuji | **Diputuskan:** matriks 3×3 di config (8.2); isi dan batas dikalibrasi tim data |
| 15 | `rag_chunks.dokumen_id` tanpa tabel dokumen. "Dokumen utama" untuk ringkasan tak punya sumber data | Sitasi dan ringkasan tak lengkap | Tabel `dokumen_sumber` dan `rules_jalur.dokumen_wajib` |
| 16 | Persona demo bergantung pada sesi yang kedaluwarsa dalam 24 jam | Demo gagal saat juri menilai di hari berikutnya | **Diputuskan:** tombol "Muat persona demo" membuat sesi baru (13) |

## Lampiran B — Glosarium

| Istilah | Arti |
|---|---|
| **SNBP** | Seleksi Nasional Berdasarkan Prestasi (jalur berbasis rapor/prestasi) |
| **SNBT** | Seleksi Nasional Berdasarkan Tes (jalur berbasis tes) |
| **PTN** | Perguruan Tinggi Negeri |
| **Prodi** | Program studi |
| **Gate** | Pengecekan syarat mutlak jalur (lolos/gagal/data_kurang) |
| **Reach / Match / Safe** | Kategori heuristik: di atas jangkauan / sesuai / aman |
| **RAG** | Retrieval-Augmented Generation: jawaban dibuat dari potongan dokumen yang diambil |
| **Golden set** | Kumpulan pertanyaan dengan jawaban dan sumber benar untuk evaluasi |
