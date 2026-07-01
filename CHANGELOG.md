# Changelog

Semua perubahan penting di repo ini didokumentasikan di sini.
Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/).

## [0.2.0] - 2025-XX-XX

### Ditambahkan
- **Error logging**: `ErrorLog` class mencatat semua error API ke `.nexus/errors.jsonl`
  (JSONL append-only dengan rotasi 5 MiB). Dilengkapi command `/errors [N]`
  dan `/clear-errors`.
- **Auto-retry**: `NvidiaClient` otomatis retry untuk 429 (rate limit), 5xx (server),
  dan network error dengan exponential backoff capped 8 detik, menghormati
  header `Retry-After`.
- **Auto-fallback model**: bila model utama gagal recoverable (rate_limit,
  server, network, atau 404 not_found), agent otomatis coba model fallback.
  Default `meta/llama-3.1-70b-instruct`, override via env `NEXUS_FALLBACK_MODEL`.
- **Kategori error** di `ModelError`: `auth`, `not_found`, `rate_limit`,
  `server`, `bad_request`, `network`, `unknown`.
- **System prompt sadar-error**: 5 error terbaru otomatis disisipkan ke system
  prompt agar agent bisa mendiagnosa pola kegagalan.
- **Fallback workspace read-only**: bila workspace tidak bisa ditulis, state
  disimpan di `~/.config/nexus-cli/<hash>`.

### Diperbaiki
- **Session tidak hilang saat keluar**: pesan user disimpan sebelum model
  dipanggil; `finally` block menjamin `save_session()` di setiap exit path
  (`/exit`, `Ctrl+C`, `EOF`, exception).
- **Atomic write**: `SessionStore.save` dan `MemoryStore.save` menulis ke
  `.tmp` lalu `os.replace`, sehingga file tidak korup saat proses crash.
- **Path absolut**: `Workspace.state_dir` di-resolve absolut agar tidak
  ambigu ketika cwd berubah.
- **Error 401/403 tidak di-retry**: sebelumnya NetworkError membuat retry
  yang tidak perlu; sekarang kategori `auth` langsung fail.
- **Path instalasi portable**: wrapper `~/.local/bin/nexus` memakai env var
  `NEXUS_CLI_HOME` bukan path hardcoded, sehingga clone ke lokasi lain
  tetap berfungsi.

### Berubah
- Versi naik dari `0.1.0` ke `0.2.0`.
- Default fallback model: `meta/llama-3.1-70b-instruct`.

## [0.1.0] - 2025-XX-XX

### Ditambahkan
- Rilis awal: terminal coding agent dengan tool `list_files`, `read_file`,
  `write_file`, `append_file`, `replace_in_file`, `search_text`,
  `shell_command`, `open_browser`, `remember`, `list_skills`,
  `mcp_list_servers`, `mcp_list_tools`, `mcp_call_tool`.
- Multi-line input dengan sentinel `EOF`.
- Skill loader dari global (`~/.config/nexus-cli/skills`) dan project
  (`.nexus/skills`).
- Session persist per-project.
- MCP stdio client (initialize, tools/list, tools/call).

[0.2.0]: #020---2025-xx-xx
[0.1.0]: #010---2025-xx-xx
