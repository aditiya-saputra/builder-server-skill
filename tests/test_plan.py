"""Uji logika diff.

Fungsi build_plan murni — tidak menyentuh jaringan — sehingga bisa diuji
dengan data tiruan. Ini yang membuat adapter bisa dikembangkan tanpa token.
"""

from bss.config import load
from bss.plan import build_plan


CFG = """
version: 1
guild: "100000000000000001"

roles:
  - key: admin
    name: "👑 Admin"
    permissions: [ADMINISTRATOR]
    color: "#EF4444"
    hoist: true
    position: 100
  - key: member
    name: "✅ Member"
    position: 50

categories:
  - key: info
    name: "━━ 📢 INFO ━━"
    overwrites:
      everyone: { deny: [SEND_MESSAGES, SEND_TTS_MESSAGES, EMBED_LINKS, ATTACH_FILES] }
    channels:
      - key: rules
        name: "📜 rules"
        type: text
        topic: "Baca dulu."
        position: 1
      - key: pengumuman
        name: "📣 pengumuman"
        type: announcement
        position: 2
"""


def make_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(CFG, encoding="utf-8")
    return load(p)


def empty_state():
    return {
        "guild": {"id": "100000000000000001", "features": []},
        "channels": [],
        "roles": [{"id": "100000000000000001", "name": "@everyone",
                   "permissions": "0", "managed": False, "position": 0}],
    }


def run(config, state):
    return build_plan(
        config,
        guild_state=state["guild"],
        channel_states=state["channels"],
        role_states=state["roles"],
    )


# ── server kosong ───────────────────────────────────────────────────────────

def test_empty_server_creates_everything(tmp_path):
    plan = run(make_config(tmp_path), empty_state())
    actions = {(c.action, c.kind) for c in plan.changes}

    assert ("create", "role") in actions
    assert ("create", "category") in actions
    assert ("create", "channel") in actions
    assert plan.caution == []          # server kosong: tidak ada yang dihapus


def test_announcement_marked_as_needing_news(tmp_path):
    plan = run(make_config(tmp_path), empty_state())
    announcement = next(
        c for c in plan.changes
        if c.action == "create" and c.kind == "channel" and c.target == "📣 pengumuman"
    )
    assert announcement.payload["type"] == 5
    assert "NEWS" in announcement.note


# ── idempotensi ─────────────────────────────────────────────────────────────

def test_matching_server_yields_empty_plan(tmp_path):
    """Server yang sudah persis harus menghasilkan nol perubahan."""
    config = make_config(tmp_path)
    everyone = "100000000000000001"

    state = {
        "guild": {
            "id": everyone,
            "features": ["COMMUNITY", "NEWS"],
            "verification_level": 0,
            "default_message_notifications": 0,
        },
        "roles": [
            {"id": everyone, "name": "@everyone", "permissions": "0",
             "managed": False, "position": 0, "color": 0},
            {"id": "r1", "name": "👑 Admin", "permissions": "8",
             "managed": False, "position": 100, "color": 0xEF4444,
             "hoist": True, "mentionable": False},
            {"id": "r2", "name": "✅ Member", "permissions": "0",
             "managed": False, "position": 50, "color": 0,
             "hoist": False, "mentionable": False},
        ],
        "channels": [
            {"id": "c1", "name": "━━ 📢 INFO ━━", "type": 4,
             "permission_overwrites": [
                 {"id": everyone, "allow": "0", "deny": "55296"},
             ]},
            {"id": "c2", "name": "📜 rules", "type": 0, "parent_id": "c1",
             "topic": "Baca dulu.", "rate_limit_per_user": 0,
             "permission_overwrites": [
                 {"id": everyone, "allow": "0", "deny": "55296"},
             ]},
            {"id": "c3", "name": "📣 pengumuman", "type": 5, "parent_id": "c1",
             "topic": None, "rate_limit_per_user": 0,
             "permission_overwrites": [
                 {"id": everyone, "allow": "0", "deny": "55296"},
             ]},
        ],
    }

    plan = run(config, state)
    # hanya mungkin tersisa urutan; tidak boleh ada create/update/delete
    assert [c for c in plan.changes if c.action in ("create", "update", "delete")] == []


# ── deteksi selisih ─────────────────────────────────────────────────────────

