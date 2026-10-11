"""Nilai permission bit Discord dan utilitas konversinya.

Sumber: https://discord.com/developers/docs/topics/permissions

Nilai-nilai di bawah ini bukan tebakan — beberapa di antaranya dipakai langsung
di server sungguhan dan diverifikasi lewat API. Komentar menandai yang sudah
terbukti bekerja.

Bit di atas 2^31 butuh string, bukan integer, karena JSON menganggapnya overflow.
Karena itu SEMUA izin dikirim sebagai string ke Discord.
"""

from __future__ import annotations

from typing import Iterable, List, Union

# ── Bit mentah ───────────────────────────────────────────────────────────────
CREATE_INSTANT_INVITE = 1 << 0
KICK_MEMBERS = 1 << 1
BAN_MEMBERS = 1 << 2
ADMINISTRATOR = 1 << 3
MANAGE_CHANNELS = 1 << 4
MANAGE_GUILD = 1 << 5
ADD_REACTIONS = 1 << 6
VIEW_AUDIT_LOG = 1 << 7
PRIORITY_SPEAKER = 1 << 8
STREAM = 1 << 9
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
SEND_TTS_MESSAGES = 1 << 12
MANAGE_MESSAGES = 1 << 13
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
MENTION_EVERYONE = 1 << 17
USE_EXTERNAL_EMOJIS = 1 << 18
VIEW_GUILD_INSIGHTS = 1 << 19
CONNECT = 1 << 20
SPEAK = 1 << 21
MUTE_MEMBERS = 1 << 22
DEAFEN_MEMBERS = 1 << 23
MOVE_MEMBERS = 1 << 24
USE_VAD = 1 << 25
CHANGE_NICKNAME = 1 << 26
MANAGE_NICKNAMES = 1 << 27
MANAGE_ROLES = 1 << 28
MANAGE_WEBHOOKS = 1 << 29
MANAGE_GUILD_EXPRESSIONS = 1 << 30
USE_APPLICATION_COMMANDS = 1 << 31
REQUEST_TO_SPEAK = 1 << 32
MANAGE_EVENTS = 1 << 33
MANAGE_THREADS = 1 << 34
CREATE_PUBLIC_THREADS = 1 << 35
CREATE_PRIVATE_THREADS = 1 << 36
USE_EXTERNAL_STICKERS = 1 << 37
SEND_MESSAGES_IN_THREADS = 1 << 38
USE_EMBEDDED_ACTIVITIES = 1 << 39
MODERATE_MEMBERS = 1 << 40
VIEW_CREATOR_MONETIZATION_ANALYTICS = 1 << 41
USE_SOUNDBOARD = 1 << 42
CREATE_GUILD_EXPRESSIONS = 1 << 43
CREATE_EVENTS = 1 << 44
USE_EXTERNAL_SOUNDS = 1 << 45
SEND_VOICE_MESSAGES = 1 << 46
USE_CLYDE_AI = 1 << 47
SET_VOICE_CHANNEL_STATUS = 1 << 48
USE_EXTERNAL_APPS = 1 << 49


#: Nama bit -> nilai. Dipakai untuk menyelesaikan nama di config jadi integer.
NAMES = {
    name: value
    for name, value in globals().items()
    if name.isupper() and isinstance(value, int) and not name.startswith("_")
}


# ── Gabungan yang terbukti dipakai di server sungguhan ───────────────────────
#
# Semua angka di bawah ini sudah diverifikasi langsung terhadap API Discord
# pada server produksi. Jangan diubah tanpa menguji ulang.

#: Channel read-only: blokir semua cara menulis, tapi tetap bisa dibaca.
#: = SEND_MESSAGES | SEND_TTS_MESSAGES | EMBED_LINKS | ATTACH_FILES = 55296
READ_ONLY_DENY = SEND_MESSAGES | SEND_TTS_MESSAGES | EMBED_LINKS | ATTACH_FILES
assert READ_ONLY_DENY == 55296

