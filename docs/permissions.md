# Permission Discord

Bagian paling rawan salah saat mengatur server Discord adalah permission:
nilainya biner, tidak ada nilai "sedikit saja", dan satu bit yang salah bisa
membuka server lebar-besar atau mengunci semua orang.

Dokumen ini mencatat nilai yang **sudah terbukti dipakai di server produksi**,
bukan sekadar daftar teori.

## Cara permission bekerja

Discord memakai *permission overwrite* berlapis, dari yang paling umum ke
paling khusus:

```
@everyone role
   ↓
role role (makin tinggi hierarkinya, makin menang)
   ↓
channel category
   ↓
channel itu sendiri (paling menang)
```

Di tiap lapis ada dua field: `allow` dan `deny`. Yang menang adalah bit yang
ada di `deny` layer paling bawah, kecuali di-`allow` di layer yang lebih
bawah lagi.

**Konsekuensi penting:** untuk menyembunyikan satu channel dari sebuah role
yang sudah di-`allow` di kategori, kamu harus `deny` di level channel —
`deny` kategori tidak cukup, karena channel-allow menang.

## Nilai bit

Semua izin di bawah ini adalah bit tunggal (satu `1` dalam binary).
Adapter mengirimnya sebagai **string**, bukan integer — karena bit di atas
`2^31` akan overflow di JSON.

| Izin | Nilai |
|---|---|
| `CREATE_INSTANT_INVITE` | 1 |
| `KICK_MEMBERS` | 2 |
| `BAN_MEMBERS` | 4 |
| `ADMINISTRATOR` | 8 |
| `MANAGE_CHANNELS` | 16 |
| `MANAGE_GUILD` | 32 |
| `ADD_REACTIONS` | 64 |
| `VIEW_AUDIT_LOG` | 128 |
| `PRIORITY_SPEAKER` | 256 |
| `STREAM` | 512 |
| `VIEW_CHANNEL` | 1024 |
| `SEND_MESSAGES` | 2048 |
| `SEND_TTS_MESSAGES` | 4096 |
| `MANAGE_MESSAGES` | 8192 |
| `EMBED_LINKS` | 16384 |
| `ATTACH_FILES` | 32768 |
| `READ_MESSAGE_HISTORY` | 65536 |
| `MENTION_EVERYONE` | 131072 |
| `USE_EXTERNAL_EMOJIS` | 262144 |
| `VIEW_GUILD_INSIGHTS` | 524288 |
| `CONNECT` | 1048576 |
| `SPEAK` | 2097152 |
| `MUTE_MEMBERS` | 4194304 |
| `DEAFEN_MEMBERS` | 8388608 |
| `MOVE_MEMBERS` | 16777216 |
| `USE_VAD` | 33554432 |
| `CHANGE_NICKNAME` | 67108864 |
| `MANAGE_NICKNAMES` | 134217728 |
| `MANAGE_ROLES` | 268435456 |
| `MANAGE_WEBHOOKS` | 536870912 |
| `MANAGE_GUILD_EXPRESSIONS` | 1073741824 |
| `USE_APPLICATION_COMMANDS` | 2147483648 |
| `REQUEST_TO_SPEAK` | 4294967296 |
| `MANAGE_EVENTS` | 8589934592 |
| `MANAGE_THREADS` | 17179869184 |
| `CREATE_PUBLIC_THREADS` | 34359738368 |
| `CREATE_PRIVATE_THREADS` | 68719476736 |
| `USE_EXTERNAL_STICKERS` | 137438953472 |
| `SEND_MESSAGES_IN_THREADS` | 274877906944 |
| `USE_EMBEDDED_ACTIVITIES` | 549755813888 |
| `MODERATE_MEMBERS` | 1099511627776 |
| `USE_SOUNDBOARD` | 4398046511104 |
| `CREATE_EVENTS` | 17592186044416 |
| `SEND_VOICE_MESSAGES` | 70368744177664 |
| `SET_VOICE_CHANNEL_STATUS` | 281474976710656 |
| `USE_EXTERNAL_APPS` | 562949953421312 |

Bit yang tidak dicatat di sini tetap ada di `adapter/bss/bits.py` — lihat
sumber resmi Discord untuk daftar paling lengkap.

## Gabungan yang terbukti

Nilai-nilai berikut sudah dipakai langsung di server produksi dan diverifikasi
lewat API. Adapter menamainya supaya config bisa dirujuk secara manusiawi
(alih-alih menulis angka mentah yang tidak terbaca).

### `READ_ONLY_DENY` = 55296

```
SEND_MESSAGES | SEND_TTS_MESSAGES | EMBED_LINKS | ATTACH_FILES
```

**Pakai untuk:** kategori informasi — semua orang bisa membaca, tidak ada yang
bisa menulis, termasuk staf yang belum di-allow khusus.

Ini adalah pola paling penting di seluruh repo. Kanal seperti rules, faq, dan
selamat-datang harus terlihat semua orang tapi tidak bisa dikomentari.