def test_detects_role_color_change(tmp_path):
    config = make_config(tmp_path)
    state = empty_state()
    state["roles"].append({
        "id": "r1", "name": "👑 Admin", "permissions": "8",
        "managed": False, "position": 100, "color": 0x00FF00,
        "hoist": True, "mentionable": False,
    })

    plan = run(config, state)
    update = next(c for c in plan.changes
                  if c.action == "update" and c.kind == "role" and c.target == "👑 Admin")
    assert "colors" in update.payload
    assert update.risk == "safe"


def test_admin_grant_is_flagged_caution(tmp_path):
    """Memberi ADMINISTRATOR harus minta konfirmasi — jangan diam-diam."""
    config = make_config(tmp_path)
    state = empty_state()
    state["roles"].append({
        "id": "r1", "name": "👑 Admin", "permissions": "0",
        "managed": False, "position": 100, "color": 0xEF4444,
        "hoist": True, "mentionable": False,
    })

    plan = run(config, state)
    update = next(c for c in plan.changes
                  if c.action == "update" and c.kind == "role" and c.target == "👑 Admin")
    assert update.risk == "caution"
    assert "ADMINISTRATOR" in update.note


def test_extra_role_is_caution_not_silent(tmp_path):
    """Role lama yang tidak ada di config tidak boleh dihapus diam-diam."""
    config = make_config(tmp_path)
    state = empty_state()
    state["roles"].append({
        "id": "rX", "name": "Lama", "permissions": "0",
        "managed": False, "position": 1, "color": 0,
    })

    plan = run(config, state)
    delete = next(c for c in plan.changes
                  if c.action == "delete" and c.kind == "role")
    assert delete.target == "Lama"
    assert delete.risk == "caution"


def test_managed_bot_role_is_never_deleted(tmp_path):
    """SKILL.md §4.6 — role managed milik bot tidak boleh disentuh."""
    config = make_config(tmp_path)
    state = empty_state()
    state["roles"].append({
        "id": "rBot", "name": "Anjay", "permissions": "0",
        "managed": True, "position": 15, "color": 0,
    })

    plan = run(config, state)
    assert not any(c.action == "delete" and c.kind == "role" and c.target == "Anjay"
                   for c in plan.changes)


def test_hides_channel_needs_hiding_permission(tmp_path):
    """Kategori info memakai deny READ_ONLY = 55296."""
    config = make_config(tmp_path)
    plan = run(config, empty_state())

    cat = next(c for c in plan.changes
               if c.action == "create" and c.kind == "category")
    everyone_ow = next(o for o in cat.payload["permission_overwrites"]
                       if o["role_key"] == "everyone")
    assert everyone_ow["deny"] == "55296"


def test_child_inherits_category_overwrites(tmp_path):
    """Channel mewarisi overwrite kategorinya (SKILL.md soal pewarisan)."""
    config = make_config(tmp_path)
    plan = run(config, empty_state())

    ch = next(c for c in plan.changes
              if c.action == "create" and c.kind == "channel" and c.target == "📜 rules")
    everyone_ow = next(o for o in ch.payload["permission_overwrites"]
                       if o["role_key"] == "everyone")
    assert everyone_ow["deny"] == "55296"


def test_channel_overwrite_can_override_category(tmp_path):
    """deny VIEW di level channel menimpa allow kategori — pola command-staff."""
    cfg_text = """
version: 1
guild: "100000000000000001"
roles:
  - key: member
    name: "Member"
  - key: mod
    name: "Mod"
categories:
  - key: c
    name: "C"
    overwrites:
      everyone: { deny: [VIEW_CHANNEL] }
      member:   { allow: [VIEW_CHANNEL, SEND_MESSAGES] }
    channels:
      - key: staff
        name: "staff"
        type: text
        overwrites:
          member: { deny: [VIEW_CHANNEL] }
          mod:    { allow: [VIEW_CHANNEL, SEND_MESSAGES] }
"""
    p = _tmp(tmp_path, cfg_text)
    config = load(p)
    plan = run(config, empty_state())

    ch = next(c for c in plan.changes
              if c.action == "create" and c.kind == "channel" and c.target == "staff")
    by_key = {o["role_key"]: o for o in ch.payload["permission_overwrites"]}

    # member: deny menimpa allow kategori
    assert by_key["member"]["deny"] == "1024"
    # mod: allow penuh
    assert by_key["mod"]["allow"] != "0"


def _tmp(tmp_path, text):
    p = tmp_path / "x.yaml"
    p.write_text(text, encoding="utf-8")
    return p
