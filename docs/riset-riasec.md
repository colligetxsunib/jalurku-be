# Riset: Komponen Tes Minat RIASEC untuk JalurKu

> Dokumen riset pendukung PRD JalurKu v0.2. Fokus: bagaimana mengembangkan tes minat
> RIASEC sebagai input modul Profil + Eksplorasi Jurusan (FR-E1/E2, logika inti 8.3),
> dengan batasan hackathon 3 hari, deterministik, legal/public-domain, dan Bahasa Indonesia.

Terakhir diperbarui: 14 Oktober 2026

---

## 1. Ringkasan Eksekutif (TL;DR untuk tim)

- **Jangan buat item dari nol.** Validasi psikometrik butuh berbulan-bulan. Pakai item
  **public domain** yang sudah tervalidasi dan adaptasi ke Bahasa Indonesia.
- **Sumber terbaik: O\*NET Interest Profiler** (U.S. Department of Labor, public domain).
  Tersedia versi 60 item (Short Form) dan 30 item (Mini-IP).
- **Rekomendasi JalurKu:** self-host **24-30 item** (4-5 item per dimensi RIASEC),
  diterjemahkan ke Bahasa Indonesia, disimpan di DB/config, di-skor di server (deterministik,
  offline, < 1 detik). Ini sejalan dengan prinsip PRD: tanpa LLM untuk keputusan, fallback
  deterministik saat demo, Bahasa Indonesia saja.
- **Output tes = vektor 6 dimensi** `[R, I, A, S, E, C]` yang langsung dipakai di rumus
  `kemiripan_minat` (PRD bagian 8.3) via cosine similarity dengan `tag_minat` tiap prodi.

---

## 2. Apa itu RIASEC (Holland Codes)

Model minat vokasional John Holland dengan 6 tipe. Premisnya: orang paling puas & sukses
di lingkungan kerja yang cocok dengan tipe minatnya.

| Kode | Tipe | Inti minat |
|------|------|------------|
| **R** | Realistic | Bekerja dengan benda, mesin, alat, aktivitas fisik, luar ruangan |
| **I** | Investigative | Meneliti, menganalisis, memecahkan masalah ilmiah/abstrak |
| **A** | Artistic | Mencipta, mendesain, menulis, berekspresi, seni |
| **S** | Social | Membantu, mengajar, merawat, melayani orang |
| **E** | Enterprising | Memimpin, membujuk, menjual, memulai usaha |
| **C** | Conventional | Mengelola data, mengatur, prosedur, administrasi, ketelitian |

Hasil dirangkum jadi **Holland Code** = 3 huruf tertinggi (mis. "IRA").
Struktur idealnya heksagonal (tipe berdekatan lebih mirip; R-I-A-S-E-C melingkar).

**Kualitas psikometrik (dari literatur):** konsistensi internal Cronbach's alpha umumnya
0.80-0.90, validitas konstruk kuat terhadap model heksagonal, konvergensi baik dengan
Five-Factor Model. (Dirangkum ulang untuk kepatuhan lisensi.)

Sumber:
- https://en.arabpsychology.com/scales/holland-code-riasec-test/
- https://www.onetcenter.org/dl_files/IP_Manual.pdf

---

## 3. Pilihan Sumber Instrumen (legal & praktis)

| Opsi | Jumlah item | Lisensi | Waktu isi | Catatan |
|------|-------------|---------|-----------|---------|
| O\*NET Interest Profiler Short Form | 60 (10/dimensi) | Public domain (US DoL) | ~10-15 mnt | Standar emas gratis; terlalu panjang untuk alur 10 menit JalurKu |
| O\*NET Mini-IP | 30 (5/dimensi) | Public domain | ~5 mnt | **Paling pas** untuk MVP |
| Open Psychometrics RIASEC | 48 | Public domain | ~7 mnt | Alternatif |
| Brief RIASEC marker scales (Liao, Armstrong & Rounds, 2008) | ~48 | Public domain | ~7 mnt | Berbasis riset, reliabilitas layak |

**Format respons O\*NET:** siswa menilai tiap *aktivitas kerja* pada skala Likert 5 poin:
`Strongly Dislike (0) - Dislike (1) - Unsure (2) - Like (3) - Strongly Like (4)`.
Skor dimensi = jumlah respons item dimensi tersebut. Untuk Short Form rentang skor 0-40 per
dimensi. (Dirangkum ulang.)

