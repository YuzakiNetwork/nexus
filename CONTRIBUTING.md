# Contributing to Nexus CLI

Terima kasih sudah tertarik berkontribusi! Panduan singkat:

## Setup development

```bash
git clone https://github.com/YuzakiNetwork/nexus.git
cd nexus
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env  # isi NVIDIA_API_KEY
```

## Menjalankan test

```bash
python3 -m pytest tests/ -v
```

Atau smoke test cepat tanpa network:

```bash
NVIDIA_API_KEY=test-key python3 -c "from nexus_cli.agent import Workspace, SessionStore; print('ok')"
```

## Style kode

- Python 3.10+, type hints dipakai di kode baru.
- Pakai `pathlib.Path`, bukan `os.path` string concatenation.
- Error harus masuk `ErrorLog` jika berasal dari API call.
- Hindari `print()` debugging — pakai `logging` modul bila perlu.

## Pull request

1. Fork repo, buat branch fitur: `git checkout -b feat/nama-fitur`.
2. Commit dengan pesan konvensional: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`.
3. Pastikan tidak ada regression: jalankan test.
4. Buka PR ke branch `main`. Jelaskan **apa** dan **kenapa**, bukan hanya **bagaimana**.
5. Jangan commit `.env`, `.nexus/`, atau credential apapun.

## Laporan bug

Pakai [issue template](../../issues/new?template=bug_report.md). Sertakan:
- Output `nexus --version` dan `python3 --version`.
- Langkah reproduksi.
- Output `/errors` (jika ada error API).
- Screenshot jika relevan.

## Ide fitur

Pakai [feature request template](../../issues/new?template=feature_request.md).
Diskusi besar (arsitektur, model) mohon buka issue dulu sebelum PR agar
tidak ada effort yang terbuang.

## Lisensi

Dengan berkontribusi, Anda setuju bahwa kontribusi Anda akan dilisensikan
di bawah [MIT License](LICENSE).
