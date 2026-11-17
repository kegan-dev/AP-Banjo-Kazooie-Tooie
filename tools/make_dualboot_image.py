"""Build the combined Tooie + Banjo-Kazooie dual-boot image (dual-boot contract 5, hack/DUALBOOT.md).

Layout, exactly 64 MiB:

    0x0000000   AP-patched Banjo-Tooie (hack/bt build): header, IPL3 6105, game, AP payload past 32 MiB.
                At most 0x2100000 bytes: its boot stub loads 1 MiB from 0x2000000.
    0x2200000   Banjo-Kazooie payload (bash hack/build_bk.sh), in a 64 KiB slot. All zeros without one.
    0x2210000   info block, written here: 'BKBTINFO', a big-endian u32 length, that many bytes of JSON.
    0x3000000   Banjo-Kazooie, 16 MiB, not relocated: the Tooie hack's launcher points osRomBase at it.

The Tooie header stays as is (its CRC covers only the first MiB, unchanged), so emulators and the
Everdrive treat the image as the AP Tooie ROM: CIC-6105, SRAM 256k, Expansion Pak.

The image has one save device, those 32 KiB of SRAM, and both games keep their save in it
(hack/DUALBOOT.md, "The save device"): the Tooie hack from offset 0, Banjo-Kazooie its save from 0x7000,
which is the border between the two: 4 game records and the global record, 0x7000..0x74DF with the
0x130-byte records of the hack build since the link (0x7000..0x749F with the 0x120-byte ones of the notes,
0x7000..0x729F with the 0xA0-byte ones of the Jinjos,
0x7000..0x725F with the 0x90-byte ones from 2026-10-25, 0x7000..0x71FF with the 0x78-byte ones before; the
record size is the build's, tools/bk_eeprom.py).

Banjo-Kazooie is the one built from the fork (bash hack/build_bk_rom.sh, which exports the ROM and what
its map says about it to hack/bk/build/bk-fork.*). The launcher loads the payload into Expansion Pak RAM
and tells BK where it is; BK calls it to go back to Tooie. Three builds have to speak the same dual-boot
contract and agree on the layout, and nothing but this tool sees all three, so it refuses unless:

  - the launcher's tags (hack/bt/n64/asm/dualboot.asm) name BK at 0x3000000, the payload at 0x2200000,
    this contract number and the handoff block at 0x805FFF00, and the Tooie ROM ends by 0x2100000;
  - every tag of the hack is in the Tooie ROM exactly once: the tools read the words behind a tag's
    only copy. A tag that is missing and one that is there twice are told apart in the refusal. Only
    BKBTARMD (the address of the chord's arming flag, for the check tools) may be missing. No tag's
    record may be cut short by the end of the ROM, BKBTARMD's included: the image's fill would
    complete it;
  - the hack's C was compiled with the same contract number as its launcher was assembled with: the C
    copy is the fourth word of the BKBTAUTO record (hack/bt/n64/src/dualboot.c), the launcher's is the
    BKBTCONT tag, and no build step of the hack can compare the two;
  - the BK ROM is 16 MiB with the CIC-6103 IPL3, is the ROM bk-fork.json was written for (sha1), carries
    the same contract number (as an integer in the JSON), and is not the retail ROM;
  - bk-fork.json has the addresses the check tools take from the info block (the names in
    tools/bk_fork_info.py, SYMBOLS and BSS_OBJECTS) and none of the keys this tool writes itself;
  - the Tooie ROM's header declares SRAM 256k, the save device Banjo-Kazooie's save code is written
    for, and the fork keeps its save at the border, 0x7000 (bkbt_sram_offset, "sram_offset" in the JSON,
    as an integer). The Tooie side of the border is a compile-time check in the hack
    (hack/bt/n64/src/save.c) and publishes nothing;
  - BK's last 128 KiB are uniform fill: they are the top of a 64 MiB image, where some flashcarts keep
    save data;
  - the payload starts with 'BKP2', carries the same contract number, loads between the megabyte of the
    Tooie hack's own payload (where the launcher runs while it loads this one) and the launcher stack,
    and fits its slot.

The info block is how the check tools (tools/bk_antitamper_check.py, tools/dualboot_roundtrip_check.py)
learn about the image without being told: everything from bk-fork.json, "bk_kind", the test settings the
Tooie hack was built with (its BKBTAUTO record) and whether there is a payload. read_image() below is
their way in, and it compares what the block says with the image around it.

--retail-control builds the one retail configuration that is kept: the unmodified retail ROM as BK, no
payload, so BK cannot return. It shows that the launcher still gives an unmodified BK the cold-boot state
its anti-tamper wants (tools/bk_antitamper_check.py). --no-bk-payload leaves the payload out of an image
with the fork's BK; that BK cannot return either.

--expect-auto A,T,R refuses a Tooie ROM whose BKBTAUTO record does not say autotest A, trips T and BK
return R. hack/build_dualboot.sh passes what the variant it has just built has to carry, so that an
image is what its name says even if the variant's flags did not reach the compiler.

    python -I tools/make_dualboot_image.py hack/bt/n64/rom/Banjo-Tooie-Patched.z64 -o roms/bkbt2-normal.z64
    python -I tools/make_dualboot_image.py hack/bt/n64/rom/Banjo-Tooie-Patched.z64 --retail-control -o roms/bkbt2-retail-control.z64

hack/build_dualboot.sh runs the builds and this tool in order.
Exit code: 0 written, 1 refused (one line saying why, and no image written), 2 for a command line that
cannot be read: an unknown or missing option, or an --expect-auto that is not three numbers (argparse's
usage and one line; no image written either).
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # the sibling import below must not leave a tools/__pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))    # python -I leaves the script's directory out
from bk_fork_info import BSS_OBJECTS, SYMBOLS  # noqa: E402
import bk_eeprom  # noqa: E402
import rom_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The contract this tool builds and reads. The launcher (BKBTCONT tag, DUALBOOT_CONTRACT in
# hack/bt/n64/asm/dualboot.asm), the hack's C (fourth word of the BKBTAUTO record, DUALBOOT_CONTRACT in
# hack/bt/n64/src/dualboot.h), the payload (header word 4, hack/bk/asm/payload.asm) and the fork
# (bkbt_contract, hack/bk/decomp/manual_syms.us.v10.txt) each carry the number.
CONTRACT = 5
IMAGE_SIZE = 0x4000000              # 64 MiB, the ceiling emulators and flashcarts enforce (docs/ROADMAP.md)
TOOIE_MAX = 0x2100000               # the Tooie boot stub loads 1 MiB from cart 0x2000000
BK_BASE = 0x3000000                 # DUALBOOT_BK_BASE
BK_SIZE = 0x1000000
PAYLOAD_OFFSET = 0x2200000          # DUALBOOT_BK_PAYLOAD
PAYLOAD_SLOT = 0x10000              # this tool's constant; the launcher takes the length from the header
INFO_OFFSET = PAYLOAD_OFFSET + PAYLOAD_SLOT
INFO_MAGIC = b"BKBTINFO"
HANDOFF = 0x805FFF00                # DUALBOOT_HANDOFF in hack/bt/n64/src/dualboot.h
PAYLOAD_MAGIC = b"BKP2"
PAYLOAD_HEADER = 0x14               # magic, entry, load address, length, contract
# The launcher runs inside the megabyte the Tooie boot stub loads at 0x80400000 while it loads the BK
# payload, and withdraws the AP anchor at 0x80400000 afterwards: the payload has to lie above that, and
# below the launcher stack (0x805FFC00) and the handoff block.
PAYLOAD_RAM_LO, PAYLOAD_RAM_HI = 0x80500000, 0x805F0000
FILL_TAIL = 0x20000                 # BK's last 128 KiB
# The save device: SRAM 256k, 32 KiB at cart address 0x08000000. Below BK_SRAM_OFFSET it is the Tooie
# hack's (DUALBOOT_BK_SRAM_OFFSET in hack/bt/n64/src/dualboot.h), from there on Banjo-Kazooie's, whose
# save is 4 records and the global record at the border (bkbt_sram_offset in
# hack/bk/decomp/manual_syms.us.v10.txt; how many bytes that is depends on the build: bk_save_range).
BK_SRAM_OFFSET = 0x7000


def bk_save_range(fork: dict) -> str:
    """Where a fork build's save lies in the image's SRAM, from the size of its records (the spacing of
    gameFile_saveData[4] in its JSON: tools/bk_eeprom.py, record_size), for the builder's report."""
    try:
        size = bk_eeprom.Layout(bk_eeprom.record_size(fork), True).size
    except (KeyError, ValueError) as exc:
        return f"Banjo-Kazooie from 0x{BK_SRAM_OFFSET:04X} (its size unknown: {exc})"
    return f"Banjo-Kazooie 0x{BK_SRAM_OFFSET:04X}..0x{BK_SRAM_OFFSET + size - 1:04X}"
