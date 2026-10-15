# Data eksplorasi DRAF (belum terverifikasi)

Isi folder ini **draf**, bukan data resmi. Dipakai `/explore` hanya bila data resmi
(`prodi.tag_minat`, `prodi.mapel_penentu`, tabel `profesi`) kosong, dan hasilnya selalu ditandai
"draf, belum terverifikasi" (`sumber_profil: draf`, `label_data`, `memakai_data_draf`, dan catatan).

| Berkas | Isi |
|---|---|
| `prodi_eksplorasi_draf.csv` | `tag_minat` (dimensi RIASEC, dipisah `\|`) dan `mapel_penentu` per prodi |
| `profesi_draf.csv` | contoh profesi per rumpun |

- Diturunkan mekanis dari klasifikasi awal rumpun di `config/app.yaml` (bagian `explore`): tag minat
  untuk bobot >= 0,5 dan mapel untuk bobot >= 0,8. **Sama untuk semua prodi dalam satu rumpun**; belum
  disesuaikan per prodi. Bangun ulang: `uv run python -m scripts.buat_draf_eksplorasi`.
- Berkas ini **tidak memuat** `terakhir_diverifikasi`; setiap baris wajib berlabel `draf` di kolom `status`
  (aplikasi menolak start bila label hilang atau kolom verifikasi muncul).
- **Tidak dicampur ke CSV utama** di `data/seed/`. Bila tim data sudah memverifikasi dan mengisi
  `prodi.csv` / `profesi.csv`, data resmi otomatis didahulukan dan draf ini tidak lagi dipakai.
- Tim data dapat menyunting per prodi, tetapi baris yang disunting tetap draf sampai dipindahkan ke
  CSV utama lewat proses verifikasi.