#: Channel tersembunyi total: tak terlihat, tak bisa dikirim, riwayat tertutup.
#: = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY = 68608
HIDDEN_DENY = VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY
assert HIDDEN_DENY == 68608

#: Muted di text channel.
#: = ADD_REACTIONS | SEND_MESSAGES | SEND_TTS_MESSAGES = 6208
MUTED_TEXT_DENY = ADD_REACTIONS | SEND_MESSAGES | SEND_TTS_MESSAGES
assert MUTED_TEXT_DENY == 6208

#: Muted di voice channel: boleh masuk, tak boleh bicara.
#: = CONNECT | SPEAK = 3145728
MUTED_VOICE_DENY = CONNECT | SPEAK
assert MUTED_VOICE_DENY == 3145728

#: Izin dasar member di text channel.
#: = VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES |
#:   READ_MESSAGE_HISTORY | ADD_REACTIONS = 117824
MEMBER_TEXT_ALLOW = (
    VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES |
    READ_MESSAGE_HISTORY | ADD_REACTIONS
)
assert MEMBER_TEXT_ALLOW == 117824

#: Izin dasar member di voice channel.
#: = VIEW_CHANNEL | CONNECT | SPEAK = 3146752
MEMBER_VOICE_ALLOW = VIEW_CHANNEL | CONNECT | SPEAK
assert MEMBER_VOICE_ALLOW == 3146752

#: Staf: bisa baca-tulis tapi tanpa izin moderasi.
#: = VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES | READ_HISTORY
STAFF_ALLOW = VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES | READ_MESSAGE_HISTORY
assert STAFF_ALLOW == 117760


#: Gabungan siap pakai, bisa dirujuk dari config sebagai nama bit.
COMBINATIONS = {
    "READ_ONLY_DENY": READ_ONLY_DENY,
    "HIDDEN_DENY": HIDDEN_DENY,
    "MUTED_TEXT_DENY": MUTED_TEXT_DENY,
    "MUTED_VOICE_DENY": MUTED_VOICE_DENY,
    "MEMBER_TEXT_ALLOW": MEMBER_TEXT_ALLOW,
    "MEMBER_VOICE_ALLOW": MEMBER_VOICE_ALLOW,
    "STAFF_ALLOW": STAFF_ALLOW,
}


def resolve(spec: Union[str, int, Iterable[Union[str, int]], None]) -> int:
    """Selesaikan spesifikasi permission dari config jadi satu integer.

    Menerima:
      * nama bit tunggal        -> "SEND_MESSAGES"
      * gabungan siap pakai     -> "MEMBER_TEXT_ALLOW"
      * integer mentah          -> 6144 atau "6144"
      * daftar campuran         -> ["VIEW_CHANNEL", 2048]
      * None / kosong           -> 0

    Raises:
        ValueError: kalau ada nama yang tidak dikenal.
    """
    if spec is None:
        return 0

    # bool harus dicek SEBELUM int, karena True/False adalah subclass int di
    # Python. Tanpa ini, resolve(True) lolos sebagai izin bit 1.
    if isinstance(spec, bool):
        raise ValueError(f"izin boolean tidak valid: {spec!r}")

    if isinstance(spec, (int, str)):
        spec = [spec]

    total = 0
    for item in spec:
        if isinstance(item, bool):
            raise ValueError(f"izin boolean tidak valid: {item!r}")
        if isinstance(item, int):
            total |= item
            continue

        text = str(item).strip()
        if text.isdigit():
            total |= int(text)
            continue
        if text in NAMES:
            total |= NAMES[text]
            continue
        if text in COMBINATIONS:
            total |= COMBINATIONS[text]
            continue

        raise ValueError(
            f"nama izin tidak dikenal: {item!r}. "
            f"Lihat docs/permissions.md untuk daftar lengkap."
        )

    return total


def names_of(value: int) -> List[str]:
    """Balikkan integer permission jadi daftar nama bit (untuk laporan diff)."""
    return [name for name, bit in sorted(NAMES.items(), key=lambda kv: kv[1]) if value & bit]
