# Catatan data JalurKu (dicek 13 Oktober 2026)

Kolom `terakhir_diverifikasi` sengaja kosong. Isi setelah verifikasi manual.

## Status per file
| File | Status |
|---|---|
| rule_gate.csv | Terisi dari paparan resmi SNPMB 2026 (13 syarat). Siklus 2026 |
| config_ketentuan.csv | Terisi. Batas pilihan, kuota sekolah, komposisi pilihan SNBT, blokir lintas jalur |
| dokumen_wajib.csv | Terisi. 3 baris bersumber sekunder, ditandai di nama dokumen |
| ptn.csv | Terisi. Provinsi UI perlu dicek (sumber lain menulis lokasi UI di Jakarta Pusat) |
| prodi.csv | 185 baris. Kolom baru `jenjang` dan `program` (akademik/vokasi). UI terisi: 16 prodi Sarjana + 15 prodi vokasi (9 D3, 6 Sarjana Terapan). 9 PTN lain kosong |
| acuan_skor_snbt.csv | Kosong. Tidak ada passing grade resmi |
| dokumen_rag_metadata.csv | 5 dokumen. PDF perlu diunduh manual |
| golden_set_draft.csv | 12 pertanyaan awal. Kolom halaman belum diisi |

## Temuan yang mengubah PRD
1. SNBP: 2 pilihan prodi, bukan 4. Jika 2 prodi, satu harus di PTN provinsi sekolah asal.
2. SNBT: maksimal 4 pilihan, tapi untuk 3-4 pilihan wajib ada program vokasi. Sarjana maksimal 2. Simulator strategi harus mengikuti ini.
3. SNBP 2026 mensyaratkan nilai TKA. Tambahkan field `punya_nilai_tka` di profil.
4. Pemeringkatan SNBP memakai rerata semua semester kecuali semester terakhir. Rapor semester 1-5 untuk SMA adalah tafsiran, bukan kutipan resmi.
5. Peluncuran SNPMB 2027 tidak ditemukan. Sumber terbaru yang kutemukan (1 Sept 2026) menyatakan jadwal 2027 belum diumumkan. Pakai 2026 sebagai acuan dan cek snpmb.id.
6. Persona Rani (NTT): tidak ada PTN NTT di 10 PTN. Dengan aturan provinsi, ia hanya bisa memilih 1 prodi di SNBP. Ganti provinsi persona atau pilih satu prodi saja di demo.
7. Tidak ada passing grade SNBT resmi. Usul: kategori SNBT memakai keketatan (peminat / daya tampung) jika tidak ada sumber skor yang bisa dipertanggungjawabkan.
8. DKV tidak ada di daftar SNBT UI. Cek keberadaan tiap kombinasi PTN x prodi. Prodi seni/olahraga mungkin butuh portofolio.

## Sumber
- Resmi: paparan SNPMB 2026 di files.snpmb.id (dibaca penuh).
- Data prodi UI: agregator pintarly.id yang mengklaim berasal dari snpmb.id. Halaman resmi yang kucoba mengembalikan 404, jadi verifikasi ke snpmb.id.
- Kolom rumpun adalah klasifikasiku sendiri, ubah sesuai kebutuhan.

## Update: prodi vokasi
- 15 prodi vokasi UI (SNBT 2026) ditambah dengan id `ui-v-*`, `program=vokasi`. Sarjana Terapan dan D3 dihitung vokasi.
- 9 dari 15 adalah D3, jadi komposisi SNBT yang mensyaratkan minimal 1 D3 bisa dipenuhi dari data UI saja.
- Vokasi PTN lain belum diambil. Gunakan ekspor snpmb.id.
- Kolom `rumpun` vokasi adalah klasifikasiku sendiri, ubah bila perlu.
