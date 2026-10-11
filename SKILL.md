---
name: builder-server-skill
description: >
  Merencanakan, membangun, memverifikasi, dan memperbaiki struktur server Discord
  (kategori, channel, role, permission matrix) secara agentik dari satu berkas
  konfigurasi YAML. Gunakan ketika pengguna meminta membuat/mengatur/merapikan
  server Discord, menambah role atau channel, menyetel permission, atau
  membandingkan kondisi server dengan rancangan.
---

# builder-server-skill

Skill ini mengajari agent cara **mengelola struktur server Discord lewat konfigurasi
deklaratif**, bukan dengan menulis curl satu per satu.

Prinsip utamanya: **agent yang merencanakan, adapter yang mengeksekusi.**
Agent tidak perlu menghafal endpoint Discord. Adapter (`adapter/bss`) menangani
REST, rate limit, dan seluruh jebakan yang sudah terbukti di lapangan.

---

## 1. Alur kerja — jangan lompati

```
  PLAN  ──►  DRY-RUN  ──►  APPLY  ──►  VERIFY  ──►  REPAIR
   │           │            │           │            │
 tulis      lihat diff    eksekusi    baca server   perbaiki
 config     dulu, belum   perubahan   sungguhan,    selisih yang
            ada yang      ke Discord  bandingkan    aman
            disentuh
```

Aturan keras:

1. **Selalu `plan` dulu.** Jangan pernah `apply` berdasarkan tebakan.
2. **Selalu tampilkan `dry-run` ke pengguna sebelum `apply`** kalau rencananya
   menghapus sesuatu atau mengubah permission.
3. **Selalu `verify` setelah `apply`.** API Discord bisa menerima request lalu
   menyimpan nilai yang berbeda dari yang kita kirim (lihat §4). Tanpa verify,
   kamu tidak akan pernah tahu.
4. **`repair` hanya untuk selisih yang aman.** Lihat §5.

---

## 2. Perintah adapter

Semua dijalankan dari root repo:

```bash
cd adapter
python -m bss plan     -c ../templates/community.yaml -g <GUILD_ID>
python -m bss dry-run  -c ../templates/community.yaml -g <GUILD_ID>
python -m bss apply    -c ../templates/community.yaml -g <GUILD_ID>
python -m bss verify   -c ../templates/community.yaml -g <GUILD_ID>
python -m bss repair   -c ../templates/community.yaml -g <GUILD_ID>
```

Token dibaca dari environment variable `DISCORD_TOKEN`. **Jangan pernah** menulis
token ke dalam berkas konfigurasi, template, commit, atau log.

| Perintah | Apa yang dilakukan | Aman dijalankan berulang |
|---|---|---|
| `plan` | Baca server, hitung diff, cetak ringkasan. Tanpa tulis. | ✅ ya |
| `dry-run` | `plan` + daftar request HTTP persis yang akan dikirim. Tanpa tulis. | ✅ ya |
| `apply` | Eksekusi diff. **Membuat/memperbarui/menghapus.** | ✅ ya (idempoten) |
| `verify` | Baca server, bandingkan dengan config, keluarkan laporan kecocokan. | ✅ ya |
| `repair` | Seperti `apply`, tapi hanya menyentuh selisih yang masuk daftar aman. | ✅ ya |

---

## 3. Format konfigurasi

Satu berkas YAML. Lihat `schemas/server-config.schema.json` untuk kontrak
lengkap dan `templates/` untuk contoh nyata.

```yaml
version: 1
guild: "1528939155546181642"

settings:
  verification_level: 2          # 0 NONE .. 4 VERY_HIGH
  default_message_notifications: 1
  community:
    enabled: true
    rules_channel: rules              # pakai `key`, bukan id
    public_updates_channel: staff-chat

roles:
  - key: admin
    name: "👑 Admin"
    permissions: [ADMINISTRATOR]      # nama bit, atau integer mentah
    color: "#EF4444"                  # hex, atau integer decimal
    hoist: true
    mentionable: false

categories:
  - key: informasi
    name: "━━ 📢 INFORMASI ━━"
    overwrites:
      everyone: { deny: [SEND_MESSAGES, SEND_TTS_MESSAGES, EMBED_LINKS, ATTACH_FILES] }
    channels:
      - key: rules
        name: "📜 rules"
        type: text                     # text | announcement | forum | voice | stage
        topic: "Ketentuan server."
```