RETAIL_SHA1 = "1fe1632098865f639e22c11b9a81ee8f29c75d7a"   # Banjo-Kazooie (USA) v1.0, .z64

# Tags at the end of the launcher (hack/bt/n64/asm/dualboot.asm) and the record of the test settings
# (hack/bt/n64/src/dualboot.c), each exactly once in the Tooie part of the image. BKBTARMD (same file)
# is not needed to build an image: it gives the check tools the address of the title-screen chord's
# arming flag, and a hack without it is read as having none. More than once is another matter, for
# every tag: the tools take the words behind a tag's only copy (tag_trouble).
TAG_BASE, TAG_PAYLOAD, TAG_CONTRACT, TAG_AUTO, TAG_ARMED = b"BKBTBASE", b"BKBTPAYL", b"BKBTCONT", b"BKBTAUTO", b"BKBTARMD"
TAGS = (TAG_BASE, TAG_PAYLOAD, TAG_CONTRACT, TAG_AUTO, TAG_ARMED)
# Keys of the info block that are this tool's to write. bk-fork.json carries the middle two as well, and
# they are compared; a JSON that carries one of the others is refused.
OWNED_KEYS = ("bk_kind", "contract", "rom_sha1", "bkbtauto", "payload")

# Banjo-Kazooie's anti-tamper compares words of its own CIC-6103 IPL3 (hack/DUALBOOT.md, "Cold-boot
# residue"). The launcher copies IPL3 0x4C0..0x768 to RDRAM 0, BK reads the cart words through
# osRomBase | offset, and every BK, the fork's included, fetches its rspboot microcode from the IPL3's
# font area (0xB70). All of that needs BK's own IPL3 intact at BASE.
IPL3_COPY = 0x4C0
# RDRAM address -> word the 6103 IPL3 leaves there (decomp src/MMM/ch/tumblar.c:36, core1/viewport.c:94,
# SM/code_2900.c:17, core2/code_4C020.c:430, core2/anctrl.c:223, GV/gvspawnqueue.c:516)
RESIDUE_WORDS = {0x1D0: 0x356BAAAE, 0x1D8: 0xAC2B0010, 0x200: 0xAC290000, 0x22C: 0x12600004,
                 0x238: 0x10000003, 0x284: 0x240B17D7}
