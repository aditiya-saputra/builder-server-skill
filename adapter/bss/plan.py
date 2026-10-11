"""Hitung selisih antara rancangan (config) dan keadaan nyata (Discord).

Ini otak dari seluruh adapter. Tidak menyentuh jaringan — murni logika diff,
sehingga bisa diuji tanpa token (lihat tests/test_plan.py).

Prinsip pencocokan:
  * role    -> cocokkan berdasar NAMA
  * channel -> cocokkan berdasar NAMA di dalam kategorinya
  * kategori-> cocokkan berdasar NAMA

Key dari config tidak pernah dikirim ke Discord, jadi tidak bisa dipakai
sebagai pengenal. Nama satu-satunya jangkar yang tersedia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import bits
from .config import CategorySpec, ChannelSpec, RoleSpec, ServerConfig


@dataclass
class Change:
    """Satu perubahan yang akan dieksekusi.

    `risk` menentukan apakah `repair` boleh menyentuhnya:
      * "safe"    -> konvergen dan terbalik, tidak menghapus akses siapapun
      * "caution" -> bisa menghapus akses atau data — minta izin pengguna
    """

    action: str          # create | update | delete | reorder | set-positions
    kind: str            # role | category | channel | guild | hierarchy
    target: str          # nama yang ditampilkan ke manusia
    payload: Dict = field(default_factory=dict)
    risk: str = "safe"
    note: str = ""
    ref: Any = None      # objek config atau state terkait, untuk apply

    @property
    def is_destructive(self) -> bool:
        return self.action == "delete" or self.risk != "safe"

    def describe(self) -> str:
        arrow = {"create": "+", "update": "~", "delete": "-", "reorder": "→", "set-positions": "→"}
        marker = arrow.get(self.action, "?")
        risk = "" if self.risk == "safe" else f"  [{self.risk}]"
        note = f"\n      {self.note}" if self.note else ""
        return f"  {marker} {self.kind:<9} {self.target}{risk}{note}"


@dataclass
class Plan:
    changes: List[Change] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add(self, change: Change) -> None:
        self.changes.append(change)

    @property
    def safe(self) -> List[Change]:
        return [c for c in self.changes if c.risk == "safe"]

    @property
    def caution(self) -> List[Change]:
        return [c for c in self.changes if c.risk != "safe"]

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def summary(self) -> str:
        if self.is_empty:
            return "Tidak ada perubahan — server sudah sesuai rancangan."
        counts: Dict[str, int] = {}
        for change in self.changes:
            counts[change.action] = counts.get(change.action, 0) + 1
        parts = ", ".join(f"{n} {action}" for action, n in counts.items())
        return f"{len(self.changes)} perubahan ({parts})"


# ── util ─────────────────────────────────────────────────────────────────────

def _norm_name(name: str) -> str:
    """Discord memaksa channel jadi lowercase. Samakan sebelum dibandingkan,
    kalau tidak semua channel akan terlihat 'berbeda' terus."""
    return name.strip().lower()


def _is_managed(role_state: Dict) -> bool:
    """Role managed (milik bot) tidak boleh disentuh — lihat SKILL.md §4.6."""
    return bool(role_state.get("managed"))


# ── pembangun plan ───────────────────────────────────────────────────────────

def build_plan(
    config: ServerConfig,
    *,
    guild_state: Dict,
    channel_states: List[Dict],
    role_states: List[Dict],
) -> Plan:
    """Bandingkan config dengan state nyata, keluarkan daftar perubahan.

    Parameter state sengaja berupa data mentah (bukan client) supaya fungsi ini
    bisa diuji offline.
    """
    plan = Plan()
    guild_id = str(guild_state["id"])

    role_id_by_key = {r["name"]: r["id"] for r in role_states}
    everyone_id = guild_id

    # ── role ────────────────────────────────────────────────────────────────
    desired_role_names = set()
    for spec in config.roles:
        desired_role_names.add(spec.name)
        existing = next((r for r in role_states if r["name"] == spec.name), None)

        if existing is None:
            plan.add(Change(
                action="create", kind="role", target=spec.name,
                payload={
                    "name": spec.name,
                    "permissions": str(spec.permissions),
                    "colors": {"primary_color": spec.color,
                               "secondary_color": None, "tertiary_color": None},
                    "hoist": spec.hoist,
                    "mentionable": spec.mentionable,
                },
                ref=spec,
            ))
            continue

        if _is_managed(existing):
            plan.warnings.append(
                f"role {spec.name!r} di config tapi di server role itu managed "
                f"oleh bot — dilewati, tidak akan diubah."
            )
            continue

        diff: Dict[str, Any] = {}
        if existing.get("permissions", "0") != str(spec.permissions):
            diff["permissions"] = str(spec.permissions)
        if int(existing.get("color", 0)) != spec.color:
            diff["colors"] = {"primary_color": spec.color,
                              "secondary_color": None, "tertiary_color": None}
        if bool(existing.get("hoist")) != spec.hoist:
            diff["hoist"] = spec.hoist
        if bool(existing.get("mentionable")) != spec.mentionable:
            diff["mentionable"] = spec.mentionable

        if diff:
            changed = ", ".join(sorted(diff))
            risk = "safe"
            note = ""
            if "permissions" in diff and spec.permissions & bits.ADMINISTRATOR:
                risk = "caution"
                note = "memberikan ADMINISTRATOR — konfirmasi diperlukan"
            plan.add(Change(
                action="update", kind="role", target=spec.name,
                payload=diff, risk=risk, note=note, ref=existing,
            ))

    # Role lama yang tidak ada di config -> jangan dihapus diam-diam.
    for state in role_states:
        if state["name"] == "@everyone" or _is_managed(state):
            continue
        if state["name"] not in desired_role_names:
            plan.add(Change(
                action="delete", kind="role", target=state["name"],
                risk="caution",
                note="menghapus role — akses member ini hilang. Konfirmasi diperlukan.",
                ref=state,
            ))

    # ── hierarki role ───────────────────────────────────────────────────────
    placements = []
    for spec in config.roles:
        role_id = role_id_by_key.get(spec.name)
        if role_id and spec.position:
            placements.append({"id": role_id, "position": spec.position})
    if placements:
        plan.add(Change(
            action="set-positions", kind="hierarchy",
            target=f"{len(placements)} role",
            payload={"placements": placements},
            ref=placements,
        ))

    # ── kategori + channel ──────────────────────────────────────────────────
    category_states = [c for c in channel_states if c.get("type") == 4]
    child_states = [c for c in channel_states if c.get("type") != 4]

    desired_category_names = set()
    desired_channel_names = set()

    for cat_index, cat_spec in enumerate(config.categories):
        desired_category_names.add(cat_spec.name)
        cat_state = next((c for c in category_states if c["name"] == cat_spec.name), None)

        if cat_state is None:
            plan.add(Change(
                action="create", kind="category", target=cat_spec.name,
                payload={"name": cat_spec.name, "type": 4,
                         "permission_overwrites": _ow(cat_spec.overwrites, role_id_by_key, everyone_id)},
                ref=cat_spec,
            ))
        else:
            diff = _ow_diff(cat_spec.overwrites, cat_state, role_id_by_key, everyone_id)
            if diff:
                plan.add(Change(
                    action="update", kind="category", target=cat_spec.name,
                    payload={"permission_overwrites": diff},
                    ref=cat_state,
                ))

        for ch_index, ch_spec in enumerate(cat_spec.channels):
            desired_channel_names.add(ch_spec.name)
            ch_state = next(
                (c for c in child_states
                 if c["name"] == ch_spec.name and c.get("parent_id") == (cat_state or {}).get("id")),
                None,
            )
            # fallback: cocokkan global kalau parent belum ada / nama unik
            if ch_state is None and not any(
                c["name"] == ch_spec.name for c in child_states
            ):
                ch_state = None
            elif ch_state is None:
                dupes = [c for c in child_states if c["name"] == ch_spec.name]
                if len(dupes) == 1 and cat_state is None:
                    ch_state = dupes[0]

            if ch_state is None:
                needs_news = ch_spec.is_announcement
                plan.add(Change(
                    action="create", kind="channel", target=ch_spec.name,
                    payload=_channel_payload(ch_spec, cat_spec, role_id_by_key, everyone_id, cat_state),
                    note="butuh feature NEWS — dibuat setelah Community aktif" if needs_news else "",
                    ref=(ch_spec, cat_spec),
                ))
            else:
                _plan_channel_update(plan, ch_spec, ch_state, role_id_by_key, everyone_id)

    for state in category_states:
        if state["name"] not in desired_category_names:
            children = [c for c in child_states if c.get("parent_id") == state["id"]]
            note = "menghapus kategori"
            if children:
                note += f" (berisi {len(children)} channel yang juga akan dihapus)"
            plan.add(Change(action="delete", kind="category", target=state["name"],
                            risk="caution", note=note, ref=state))

    for state in child_states:
        if state["name"] not in desired_channel_names:
            plan.add(Change(action="delete", kind="channel", target=state["name"],
                            risk="caution", note="menghapus channel", ref=state))

    # ── pengaturan guild ────────────────────────────────────────────────────
    _plan_guild_settings(plan, config, guild_state, role_id_by_key, everyone_id)

    return plan


def _ow(spec: Dict[str, Dict[str, int]], role_ids: Dict[str, str], everyone_id: str) -> List[Dict]:
    """Bangun entri permission overwrite.

    Setiap entri membawa `role_key` SEKALIGUS `id` (kalau sudah dikenal).
    `role_key` inilah yang membuat apply bisa meng-id-kan ulang — plan dibuat
    SEBELUM role baru terbuat, jadi id-nya belum tentu tersedia saat itu.
    """
    out = []
    for role_key, values in spec.items():
        role_id = everyone_id if role_key == "everyone" else role_ids.get(role_key)
        entry = {"role_key": role_key, "type": "role",
                 "allow": str(values["allow"]), "deny": str(values["deny"])}
        if role_id:
            entry["id"] = role_id
        out.append(entry)
    return out


def _ow_diff(spec, state, role_ids, everyone_id) -> Optional[List[Dict]]:
    """Kembalikan overwrite baru kalau berbeda, None kalau sudah cocok.

    Hanya role yang kita deklarasikan yang dibandingkan. Overwrite milik role
    managed (bot) diabaikan — kalau tidak, setiap channel yang punya overwrite
    bot akan selamanya dianggap berbeda.
    """
    desired = _ow(spec, role_ids, everyone_id)
    existing = {o["id"]: o for o in state.get("permission_overwrites", [])}

    for entry in desired:
        current = existing.get(entry.get("id"))
        if current is None:
            return desired
        if (str(current.get("allow", "0")) != entry["allow"]
                or str(current.get("deny", "0")) != entry["deny"]):
            return desired
    return None


def _channel_payload(ch_spec, cat_spec, role_ids, everyone_id, cat_state) -> Dict:
    payload: Dict[str, Any] = {
        "name": ch_spec.name,
        "type": ch_spec.discord_type,
    }
    if cat_state is not None:
        payload["parent_id"] = cat_state["id"]
    if ch_spec.topic:
        payload["topic"] = ch_spec.topic
    if ch_spec.slowmode is not None:
        payload["rate_limit_per_user"] = ch_spec.slowmode

    merged = dict(cat_spec.overwrites)
    merged.update(ch_spec.overwrites)
    overwrites = _ow(merged, role_ids, everyone_id)
    if overwrites:
        payload["permission_overwrites"] = overwrites
    return payload


def _plan_channel_update(plan: Plan, ch_spec: ChannelSpec, ch_state: Dict, role_ids, everyone_id) -> None:
    diff: Dict[str, Any] = {}

    if ch_spec.topic is not None and ch_state.get("topic") != ch_spec.topic:
        diff["topic"] = ch_spec.topic
    if ch_spec.slowmode is not None and int(ch_state.get("rate_limit_per_user", 0)) != ch_spec.slowmode:
        diff["rate_limit_per_user"] = ch_spec.slowmode

    desired_cat = ch_spec.overwrites
    if desired_cat:
        current = {o["id"]: o for o in ch_state.get("permission_overwrites", [])}
        for role_key, values in desired_cat.items():
            role_id = everyone_id if role_key == "everyone" else role_ids.get(role_key)
            if not role_id:
                continue
            now = current.get(role_id)
            if (now is None
                    or str(now.get("allow", "0")) != str(values["allow"])
                    or str(now.get("deny", "0")) != str(values["deny"])):
                diff["permission_overwrites"] = _ow(desired_cat, role_ids, everyone_id)
                break

    if diff:
        plan.add(Change(action="update", kind="channel", target=ch_spec.name,
                        payload=diff, ref=ch_state))


def _plan_guild_settings(plan: Plan, config: ServerConfig, guild_state: Dict, role_ids, everyone_id) -> None:
    diff: Dict[str, Any] = {}

    if config.verification_level is not None:
        current = int(guild_state.get("verification_level", 0))
        if current != config.verification_level:
            diff["verification_level"] = config.verification_level

    if config.default_message_notifications is not None:
        if int(guild_state.get("default_message_notifications", 0)) != config.default_message_notifications:
            diff["default_message_notifications"] = config.default_message_notifications

    if not diff:
        return

    risk = "safe"
    if "verification_level" in diff:
        current_vl = int(guild_state.get("verification_level", 0))
        if diff["verification_level"] < current_vl:
            risk = "caution"

    plan.add(Change(
        action="update", kind="guild", target="pengaturan server",
        payload=diff, risk=risk,
        note="menurunkan verification_level" if risk != "safe" else "",
    ))
