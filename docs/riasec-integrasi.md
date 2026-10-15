# Catatan integrasi instrumen tes minat (RIASEC)

## Keputusan: butir PR #1 tidak dipakai

PR #1 (branch `dev`, commit `a136711`) membawa 24 butir tes minat yang merupakan terjemahan dari
O*NET Interest Profiler. Butir itu **tidak dipakai** oleh JalurKu karena alasan lisensi:

- Salinan verbatim O*NET Interest Profiler berlisensi CC BY-ND 4.0 (tanpa turunan).
- Terjemahan adalah **modifikasi**, dan modifikasi O*NET memerlukan O*NET Tools Developer License,
  yang antara lain mewajibkan kredit, tautan lisensi, validasi produk, dan pernyataan modifikasi.
- Klaim "public domain" pada PR #1 keliru; butir O*NET bukan domain publik.

Butir yang dipakai JalurKu (`data/riasec/instrumen_v1.json`) **orisinal**, ditulis tim dari definisi
enam tipe Holland (Realistic, Investigative, Artistic, Social, Enterprising, Conventional), bukan
terjemahan, salinan, atau parafrase butir O*NET maupun butir PR #1. Kemiripan yang wajar (topik
kegiatan yang sama) tak terhindarkan karena kedua instrumen mengukur kerangka yang sama, tetapi
tidak ada teks butir yang merupakan karya turunan O*NET.

Pemeriksaan kemiripan dilakukan dengan membandingkan token dan frasa terhadap butir PR; butir
dengan kemiripan tertinggi dilaporkan ke pemilik data untuk review bersama guru BK
(`reports/butir_riasec_review.csv`).

## Yang diambil dari PR #1

Dari PR #1 hanya diambil hal yang teknis dan tidak berkaitan dengan butir:

- `response_model` Pydantic untuk respons `GET /riasec/questions` dan `POST /riasec/submit`
  (`app/schemas/riasec.py`), dengan tambahan satu-satunya di GET: `min_terjawab` (aditif);
- pola validasi id butir pada skema permintaan;
- posisi akhir folder "04b Tes minat RIASEC" pada API Collection.

Isi respons tidak berubah dari kontrak dashboard: POST tetap memuat holland_code, skor_norm,
keyakinan, dan pernyataan "bukan tes psikologi".

## Aturan nama

Nama O*NET hanya boleh muncul di dokumen ini, sebagai alasan butir PR tidak dipakai. Di
`config/`, `app/`, `data/riasec/`, respons API, dan dokumen lain yang dikirim ke pengguna, tidak
boleh ada penyebutan O*NET atau klaim "domain publik"/"public domain" (dijaga tes
`tests/test_riasec.py`).