# cart offset -> low 16 bits osPiReadIo must return (decomp src/CC/code_13C0.c:171, SM/smspawnqueue.c:68,
# MM/crc.c:34, GV/crc.c:26, BGS/ch/mudhut.c:61, core2/gccube.c:1337)
CART_WORDS = {0x504: 0xA460, 0x574: 0x6C07, 0x578: 0x8965, 0x800: 0x0001, 0xD10: 0x0400, 0xE38: 0x828A}


def need(cond: bool, msg: str) -> None:
    """Refuse with a one-line message. Not an assert: python -O must not switch the guards off."""
    if not cond:
        sys.exit(f"{Path(sys.argv[0]).name}: {msg}")


class ImageError(ValueError):
    """What read_image raises about a file that is a dual-boot image but not one this contract describes."""


def read_file(path: Path, what: str, hint: str = "") -> bytes:
    """The bytes of an input file, or a one-line refusal."""
    need(path.is_file(), f"no {what} at {path}" + (f": {hint}" if hint else ""))
    try:
        return path.read_bytes()
    except OSError as exc:
        need(False, f"cannot read the {what} at {path} ({exc.strerror})")


def check_bk_ipl3(bk: bytes) -> None:
    for addr, want in RESIDUE_WORDS.items():
        got = struct.unpack_from(">I", bk, IPL3_COPY + addr)[0]
        need(got == want, f"BK IPL3 0x{IPL3_COPY + addr:X} = {got:08X}, residue check at RDRAM 0x{addr:X} wants {want:08X}")
    for off, want in CART_WORDS.items():
        got = struct.unpack_from(">I", bk, off)[0] & 0xFFFF
        need(got == want, f"BK IPL3 0x{off:X} low half = {got:04X}, cart check wants {want:04X}")


def tag_words(tooie: bytes, tag: bytes, count: int):
    """The `count` big-endian words behind a tag that has to be in the Tooie part exactly once, else None."""
    at = tooie.find(tag)
    if at < 0 or tooie.count(tag) != 1 or at + len(tag) + 4 * count > len(tooie):
        return None
    return struct.unpack_from(f">{count}I", tooie, at + len(tag))


def launcher_facts(tooie: bytes) -> dict:
    """What the Tooie hack publishes about itself. An entry is None when its tag is not in the ROM
    exactly once; "tags" says how often each tag is there, so that a caller can tell a hack that never
    had a tag from a ROM that has it twice (tag_trouble).
    c_contract is the contract number the hack's C was compiled with (the launcher's is `contract`);
    chord_armed the KSEG0 address of the one-byte arming flag of the title-screen chord."""
    base, payload, cont, auto, armed = (tag_words(tooie, tag, n) for tag, n in
                                        ((TAG_BASE, 1), (TAG_PAYLOAD, 1), (TAG_CONTRACT, 2), (TAG_AUTO, 4), (TAG_ARMED, 1)))
    return {"base": base and base[0], "payload_offset": payload and payload[0],
            "contract": cont and cont[0], "handoff": cont and cont[1],
            "bkbtauto": auto and {"autotest": auto[0], "trips": auto[1], "bk_return": auto[2]},
            "c_contract": auto and auto[3], "chord_armed": armed and armed[0],
            "tags": {tag.decode("ascii"): tooie.count(tag) for tag in TAGS}}