Sumber:
- https://services.onetcenter.org/ip
- https://psypack.com/assessments/onet-interest-profiler/
- https://onetcenter.org/dl_tools/ipsf/IP_Score_Report.pdf

### Rekomendasi untuk JalurKu
Pakai **24-30 item** (4-5 item per dimensi), diadaptasi dari Mini-IP O\*NET ke Bahasa
Indonesia + konteks siswa SMA. Alasan: PRD menargetkan seluruh alur ~10 menit dan "minat
6-8 pertanyaan cepat". 30 item masih menjaga reliabilitas layak sambil cepat.

---

## 4. Dua Jalur Implementasi

### Jalur A - O\*NET Web Services API (resmi, gratis, perlu registrasi)
O\*NET menyediakan REST API gratis (JSON) yang:
- mengembalikan daftar pertanyaan Mini-IP (30) atau Short Form (60),
- menerima jawaban siswa,
- mengembalikan skor RIASEC + okupasi terkait.

Perlu daftar developer (gratis) untuk dapat API key.

- Kelebihan: tidak perlu kurasi/validasi item sendiri, resmi & terawat.
- Kekurangan untuk JalurKu:
  - **Item berbahasa Inggris** (PRD = Bahasa Indonesia saja).
  - **Dependensi jaringan eksternal** saat demo (bertentangan dengan prinsip fallback
    deterministik & keandalan demo di PRD bagian 13).

Sumber: https://services.onetcenter.org/ip , https://services.onetcenter.org/reference/

### Jalur B - Self-host item (REKOMENDASI)
Unduh item O\*NET (public domain) -> terjemahkan & adaptasi ke Bahasa Indonesia + konteks
siswa SMA Indonesia -> simpan di DB/config sendiri -> skor di server.

Cocok dengan JalurKu karena:
- Bahasa Indonesia (wajib per PRD).
- Offline, tanpa dependensi eksternal saat demo.
- Deterministik, respons < 1 detik (NFR performa).
- Full kontrol untuk mapping ke 17 prodi MVP.

Catatan lisensi: materi O\*NET adalah public domain, tetapi sertakan atribusi sumber dan
simpan metadata asal (sejalan dengan FR-D2 & bagian 12 tentang kurasi data).

---

## 5. Scoring (Deterministik, tanpa LLM)

```text
Untuk tiap dimensi d dalam {R,I,A,S,E,C}:
    skor_mentah[d] = Σ jawaban item milik dimensi d        (tiap jawaban 0..4)
    skor_maks[d]   = jumlah_item[d] * 4
    skor_norm[d]   = skor_mentah[d] / skor_maks[d]          (0..1)

Vektor minat siswa S = [skor_norm[R], ..., skor_norm[C]]
Holland Code = 3 dimensi dengan skor_norm tertinggi, urut menurun (mis. "IRC")
```

Contoh (24 item, 4 per dimensi, skor_maks = 16 per dimensi):
```
R=10 I=14 A=6 S=4 E=8 C=12
norm: R=.63 I=.88 A=.38 S=.25 E=.50 C=.75
Holland Code = I C R
```

---

## 6. Integrasi ke Rumus Eksplorasi Jurusan (PRD bagian 8.3)

PRD: `kecocokan = w1 * kemiripan_minat + w2 * kesesuaian_nilai`, bobot awal 0.5/0.5.

### 6.1 kemiripan_minat
Beri tiap prodi `tag_minat` berupa vektor RIASEC (bisa diturunkan dari kode RIASEC okupasi
O\*NET yang relevan). Lalu:

```python
def cosine_similarity(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = sum(x*x for x in a) ** 0.5
    nb = sum(y*y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0

kemiripan_minat = cosine_similarity(vektor_minat_siswa, prodi.tag_minat)  # 0..1
```

### 6.2 Contoh mapping tag_minat prodi (DRAFT - harus diverifikasi tim data)
Vektor urutan [R, I, A, S, E, C], skala 0..1. Angka di bawah ilustratif; set final sebaiknya
diturunkan dari kode RIASEC O\*NET + review guru BK.

