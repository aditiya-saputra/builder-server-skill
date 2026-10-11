"""Bandingkan keadaan nyata di Discord dengan rancangan di config.

Kenapa perlu modul terpisah dari plan.py:
    Discord kadang membalas 200 tetapi MENYIMPAN NILAI BERBEDA dari yang
    kita kirim. Yang paling terbukti adalah PATCH rules_channel_id saat
    Community aktif — API bilang sukses, nilai lama tetap dipertahankan.

    Karena itu verify tidak pernah mempercayai isi response write. Ia selalu
    GET ulang, lalu membandingkan dari nol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import bits
from .config import ServerConfig


@dataclass
class Mismatch:
    """Satu perbedaan antara keadaan nyata dan rancangan."""

    kind: str          # role | category | channel | guild | hierarchy
    target: str
    field: str
    wanted: Any
    actual: Any

    def __str__(self) -> str:
        return f"  {self.kind:<9} {self.target}  .{self.field}\n      rancangan: {self.wanted}\n      nyata    : {self.actual}"


@dataclass
class Report:
    mismatches: List[Mismatch] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.missing

    def render(self) -> str:
        if self.ok and not self.extra:
            lines = ["✓ VERIFIED — server sesuai rancangan."]
        else:
            lines = ["✗ VERIFY gagal — server berbeda dari rancangan."]

        if self.missing:
            lines.append("\nHilang (ada di rancangan, tidak ada di server):")
            lines.extend(f"  - {m}" for m in self.missing)

        if self.mismatches:
            lines.append("\nBerbeda:")
            lines.extend(str(m) for m in self.mismatches)

        if self.extra:
            lines.append("\nExtra (ada di server, tidak ada di rancangan — tidak dihapus otomatis):")
            lines.extend(f"  - {m}" for m in self.extra)

        if self.notes:
            lines.append("\nCatatan:")
            lines.extend(f"  - {n}" for n in self.notes)

        return "\n".join(lines)


def verify(config: ServerConfig, *, guild_state: Dict, channel_states: List[Dict],
           role_states: List[Dict]) -> Report:
    """Ulangi perbandingan dari plan, tapi sebagai pemeriksaan kepatuhan.

    Berbeda dari build_plan: fungsi ini TIDAK menyarankan perbaikan. Ia hanya
    melaporkan apakah server sudah persis seperti yang diminta.
    """
    report = Report()
    guild_id = str(guild_state["id"])

    # ── role ────────────────────────────────────────────────────────────────
    for spec in config.roles:
        state = next((r for r in role_states if r["name"] == spec.name), None)
        if state is None:
            report.missing.append(f"role {spec.name}")
            continue

        if state.get("managed"):
            report.notes.append(f"role {spec.name} managed oleh bot — tidak diurusi")
            continue

        _check(report, "role", spec.name, "permissions",
               str(spec.permissions), str(state.get("permissions", "0")),
               formatter=lambda v: " | ".join(bits.names_of(int(v))) or "NONE")

        if int(state.get("color", 0)) != spec.color:
            report.mismatches.append(Mismatch(
                "role", spec.name, "color",
                f"#{spec.color:06X}", f"#{int(state.get('color', 0)):06X}"))

        _check(report, "role", spec.name, "hoist", spec.hoist, bool(state.get("hoist")))
        _check(report, "role", spec.name, "mentionable", spec.mentionable,
               bool(state.get("mentionable")))

    # ── hierarki ────────────────────────────────────────────────────────────
    by_name = {r["name"]: r for r in role_states}
    for spec in config.roles:
        if not spec.position:
            continue
        state = by_name.get(spec.name)
        if state is None or state.get("managed"):
            continue
        actual_pos = int(state.get("position", 0))
        if actual_pos != spec.position:
            report.mismatches.append(Mismatch(
                "hierarchy", spec.name, "position", spec.position, actual_pos))

    # ── kategori + channel ──────────────────────────────────────────────────
    categories = [c for c in channel_states if c.get("type") == 4]
    children = [c for c in channel_states if c.get("type") != 4]

    for cat_spec in config.categories:
        cat_state = next((c for c in categories if c["name"] == cat_spec.name), None)
        if cat_state is None:
            report.missing.append(f"kategori {cat_spec.name}")
            continue

        _check_overwrites(report, "category", cat_spec.name, cat_spec.overwrites, cat_state)

        for ch_spec in cat_spec.channels:
            ch_state = next(
                (c for c in children
                 if c["name"] == ch_spec.name and c.get("parent_id") == cat_state["id"]),
                None,
            )
            if ch_state is None:
                report.missing.append(f"channel {ch_spec.name} (di {cat_spec.name})")
                continue

            if ch_spec.topic is not None:
                _check(report, "channel", ch_spec.name, "topic",
                       ch_spec.topic, ch_state.get("topic"))

            if ch_spec.slowmode is not None:
                _check(report, "channel", ch_spec.name, "slowmode",
                       ch_spec.slowmode, int(ch_state.get("rate_limit_per_user", 0)))

            _check_overwrites(report, "channel", ch_spec.name,
                              ch_spec.overwrites, ch_state)

    # ── pengaturan guild ────────────────────────────────────────────────────
    if config.verification_level is not None:
        _check(report, "guild", "server", "verification_level",
               config.verification_level, int(guild_state.get("verification_level", 0)))

    if config.default_message_notifications is not None:
        _check(report, "guild", "server", "default_message_notifications",
               config.default_message_notifications,
               int(guild_state.get("default_message_notifications", 0)))

    # ── community ───────────────────────────────────────────────────────────
    if config.community and config.community.enabled:
        _check_community(report, config, guild_state, channel_states)

    # ── benda yang tidak ada di rancangan ───────────────────────────────────
    _collect_extras(report, config, categories, children, role_states, guild_id)

    return report


# ── util ─────────────────────────────────────────────────────────────────────

def _check(report: Report, kind: str, target: str, field: str,
           wanted: Any, actual: Any, formatter=None) -> None:
    if wanted == actual:
        return
    if formatter:
        wanted = formatter(wanted)
        actual = formatter(actual)
    report.mismatches.append(Mismatch(kind, target, field, wanted, actual))


def _check_overwrites(report: Report, kind: str, target: str,
                      desired: Dict[str, Dict[str, int]], state: Dict) -> None:
    """Bandingkan overwrite yang kita deklarasikan saja.

    Overwrite milik role managed (bot) tidak kita urus, jadi diabaikan.
    """
    live = {o["id"]: o for o in state.get("permission_overwrites", [])}
    role_ids = _role_id_map(state, desired)

    for role_key, values in desired.items():
        role_id = role_ids.get(role_key)
        if role_id is None:
            continue
        now = live.get(role_id)
        if now is None:
            report.mismatches.append(Mismatch(
                kind, target, f"overwrites[{role_key}]", "ada", "hilang"))
            continue

        for side in ("allow", "deny"):
            want = str(values[side])
            got = str(now.get(side, "0"))
            if want != got:
                report.mismatches.append(Mismatch(
                    kind, target, f"overwrites[{role_key}].{side}",
                    f"{want} ({_names(want)})",
                    f"{got} ({_names(got)})"))


def _role_id_map(state: Dict, desired: Dict) -> Dict[str, str]:
    """Dapatkan id per role_key. `everyone` selalu ada."""
    mapping = {"everyone": str(state["guild_id"]) if "guild_id" in state else ""}
    # parent_id tidak memuat guild id; ambil dari overwrite yang ada saja.
    for o in state.get("permission_overwrites", []):
        mapping.setdefault(f"id:{o['id']}", o["id"])
    return _resolve_everyone(mapping, state)


def _resolve_everyone(mapping: Dict[str, str], state: Dict) -> Dict[str, str]:
    """Pecahkan `everyone` memakai overwrite yang sudah ada di channel itu."""
    # @everyone selalu punya overwrite sendiri di channel yang punya custom perms.
    for o in state.get("permission_overwrites", []):
        # id @everyone sama dengan guild id; tidak tersedia di sini,
        # jadi andalkan fakta bahwa Discord selalu menyimpannya bila ada deny/allow.
        mapping.setdefault("everyone", o["id"])
        break
    return mapping


def _names(value: str) -> str:
    try:
        return " | ".join(bits.names_of(int(value))) or "NONE"
    except (TypeError, ValueError):
        return "?"


def _check_community(report: Report, config: ServerConfig,
                     guild_state: Dict, channel_states: List[Dict]) -> None:
    """Community adalah pemeriksaan paling penting (SKILL.md §4.1).

    API bisa membalas 200 saat menolak perubahan rules/public_updates.
    Satu-satunya cara tahu adalah membaca ulang nilai yang benar-benar tersimpan.
    """
    features = guild_state.get("features") or []
    if "COMMUNITY" not in features:
        report.mismatches.append(Mismatch(
            "guild", "community", "enabled", True, f"tidak aktif (features={features})"))
        return

    for label, field in (("rules_channel", "rules_channel_id"),
                         ("public_updates_channel", "public_updates_channel_id")):
        key = getattr(config.community, label)
        channel = config.find_channel(key)
        if channel is None:
            continue

        wanted_id = _id_of_channel(channel_states, channel.name)
        actual_id = guild_state.get(field)

        if wanted_id is None:
            report.notes.append(f"tidak bisa memverifikasi {field}: channel {channel.name} tidak ditemukan")
            continue

        if str(actual_id) != wanted_id:
            report.mismatches.append(Mismatch(
                "guild", label, field,
                f"{channel.name} ({wanted_id})",
                f"{actual_id} — kemungkinan ditolak diam-diam saat Community aktif"))


def _id_of_channel(states: List[Dict], name: str) -> Optional[str]:
    for c in states:
        if c["name"] == name and c.get("type") != 4:
            return str(c["id"])
    return None


def _collect_extras(report: Report, config: ServerConfig, categories, children,
                    role_states, guild_id: str) -> None:
    """Kumpulkan benda di server yang tidak ada di rancangan.

    TIDAK dihapus otomatis — hanya dilaporkan, karena bisa jadi buatan manusia
    atau bot lain yang tidak boleh kita sentuh.
    """
    desired_cat = {c.name for c in config.categories}
    desired_ch = {c.name for c in config.all_channels()}
    desired_role = {r.name for r in config.roles}

    for state in categories:
        if state["name"] not in desired_cat:
            report.extra.append(f"kategori {state['name']}")

    for state in children:
        if state["name"] not in desired_ch:
            report.extra.append(f"channel {state['name']}")

    for state in role_states:
        if state["name"] == "@everyone" or state.get("managed"):
            continue
        if state["name"] not in desired_role:
            report.extra.append(f"role {state['name']}")
