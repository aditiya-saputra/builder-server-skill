"""Uji muat dan validasi konfigurasi.

Tidak butuh token atau jaringan.
"""

import pytest

from bss.config import ConfigError, load


MINIMAL = """
version: 1
guild: "123456789012345678"
"""


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_minimal(tmp_path):
    cfg = load(write(tmp_path, MINIMAL))
    assert cfg.guild == "123456789012345678"
    assert cfg.roles == []
    assert cfg.categories == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        load(tmp_path / "nope.yaml")


def test_wrong_version_rejected(tmp_path):
    bad = MINIMAL.replace("version: 1", "version: 99")
    with pytest.raises(ConfigError, match="tidak valid"):
        load(write(tmp_path, bad))


def test_bad_guild_id_rejected(tmp_path):
    bad = MINIMAL.replace('"123456789012345678"', '"abc"')
    with pytest.raises(ConfigError, match="tidak valid"):
        load(write(tmp_path, bad))


def test_unknown_permission_rejected(tmp_path):
    cfg_text = MINIMAL + """
roles:
  - key: mod
    name: "Mod"
    permissions: [NOT_A_PERMISSION]
"""
    with pytest.raises(ConfigError, match="tidak dikenal"):
        load(write(tmp_path, cfg_text))


def test_duplicate_key_rejected(tmp_path):
    cfg_text = MINIMAL + """
roles:
  - key: dup
    name: "A"
  - key: dup
    name: "B"
"""
    with pytest.raises(ConfigError, match="duplikat"):
        load(write(tmp_path, cfg_text))


def test_dangling_overwrite_role_rejected(tmp_path):
    cfg_text = MINIMAL + """
categories:
  - key: info
    name: "INFO"
    channels:
      - key: rules
        name: "rules"
        type: text
        overwrites:
          ghost-role: { deny: [SEND_MESSAGES] }
"""
    with pytest.raises(ConfigError, match="menggantung"):
        load(write(tmp_path, cfg_text))


def test_dangling_community_ref_rejected(tmp_path):
    cfg_text = MINIMAL + """
settings:
  community:
    enabled: true
    rules_channel: missing-channel
    public_updates_channel: also-missing
"""
    with pytest.raises(ConfigError, match="menggantung"):
        load(write(tmp_path, cfg_text))


def test_color_hex_parsed(tmp_path):
    cfg_text = MINIMAL + """
roles:
  - key: admin
    name: "Admin"
    color: "#EF4444"
"""
    cfg = load(write(tmp_path, cfg_text))
    assert cfg.roles[0].color == 0xEF4444


def test_color_int_parsed(tmp_path):
    cfg_text = MINIMAL + """
roles:
  - key: admin
    name: "Admin"
    color: 15575278
"""
    cfg = load(write(tmp_path, cfg_text))
    assert cfg.roles[0].color == 15575278


def test_overwrites_resolved_to_ints(tmp_path):
    cfg_text = MINIMAL + """
roles:
  - key: member
    name: "Member"
categories:
  - key: chat
    name: "CHAT"
    overwrites:
      everyone: { deny: [VIEW_CHANNEL] }
      member:   { allow: [VIEW_CHANNEL, SEND_MESSAGES] }
    channels:
      - key: general
        name: "general"
        type: text
"""
    cfg = load(write(tmp_path, cfg_text))
    ow = cfg.categories[0].overwrites
    assert ow["everyone"]["deny"] == 1024
    assert ow["member"]["allow"] == 3072


def test_announcement_flag(tmp_path):
    cfg_text = MINIMAL + """
categories:
  - key: info
    name: "INFO"
    channels:
      - key: pengumuman
        name: "pengumuman"
        type: announcement
"""
    cfg = load(write(tmp_path, cfg_text))
    assert cfg.uses_announcement is True
    assert cfg.find_channel("pengumuman").is_announcement is True


def test_community_aware_detection(tmp_path):
    with_community = MINIMAL + """
settings:
  community:
    enabled: true
    rules_channel: rules
    public_updates_channel: rules
categories:
  - key: info
    name: "INFO"
    channels:
      - key: rules
        name: "rules"
        type: text
"""
    cfg = load(write(tmp_path, with_community))
    assert cfg.community.enabled is True
    # boleh menunjuk channel yang sama
    assert cfg.community.rules_channel == cfg.community.public_updates_channel


def test_template_files_all_load():
    """Pastikan ketiga template yang dikirim ikut repo valid."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "templates"
    for name in ("community.yaml", "developer.yaml", "gaming.yaml"):
        cfg = load(root / name)
        assert cfg.guild
        assert cfg.categories, f"{name} seharusnya punya kategori"
        assert cfg.roles, f"{name} seharusnya punya role"
