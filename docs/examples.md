# Contoh

Dokumen ini menunjukkan cara memakai skill pada tiga situasi nyata.
Semua perintah dijalankan dari root repo.

```bash
export DISCORD_TOKEN="<token-bot>"
```

Token hanya dari environment variable. Jangan pernah ditulis ke config,
template, commit, atau log.

---

## 1. Membangun server baru

**Situasi:** punya server kosong, mau server komunitas dengan pengumuman.

```bash
cd adapter
cp ../templates/community.yaml ../my-server.yaml
# edit: ganti `guild`, sesuaikan nama channel dan role

python -m bss plan -c ../my-server.yaml
```

Keluaran kira-kira:

```
Rencana: 22 perubahan (12 create, 1 set-positions, ...)

  + role      👑 Admin
  + role      🛡️ Moderator
  + role      ✅ Member
  + kategori  ━━ 📢 INFORMASI ━━
  + channel   👋 selamat-datang
  + channel   📣 pengumuman
      butuh feature NEWS — dibuat setelah Community aktif
  ...
```

Kalau tidak ada penghapusan, aman lanjut:

```bash
python -m bss apply -c ../my-server.yaml
```

Urutan eksekusi adapter — dan kenapa tidak boleh dibalik:

```
1. matikan Community dulu kalau ada penghapusan channel terkunci
2. hapus channel (anak dulu) dan role
3. buat role              ← sebelum channel, karena overwrite merujuk id role
4. buat kategori
5. buat channel biasa     ← rules harus sudah ada sebelum Community nyala
6. nyalakan Community     ← features + rules + updates dalam SATU PATCH
7. BARU buat channel announcement
8. update (rename, topic, overwrite)
9. set posisi role        ← setelah semua role dibuat
10. set pengaturan guild
```

Setelah itu, verifikasi:

```bash
python -m bss verify -c ../my-server.yaml
```

```
✓ VERIFIED — server sesuai rancangan.
```

---

## 2. Menambah channel baru

**Situasi:** server sudah jalan, mau tambah channel `📜 patch-notes` di kategori
info.

```bash
# edit config, tambahkan entry channel
python -m bss plan -c ../my-server.yaml
```

Yang penting diperiksa: **hanya boleh ada penambahan**, tidak ada delete.

```
Rencana: 1 perubahan (1 create)

  + channel   📜 patch-notes
```

Lalu:

```bash
python -m bss apply -c ../my-server.yaml
python -m bss verify -c ../my-server.yaml
```

Karena `apply` idempoten, menjalankannya dua kali aman — kali kedua akan
bilang `Tidak ada perubahan`.

---

## 3. Memperbaiki server yang sudah berantakan

**Situasi:** server sudah diisi manual, ada channel dan role yang tidak rapi.
Config menggambarkan keadaan **ideal**.

```bash
python -m bss plan -c ../ideal.yaml
```

Contoh keluaran:

```
Rencana: 6 perubahan (2 create, 3 update, 1 delete)

  ~ role      🛡️ Moderator
  + role      🤝 Helper
  ~ channel   💬 obrolan
  - role      test234  [caution]
      menghapus role — akses member ini hilang. Konfirmasi diperlukan.

⚠  Perubahan berisiko terdeteksi — membutuhkan konfirmasi.
```

**Jangan langsung `apply`.** Jalankan `repair` dulu, yang hanya menyentuh
yang aman:

```bash
python -m bss repair -c ../ideal.yaml
```

```
REPAIR — hanya perubahan ber-risks safe yang dieksekusi.
...
✓ 3 perubahan diterapkan.
⊘ 1 dilewati:
    delete role test234  — risiko caution — lewati (safe_only)
```

Tinggal `test234` yang tersisa. Kalau memang mau menghapusnya, jalankan
`apply --yes` — tapi pastikan sudah yakin.

### Kenapa `test234` bukan `safe`

Karena menghapus role menghilangkan akses seseorang, dan itu tidak bisa
dikembalikan dengan menjalankan `repair` lagi. `SKILL.md` §5 mencatat
daftar lengkap apa yang dianggap berisiko.

---

## 4. Membaca pesan error Discord

Kalau API menolak, jangan menebak. Pesan errornya biasanya sudah menjelaskan.

**`Cannot delete a channel required for community servers`**
→ Channel itu `rules_channel` atau `public_updates_channel`. Matikan Community
dulu (adapter melakukannya otomatis kalau config benar).

**`BASE_TYPE_CHOICES ... invalid ...`**
→ Tipe channel tidak valid untuk guild ini. Pesannya memuat daftar yang
berlaku — baca, jangan tebak. Umumnya `announcement` butuh feature `NEWS`.

**`400` saat PATCH `features` sendirian**
→ `features` tidak bisa dikirim tanpa `rules_channel_id` dan
`public_updates_channel_id` di PATCH yang sama. Lihat `SKILL.md` §4.3.

**Role tidak bisa diubah / dihapus**
→ Role itu `managed` (milik bot), atau posisinya di atas role bot kamu.
Role bot harus berada di posisi paling atas dari semua role yang ingin diurusnya.

---

## 5. Pola permission yang sering dibutuhkan

### Sembunyikan channel dari member biasa

```yaml
- key: command-staff
  name: "⚙️ command-staff"
  type: text
  overwrites:
    member:    { deny: [VIEW_CHANNEL] }
    moderator: { allow: [VIEW_CHANNEL, SEND_MESSAGES, READ_MESSAGE_HISTORY,
                         EMBED_LINKS, ATTACH_FILES] }
```

`deny` harus di level channel, bukan kategori — karena `✅ Member` sudah
di-allow `VIEW_CHANNEL` di kategori. Detail di `docs/permissions.md`.

### Channel pengumuman yang hanya bisa ditulis staf

```yaml
overwrites:
  everyone:
    deny: [SEND_MESSAGES, SEND_TTS_MESSAGES, EMBED_LINKS, ATTACH_FILES]
  moderator:
    allow: [VIEW_CHANNEL, SEND_MESSAGES, READ_MESSAGE_HISTORY,
            EMBED_LINKS, ATTACH_FILES]
```

### Mute menyeluruh

Role `🔇 Muted` dengan overwrite di setiap kategori:

```yaml
overwrites:
  muted:
    deny: [ADD_REACTIONS, SEND_MESSAGES, SEND_TTS_MESSAGES]   # text
  # dan untuk kategori voice:
  muted:
    deny: [CONNECT, SPEAK]
```

---

## 6. Verifikasi manual yang tidak bisa diotomasi

Setelah `verify` bilang OK, masih ada satu hal yang perlu dicek tangan:

**View Server As Role** — klik kanan server → pilih role.

Dari situ kamu melihat persis apa yang dilihat role itu, termasuk channel yang
seharusnya tersembunyi. Ini pemeriksaan paling cepat menangkap kesalahan
permission yang lolos dari diff — terutama kategori staf yang tidak sengaja
terbuka.
