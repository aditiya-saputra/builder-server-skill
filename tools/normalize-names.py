#!/usr/bin/env python3
"""Samakan konvensi nama channel di template dengan yang dipakai server live.

Server live memakai `【emoji・nama】` untuk channel (diminta di sesi awal).
Template sempat memakai `emoji nama`, dan karena pencocokan plan berbasis
nama, itu membuat SELURUH channel terlihat berbeda — 31 create + 31 delete
padahal isinya sama.

Kategori tetap `━━ emoji NAMA ━━` — Discord mempertahankan huruf besar di
kategori, jadi konvensinya memang berbeda dan tidak boleh disamakan.

Cara pakai:
    python3 tools/normalize-names.py templates/*.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Nama channel berada di indentasi 8 spasi; kategori di 4 spasi.
# Ini pembeda yang cukup karena strukturnya konsisten di semua template.
CHANNEL_NAME = re.compile(r'^( {8}name: ")([^"]+)(")')

# Nama yang sudah dibungkus 【】 tidak disentuh lagi.
ALREADY_WRAPPED = re.compile(r"^【.+】$")


def wrap(name: str) -> str:
    """Ubah `emoji nama` jadi `【emoji・nama】`.

    Emoji dipisah dari nama pada spasi pertama. Emoji tidak pernah memuat
    spasi, jadi split sekali sudah cukup dan aman untuk emoji multi-codepoint
    seperti 🖼️ (punya variation selector) atau 🧑‍💻 (pakai ZWJ).
    """
    if ALREADY_WRAPPED.match(name):
        return name

    if " " not in name:
        # Hanya emoji tanpa teks — tetap dibungkus supaya konsisten.
        return f"【{name}】"

    emoji, rest = name.split(" ", 1)
    return f"【{emoji}・{rest}】"


def process(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    out = []

    for line in lines:
        m = CHANNEL_NAME.match(line.rstrip("\n"))
        if m:
            prefix, name, suffix = m.groups()
            new_name = wrap(name)
            if new_name != name:
                line = f"{prefix}{new_name}{suffix}\n"
                changed += 1
        out.append(line)

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed, len(out)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    total = 0
    for arg in argv:
        path = Path(arg)
        changed, _ = process(path)
        print(f"{path}: {changed} nama channel dibungkus")
        total += changed

    print(f"\nTotal: {total} nama diubah")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
