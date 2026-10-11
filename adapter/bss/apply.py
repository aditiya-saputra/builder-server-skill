"""Eksekusi plan ke Discord.

Bagian paling rapuh dari seluruh adapter ada di sini, karena Discord
mempunyai urutan ketergantungan yang tidak bisa dibalik (SKILL.md §4):

    announcement  →  butuh NEWS  →  butuh Community aktif
    Community     →  butuh rules_channel + public_updates_channel sudah ada
    Community aktif →  kedua channel itu TERKUNGI, tak bisa dihapus

Maka urutan eksekusi yang benar adalah:

    1. matikan Community dulu kalau ada penghapusan channel terkunci
    2. hapus channel (anak dulu, lalu kategori) dan role
    3. buat role                     ← sebelum channel, karena overwrite merujuk id
    4. buat kategori
    5. buat channel non-announcement  ← rules harus sudah ada sebelum Community nyala
    6. nyalakan Community             ← features + rules + updates dalam 1 PATCH
    7. BARU buat channel announcement
    8. update (rename, topic, overwrite)
    9. set posisi role                ← setelah semua role dibuat
   10. set pengaturan guild

Salah urutan di atas akan gagal dengan pesan error yang membingungkan,
atau lebih buruk: balas 200 tapi tidak menyimpan apa pun.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import DiscordClient
from .config import ServerConfig
from .plan import Change, Plan


class ApplyResult:
    def __init__(self) -> None:
        self.applied: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[str] = []

    def ok(self, change: Change, detail: str = "") -> None:
        suffix = f"  ({detail})" if detail else ""
        self.applied.append(f"{change.action} {change.kind} {change.target}{suffix}")

    def skip(self, change: Change, reason: str) -> None:
        self.skipped.append(f"{change.action} {change.kind} {change.target}  — {reason}")

    def fail(self, change: Change, error: Exception) -> None:
        self.errors.append(f"{change.action} {change.kind} {change.target}  — {error}")

    @property
    def ok_count(self) -> int:
        return len(self.applied)


def apply(
    config: ServerConfig,
    plan: Plan,
    client: DiscordClient,
    *,
    safe_only: bool = False,
    verbose: bool = True,
) -> ApplyResult:
    """Jalankan plan.

    Args:
        safe_only: kalau True (dipakai `repair`), hanya perubahan ber-risks safe
            yang dieksekusi. Yang caution dilewati dan dilaporkan.
    """
    guild_id = config.guild
    result = ApplyResult()

    def take(change: Change) -> bool:
        """True kalau change ini boleh dieksekusi."""
        if safe_only and change.risk != "safe":
            result.skip(change, f"risiko {change.risk} — lewati (safe_only)")
            return False
        return True

    # Muat state awal — dibutuhkan untuk keputusan urutan Community.
    guild_state = client.guild(guild_id)
    channel_states = client.channels(guild_id)
    locked_ids = _locked_channel_ids(guild_state)

    deletes = [c for c in plan.changes if c.action == "delete"]
    touches_locked = any(
        c.kind in ("channel", "category") and getattr(c.ref, "id", None) in locked_ids
        for c in deletes
    )

    # ── 1. Community dimatikan bila ada penghapusan channel terkunci ────────
    # Channel yang ditunjuk sebagai rules_channel_id / public_updates_channel_id
    # tidak bisa dihapus selama Community aktif. Matikan dulu supaya kunci lepas.
    if touches_locked and guild_state.get("features"):
        try:
            client.update_guild(guild_id, {"features": []})
            if verbose:
                print("  = community dimatikan dulu (melepas kunci channel)")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"gagal mematikan community — {exc}")
            return result

    # ── 2. penghapusan: channel anak dulu, lalu kategori, lalu role ─────────
    for change in deletes:
        if not take(change):
            continue
        try:
            if change.kind == "channel":
                client.delete_channel(change.ref["id"])
            elif change.kind == "category":
                client.delete_channel(change.ref["id"])
            elif change.kind == "role":
                client.delete_role(guild_id, change.ref["id"])
            result.ok(change)
            if verbose:
                print(f"  - {change.kind} {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # ── 3. role dibuat dulu — overwrite channel merujuk id role ─────────────
    created_role_ids: Dict[str, str] = {}
    for change in plan.changes:
        if change.action != "create" or change.kind != "role" or not take(change):
            continue
        try:
            created = client.create_role(guild_id, change.payload)
            created_role_ids[change.target] = created["id"]
            result.ok(change, created["id"])
            if verbose:
                print(f"  + role {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # Tambahkan role yang sudah ada supaya overwrite bisa merujuk.
    for state in client.roles(guild_id):
        created_role_ids.setdefault(state["name"], state["id"])
    everyone_id = guild_id

    # ── 4. kategori ────────────────────────────────────────────────────────
    category_ids: Dict[str, str] = {}
    for state in client.channels(guild_id):
        if state.get("type") == 4:
            category_ids[state["name"]] = state["id"]

    for change in plan.changes:
        if change.action != "create" or change.kind != "category" or not take(change):
            continue
        try:
            payload = _with_overwrite_ids(change.payload, created_role_ids, everyone_id)
            created = client.create_channel(guild_id, payload)
            category_ids[change.target] = created["id"]
            result.ok(change, created["id"])
            if verbose:
                print(f"  + kategori {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # ── 5 & 7. channel: non-announcement dulu, announcement setelah Community ─
    channel_creates = [c for c in plan.changes
                       if c.action == "create" and c.kind == "channel"]
    ordinary = [c for c in channel_creates if not _wants_announcement(c)]
    announcements = [c for c in channel_creates if _wants_announcement(c)]

    created_channel_ids: Dict[str, str] = {}
    for change in ordinary:
        if not take(change):
            continue
        try:
            payload = _with_overwrite_ids(change.payload, created_role_ids, everyone_id)
            _attach_parent(payload, category_ids)
            created = client.create_channel(guild_id, payload)
            created_channel_ids[change.target] = created["id"]
            result.ok(change, created["id"])
            if verbose:
                print(f"  + channel {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # ── 6. nyalakan Community kalau config meminta ─────────────────────────
    if config.community and config.community.enabled:
        rules_id = created_channel_ids.get(config.community.rules_channel)
        updates_id = created_channel_ids.get(config.community.public_updates_channel)

        if rules_id and updates_id:
            try:
                # features TIDAK BISA dikirim sendirian — wajib bersama
                # rules_channel_id dan public_updates_channel_id. Lihat SKILL.md §4.3.
                client.update_guild(guild_id, {
                    "features": ["COMMUNITY", "NEWS"],
                    "rules_channel_id": rules_id,
                    "public_updates_channel_id": updates_id,
                })
                if verbose:
                    print("  = community DINYALAKAN, NEWS aktif")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"gagal menyalakan community — {exc}")
        else:
            missing = [k for k, v in ((config.community.rules_channel, rules_id),
                                      (config.community.public_updates_channel, updates_id))
                       if not v]
            result.errors.append(
                "community tidak bisa dinyalakan, channel berikut belum terbuat: "
                + ", ".join(missing)
            )

    for change in announcements:
        if not take(change):
            continue
        try:
            payload = _with_overwrite_ids(change.payload, created_role_ids, everyone_id)
            _attach_parent(payload, category_ids)
            created = client.create_channel(guild_id, payload)
            created_channel_ids[change.target] = created["id"]
            result.ok(change, f"{created['id']} announcement")
            if verbose:
                print(f"  + channel {change.target}  (announcement)")
        except Exception as exc:  # noqa: BLE001
            result.fail(
                change,
                Exception(f"{exc} — kemungkinan NEWS belum aktif, cek settings.community"),
            )

    # ── 8. update: rename, topic, slowmode, overwrite ──────────────────────
    for change in plan.changes:
        if change.action != "update" or not take(change):
            continue
        try:
            if change.kind == "role":
                client.update_role(guild_id, change.ref["id"], change.payload)
            elif change.kind in ("channel", "category"):
                client.update_channel(change.ref["id"], change.payload)
            elif change.kind == "guild":
                client.update_guild(guild_id, change.payload)
            result.ok(change)
            if verbose:
                print(f"  ~ {change.kind} {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # ── 9. hierarki role — satu PATCH untuk banyak role ────────────────────
    for change in plan.changes:
        if change.action != "set-positions" or not take(change):
            continue
        try:
            client.set_role_positions(guild_id, change.payload["placements"])
            result.ok(change, f"{len(change.payload['placements'])} role")
            if verbose:
                print(f"  → hierarki {change.target}")
        except Exception as exc:  # noqa: BLE001
            result.fail(change, exc)

    # ── 10. afk / system channel (perlu id yang baru terbuat) ──────────────
    _apply_channel_refs(config, client, guild_id, created_channel_ids, result, verbose)

    return result


# ── util ─────────────────────────────────────────────────────────────────────

def _locked_channel_ids(guild_state: Dict) -> set:
    """Channel yang tak bisa dihapus selama Community aktif (SKILL.md §4.1)."""
    ids = set()
    for field in ("rules_channel_id", "public_updates_channel_id"):
        value = guild_state.get(field)
        if value:
            ids.add(str(value))
    return ids


def _wants_announcement(change: Change) -> bool:
    payload = change.payload or {}
    return payload.get("type") == 5


def _with_overwrite_ids(payload: Dict, role_ids: Dict[str, str], everyone_id: str) -> Dict:
    """Payload dari plan memakai placeholder role_key; ganti jadi id sungguhan."""
    overwrites = payload.get("permission_overwrites")
    if not overwrites:
        return payload

    resolved = []
    for entry in overwrites:
        entry = dict(entry)
        role_key = entry.pop("role_key", None)
        if role_key is not None:
            entry["id"] = everyone_id if role_key == "everyone" else role_ids.get(role_key, everyone_id)
        resolved.append(entry)
    payload = dict(payload)
    payload["permission_overwrites"] = resolved
    return payload


def _attach_parent(payload: Dict, category_ids: Dict[str, str]) -> None:
    parent_name = payload.get("parent_name")
    if parent_name and parent_name in category_ids:
        payload["parent_id"] = category_ids[parent_name]
        payload.pop("parent_name", None)


def _apply_channel_refs(
    config: ServerConfig,
    client: DiscordClient,
    guild_id: str,
    created_channel_ids: Dict[str, str],
    result: ApplyResult,
    verbose: bool,
) -> None:
    """Setelah semua channel ada, barulah id AFK / system bisa dirujuk."""
    if not (config.afk_channel or config.system_channel):
        return

    live = {c["name"]: c["id"] for c in client.channels(guild_id)}
    payload: Dict[str, Any] = {}

    if config.afk_channel:
        afk_id = created_channel_ids.get(config.afk_channel) or live.get(
            _name_for_key(config, config.afk_channel)
        )
        if afk_id:
            payload["afk_channel_id"] = afk_id

    if config.system_channel:
        sys_id = created_channel_ids.get(config.system_channel) or live.get(
            _name_for_key(config, config.system_channel)
        )
        if sys_id:
            payload["system_channel_id"] = sys_id

    if not payload:
        return

    try:
        client.update_guild(guild_id, payload)
        result.ok(Change(action="update", kind="guild", target="afk/system channel"))
        if verbose:
            print("  ~ guild: AFK + system channel")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"gagal set afk/system channel — {exc}")


def _name_for_key(config: ServerConfig, key: str) -> str:
    channel = config.find_channel(key)
    return channel.name if channel else key
