# Instrumen tes minat RIASEC

Backend membaca butir dari `instrumen_v1.json` di folder ini. Butir tersebut **orisinal, disusun
tim berdasarkan kerangka teori Holland (RIASEC)**: kegiatan yang disukai, satu kalimat pendek, bahasa
untuk siswa SMA. Instrumen **belum divalidasi psikometrik** dan **bukan tes psikologi** maupun
diagnosis; setiap respons API membawa pernyataan itu. Lembar review untuk pemilik data dan guru BK:
`reports/butir_riasec_review.csv` (berlabel "draf, belum diverifikasi").

`instrumen_contoh.json` hanya **fixture tes** (2 butir placeholder per dimensi, berlabel "contoh").
Bila `instrumen_v1.json` tidak ada, backend memakai berkas contoh dan semua hasilnya berkeyakinan
`rendah` supaya tidak pernah terlihat seperti instrumen sungguhan.

## Format `instrumen_v1.json`

```json
{
  "versi_instrumen": "riasec-id-v1",
  "sumber": "Disusun tim berdasarkan kerangka teori Holland (RIASEC). Butir orisinal, belum divalidasi psikometrik, bukan tes psikologi.",
  "skala": {"min": 0, "maks": 4, "label": {"0": "Sangat tidak suka", "4": "Sangat suka"}},
  "dimensi": ["realistis", "investigatif", "artistik", "sosial", "enterprising", "konvensional"],
  "item": [
    {"id": "r1", "teks": "Memperbaiki sepeda yang rusak, misalnya rantai atau remnya.", "dimensi": "realistis"}
  ]
}
```

Aturan yang diperiksa saat aplikasi start (kesalahan = aplikasi gagal start):

- `dimensi` harus tepat sama dengan `minat.dimensi` di `config/app.yaml`.
- `id` butir unik dan lolos pola `^[a-z][a-z0-9_-]*$` (maksimal 64 karakter).
- Tiap dimensi punya minimal 1 butir; `skala.min` dan `skala.maks` bilangan bulat, `min < maks`.

Setelah mengganti berkas ini, jalankan `uv run python -m scripts.build_api_collection` supaya
API Collection memakai id butir yang baru.
