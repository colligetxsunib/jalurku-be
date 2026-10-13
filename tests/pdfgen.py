"""Pembuat PDF minimal untuk tes (tanpa dependensi tambahan). Teks ASCII, satu teks per halaman."""

from __future__ import annotations


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def buat_pdf(halaman: list[str]) -> bytes:
    """`halaman[i]` boleh berisi beberapa baris (dipisah \\n). Halaman '' = halaman tanpa teks."""
    n = len(halaman)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objek: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, teks in enumerate(halaman):
        konten = 5 + 2 * i
        objek.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {konten} 0 R "
                "/Resources << /Font << /F1 3 0 R >> >> >>"
            ).encode()
        )
        baris = [b for b in teks.split("\n") if b] if teks else []
        isi = (
            "BT /F1 11 Tf 14 TL 36 750 Td " + " T* ".join(f"({_esc(b)}) Tj" for b in baris) + " ET"
            if baris
            else ""
        )
        objek.append(f"<< /Length {len(isi)} >>\nstream\n{isi}\nendstream".encode())

    keluar = bytearray(b"%PDF-1.4\n")
    offset: list[int] = []
    for i, o in enumerate(objek, start=1):
        offset.append(len(keluar))
        keluar += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(keluar)
    keluar += f"xref\n0 {len(objek) + 1}\n0000000000 65535 f \n".encode()
    keluar += "".join(f"{off:010d} 00000 n \n" for off in offset).encode()
    keluar += (
        f"trailer\n<< /Size {len(objek) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(keluar)


def paragraf(kata_kunci: str, jumlah_kalimat: int = 6) -> str:
    """Teks Indonesia sintetis, tiap kalimat unik, beberapa baris (seperti hasil ekstraksi PDF)."""
    kalimat = [
        f"Ketentuan {kata_kunci} nomor {i + 1} menjelaskan bahwa peserta wajib memeriksa persyaratan "
        f"resmi sebelum mendaftar dan mengikuti seleksi tahun 2026."
        for i in range(jumlah_kalimat)
    ]
    # pecah ke beberapa baris pendek seperti keluaran PDF
    teks = " ".join(kalimat)
    kata = teks.split()
    return "\n".join(" ".join(kata[i : i + 9]) for i in range(0, len(kata), 9))
