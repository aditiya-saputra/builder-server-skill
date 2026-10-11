# Arsitektur

Skill ini memisahkan tiga hal yang biasanya tercampur dalam bot Discord:

```
┌──────────────────────────────────────────────────────────────────┐
│  SKILL.md          Prosedur kerja — dibaca oleh agent AI          │
│                                                                  │
│    Planner ──────► Adapter ──────► Verifier                      │
│   (agent AI)     (Python REST)    (diff nyata vs rancangan)      │
│                                                                  │
│   merencanakan   mengeksekusi     memeriksa hasil                │
│   dari bahasa    tindakan yang                                   │
│   alami          tervalidasi                                     │
└──────────────────────────────────────────────────────────────────┘
```

## Kenapa dipisah

**`SKILL.md` berisi instruksi. Adapter berisi eksekusi.**

Kalau keduanya digabung, dua masalah muncuk:

1. Skill tidak bisa dipakai ulang. Instruksi tentang cara menata server Discord
   seharusnya tidak ikut hilang kalau kamu mengganti bahasa adapter.
2. Adapter tidak bisa diuji tanpa agent. Logika diff dan konversi permission
   adalah bagian yang paling mudah rusak — dan bagian yang paling butuh test.

Dengan dipisah, `pytest` bisa memverifikasi adapter tanpa token, tanpa
jaringan, dan tanpa agent yang menjalankannya.

## Keputusan arsitektur penting

### HTTP-only, stateless

Adapter tidak memakai gateway/WebSocket dan tidak punya proses yang harus jalan
terus. Setiap operasi adalah request REST biasa.

Ini bukan penghematan semata. Sebagian besar pekerjaan "mengelola server
Discord" — membuat channel, mengatur role, menyetel permission — murni
operasi CRUD lewat REST. Menambah gateway berarti menambah:

- proses jalan terus yang harus dipantau
- state koneksi yang bisa putus
- cara-cara gagal baru (heartbeat timeout, session resume, dsb.)

untuk hasil yang sama. Gateway baru berguna kalau kamu butuh *event* —
reaction-role otomatis, listener, AutoMod sendiri. Itu adapter terpisah,
bukan bagian dari MVP ini.

### Config sebagai sumber kebenaran

Ini keputusan yang paling membedakan skill ini dari sekadar script curl.

Tanpa config tersimpan sebagai data, setiap permintaan kecil berarti
**mengarang ulang seluruh server** — dan menghapus riwayat channel yang sudah
hidup, thread yang sudah ada, dan pesan yang sudah terkirim.

Dengan config, adapter bisa:

1. membaca keadaan **nyata** dari Discord
2. membandingkannya dengan keadaan yang **diinginkan**
3. membuat **perubahan bertahap** — hanya menyentuh yang berbeda

Ini yang membuat `apply` idempoten: menjalankannya dua kali berturut-turut
menghasilkan nol perubahan pada kali kedua.

### Nama sebagai pengenal

Discord tidak menyimpan "key" yang kita tentukan sendiri. Karena itu config
memakai dua hal sekaligus:

- **`key`** — identifier internal untuk referensi antar-field di config
  (`afk_channel: afk`, overwrite `role: mod`). Tidak pernah dikirim ke Discord.
- **`name`** — yang benar-benar tampil, dan satu-satunya jangkar untuk
  mencocokkan config dengan state nyata.

Pencocokan: role berdasar nama, kategori berdasar nama, channel berdasar nama
*dalam* kategorinya.

Ini punya batasan yang perlu diketahui: kalau kamu mengganti nama sebuah
channel, adapter akan melihatnya sebagai "channel lama dihapus + channel baru
dibuat" — bukan rename. Kalau itu tidak diinginkan, ubah nama di config
sekaligus dengan tindakan lain, atau lakukan rename manual sekali lalu
sesuaikan config.

## Aliran data

```yaml
                    ┌─────────────┐
  config.yaml ────►│   config.py  │──► ServerConfig (dataclass)
                    └─────────────┘         │
                                            ▼
                    ┌─────────────┐   ┌───────────┐
  Discord API ────►│  client.py  │──►│  plan.py  │──► Plan [Change]
                    └─────────────┘   └───────────┘         │
                                                            ▼
                                                    ┌───────────┐
                                                    │ apply.py  │──► Discord API
                                                    └───────────┘
                                                            │
                                                            ▼ (GET ulang)
                                                    ┌───────────┐
                                                    │ verify.py │──► Report
                                                    └───────────┘
```

`plan.py` sengaja **tidak menyentuh jaringan**. Ia menerima state mentah
sebagai parameter. Karena itu seluruh logika diff bisa diuji offline —
lihat `tests/test_plan.py`.

## Mengapa verify terpisah dari plan

Ini paling sering dilupakan, dan sudah terbukti mahal harganya.

**Discord bisa membalas `200` tetapi menyimpan nilai yang berbeda dari yang
kita kirim.**

Yang paling terbukti: `PATCH /guilds/{id}` dengan `rules_channel_id` saat
Community aktif. API membalas sukses, tapi nilai lama dipertahankan. Kalau
kamu percaya pada isi response write, kamu akan mengira semuanya berjalan
lancar padahal tidak.

Karena itu `verify` **tidak pernah** mempercayai response write. Ia selalu
GET ulang, lalu membandingkan dari nol. `SKILL.md` §1 mewajibkan verify
setiap kali apply — bukan hiasan, tapi satu-satunya cara tahu.

## Risiko dan safe_only

Setiap `Change` membawa `risk`:

| `risk` | Arti | `repair` boleh? |
|---|---|---|
| `safe` | konvergen dan terbalik — tidak menghapus akses siapapun | ✅ ya |
| `caution` | bisa menghapus akses atau data | ❌ tidak, minta izin |

`repair` = `apply(safe_only=True)`. Ia mengeksekusi yang `safe` dan
melaporkan yang `caution` sebagai dilewati.

`apply` mengeksekusi semuanya, tapi **menolak berjalan** kalau ada `caution`
dan `--yes` tidak diberikan. Ini supaya tidak ada yang menghapus channel
secara tidak sengaja.

Daftar lengkap apa yang termasuk `caution` ada di `SKILL.md` §5.

## Menambah adapter platform lain

Discord adalah adapter pertama, bukan batas proyeknya.

Kalau cakupan meluas ke platform lain, tambahkan `adapter/<platform>/` dengan
tiga titik masuk yang sama:

```python
def fetch_state(...) -> State      # baca keadaan nyata
def build_plan(config, state) -> Plan
def apply(config, plan, ...) -> Result
def verify(config, state) -> Report
```

`SKILL.md` dan alur Planner/Adapter/Verifier tetap berlaku apa adanya. Yang
berubah hanya `schemas/` (kontrak config per platform) dan `templates/`.