| Prodi (subset MVP) | Holland Code | R | I | A | S | E | C |
|--------------------|--------------|---|---|---|---|---|---|
| Teknologi Informasi / Ilmu Komputer | ICR | .4 | .9 | .2 | .1 | .3 | .6 |
| Akuntansi | CEI | .2 | .5 | .1 | .2 | .5 | .9 |
| Hukum | ESC | .1 | .5 | .3 | .5 | .8 | .6 |
| Kedokteran Umum | ISR | .4 | .9 | .1 | .7 | .3 | .4 |
| Komunikasi | AES | .1 | .3 | .7 | .7 | .7 | .3 |
| Desain Komunikasi Visual | AIR | .4 | .4 | .9 | .2 | .4 | .2 |
| Psikologi | SIA | .1 | .7 | .4 | .9 | .4 | .3 |
| Manajemen | ECS | .1 | .3 | .2 | .5 | .9 | .7 |
| Hubungan Internasional | ESA | .1 | .5 | .4 | .6 | .8 | .4 |
| Teknik Sipil | RIC | .9 | .6 | .2 | .2 | .4 | .6 |
| Teknik Industri | REC | .7 | .6 | .2 | .3 | .6 | .7 |
| Teknik Mesin | RIC | .9 | .6 | .1 | .1 | .3 | .5 |
| Teknik Kimia | IRC | .7 | .8 | .1 | .2 | .3 | .6 |
| Arsitektur | ARI | .6 | .5 | .9 | .2 | .4 | .4 |
| Teknik Lingkungan | RIC | .7 | .7 | .2 | .4 | .3 | .6 |
| Kedokteran Gigi | IRS | .5 | .8 | .2 | .6 | .3 | .5 |
| Teknik Elektro | RIC | .8 | .8 | .1 | .1 | .3 | .6 |

> PENTING: angka ini DRAFT awal untuk memulai, bukan data final. Harus diverifikasi tim data
> + guru BK sebelum dipakai (konsisten dengan prinsip PRD bagian 12).

### 6.3 Peran LLM (batasan PRD 8.5)
- LLM TIDAK menghitung skor / Holland Code (semua deterministik).
- LLM BOLEH: (a) mengubah "cerita minat bebas" siswa jadi estimasi vektor RIASEC awal
  (opsi di PRD), (b) menjelaskan hasil ("kenapa prodi ini cocok") memakai template + konteks.

---

## 7. Contoh Item (Bahasa Indonesia, DRAFT adaptasi)

Format: siswa menilai "Seberapa suka kamu melakukan aktivitas ini?"
Skala: `Sangat tidak suka (0) - Tidak suka (1) - Netral (2) - Suka (3) - Sangat suka (4)`.
Item di bawah adaptasi gaya aktivitas O\*NET ke konteks siswa SMA Indonesia (4 per dimensi).

**Realistic (R)**
1. Memperbaiki alat elektronik atau mesin.
2. Merakit perabot atau barang dari petunjuk.
3. Bekerja di luar ruangan atau di lapangan.
4. Mengoperasikan peralatan atau mesin.

**Investigative (I)**
1. Melakukan percobaan sains di laboratorium.
2. Mempelajari cara kerja suatu fenomena alam.
3. Memecahkan soal matematika atau logika yang rumit.
4. Menganalisis data untuk menemukan pola.

**Artistic (A)**
1. Menggambar, melukis, atau mendesain sesuatu.
2. Menulis cerita, puisi, atau naskah.
3. Bermain musik atau menciptakan lagu.
4. Merancang tampilan visual (poster, konten, dekorasi).

**Social (S)**
1. Mengajari teman memahami pelajaran.
2. Membantu orang menyelesaikan masalah pribadi.
3. Menjadi relawan kegiatan sosial.
4. Merawat atau mendampingi orang yang membutuhkan.

**Enterprising (E)**
1. Memimpin sebuah tim atau proyek.
2. Membujuk orang untuk menyetujui ide saya.
3. Memulai dan mengelola usaha kecil.
4. Berbicara meyakinkan di depan banyak orang.

**Conventional (C)**
1. Menyusun data atau catatan dengan rapi.
2. Mengikuti prosedur dan aturan yang jelas.
3. Mengelola jadwal, anggaran, atau arsip.
4. Mengerjakan tugas yang butuh ketelitian detail.

> Catatan: ini DRAFT. Idealnya di-review agar natural & bebas bias, lalu dikunci sebagai data
> dengan metadata sumber (O\*NET, public domain) sesuai FR-D2.

---

## 8. Skema Data (selaras Model Data PRD bagian 10)

Minat sudah ada di `profiles.minat (JSON)`. Usulan isi JSON + tabel pendukung opsional.