def tag_trouble(facts: dict, required=(), at_most_once=()) -> str | None:
    """Which tags a Tooie hack ROM does not carry as it has to, in words that follow "the ROM": "has no
    BKBTCONT tag", "has the BKBTARMD tag 2 times". None when every tag in `required` is there exactly
    once and none in `at_most_once` more than once. The two faults get different words because they
    have different causes: a hack from before the tag existed lacks it, and no build of the hack writes
    one twice, so a second copy means something else has put those eight bytes into the ROM."""
    counts = facts["tags"]
    missing = [tag.decode("ascii") for tag in required if counts[tag.decode("ascii")] == 0]
    doubled = [tag.decode("ascii") for tag in (*required, *at_most_once) if counts[tag.decode("ascii")] > 1]
    said = []
    if missing:
        said.append("has no " + " and no ".join(missing) + " tag")
    if doubled:
        said.append("has " + " and ".join(f"the {name} tag {counts[name]} times" for name in doubled)
                    + " (a tag has to be there exactly once, or no tool can tell which copy the hack means)")
    return ", and ".join(said) or None


def contract_words_differ(facts: dict):
    """Why the hack's two copies of the contract number do not agree, or None when they do."""
    c, asm = facts["c_contract"], facts["contract"]
    if c == asm:
        return None
    if c is None or c > 0xFF:       # the number is the low byte of the launch token; this is whatever lies behind an older record
        return ("the Tooie hack's BKBTAUTO record has no contract number behind its three settings"
                + ("" if c is None else f" (the word there reads 0x{c:08X})")
                + ": a hack from before 2026-10-12, when its C began to publish the number it was compiled with")
    return (f"the Tooie hack's C was compiled for dual-boot contract {c} (fourth word of its BKBTAUTO record), its launcher was "
            f"assembled for {asm} (BKBTCONT): DUALBOOT_CONTRACT in src/dualboot.h and asm/dualboot.asm differ")


def header_declares_sram(rom: bytes) -> bool:
    """Does the ROM header carry the EverDrive save declaration for SRAM 256k? 'ED' at 0x3C..0x3D and
    0x3 in the high nibble of 0x3F (tools/ed64romconfig.py; `ed64romconfig -w sram256k` in
    hack/bt/n64/Makefile). mupen64plus picks the image's save type by it."""
    return len(rom) >= 0x40 and rom[0x3C:0x3E] == b"ED" and rom[0x3F] >> 4 == 3


def sram_offset_problem(fork: dict) -> str | None:
    """What is wrong with the place a fork build keeps its save at, as its JSON or an info block's copy
    of it gives it, or None. The type first: "28672" is not 28672."""
    if "sram_offset" not in fork:
        return "has no \"sram_offset\": written for a fork build from before the save device"
    value = fork["sram_offset"]
    if type(value) is not int:
        return f"gives the place of the save in SRAM as {value!r}, which is not an integer"
    if value != BK_SRAM_OFFSET:
        return (f"puts Banjo-Kazooie's save at SRAM 0x{value:X} (bkbt_sram_offset), but the border between the two games' "
                f"saves is 0x{BK_SRAM_OFFSET:X}")
    return None


def fork_info_problem(fork) -> str | None:
    """What is wrong with the content of a bk-fork.json (or of an info block's copy of it), or None."""
    if not isinstance(fork, dict):
        return "is not a JSON object"
    symbols, bss = fork.get("symbols"), fork.get("bss")
    if not isinstance(symbols, dict) or not isinstance(bss, dict):
        return "has no \"symbols\" or no \"bss\" (tools/bk_fork_info.py writes both)"
    missing = [n for n in SYMBOLS if n not in symbols] + [f".bss of {o}" for o in BSS_OBJECTS if o not in bss]
    if missing:
        return f"lacks {', '.join(missing)}: written for a fork build from before these exports"
    try:
        for name in SYMBOLS:
            int(symbols[name], 16)
        for obj in BSS_OBJECTS:
            lo, hi = (int(x, 16) for x in bss[obj])
            if not lo < hi:
                return f"gives an empty .bss for {obj}"
    except (TypeError, ValueError):
        return "has an address that is not a hex string, or a .bss that is not a pair of them"
    return None


def free_tail(bk: bytes) -> int:
    """Bytes at the end of the ROM that all equal its last byte."""
    return len(bk) - len(bk.rstrip(bk[-1:]))