Penting soal nama:

- **Channel dipaksa lowercase** oleh Discord. `Rules` dikembalikan menjadi `rules`.
- **Kategori mempertahankan huruf besar** — `📢・INFORMASI` aman.
- Emoji dan `・` diterima di nama channel, kategori, dan role.
- `key` hanya untuk referensi antar-field di config (mis. `afk_channel: afk`).
  `key` tidak pernah dikirim ke Discord.

---

## 4. Jebakan Discord yang SUDAH TERBUKTI — baca sebelum menulis config

Ini bagian paling bernilai dari skill ini. Semua ditemukan lewat pengujian
langsung terhadap API, bukan tebakan.

### 4.1 Community mengunci channel dan menghilangkan `NEWS`

Saat feature `COMMUNITY` aktif, guild **wajib** punya `rules_channel_id` dan
`public_updates_channel_id`. Kedua channel itu:

- **tidak bisa dihapus** → `400 Cannot delete a channel required for community servers`
- **tidak bisa di-null** → `400`
- **tidak bisa di-repoint** → API membalas `200` tapi nilai lama dipertahankan
  (silent reject — inilah kenapa `verify` wajib)

Sebaliknya, mematikan Community (`PATCH {"features":[]}`) melepas kunci itu.

### 4.2 Channel announcement (type 5) butuh `NEWS`, `NEWS` butuh Community

`type: 5` ditolak selama `NEWS` tidak ada. Dan `NEWS` hanya hidup saat
Community aktif. Ini menciptakan lingkaran:

```
butuh announcement  →  butuh NEWS  →  butuh Community  →  butuh channel yang sudah ada
```

**Urutan yang benar (sudah terbukti jalan):**

```
1. PATCH {"features":[]}                    → Community mati, kunci lepas
2. bangun struktur non-announcement         → type 5 belum bisa dibuat
3. PATCH {"features":["COMMUNITY","NEWS"],
          "rules_channel_id": <id>,
          "public_updates_channel_id": <id>}
                                            → Community + NEWS nyala
4. BARU buat channel type 5
```

### 4.3 `features` harus dikirim bersama rules + updates

Mengirim `{"features":["COMMUNITY","NEWS"]}` **saja** menghasilkan `400`.
Field `rules_channel_id` dan `public_updates_channel_id` wajib ikut dalam
PATCH yang sama. Adapter sudah menangani ini — jangan coba PATCH `features`
sendirian.

### 4.4 `rules` dan `public_updates` boleh channel yang sama

Tidak perlu membuat channel tambahan khusus untuk keduanya.

### 4.5 Hierarki role tidak mengikuti urutan pembuatan

Role baru semuanya lahir di `position: 1` dan diurutkan oleh id, sehingga
**urutan pembuatan terbalik** di sidebar. Kamu harus mengirim PATCH eksplisit
ke `PATCH /guilds/{id}/roles` dengan array `{id, position}` untuk semua role.

### 4.6 Role managed oleh bot tidak boleh dihapus

`GET /guilds/{id}/roles` mengembalikan `managed: true` untuk role milik bot.
Menghapusnya akan merusak bot itu. Selalu saring: `select(.managed == false)`.

### 4.7 Menghapus kategori TIDAK menghapus isinya

Anak-anaknya menjadi parentless. Hapus channel dulu, baru kategorinya.

### 4.8 Type channel yang valid untuk dibuat

```
0  text        2  voice       4  category
5  announcement (butuh NEWS)   6  stage
13 stage?      14 ?            15 forum         16 media
```

