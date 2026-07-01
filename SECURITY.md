# Security Policy

## Supported Versions

| Versi  | Didukung         |
|--------|------------------|
| 0.2.x  | ✅ aktif          |
| 0.1.x  | ⚠️ hanya patch keamanan kritis |
| < 0.1  | ❌ tidak didukung |

## Reporting a Vulnerability

**Jangan laporkan漏洞 keamanan lewat issue publik.**

Kirim laporan ke email maintainer (lihat profil GitHub) dengan subject
`[SECURITY] nexus-cli`. Sertakan:

- Deskripsi漏洞 dan dampak potensial.
- Langkah reproduksi (proof-of-concept bila ada).
- Versi yang terpengaruh.
- Estimasi tingkat keparahan (low / medium / high / critical).

Kami akan merespons dalam **7 hari kerja** dan berusaha:

1. Konfirmasi penerimaan.
2. Reproduksi internal.
3. Patch + CVE coordination bila perlu.
4. Disclosure publik setelah patch tersedia.

## Konfigurasi aman

- File `.env` di `~/.config/nexus-cli/` di-`chmod 600` oleh installer.
- `NVIDIA_API_KEY` JANGAN pernah di-commit atau di-paste ke issue/PR.
- API key hanya dipakai untuk request server-side ke NVIDIA; tidak ada
  telemetry yang dikirim ke server lain.

## Sandboxing

- Semua akses file dibatasi ke `--workspace` (path traversal dicegah).
- Shell command punya daftar blokir (`rm -rf /`, `mkfs`, `dd`, dll).
- Tetapkan workspace ke folder terpisah kalau agent dipakai untuk eksperimen.

## Dependensi

Hanya `requests` (stdlib urllib3 + certifi). Tetap aman; dependabot akan
memberi tahu kalau ada advisory.

Terima kasih sudah membantu menjaga Nexus CLI tetap aman 🙏
