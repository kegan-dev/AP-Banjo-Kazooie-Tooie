"""The name in an N64 ROM's header: 20 bytes at 0x20, ASCII padded with spaces, which emulators show (Project64's ROM
browser, title bar and "Options > Config: <name>") and name saves after (Project64, mupen64plus). It lies outside the
range the boot code's checksum covers (0x1000..0x101000), so writing it changes nothing else.

The ROMs the clients make carry AP names (the owner's decision of 2026-11-12, docs/ROADMAP.md, item 6): the BK export
"Banjo-Kazooie AP" (hack/build_bk_rom.sh), the dual-boot image "BK & Tooie AP" (tools/make_dualboot_image.py, which
imports this). The patch descriptions carry the names to the clients' patcher (tools/make_patches.py, "header_name").

    py -3.12 -I -B tools/rom_name.py <rom> "<name>"     writes it, in place (--bk: BK_NAME, --image: IMAGE_NAME)
    py -3.12 -I -B tools/rom_name.py <rom>              prints it
"""
from __future__ import annotations

import sys
from pathlib import Path

NAME_AT, NAME_SIZE = 0x20, 20       # the header's name field (the N64's cartridge header: 0x20..0x33)
BK_NAME = "Banjo-Kazooie AP"        # the BK export's (hack/build_bk_rom.sh)
IMAGE_NAME = "BK & Tooie AP"        # the dual-boot image's, every variant (tools/make_dualboot_image.py)


def field(name: str) -> bytes:
    """The 20 bytes of `name`: printable ASCII, at most 20 characters, padded with spaces."""
    if not name or len(name) > NAME_SIZE or not all(0x20 <= ord(c) < 0x7F for c in name):
        raise ValueError(f"a ROM name is 1..{NAME_SIZE} printable ASCII characters: {name!r}")
    return name.encode("ascii").ljust(NAME_SIZE, b" ")


def named(rom: bytes, name: str) -> bytes:
    """`rom` with `name` in its header."""
    if len(rom) < NAME_AT + NAME_SIZE:
        raise ValueError("too short for an N64 ROM header")
    return rom[:NAME_AT] + field(name) + rom[NAME_AT + NAME_SIZE:]


def name_of(rom: bytes) -> str:
    return rom[NAME_AT:NAME_AT + NAME_SIZE].decode("ascii", "replace").rstrip(" \x00")


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__)
        return 2
    path = Path(argv[0])
    rom = path.read_bytes()
    if len(argv) == 1:
        print(name_of(rom))
        return 0
    name = {"--bk": BK_NAME, "--image": IMAGE_NAME}.get(argv[1], argv[1])
    try:
        path.write_bytes(named(rom, name))
    except ValueError as exc:
        print(f"rom_name.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