def check_payload(payload: bytes) -> None:
    need(len(payload) >= PAYLOAD_HEADER and payload[:4] == PAYLOAD_MAGIC,
         "BK payload does not start with 'BKP2' (a 'BKPL' payload is from before contract 2): bash hack/build_bk.sh")
    entry, load, length, contract = struct.unpack_from(">IIII", payload, 4)
    need(contract == CONTRACT, f"BK payload speaks dual-boot contract {contract}, this image is contract {CONTRACT}")
    need(length == len(payload) and length % 8 == 0 and length <= PAYLOAD_SLOT,
         f"BK payload header says {length} bytes, file has {len(payload)} (slot {PAYLOAD_SLOT}, multiple of 8)")
    need(PAYLOAD_RAM_LO <= load and load + length <= PAYLOAD_RAM_HI and load % 4 == 0,
         f"BK payload at 0x{load:08X} is outside 0x{PAYLOAD_RAM_LO:08X}..0x{PAYLOAD_RAM_HI:08X}")
    need(load + PAYLOAD_HEADER <= entry < load + length and entry % 4 == 0,
         f"BK payload entry 0x{entry:08X} is outside the payload")


def read_image(rom: bytes):
    """What a dual-boot image says about itself, for the check tools. None for a ROM that carries no
    launcher (a plain Banjo-Kazooie or Tooie ROM). Raises ImageError for an image this contract does
    not describe, or one whose parts do not belong together: the check tools act on what the info block
    says, so everything in it that the image can confirm is compared here.

    Returns a dict: base, payload_offset, contract, handoff (from the launcher's tags), bkbtauto (the
    Tooie hack's test settings), c_contract, chord_armed (launcher_facts), info (the info block's JSON),
    payload (the bytes in the slot, empty without one) and payload_ram (its load address, or None)."""
    facts = launcher_facts(rom[:TOOIE_MAX])
    counts = facts["tags"]
    if not counts["BKBTBASE"] and not counts["BKBTPAYL"]:
        return None
    if not counts["BKBTCONT"]:
        raise ImageError("the launcher carries no BKBTCONT tag: an image from before dual-boot contract 2 "
                         "(BK relocated to 0x2200000). Build a new one with hack/build_dualboot.sh")
    # a tag twice is refused here, BKBTARMD too: a check tool would otherwise go on without the words
    # behind it and report the hack as one that never had the tag
    trouble = tag_trouble(facts, required=(TAG_BASE, TAG_PAYLOAD, TAG_CONTRACT, TAG_AUTO), at_most_once=(TAG_ARMED,))
    if trouble:
        raise ImageError(f"the Tooie hack in the image {trouble}")
    base, pay = facts["base"], facts["payload_offset"]
    if None in (base, pay, facts["contract"], facts["bkbtauto"]) or (counts["BKBTARMD"] and facts["chord_armed"] is None):
        raise ImageError("the Tooie part of the image ends inside the record behind one of its dual-boot tags")
    if facts["contract"] != CONTRACT:
        raise ImageError(f"the launcher speaks dual-boot contract {facts['contract']}, this tool reads contract {CONTRACT}")
    if contract_words_differ(facts):
        raise ImageError(contract_words_differ(facts))
    if len(rom) != IMAGE_SIZE or base + BK_SIZE > len(rom) or pay + PAYLOAD_SLOT > base:
        raise ImageError(f"{len(rom)} bytes with BK at 0x{base:X} and the payload slot at 0x{pay:X}: not a contract {CONTRACT} image"
                         + (" (the Tooie hack ROM by itself? tools/dualboot_roundtrip_check.py --tooie-alone)" if len(rom) <= TOOIE_MAX else ""))
    at = pay + PAYLOAD_SLOT
    if rom[at:at + 8] != INFO_MAGIC:
        raise ImageError(f"no info block at 0x{at:X}: not written by tools/make_dualboot_image.py")
    length = struct.unpack_from(">I", rom, at + 8)[0]
    if at + 12 + length > base:
        raise ImageError(f"the info block at 0x{at:X} claims {length} bytes")
    try:
        info = json.loads(rom[at + 12:at + 12 + length].decode("ascii"))
    except ValueError as exc:
        raise ImageError(f"the info block at 0x{at:X} is not ASCII JSON ({exc})") from None
    if not isinstance(info, dict):
        raise ImageError(f"the info block at 0x{at:X} is not a JSON object")
    if type(info.get("contract")) is not int or info["contract"] != CONTRACT:
        # !r: a block that says "2" where the number 2 belongs must not read as if 2 differed from 2
        raise ImageError(f"the info block is for dual-boot contract {info.get('contract')!r}, this tool reads contract {CONTRACT!r}")
    sha1 = hashlib.sha1(rom[base:base + BK_SIZE]).hexdigest()
    if info.get("rom_sha1") != sha1:
        raise ImageError(f"the BK at 0x{base:X} has sha1 {sha1}, the info block describes {info.get('rom_sha1')}")
    kind = info.get("bk_kind")
    if kind not in ("fork", "retail") or (kind == "retail") != (sha1 == RETAIL_SHA1):
        raise ImageError(f"the info block calls the BK at 0x{base:X} '{kind}', but its sha1 {sha1} is "
                         + ("the retail ROM's" if sha1 == RETAIL_SHA1 else "not the retail ROM's"))
    if kind == "fork" and fork_info_problem(info):
        raise ImageError(f"the info block {fork_info_problem(info)}. Build a new image with hack/build_dualboot.sh")
    if kind == "fork" and sram_offset_problem(info):
        raise ImageError(f"the info block {sram_offset_problem(info)}. Build a new image with hack/build_dualboot.sh")
    if not header_declares_sram(rom):
        raise ImageError("the image's header does not declare SRAM 256k ('ED' at 0x3C, 0x3 in the high nibble of 0x3F)")
    if info.get("bkbtauto") != facts["bkbtauto"]:
        raise ImageError(f"the info block gives the Tooie hack's test settings as {info.get('bkbtauto')}, "
                         f"the hack's BKBTAUTO record says {facts['bkbtauto']}")
    payload, payload_ram = b"", None
    if rom[pay:pay + 4] == PAYLOAD_MAGIC:
        payload_ram, length, contract = struct.unpack_from(">III", rom, pay + 8)
        if contract != CONTRACT:    # the launcher loads it all the same, and BK then never calls it
            raise ImageError(f"the BK payload in the slot at 0x{pay:X} speaks dual-boot contract {contract}, the image is contract {CONTRACT}")
        payload = rom[pay:pay + min(length, PAYLOAD_SLOT)]
    if bool(payload) != bool(info.get("payload")):
        raise ImageError("the info block and the payload slot disagree on whether there is a payload")
    return dict(facts, info=info, payload=payload, payload_ram=payload_ram)