### profiles.minat (JSON)
```json
{
  "metode": "kuesioner",            // "kuesioner" | "cerita_bebas"
  "versi_instrumen": "riasec-id-v1",
  "jawaban": { "R1": 3, "R2": 4, "I1": 2, "...": 0 },
  "skor_mentah": { "R": 10, "I": 14, "A": 6, "S": 4, "E": 8, "C": 12 },
  "skor_norm":   { "R": 0.63, "I": 0.88, "A": 0.38, "S": 0.25, "E": 0.50, "C": 0.75 },
  "holland_code": "ICR",
  "dihitung_pada": "2026-10-14T10:00:00Z"
}
```

### Tabel bank item (opsional, kalau tidak mau hardcode di config)
```
riasec_items(
  id, dimensi, teks_id, versi_instrumen, urutan,
  sumber_url, terakhir_diverifikasi
)
```

### prodi.tag_minat (JSON) - sudah ada di PRD
```json
{ "R": 0.4, "I": 0.9, "A": 0.2, "S": 0.1, "E": 0.3, "C": 0.6 }
```

---

## 9. Usulan API (selaras Spesifikasi API PRD bagian 11)

Tes minat masuk natural ke endpoint profil + explore yang sudah ada; bisa ditambah 1 endpoint
pembantu agar frontend tidak perlu tahu bank item.

- `GET /api/v1/riasec/items` -> daftar item (id, dimensi, teks) untuk ditampilkan.
- `PUT /api/v1/profile` -> kirim `minat.jawaban`; server menghitung skor_norm & holland_code
  lalu menyimpannya (deterministik).
- `POST /api/v1/explore` -> pakai `skor_norm` untuk `kemiripan_minat` -> `kecocokan`.

Contoh respons bagian minat setelah PUT /profile:
```json
{
  "minat": {
    "holland_code": "ICR",
    "skor_norm": { "R": 0.63, "I": 0.88, "A": 0.38, "S": 0.25, "E": 0.50, "C": 0.75 }
  }
}
```

---

## 10. Rencana Eksekusi untuk 3 Hari

- **Hari 1 (13 Okt):** Kunci daftar 24-30 item ID (adaptasi dari seksi 7). Simpan di config/DB.
  Implement fungsi skoring deterministik + unit test (input jawaban -> skor_norm, holland_code).
- **Hari 2 (14 Okt):** Kunci `tag_minat` 17 prodi (seksi 6.2) bersama tim data. Integrasi ke
  `/explore` via cosine similarity. Hubungkan ke rumus `kecocokan` 8.3.
- **Hari 3 (15 Okt):** Integrasi frontend (UI kuesioner + tampil Holland Code & matriks
  kecocokan x kelayakan). Opsional: LLM untuk penjelasan hasil & parsing "cerita bebas".

Scope aman kalau waktu habis: tetap kuesioner 24 item + skoring + mapping statis. Parsing
"cerita bebas" via LLM = nice-to-have.

---

## 11. Catatan Kejujuran & Etika (selaras PRD bagian 13)

- Tampilkan hasil sebagai **matriks kecocokan x kelayakan**, bukan satu angka tunggal (8.3).
- Beri label bahwa tes minat bersifat **indikatif**, bukan vonis; minat bisa berkembang.
- Jangan kirim identitas siswa ke LLM; kirim hanya ringkasan vektor minat bila perlu penjelasan.
- Minat adalah salah satu input; keputusan kelayakan tetap dari rules engine deterministik.

---

## 12. Daftar Sumber

- O\*NET Interest Profiler (US Dept. of Labor, public domain): https://services.onetcenter.org/ip
- O\*NET Interest Profiler Manual v1.0: https://www.onetcenter.org/dl_files/IP_Manual.pdf
- O\*NET Short Form psychometrics / self-scoring: https://www.onetcenter.org/dl_files/IPSF_PP.pdf
- O\*NET Score Report (deskripsi 6 tipe): https://onetcenter.org/dl_tools/ipsf/IP_Score_Report.pdf
- O\*NET Web Services reference: https://services.onetcenter.org/reference/
- Holland Code (RIASEC) overview: https://en.arabpsychology.com/scales/holland-code-riasec-test/
- Brief public domain RIASEC marker scales (Liao, Armstrong & Rounds, 2008):
  https://www.researchgate.net/publication/222697129
- Open Psychometrics RIASEC: https://openpsychometrics.org/tests/RIASEC/

> Konten dari sumber web di atas telah diparafrasekan/diringkas untuk kepatuhan lisensi.