Nilai pasti bergantung pada feature guild. Kalau API menolak, pesan errornya
mencantumkan daftar `BASE_TYPE_CHOICES` yang valid — baca pesan itu, jangan
menebak.

### 4.9 Rate limit

Sekitar 5 request/detik per route. Sisipkan jeda ~0.3 detik antar request.
Adapter sudah melakukannya otomatis.

---

## 5. Batasan `repair` — jangan sentuh sisanya

`repair` hanya boleh menyentuh perubahan **konvergen dan terbalik**:

| Aman untuk repair | Berisiko — minta izin pengguna dulu |
|---|---|
| Rename channel / kategori | Menghapus channel |
| Mengganti `topic` | Menghapus role |
| Menambah / mengubah `color` role | Menurunkan `position` role di bawah role lain |
| Menambah / mengubah `hoist`, `mentionable` | Mengubah `permissions` role jadi `ADMINISTRATOR` |
| Menambah channel baru | Mengubah `settings.community` |
| Menambah role baru | Mengubah permission overwrite jadi lebih luas |
| Menyesuaikan `position` channel dalam kategori | Mengubah `verification_level` ke bawah |

Alasannya: yang di kolom kiri tidak menghapus akses siapapun. Yang di kolom
kanan bisa membuka server lebar-besar atau memutus akses seseorang.

**Kalau rencana mengandung salah satu dari kolom kanan, hentikan dan tanyakan
ke pengguna.** Tunjukkan diff-nya. Jangan pernah diam-diam menurunkan
`verification_level` atau menghapus channel.

---

## 6. Prosedur standar

### Membangun server baru

```
1. tanya kebutuhan: komunitas / developer / gaming / lainnya
2. salin template terdekat dari templates/ sebagai titik awal
3. sesuaikan nama, channel, role
4. plan  → tunjukkan ringkasan ke pengguna
5. dry-run → tunjukkan request yang akan dikirim kalau ada penghapusan
6. apply
7. verify → laporkan hasilnya
```

### Memperbaiki server yang sudah ada

```
1. tulis config yang menggambarkan keadaan IDEAL
2. plan  → lihat apa yang server sebenarnya punya
3. review diff — pisahkan "aman" vs "berisiko"
4. repair untuk yang aman, tanyakan yang berisiko
5. verify
```

### Menambah channel atau role saja

```
1. edit config, tambah entry baru
2. plan   → harusnya hanya menunjukkan penambahan
3. apply  → hanya entry baru yang dibuat
4. verify
```

---

## 7. Keamanan

- **Token** hanya dari `DISCORD_TOKEN` env var. Tidak pernah di-commit.
- **Jangan pernah** mencetak isi `.env` atau variabel yang mirip.
- **Bot minimalis.** Beri bot permission `MANAGE_ROLES` + `MANAGE_CHANNELS`
  + `VIEW_CHANNEL` saja. Jangan kasih `ADMINISTRATOR` kecuali memang perlu —
  permission bot = izin atas token milik orang lain.
- **Role bot harus di posisi paling atas** dari semua role yang ingin diurusnya.
  Discord menolak mengubah role yang lebih tinggi dari role bot sendiri.
- **Audit trail.** Adapter otomatis menyertakan header
  `X-Audit-Log-Reason: builder-server-skill`. Jangan hilangkan.
- **`View Server As Role`** di client Discord adalah cara tercepat memverifikasi
  visibility secara manual setelah `verify`.

---

## 8. Kapan harus menolak

Berhenti dan jelaskan ke pengguna, tanpa mengeksekusi, kalau diminta:

- Menghapus semua channel atau role (kemungkinan salah target guild)
- Menurunkan `verification_level` saat server sedang rawan raid
- Memberi `ADMINISTRATOR` ke role yang berisi member biasa
- Menjadikan `@everyone` boleh `SEND_MESSAGES` di channel info
- Menjalankan apply ke guild yang tidak mereka sebutkan id-nya secara eksplisit

Dalam kasus ini, tampilkan dulu `plan` dan `dry-run`, lalu tunggu konfirmasi.
