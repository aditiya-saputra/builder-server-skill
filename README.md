# builder-server-skill

> Skill OpenCode untuk **merencanakan, membangun, memverifikasi, dan memperbaiki**
> struktur server Discord secara agentik — dari satu berkas konfigurasi YAML.

Bukan bot template. Bukan library. Ini skill yang **mengajari AI cara bekerja**
dengan server Discord: membaca keadaan nyata, membandingkannya dengan rancangan,
lalu memperbaiki selisihnya secara bertahap.

```
┌─────────────────────────────────────────────────────────────┐
│  SKILL.md          Prosedur kerja untuk agent AI            │
│                                                             │
│  ┌───────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │  Planner  │──►│   Adapter    │──►│   Verifier   │        │
│  │ (agent AI)│   │ (Python REST)│   │ (diff actual │        │
│  │           │   │              │   │   vs wanted) │        │
│  └───────────┘   └──────────────┘   └──────────────┘        │
│   merencanakan    mengeksekusi      memeriksa hasil         │
│   dari bahasa     tindakan yang                             │
│   alami           tervalidasi                               │
└─────────────────────────────────────────────────────────────┘
```

## Kenapa dipisah

`SKILL.md` berisi **instruksi dan prosedur**. Adapter berisi **operasi Discord
yang tervalidasi**. Pemisahan ini membuat skill bisa dipakai ulang tanpa
menulis ulang sistem bot — dan adapter bisa diuji secara terpisah tanpa agent.

Satu keputusan arsitektur yang penting: **adapter HTTP-only dan stateless.**
Tidak ada WebSocket, tidak ada proses jalan terus. Setiap operasi adalah
request REST biasa. Ini sengaja — sesuai constraint asli proyek ini (curl-only),
dan membuat seluruh alur bisa diuji, diulang, dan dipahami dalam satu kali baca.

## Instalasi

```bash
git clone https://github.com/<you>/builder-server-skill.git
cd builder-server-skill/adapter
pip install -e .
export DISCORD_TOKEN="token-bot-kamu"
```

Token hanya dibaca dari environment variable. Tidak pernah ditulis ke berkas
konfigurasi, template, commit, atau log.

## Cara pakai

```bash
cd adapter

# Lihat apa yang akan berubah — tanpa menyentuh server
python -m bss plan    -c ../templates/community.yaml -g <GUILD_ID>

# Lihat request HTTP persis yang akan dikirim
python -m bss dry-run -c ../templates/community.yaml -g <GUILD_ID>

# Eksekusi
python -m bss apply   -c ../templates/community.yaml -g <GUILD_ID>

# Bandingkan hasil dengan rancangan
python -m bss verify  -c ../templates/community.yaml -g <GUILD_ID>

# Perbaiki selisih yang aman saja
python -m bss repair  -c ../templates/community.yaml -g <GUILD_ID>
```

## Fitur MVP

| Fitur | Fungsi |
|---|---|
| **Plan** | Menyusun rancangan server dari instruksi bahasa alami |
| **Build** | Membuat kategori, channel, dan role |
| **Permissions** | Mengatur serta memvalidasi izin |
| **Verify** | Memeriksa apakah hasil sesuai rancangan |
| **Repair** | Memperbaiki perbedaan yang aman |
| **Dry run** | Menampilkan rencana perubahan sebelum eksekusi |

## Kenapa konfigurasi YAML

Karena itu yang membedakan skill ini dari sekadar script curl.

Dengan konfigurasi tersimpan sebagai data, AI bisa membandingkan **keadaan yang
diinginkan** dengan **keadaan aktual**, lalu membuat perubahan **secara
bertahap** — alih-alih mengarang ulang seluruh server setiap kali dipanggil.
Tanpa ini, setiap permintaan kecil berarti membangun ulang dari nol dan
menghapus riwayat channel yang sudah hidup.

## Repo ini sudah diuji di server sungguhan

Seluruh jebakan di `SKILL.md` §4 bukan tebakan. Semua ditemukan dengan
mengoperasikan API Discord sungguhan dan membaca pesan errornya:

- Community **mengunci** `rules_channel` dan `public_updates_channel` — tak bisa
  dihapus, di-null, atau di-repoint (API membalas `200` tapi menyimpan nilai lama)
- Channel announcement butuh feature `NEWS`, yang hanya hidup saat Community aktif
- `features` tidak bisa dikirim sendirian — wajib bersama `rules_channel_id` dan
  public_updates_channel_id
- Role baru semuanya lahir di `position: 1`, jadi hierarki harus di-set eksplisit
- Role managed milik bot tidak boleh dihapus

Detail lengkap ada di [`SKILL.md`](SKILL.md) §4.

## Struktur repo

```text
builder-server-skill/
├── SKILL.md                     Prosedur kerja untuk agent (inti skill)
├── README.md                    Berkas ini
├── LICENSE
├── docs/
│   ├── architecture.md          Kenapa Planner/Adapter/Verifier dipisah
│   ├── permissions.md           Matriks izin dan nilai bit
│   └── examples.md              Kasus nyata end-to-end
├── templates/
│   ├── community.yaml           Server komunitas umum
│   ├── developer.yaml           Server developer / proyek open-source
│   └── gaming.yaml              Server gaming
├── schemas/
│   └── server-config.schema.json
├── adapter/
│   ├── pyproject.toml
│   └── bss/
│       ├── client.py            REST client Discord (rate limit, audit header)
│       ├── bits.py              Nilai permission bit & alias
│       ├── config.py            Muat + validasi YAML terhadap schema
│       ├── plan.py              Hitung diff rancangan vs aktual
│       ├── apply.py             Eksekusi diff
│       ├── verify.py            Baca aktual, bandingkan, laporkan
│       └── __main__.py          CLI
└── tests/
    ├── test_bits.py
    ├── test_config.py
    └── test_plan.py
```

## Menjalankan test

```bash
cd adapter
pip install -e ".[dev]"
pytest
```

Test tidak membutuhkan token atau koneksi jaringan — logika diff dan konversi
permission diuji secara murni.

## Menambah adapter lain

Discord adalah **adapter pertama, bukan batas proyeknya.**

Kalau cakupannya meluas ke platform lain, tambahkan `adapter/<platform>/` dengan
tiga fungsi yang sama — `fetch_state`, `apply_plan`, `verify` — dan buat schema
konfigurasi per platform. `SKILL.md` dan alur Planner/Adapter/Verifier tetap
berlaku apa adanya.

## Lisensi

MIT — lihat [`LICENSE`](LICENSE).
