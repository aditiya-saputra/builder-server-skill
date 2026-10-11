"""CLI untuk adapter builder-server-skill.

    python -m bss plan     -c config.yaml -g GUILD_ID
    python -m bss dry-run  -c config.yaml -g GUILD_ID
    python -m bss apply    -c config.yaml -g GUILD_ID
    python -m bss verify   -c config.yaml -g GUILD_ID
    python -m bss repair   -c config.yaml -g GUILD_ID

Aturan yang dipaksa di sini (lihat SKILL.md §1 dan §5):
    * apply membutuhkan --yes kalau plan berisi perubahan berisiko
    * dry-run tidak pernah menyentuh server
    * repair hanya mengeksekusi perubahan ber-risks safe
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .apply import apply
from .client import DiscordClient, DiscordError
from .config import ConfigError, load
from .plan import Plan, build_plan
from .verify import verify


def fetch_state(client: DiscordClient, guild_id: str):
    """Ambil semua state yang dibutuhkan untuk plan maupun verify."""
    return {
        "guild": client.guild(guild_id),
        "channels": client.channels(guild_id),
        "roles": client.roles(guild_id),
    }


def render_plan(plan: Plan, *, show_requests: bool = False) -> str:
    lines = [f"Rencana: {plan.summary()}"]

    if plan.is_empty:
        return lines[0]

    lines.append("")
    for change in plan.changes:
        lines.append(change.describe())

    if plan.warnings:
        lines.append("\nPeringatan:")
        lines.extend(f"  ! {w}" for w in plan.warnings)

    if show_requests:
        lines.append("\nRequest HTTP yang akan dikirim:")
        for change in plan.changes:
            lines.append(f"  {change.action:<14} {change.kind:<9} {change.target}")
            if change.payload:
                lines.append(f"      payload: {change.payload}")

    if plan.caution:
        lines.append("\n⚠  Perubahan berisiko terdeteksi — membutuhkan konfirmasi.")
        lines.append("   Lihat SKILL.md §5 untuk daftar apa yang dianggap berisiko.")

    return "\n".join(lines)


def build_change_plan(config, state: Optional[dict] = None,
                      client: Optional[DiscordClient] = None) -> Plan:
    if state is None:
        state = fetch_state(client, config.guild)
    return build_plan(
        config,
        guild_state=state["guild"],
        channel_states=state["channels"],
        role_states=state["roles"],
    )


def cmd_plan(args) -> int:
    config = load(args.config)
    client = DiscordClient()
    plan = build_change_plan(config, client=client)
    print(render_plan(plan, show_requests=False))
    print(f"\nMetrik: {client.metrics.requests} request, "
          f"{client.metrics.retries} retry, "
          f"{client.metrics.rate_limit_hits} rate-limit, "
          f"{client.metrics.duration:.1f}s")
    return 0


def cmd_dry_run(args) -> int:
    config = load(args.config)
    client = DiscordClient()
    plan = build_change_plan(config, client=client)
    print("DRY RUN — tidak ada yang dikirim ke Discord.\n")
    print(render_plan(plan, show_requests=True))
    return 0


def cmd_apply(args) -> int:
    config = load(args.config)
    client = DiscordClient()
    plan = build_change_plan(config, client=client)

    print(render_plan(plan))

    if plan.is_empty:
        print("\nTidak ada yang perlu dilakukan.")
        return 0

    if plan.caution and not args.yes:
        print("\nDIBATALKAN. Rencana berisi perubahan berisiko.")
        print("Tinjau dulu, lalu jalankan ulang dengan --yes kalau sudah yakin.")
        return 2

    print("\nMengeksekusi…\n")
    result = apply(config, plan, client, safe_only=False, verbose=True)

    _print_result(result)
    return 1 if result.errors else 0


def cmd_repair(args) -> int:
    config = load(args.config)
    client = DiscordClient()
    plan = build_change_plan(config, client=client)

    print("REPAIR — hanya perubahan ber-risks safe yang dieksekusi.\n")
    print(render_plan(plan))

    if plan.is_empty:
        print("\nTidak ada yang perlu diperbaiki.")
        return 0

    if plan.caution:
        print(f"\n{len(plan.caution)} perubahan berisiko DILEWATI.")
        print("   Jalankan `apply --yes` bila memang mau mengeksekusinya.\n")

    result = apply(config, plan, client, safe_only=True, verbose=True)
    _print_result(result)
    return 1 if result.errors else 0


def cmd_verify(args) -> int:
    config = load(args.config)
    client = DiscordClient()
    state = fetch_state(client, config.guild)

    report = verify(
        config,
        guild_state=state["guild"],
        channel_states=state["channels"],
        role_states=state["roles"],
    )
    print(report.render())
    return 0 if report.ok else 1


def _print_result(result) -> None:
    print(f"\n✓ {result.ok_count} perubahan diterapkan.")
    if result.skipped:
        print(f"⊘ {len(result.skipped)} dilewati:")
        for line in result.skipped:
            print(f"    {line}")
    if result.errors:
        print(f"✗ {len(result.errors)} gagal:")
        for line in result.errors:
            print(f"    {line}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bss",
        description="Discord server structure adapter (builder-server-skill)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("-c", "--config", required=True, help="berkas konfigurasi YAML")
        p.add_argument("-g", "--guild", help="id guild (ditimpa dari config bila ada)")
        p.set_defaults(func=fn)
        return p

    add("plan", cmd_plan, help="hitung diff, tampilkan ringkasan (tanpa tulis)")
    add("dry_run", cmd_dry_run, help="tampilkan request yang akan dikirim (tanpa tulis)")
    apply_p = add("apply", cmd_apply, help="eksekusi diff ke Discord")
    repair_p = add("repair", cmd_repair, help="eksekusi hanya perubahan aman")
    add("verify", cmd_verify, help="baca ulang server, bandingkan dengan rancangan")

    # --yes harus ditambahkan SEBELUM parse_args, kalau tidak tidak akan
    # dikenali sebagai argumen valid.
    apply_p.add_argument("--yes", action="store_true",
                         help="wajib bila plan berisi perubahan berisiko")
    repair_p.add_argument("--yes", action="store_true", help="(diabaikan, repair selalu aman)")

    # dry-run juga bisa dipanggil dengan tanda hubung
    args = parser.parse_args(argv)
    if args.command == "dry_run":
        args.command = "dry-run"

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Konfigurasi tidak valid:\n{exc}", file=sys.stderr)
        return 2
    except DiscordError as exc:
        print(f"Discord API error:\n{exc}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(f"Kesalahan: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