### `HIDDEN_DENY` = 68608

```
VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY
```

**Pakai untuk:** kategori staf — tidak terlihat sama sekali di sidebar.

### `MUTED_TEXT_DENY` = 6208

```
ADD_REACTIONS | SEND_MESSAGES | SEND_TTS_MESSAGES
```

**Pakai untuk:** role Muted di text channel.

Catatan: `ADD_REACTIONS` ikut diblokir supaya member yang dimute tidak bisa
meng spam reaction — detail kecil yang sering terlewat.

### `MUTED_VOICE_DENY` = 3145728

```
CONNECT | SPEAK
```

**Pakai untuk:** Muted di voice.

Desain: Muted **boleh masuk** channel voice (jadi tetap bisa dengar dan
mengobrol lewat text), tapi tidak boleh bicara. Kalau kamu juga memblokir
`CONNECT`, member itu benar-benar terpisah dari komunitas voice.

### `MEMBER_TEXT_ALLOW` = 117824

```
VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES | READ_MESSAGE_HISTORY | ADD_REACTIONS
```

**Pakai untuk:** `✅ Member` di kategori ngobrol — pola dasar yang
mengaktifkan channel bagi member biasa.

### `MEMBER_VOICE_ALLOW` = 3146752

```
VIEW_CHANNEL | CONNECT | SPEAK
```

### `STAFF_ALLOW` = 117760

```
VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES | READ_MESSAGE_HISTORY
```

**Pakai untuk:** Helper / Support / Event Manager — bisa baca-tulis tanpa
punya izin moderasi.

## Pola permission yang sering dipakai

### 1. Kategori terbuka tapi read-only

```yaml
overwrites:
  everyone:
    deny: [SEND_MESSAGES, SEND_TTS_MESSAGES, EMBED_LINKS, ATTACH_FILES]
```

Semua orang melihat, tidak ada yang menulis. Channel pengumuman yang hanya
boleh ditulis staf memakai pola ini, lalu di-`allow` khusus untuk role staf.

### 2. Kategori tersembunyi, dibuka per role

```yaml
overwrites:
  everyone: { deny: [VIEW_CHANNEL] }
  member:   { allow: [VIEW_CHANNEL, SEND_MESSAGES, EMBED_LINKS,
                      ATTACH_FILES, READ_MESSAGE_HISTORY, ADD_REACTIONS] }
  muted:    { deny: [ADD_REACTIONS, SEND_MESSAGES, SEND_TTS_MESSAGES] }
```

`@everyone` tidak melihat kategori. `✅ Member` di-allow — inilah yang
mengaktifkan seluruh channel di dalamnya. `🔇 Muted` di-deny kembali supaya
terkena meski masih pegang role Member.

### 3. Sembunyikan satu channel dari member

```yaml
overwrites:
  member:     { deny: [VIEW_CHANNEL] }
  moderator:  { allow: [VIEW_CHANNEL, SEND_MESSAGES, READ_MESSAGE_HISTORY,
                        EMBED_LINKS, ATTACH_FILES] }
```

Karena `✅ Member` sudah di-`allow` `VIEW_CHANNEL` di level kategori, satu-satunya
cara menyembunyikan channel tertentu adalah `deny` di **level channel**.
`deny` kategori tidak menang — channel-allow lebih bawah, jadi ia yang menang.

Ini pola untuk `command-staff`, `mod-log`, dan `ticket-staff`.

## Kesalahan yang paling mahal

| Kesalahan | Akibat |
|---|---|
| Lupa blokir `VIEW_CHANNEL` di kategori staf | Seluruh log moderasi terlihat publik |
| `everyone: { allow: [VIEW_CHANNEL] }` di kategori info | Channel info tidak bisa dikunci read-only |
| Mute tapi lupa `ADD_REACTIONS` | Member yang dimute tetap bisa spam reaction |
| `MANAGE_ROLES` diberikan ke role berisi member biasa | Mereka bisa menaikkan role mereka sendiri sampai setinggi bot |
| `ADMINISTRATOR` ke role helper | Bisa mengubah apa saja, termasuk menghapus channel |
| Menurunkan `verification_level` saat rawan raid | Membuka pintu untuk bot spam |

Terakhir: **permission bot = izin atas token milik orang lain.** Beri bot
hanya `MANAGE_ROLES` + `MANAGE_CHANNELS` + `VIEW_CHANNEL`. `ADMINISTRATOR`
ke bot adalah keputusan yang harus disadari, bukan default.

## Cara memeriksa manual

Setelah `verify` selesai, cara tercepat memastikan visibility benar adalah
**View Server As Role** di client Discord (klik kanan server → View Server As
Role). Dari situ kamu melihat persis apa yang dilihat role itu — termasuk
channel yang seharusnya tersembunyi.

Ini pemeriksaan yang tidak bisa diotomasi, dan paling sering menangkap hal
yang lolos dari diff.
