# Third-Party Notices

Bagian ini berisi informasi tentang komponen pihak ketiga yang dipakai atau
didistribusikan ulang di repositori ini.

## Ponytail skill files

File `ponytail.md` dan `ponytail-review.md` di installer (yang disalin ke
`~/.config/nexus-cli/skills/` saat `bash install.sh`) adalah turunan dari
project [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail),
berlisensi MIT.

Lisensi asli:

> MIT License
>
> Copyright (c) 2025 DietrichGebert
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.

File skill yang terinstal memuat frontmatter asli (`homepage:` ke repo
upstream). Perubahan hanya soal:

- Penamaan file: `SKILL.md` → `ponytail.md` / `ponytail-review.md`
  (sesuai konvensi loader `nexus_cli`, yang memindai `*.md` langsung,
  bukan subdirektori).

Skill tambahan (audit/debt/gain/help) tidak dimasukkan ke installer karena
bersifat dokumentasi/benchmark, bukan aturan perilaku agen. Tersedia di
[repo upstream](https://github.com/DietrichGebert/ponytail) untuk dipakai
manual.

## Dependensi Python

- `requests` — Apache 2.0. Resmi dipaketkan banyak distribusi Linux
  (`python3-requests`).
