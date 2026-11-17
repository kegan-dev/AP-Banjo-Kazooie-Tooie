"""Describe a Banjo-Kazooie built from the fork (hack/bk/decomp, make BKBT=1) for the dual-boot tools.

Reads the ROM and the linker map of the same build and writes a small JSON file:

    rom_sha1    sha1 of the ROM, which ties the addresses below to exactly that ROM
    contract    the dual-boot contract number the ROM implements (the absolute symbol bkbt_contract,
                hack/bk/decomp/manual_syms.us.v10.txt)
    sram_offset where in SRAM this ROM keeps its save, 4 records and the global record (the absolute symbol
                bkbt_sram_offset, same file), as an integer; tools/make_dualboot_image.py compares it
                with the border the two games share
    symbols     addresses of the pointer variables the fork exports for tools (bkbt_ptr_pad in
                src/core1/joy.c: the pad record the chord is read from; bkbt_ptr_chord_seen in
                src/core1/code_0.c: the count of main-loop iterations that saw the chord down;
                bkbt_ptr_ucode in src/core1/ucode.c: the rspboot buffer) and of sGsWorldData (+4 = map)
                and sGameState (+4 = game mode, +0x14 = map change request), and of the four globals
                the save check reads (tools/dualboot_save_check.py): gSaveData, gameFile_saveData,
                gameFile_GameIdToFileIdMap and D_80383F04, the spare file; of savedata_8033CC98,
                the function whose code the save check's --range-test changes in RAM; and of
                __osViNext, the VI context whose black state the hub door's check reads (since
                2026-11-02, tools/dualboot_door_check.py)
    bss         [start, end) of the .bss of joy.c.o, code_0.c.o and ucode.c.o: a pointer a tool reads out
                of RAM through one of the variables above has to lie inside the object it belongs to, or
                the tool is looking at something else (another build, a game that is not running yet)

Addresses are written as hex strings. hack/build_bk_rom.sh calls this after a hack build and puts the
result beside a copy of the ROM and the map in hack/bk/build/ (bk-fork.z64, bk-fork.map, bk-fork.json);
tools/make_dualboot_image.py copies the JSON into the image's info block, where the check tools find it.
SYMBOLS and BSS_OBJECTS below are the names every one of those tools relies on; the image builder
refuses a JSON that lacks one of them.

It refuses a build that is not a BKBT=1 build: bkbt_init, bkbt_frame, bkbt_padButton, bkbt_launched and
the three exports exist only there (the matching build has none of them, and its ROM is retail's), and
a map without bkbt_sram_offset, which a fork build from before the save device lacks. It also refuses
a ROM and a map that do not belong together: it inflates core1's data out of the ROM and requires each of
the three pointer variables, at the address the map gives it, to hold an address inside the .bss the map
gives its object.

    python -I tools/bk_fork_info.py <rom> <map> -o <json>

Exit code: 0 written, 1 refused (one line saying why).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

BK_SIZE = 0x1000000
# The pointer variables the fork exports and the object whose .bss each has to point into
# (hack/bk/decomp/BKBT.md, "Exports for tools"; src/core1/joy.c, code_0.c and ucode.c, all under #if BKBT).
EXPORTS = (("bkbt_ptr_pad", "joy.c.o"), ("bkbt_ptr_chord_seen", "code_0.c.o"), ("bkbt_ptr_ucode", "ucode.c.o"))
# Symbols only a BKBT=1 build has. bkbt_launched came with the save device (src/core1/code_0.c).
BKBT_ONLY = ("bkbt_init", "bkbt_frame", "bkbt_padButton", "bkbt_launched") + tuple(name for name, _obj in EXPORTS)
# The game's own globals the save check reads: the global record (src/core1/code_1D5D0.c:15), the four
# file records, which file holds which game, and the spare file (src/core2/code_B5E00.c:8-10); and the
# function that writes one file, whose count of blocks the check's --range-test changes in RAM
# (src/core2/code_B5040.c:386-393). Two names are ones the decomp generated: if upstream renames them,
# this list follows.
SAVE_SYMBOLS = ("gSaveData", "gameFile_saveData", "gameFile_GameIdToFileIdMap", "D_80383F04", "savedata_8033CC98")
# What the JSON carries. The two structs are global symbols of the game itself (src/core2/gsworld.c:10-14
# and src/core2/code_5C870.c:46-55 in the fork).
# The Archipelago anchor (src/core1/code_0.c, include/bkbt.h): the struct whose address bkbt_init publishes
# at physical 0x400000. A tool reads the word there and compares it with this address.
ANCHOR_SYMBOL = "bkbt_ap_anchor"
ANCHOR_MAGIC = b"BKAP"
# libultra's pointer to the VI context it shows next, whose state's VI_STATE_BLACK (0x20) osViBlack sets: the hub
# door's check reads it to see that the screen is black behind the curtain (tools/dualboot_door_check.py,
# lib/ultralib/src/io/viblack.c), since the links' build of 2026-11-02
VI_SYMBOL = "__osViNext"
# The game's record of the jiggies picked up (src/core2/jiggyscore.c:11-14, 13 bytes of bits, saved at the record's
# +0x02): the door check sets one just before BK's way out and finds it in the save, since 2026-11-02
JIGGY_SYMBOL = "jiggyscore"
SYMBOLS = (tuple(name for name, _obj in EXPORTS) + ("sGsWorldData", "sGameState") + SAVE_SYMBOLS + (ANCHOR_SYMBOL,)
           + (VI_SYMBOL, JIGGY_SYMBOL))
BSS_OBJECTS = tuple(obj for _name, obj in EXPORTS)
BSS_PREFIX = "build/us.v10/src/core1/"

# GNU ld map lines: "                0x000000008023dc0c                bkbt_init", with " = 0x2" behind an
# assignment from a linker script, and " .bss           0x0000000080281200      0x640 build/.../joy.c.o"
SYMBOL_LINE = re.compile(r"^\s+0x([0-9a-f]{16})\s+([A-Za-z_][A-Za-z0-9_]*)(?: = .*)?$")
SECTION_LINE = re.compile(r"^ (\.\w+)\s+0x([0-9a-f]{16})\s+0x([0-9a-f]+) (\S+)$")


def need(cond: bool, msg: str) -> None:
    """Refuse with a one-line message. Not an assert: python -O must not switch the guards off."""
    if not cond:
        sys.exit(f"{Path(sys.argv[0]).name}: {msg}")


def parse_map(text: str):
    """(symbols, sections): name -> address (the first definition counts), (object path, section) ->
    (address, size)."""
    syms, secs = {}, {}
    for line in text.splitlines():
        m = SYMBOL_LINE.match(line)
        if m:
            syms.setdefault(m.group(2), int(m.group(1), 16))
            continue
        m = SECTION_LINE.match(line)
        if m and int(m.group(3), 16):
            secs.setdefault((m.group(4), m.group(1)), (int(m.group(2), 16), int(m.group(3), 16)))
    return syms, secs


def core1_data(rom: bytes, start: int) -> bytes:
    """core1's initialised data as the boot code inflates it. core1 is two Rare zip streams back to back
    at core1_ROM_START, text then data, each '11 72', a big-endian u32 inflated size and raw deflate
    (tools/bk_rom.py; seen in the fork's hack and matching ROMs on 2026-10-11)."""
    out = b""
    for what in ("text", "data"):
        need(rom[start:start + 2] == bytes((0x11, 0x72)), f"no Rare zip stream for core1's {what} at ROM 0x{start:X}")
        packed = rom[start + 6:]
        inflater = zlib.decompressobj(-15)
        try:
            out = inflater.decompress(packed)
        except zlib.error as exc:
            need(False, f"core1's {what} at ROM 0x{start:X} does not inflate ({exc})")
        need(inflater.eof and len(out) == struct.unpack_from(">I", rom, start + 2)[0],
             f"core1's {what} at ROM 0x{start:X} does not inflate to the size its header gives")
        start += 6 + len(packed) - len(inflater.unused_data)
    return out


def fork_info(rom: bytes, map_text: str) -> dict:
    need(len(rom) == BK_SIZE, f"the ROM is {len(rom)} bytes, not 16 MiB")
    syms, secs = parse_map(map_text)
    missing = [name for name in BKBT_ONLY if name not in syms]
    need(not missing, f"the map has no {', '.join(missing)}: not a BKBT=1 build of the fork as it is now (bash hack/build_bk_rom.sh)")
    need("bkbt_contract" in syms, "the map has no bkbt_contract (hack/bk/decomp/manual_syms.us.v10.txt)")
    need("bkbt_sram_offset" in syms, "the map has no bkbt_sram_offset (hack/bk/decomp/manual_syms.us.v10.txt): "
                                     "a fork build from before the save device")
    for name in SYMBOLS:
        need(name in syms, f"the map has no {name}")
    bss = {}
    for obj in BSS_OBJECTS:
        need((BSS_PREFIX + obj, ".bss") in secs, f"the map has no .bss of {BSS_PREFIX}{obj}")
        start, size = secs[(BSS_PREFIX + obj, ".bss")]
        bss[obj] = [f"0x{start:08X}", f"0x{start + size:08X}"]
    # ROM and map belong together: the exports in the ROM point into the objects the map says they are in
    for name in ("core1_ROM_START", "core1_DATA_START"):
        need(name in syms, f"the map has no {name}")
    data = core1_data(rom, syms["core1_ROM_START"])
    for name, obj in EXPORTS:
        at = syms[name] - syms["core1_DATA_START"]
        need(0 <= at <= len(data) - 4, f"{name} at 0x{syms[name]:08X} is not inside core1's data")
        value = struct.unpack_from(">I", data, at)[0]
        lo, hi = (int(x, 16) for x in bss[obj])
        need(lo <= value < hi, f"{name} holds 0x{value:08X} in the ROM, outside the .bss of {obj} in the map "
                               f"(0x{lo:08X}..0x{hi:08X}): this ROM and this map are not of the same build")
    at = syms[ANCHOR_SYMBOL] - syms["core1_DATA_START"]
    need(0 <= at <= len(data) - 12, f"{ANCHOR_SYMBOL} at 0x{syms[ANCHOR_SYMBOL]:08X} is not inside core1's data")
    need(data[at:at + 4] == ANCHOR_MAGIC and data[at + 4] == 1,
         f"{ANCHOR_SYMBOL} in the ROM reads {data[at:at + 12].hex()}, not 'BKAP' and game_id 1: this ROM and this map "
         "are not of the same build")
    return {"rom_sha1": hashlib.sha1(rom).hexdigest(),
            "contract": syms["bkbt_contract"],
            "sram_offset": syms["bkbt_sram_offset"],
            "symbols": {name: f"0x{syms[name]:08X}" for name in SYMBOLS},
            "bss": bss}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom", type=Path, help="the fork's hack ROM (build/us.v10/banjo.us.v10.z64)")
    ap.add_argument("map", type=Path, help="the linker map of the same build (banjo.us.v10.map)")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args(argv)
    for path, what in ((args.rom, "ROM"), (args.map, "map")):
        need(path.is_file(), f"no {what} at {path}")
    info = fork_info(args.rom.read_bytes(), args.map.read_text(encoding="utf-8", errors="replace"))
    try:
        args.output.write_text(json.dumps(info, indent=1) + "\n", encoding="ascii")
    except OSError as exc:
        need(False, f"cannot write {args.output} ({exc.strerror})")
    print(f"wrote {args.output}: contract {info['contract']}, save at SRAM 0x{info['sram_offset']:04X}, rom sha1 {info['rom_sha1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
