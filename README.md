# Nexus CLI

Nexus CLI adalah coding agent terminal sederhana seperti Codex, OpenClaw, atau Aider. Model default memakai `minimaxai/minimax-m3` melalui NVIDIA API.

## Install

Install sekali, lalu command `nexus` bisa dipakai dari folder mana pun:

```bash
cd /home/inji/nexus_cli
bash install.sh
```

Jika `~/.local/bin` baru ditambahkan ke PATH, reload shell:

```bash
source ~/.bashrc
```

Isi API key di config global:

```bash
nano ~/.config/nexus-cli/.env
```

Formatnya:

```bash
NVIDIA_API_KEY=...
```

Setelah itu masuk ke proyek apa pun dan jalankan:

```bash
cd /path/proyek
nexus
```

Installer membuat wrapper `~/.local/bin/nexus` yang otomatis memakai folder saat ini sebagai workspace.
Installer juga membuat skill default di `~/.config/nexus-cli/skills`.

## Install Manual

```bash
cd /home/inji/nexus_cli
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

Isi `.env`:

```bash
NVIDIA_API_KEY=...
```

## Pakai

```bash
nexus --workspace /path/proyek
```

Atau tanpa install:

```bash
python3 -m nexus_cli --workspace /path/proyek
```

Prompt sekali jalan dengan gambar atau video:

```bash
nexus --workspace . --image screenshot.png "Jelaskan isi gambar ini"
```

## Perintah interaktif

- `/help` menampilkan bantuan.
- `/status` menampilkan workspace, memori, skill, dan MCP.
- `/read path` membaca file.
- `/write path` menulis file dari editor multi-line.
- `/append path` menambah teks ke file.
- `/search pattern` mencari teks dengan `rg`.
- `/run command` menjalankan terminal command di workspace.
- `/open url_or_path` membuka URL atau file lokal di browser.
- `/image path_or_url prompt` mengirim gambar/video lokal atau URL ke model.
- `/remember text` menyimpan memori lokal.
- `/memory` melihat memori.
- `/skills` melihat skill yang terdeteksi.
- `/mcp` melihat server MCP dari config.
- `/errors [N]` melihat N error API terakhir yang dicatat ke `.nexus/errors.jsonl`.
- `/clear-errors` mengosongkan log error.
- `/exit` keluar.

## Ketahanan & kualitas

### Error logging otomatis

Semua error API dicatat ke `.nexus/errors.jsonl` (JSONL append-only dengan
rotasi 5 MiB). Lihat via `/errors 20`. Agen juga menerima ringkasan 5 error
terakhir di system prompt agar bisa mendiagnosa pola kegagalan.

### Auto-retry & fallback model

- Retry otomatis untuk 429 (rate limit), 408, 425, 5xx, dan network error,
  dengan exponential backoff capped 8 detik. Header `Retry-After` dihormati.
- Bila model utama gagal recoverable (rate_limit, server, network, atau 404
  not_found), agen otomatis coba fallback model. Default
  `meta/llama-3.1-70b-instruct`, override via env `NEXUS_FALLBACK_MODEL`.
- Error 401/403 (auth) langsung propagate tanpa retry — biasanya API key salah.

### Persistensi yang aman

- Session disimpan ke `.nexus/session.json` dengan **atomic write**
  (tulis ke `.tmp` lalu `os.replace`), sehingga file tidak korup saat
  proses crash / Ctrl+C / power loss.
- Pesan user disimpan sebelum model dipanggil — `/exit` setelah percakapan
  panjang tidak akan kehilangan pesan.
- Path state disimpan absolut agar tidak ambigu ketika cwd berubah.

## Development

```bash
# Install editable
pip install -e .

# Run tests
pip install pytest
python3 -m pytest tests/ -v
```

CI otomatis: lihat `.github/workflows/ci.yml` (test matrix Python 3.10/3.11/3.12).

## Fitur agent

Agent dapat memanggil tool lokal dengan format JSON di respons model:

```json
{"tool":"read_file","args":{"path":"README.md"}}
```

Tool yang tersedia:

- `list_files`
- `read_file`
- `write_file`
- `append_file`
- `replace_in_file`
- `search_text`
- `shell_command`
- `open_browser`
- `remember`
- `list_skills`
- `mcp_list_servers`
- `mcp_list_tools`
- `mcp_call_tool`

Semua akses file dibatasi ke `--workspace`.

## Skills

Taruh file Markdown di `.nexus/skills/*.md`. Isi skill akan masuk ke system prompt.
Skill global bisa ditaruh di `~/.config/nexus-cli/skills/*.md` dan berlaku untuk semua proyek.

### Skill yang terpasang otomatis

| File | Sumber | Fungsi |
|------|--------|--------|
| `core.md` | installer | Pedoman kerja coding agent |
| `terminal.md` | installer | Cara pakai `shell_command` |
| `browser.md` | installer | Cara pakai `open_browser` |
| `ponytail.md` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT) | Lazy coding: YAGNI → stdlib → native → one-liner |
| `ponytail-review.md` | same | Format review over-engineering untuk diff |

Ponytail membantu agen menulis kode seminimal mungkin sambil tetap
menjaga validation, error handling, dan security. Lihat
[repo upstream](https://github.com/DietrichGebert/ponytail) untuk benchmark
dan skill tambahan (audit/debt/gain/help).

### Tambah skill sendiri

```bash
mkdir -p .nexus/skills
cat > .nexus/skills/python-style.md <<'EOF'
# Python Style

Selalu jalankan `python -m compileall` setelah mengubah file Python.
EOF
```

## Memory

Memori disimpan di `.nexus/memory.json`.

## MCP

Buat `.nexus/mcp.json`:

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
      "env": {}
    }
  }
}
```

Saat ini MCP mendukung server stdio dasar: initialize, tools/list, dan tools/call.

## Berkontribusi

Lihat [CONTRIBUTING.md](CONTRIBUTING.md) untuk setup development, gaya kode,
dan panduan PR.

## Keamanan

Untuk laporan kerentanan, lihat [SECURITY.md](SECURITY.md).

## Lisensi

[MIT](LICENSE) © 2025 YuzakiNetwork.