def parse_expect_auto(text: str) -> dict:
    """--expect-auto A,T,R as the dict launcher_facts gives for the BKBTAUTO record."""
    try:
        autotest, trips, bk_return = (int(x, 0) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("three numbers: autotest,trips,return (say 1,1,300)") from None
    return {"autotest": autotest, "trips": trips, "bk_return": bk_return}


def main(argv=None) -> int:
    build = ROOT / "hack" / "bk" / "build"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tooie", type=Path, help="AP-patched Banjo-Tooie ROM (hack/bt build output)")
    ap.add_argument("--bk", type=Path, help="Banjo-Kazooie ROM (default: hack/bk/build/bk-fork.z64; with "
                    "--retail-control: roms/Banjo-Kazooie (USA).z64)")
    ap.add_argument("--bk-info", type=Path, help="what bk_fork_info.py wrote about that ROM (default: the ROM's name with .json)")
    ap.add_argument("--bk-payload", type=Path, help="Banjo-Kazooie payload (default: hack/bk/build/bk-payload.bin)")
    ap.add_argument("--no-bk-payload", action="store_true", help="leave the payload out: BK cannot return")
    ap.add_argument("--retail-control", action="store_true",
                    help="the unmodified retail ROM as BK, no payload (the control for the launcher's cold-boot residue)")
    ap.add_argument("--expect-auto", type=parse_expect_auto, metavar="A,T,R",
                    help="refuse a Tooie ROM whose BKBTAUTO record is not autotest A, trips T, BK return R")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args(argv)
    # options that would be ignored must not look as if they had been honoured
    if args.retail_control:
        ignored = [name for name, given in (("--bk-payload", args.bk_payload), ("--no-bk-payload", args.no_bk_payload),
                                            ("--bk-info", args.bk_info)) if given]
        need(not ignored, f"--retail-control builds the retail ROM in with no payload and no description of it: "
                          f"it cannot be combined with {', '.join(ignored)}")
    need(not (args.no_bk_payload and args.bk_payload), "--no-bk-payload and --bk-payload contradict each other")

    hint = "rebuild the hack (bash hack/build_bt.sh clean)"
    bt = read_file(args.tooie, "Tooie ROM", "bash hack/build_bt.sh clean")
    need(b"TOOIE" in bt[0x20:0x34], "first ROM is not Banjo-Tooie")
    need(len(bt) <= TOOIE_MAX, f"Tooie ROM is 0x{len(bt):X} bytes, more than 0x{TOOIE_MAX:X}: the image has no room for it")
    need(header_declares_sram(bt), "the Tooie ROM's header does not declare SRAM 256k ('ED' at 0x3C, 0x3 in the high nibble of "
                                   "0x3F), the save device both games' saves are written for: rebuild the hack (bash hack/build_bt.sh clean)")
    facts = launcher_facts(bt)
    # BKBTARMD may be missing (the check tools then say that they cannot find the arming flag), but a ROM
    # that has it twice is no better than one that has BKBTBASE twice
    trouble = tag_trouble(facts, required=(TAG_BASE, TAG_PAYLOAD, TAG_CONTRACT, TAG_AUTO), at_most_once=(TAG_ARMED,))
    need(not trouble, f"Tooie ROM {trouble}: " + (f"a hack from before dual-boot contract {CONTRACT}? " if trouble and "has no" in trouble else "")
         + hint)
    need(None not in (facts["base"], facts["payload_offset"], facts["contract"], facts["handoff"], facts["bkbtauto"]),
         f"Tooie ROM ends inside the record behind one of its dual-boot tags; {hint}")
    # The same for BKBTARMD when it is there. In the image the zero fill behind the ROM would complete
    # the record, and the check tools would read an arming flag address that the hack never wrote.
    need(facts["tags"]["BKBTARMD"] == 0 or facts["chord_armed"] is not None, f"Tooie ROM ends inside its BKBTARMD record; {hint}")
    need(facts["base"] == BK_BASE, f"launcher was built for BK at 0x{facts['base']:X} (DUALBOOT_BK_BASE), this layout has it at 0x{BK_BASE:X}")
    need(facts["payload_offset"] == PAYLOAD_OFFSET, f"launcher looks for the BK payload at 0x{facts['payload_offset']:X} "
                                                    f"(DUALBOOT_BK_PAYLOAD), this layout has it at 0x{PAYLOAD_OFFSET:X}")
    need(facts["contract"] == CONTRACT, f"launcher speaks dual-boot contract {facts['contract']}, this tool builds contract {CONTRACT}")
    need(facts["handoff"] == HANDOFF, f"launcher's handoff block is at 0x{facts['handoff']:08X}, not 0x{HANDOFF:08X}")
    need(not contract_words_differ(facts), f"{contract_words_differ(facts)}; {hint}")
    auto = facts["bkbtauto"]
    if args.expect_auto is not None:
        need(auto == args.expect_auto,
             f"the Tooie ROM's BKBTAUTO record says autotest {auto['autotest']}, trips {auto['trips']}, BK return {auto['bk_return']}; "
             f"--expect-auto wants {args.expect_auto['autotest']},{args.expect_auto['trips']},{args.expect_auto['bk_return']}: "
             "this is not the build that was asked for (did EXTRA_CFLAGS reach the compiler?)")

    bk_path = args.bk or (ROOT / "roms" / "Banjo-Kazooie (USA).z64" if args.retail_control else build / "bk-fork.z64")
    bk = read_file(bk_path, "Banjo-Kazooie ROM", "" if args.retail_control else "bash hack/build_bk_rom.sh")
    need(len(bk) == BK_SIZE, f"Banjo-Kazooie ROM is {len(bk)} bytes, not 16 MiB")
    check_bk_ipl3(bk)
    sha1 = hashlib.sha1(bk).hexdigest()
    tail = free_tail(bk)
    need(tail >= FILL_TAIL, f"only the last {tail} bytes of the Banjo-Kazooie ROM are fill, the image needs its last {FILL_TAIL} "
                            "free (the top of a 64 MiB cart, where some flashcarts keep save data)")
    info = {"bk_kind": "retail" if args.retail_control else "fork", "contract": CONTRACT, "rom_sha1": sha1}
    payload = b""
    if args.retail_control:
        need(sha1 == RETAIL_SHA1, f"--retail-control wants the unmodified Banjo-Kazooie (USA) v1.0 ROM (sha1 {RETAIL_SHA1}), "
                                  f"{bk_path.name} has {sha1}")
    else:
        need(sha1 != RETAIL_SHA1, f"{bk_path.name} is the retail ROM: the image takes the fork's hack build "
                                  "(bash hack/build_bk_rom.sh); the retail ROM only goes in with --retail-control")
        info_path = args.bk_info or bk_path.with_suffix(".json")
        raw = read_file(info_path, "description of the Banjo-Kazooie ROM", "bash hack/build_bk_rom.sh writes the pair")
        try:
            fork = json.loads(raw.decode("ascii"))
        except ValueError as exc:
            fork = None
            need(False, f"{info_path.name} is not ASCII JSON ({exc})")
        need(isinstance(fork, dict), f"{info_path.name} is not a JSON object")
        need(fork.get("rom_sha1") == sha1, f"{info_path.name} describes a ROM with sha1 {fork.get('rom_sha1')}, "
                                           f"{bk_path.name} has {sha1}: the pair does not belong together")
        # The type first: "2" is not 2, and printed without quotes the refusal below would say that 2
        # differs from 2. (bool is an int to Python, and 2.0 == 2: neither is what bk_fork_info.py writes.)
        need(type(fork.get("contract")) is int,
             f"{info_path.name} gives the dual-boot contract as {fork.get('contract')!r}, which is not an integer"
             if "contract" in fork else f"{info_path.name} has no \"contract\"")
        need(fork["contract"] == CONTRACT, f"this Banjo-Kazooie speaks dual-boot contract {fork['contract']} (bkbt_contract), "
                                           f"the launcher {CONTRACT}")
        mine = [key for key in OWNED_KEYS if key in fork and key not in ("contract", "rom_sha1")]
        need(not mine, f"{info_path.name} carries {', '.join(mine)}, which this tool writes itself: not a file tools/bk_fork_info.py wrote")
        need(not fork_info_problem(fork), f"{info_path.name} {fork_info_problem(fork)}: bash hack/build_bk_rom.sh")
        need(not sram_offset_problem(fork), f"{info_path.name} {sram_offset_problem(fork)}: bash hack/build_bk_rom.sh")
        # this tool's own keys win whatever the file says; they were compared or refused above
        info.update((key, value) for key, value in fork.items() if key not in OWNED_KEYS)
        if not args.no_bk_payload:
            payload = read_file(args.bk_payload or build / "bk-payload.bin", "BK payload", "bash hack/build_bk.sh (or --no-bk-payload)")
            check_payload(payload)
    info["bkbtauto"] = auto
    info["payload"] = bool(payload)
    blob = json.dumps(info, indent=1).encode("ascii")
    need(INFO_OFFSET + 12 + len(blob) <= BK_BASE, "info block does not fit below Banjo-Kazooie")

    img = bytearray(IMAGE_SIZE)
    img[0:len(bt)] = bt
    # the image's own name in its header, which emulators show and Project64 names its save after (since
    # 2026-11-12, the owner's decision: an AP name; the Tooie hack's ROM keeps "RANDO TOOIE"); outside the checksum
    img[rom_name.NAME_AT:rom_name.NAME_AT + rom_name.NAME_SIZE] = rom_name.field(rom_name.IMAGE_NAME)
    img[PAYLOAD_OFFSET:PAYLOAD_OFFSET + len(payload)] = payload
    img[INFO_OFFSET:INFO_OFFSET + 12 + len(blob)] = INFO_MAGIC + struct.pack(">I", len(blob)) + blob
    img[BK_BASE:BK_BASE + len(bk)] = bk
    try:        # what the check tools will see must be what was just checked
        seen = read_image(bytes(img))
    except ImageError as exc:
        seen = None
        need(False, f"the image does not read back: {exc}")
    need(seen is not None and seen["info"] == info and seen["payload"] == payload, "the image does not read back as written")
    # and the hack's tags must say in the image what they say in the ROM: nothing behind the ROM may have
    # completed a record or made a second copy of a tag
    changed = [key for key, value in facts.items() if seen[key] != value]
    need(not changed, f"the Tooie hack's tags read differently in the image than in the ROM ({', '.join(changed)})")
    try:
        args.output.write_bytes(img)
    except OSError as exc:
        need(False, f"cannot write {args.output} ({exc.strerror})")
    print(f"wrote {args.output}: {len(img)} bytes, sha1 {hashlib.sha1(img).hexdigest()}, named {rom_name.IMAGE_NAME!r}")
    back = f"BK comes back by itself after {auto['bk_return']} main-loop iterations" if auto["bk_return"] else "BK stays"
    print(f"  Tooie hack {len(bt)} B, contract {CONTRACT}, "
          + (f"door test build: through the hub door by itself, {auto['trips']} time(s)" if auto["autotest"] == 2
             else f"cross test build: the hub door and the doors between the games, {auto['trips']} time(s)"
             if auto["autotest"] == 3
             else f"test build: goes to BK by itself, {auto['trips']} time(s); {back}" if auto["autotest"]
             else "normal build: L + R + Start on the title screen"))
    print(f"  Banjo-Kazooie ({info['bk_kind']}) at 0x{BK_BASE:X}, sha1 {sha1}, free tail {tail} B "
          f"({tail - FILL_TAIL} B of room before the last {FILL_TAIL} B)")
    print(f"  save device SRAM 256k: the Tooie hack below 0x{BK_SRAM_OFFSET:04X}, "
          + (bk_save_range(info) if info["bk_kind"] == "fork"
             else "the retail Banjo-Kazooie keeps no save in an image"))
    print((f"  BK payload {len(payload)} B at 0x{PAYLOAD_OFFSET:X}" if payload else "  no BK payload: Banjo-Kazooie cannot return")
          + f", info block {len(blob)} B at 0x{INFO_OFFSET:X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
