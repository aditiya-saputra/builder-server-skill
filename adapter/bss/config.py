"""Muat dan validasi berkas konfigurasi server.

Konfigurasi adalah sumber kebenaran yang kita inginkan. Adapter tidak pernah
menebak — ia membaca config ini, membaca state nyata dari Discord, lalu
menghitung selisihnya (lihat plan.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
import yaml

from . import bits
from .client import CHANNEL_TYPES

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "server-config.schema.json"


class ConfigError(ValueError):
    """Konfigurasi tidak valid — pesan berisi lokasi dan perbaikannya."""


@dataclass
class ChannelSpec:
    key: str
    name: str
    type: str
    topic: Optional[str] = None
    slowmode: Optional[int] = None
    position: Optional[int] = None
    overwrites: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def discord_type(self) -> int:
        return CHANNEL_TYPES[self.type]

    @property
    def is_announcement(self) -> bool:
        """Butuh feature NEWS — hanya bisa dibuat setelah Community aktif."""
        return self.type == "announcement"

    @property
    def is_forum(self) -> bool:
        return self.type == "forum"


@dataclass
class CategorySpec:
    key: str
    name: str
    position: Optional[int] = None
    overwrites: Dict[str, Dict[str, int]] = field(default_factory=dict)
    channels: List[ChannelSpec] = field(default_factory=list)


@dataclass
class RoleSpec:
    key: str
    name: str
    permissions: int = 0
    color: int = 0
    hoist: bool = False
    mentionable: bool = False
    position: int = 0


@dataclass
class CommunitySpec:
    enabled: bool
    rules_channel: str
    public_updates_channel: str


@dataclass
class ServerConfig:
    version: int
    guild: str
    roles: List[RoleSpec]
    categories: List[CategorySpec]
    verification_level: Optional[int] = None
    default_message_notifications: Optional[int] = None
    afk_channel: Optional[str] = None
    system_channel: Optional[str] = None
    community: Optional[CommunitySpec] = None

    def role_by_key(self, key: str) -> Optional[RoleSpec]:
        return next((r for r in self.roles if r.key == key), None)

    def role_by_name(self, name: str) -> Optional[RoleSpec]:
        return next((r for r in self.roles if r.name == name), None)

    def find_channel(self, key: str) -> Optional[ChannelSpec]:
        """Cari channel di seluruh kategori lewat key-nya."""
        for category in self.categories:
            for channel in category.channels:
                if channel.key == key:
                    return channel
        return None

    def category_of(self, channel_key: str) -> Optional[CategorySpec]:
        for category in self.categories:
            if any(c.key == channel_key for c in category.channels):
                return category
        return None

    def all_channels(self) -> List[ChannelSpec]:
        return [c for category in self.categories for c in category.channels]

    @property
    def uses_announcement(self) -> bool:
        return any(c.is_announcement for c in self.all_channels())

    @property
    def uses_forum(self) -> bool:
        return any(c.is_forum for c in self.all_channels())


def _parse_color(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(str(value).lstrip("#"), 16)


def _parse_overwrites(raw: Optional[Dict]) -> Dict[str, Dict[str, int]]:
    """Ubah {role_key: {allow: [...], deny: [...]}} jadi {key: {allow, deny}}.

    Nilai permission diselesaikan ke integer di sini, sekali saja.
    """
    if not raw:
        return {}
    parsed: Dict[str, Dict[str, int]] = {}
    for role_key, spec in raw.items():
        try:
            parsed[role_key] = {
                "allow": bits.resolve(spec.get("allow")),
                "deny": bits.resolve(spec.get("deny")),
            }
        except ValueError as exc:
            raise ConfigError(
                f"izin tidak valid pada overwrite role {role_key!r}: {exc}"
            ) from exc
    return parsed


def load(path: str | Path) -> ServerConfig:
    """Muat config YAML lalu validasi terhadap schema."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"berkas config tidak ditemukan: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML tidak valid di {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"isi {path} harus berupa mapping, bukan {type(raw).__name__}")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        lines = [f"config tidak valid di {path}:"]
        for err in errors:
            where = ".".join(str(p) for p in err.absolute_path) or "(root)"
            lines.append(f"  - {where}: {err.message}")
        raise ConfigError("\n".join(lines))

    return _build(raw)


