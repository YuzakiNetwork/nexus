---
name: Bug Report
about: Lapor bug agar bisa kami reproduksi dan perbaiki
title: "[BUG] "
labels: bug
assignees: ''
---

## Ringkasan

Jelaskan bug dalam 1-2 kalimat.

## Langkah reproduksi

1. Jalankan `nexus --workspace /path/ke/proyek`
2. Ketik prompt: `...`
3. Lihat error: `...`

## Expected behavior

Apa yang seharusnya terjadi.

## Actual behavior

Apa yang terjadi saat ini.

## Environment

- OS: [mis. Ubuntu 22.04, macOS 14, Windows 11]
- Python: [output dari `python3 --version`]
- Versi nexus: [output dari `nexus --help` atau `python3 -m nexus_cli --help`]
- Model: [mis. `minimaxai/minimax-m3`, default]

## Log error

Output dari `/errors` (di dalam CLI interaktif), atau tempel isi
`.nexus/errors.jsonl` (sensor API key!).

```jsonl
[output here]
```

## Screenshot / rekaman

Jika relevan.

## Kemungkinan penyebab

Kalau Anda sudah punya hipotesis, bagikan — tapi jangan merasa wajib.