def _build(raw: Dict) -> ServerConfig:
    settings = raw.get("settings") or {}
    community_raw = settings.get("community")

    community = None
    if community_raw:
        community = CommunitySpec(
            enabled=bool(community_raw["enabled"]),
            rules_channel=community_raw["rules_channel"],
            public_updates_channel=community_raw["public_updates_channel"],
        )

    roles = []
    for item in raw.get("roles") or []:
        try:
            permissions = bits.resolve(item.get("permissions"))
        except ValueError as exc:
            raise ConfigError(
                f"izin tidak valid pada role {item.get('key')!r}: {exc}"
            ) from exc
        roles.append(RoleSpec(
            key=item["key"],
            name=item["name"],
            permissions=permissions,
            color=_parse_color(item.get("color")),
            hoist=bool(item.get("hoist", False)),
            mentionable=bool(item.get("mentionable", False)),
            position=int(item.get("position", 0)),
        ))

    categories = []
    for cat in raw.get("categories") or []:
        channels = []
        for ch in cat.get("channels") or []:
            channels.append(ChannelSpec(
                key=ch["key"],
                name=ch["name"],
                type=ch["type"],
                topic=ch.get("topic"),
                slowmode=ch.get("slowmode"),
                position=ch.get("position"),
                overwrites=_parse_overwrites(ch.get("overwrites")),
            ))
        categories.append(CategorySpec(
            key=cat["key"],
            name=cat["name"],
            position=cat.get("position"),
            overwrites=_parse_overwrites(cat.get("overwrites")),
            channels=channels,
        ))

    config = ServerConfig(
        version=raw["version"],
        guild=str(raw["guild"]),
        roles=roles,
        categories=categories,
        verification_level=settings.get("verification_level"),
        default_message_notifications=settings.get("default_message_notifications"),
        afk_channel=settings.get("afk_channel"),
        system_channel=settings.get("system_channel"),
        community=community,
    )

    _check_duplicate_keys(config)
    _check_dangling_refs(config)
    return config


def _check_duplicate_keys(config: ServerConfig) -> None:
    seen = set()
    for item in [*config.roles, *config.categories, *config.all_channels()]:
        if item.key in seen:
            raise ConfigError(
                f"key duplikat: {item.key!r}. Key harus unik di seluruh config "
                f"supaya bisa dirujuk tanpa ambigu."
            )
        seen.add(item.key)


def _check_dangling_refs(config: ServerConfig) -> None:
    """Pastikan semua key yang dirujuk benar-benar ada."""
    role_keys = {r.key for r in config.roles}
    channel_keys = {c.key for c in config.all_channels()}

    problems = []

    if config.community:
        for label, key in (
            ("settings.community.rules_channel", config.community.rules_channel),
            ("settings.community.public_updates_channel", config.community.public_updates_channel),
        ):
            if key not in channel_keys:
                problems.append(f"{label} merujuk {key!r} yang tidak ada di categories")

    for label, key in (("settings.afk_channel", config.afk_channel),
                       ("settings.system_channel", config.system_channel)):
        if key and key not in channel_keys:
            problems.append(f"{label} merujuk {key!r} yang tidak ada di categories")

    for category in config.categories:
        for role_key in category.overwrites:
            if role_key != "everyone" and role_key not in role_keys:
                problems.append(
                    f"kategori {category.key!r} memakai overwrite role {role_key!r} "
                    f"yang tidak didefinisikan di roles"
                )
        for channel in category.channels:
            for role_key in channel.overwrites:
                if role_key != "everyone" and role_key not in role_keys:
                    problems.append(
                        f"channel {channel.key!r} memakai overwrite role {role_key!r} "
                        f"yang tidak didefinisikan di roles"
                    )

    if problems:
        raise ConfigError("referensi menggantung:\n  - " + "\n  - ".join(problems))


def community_aware(config: ServerConfig) -> bool:
    """True kalau config butuh urutan build khusus Community.

    Lihat SKILL.md §4.2 — announcement butuh NEWS, NEWS butuh Community aktif,
    dan Community butuh channel yang sudah ada. Ini tidak bisa dibalik.
    """
    return bool(config.community and config.community.enabled) or config.uses_announcement
