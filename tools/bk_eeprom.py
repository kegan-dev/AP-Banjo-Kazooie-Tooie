"""Banjo-Kazooie's save, in Python: the checksum of the decomp, the layout of BK's save bytes in a build, and
a description of them. (The name is from when BK's save was an EEPROM image; it still reads those.)

Checksum: hack/bk/decomp/src/core1/glcrc.c:4-30 (glcrc_calcChecksum) with the seed step of
asm/core1/code_1E820.s:40-57 (func_8025C29C); what is stored is crc1 ^ crc2 over everything before the
last four bytes (src/core2/code_B5040.c, savedata_update_crc and _savedata_verify, called with
sizeof(SaveData) for a game record and sizeof(GlobalData) for the global one).

Layout: 4 game records (SaveData, include/save.h) one behind the other, then the global record (GlobalData,
0x20 bytes, +0x1C checksum). A record:
    +0x00 magic 0x11 when the file holds a game, +0x01 slotIndex = game number + 1, +0x02..+0x71 the game's
    data (savedata_init, src/core2/code_B5040.c), +0x72 padding[2] (in the hack build since 2026-10-27
    +0x72 u8 jiggies_given, +0x73 padding, and since the Mumbo tokens +0x73 u8 tokens_given), then
      retail (and fork builds before 2026-10-25): +0x74 checksum                              0x78 bytes
      the fork's hack build since 2026-10-25:     +0x74 u32 seed, +0x78 u8 move_locations[20]
                                                  (BKBT_AP_MOVE_COUNT), +0x8C checksum          0x90 bytes
      the fork's hack build since the Jinjos:     the same to +0x8B, then +0x8C u8 jinjos_checked[10]
                                                  (a colour mask per level - 1), +0x96 spare[6],
                                                  +0x9C checksum                                0xA0 bytes
      the fork's hack build since the notes:      the same to +0x95, then +0x96 u8 notes_collected[125]
                                                  (a bit per BKBT_AP_NOTE_INDEX, (level - 1) * 100 + n,
                                                  byte i >> 3, bit i & 7), +0x113 spare[9],
                                                  +0x11C checksum                              0x120 bytes
                                                  (+0x114 u32 link since the links of 2026-11-02)
      the fork's hack build since the link:       the same to +0x117, then +0x118 u8 traps_applied[5]
                                                  (by kind: trip, slip, transform, squish, tip),
                                                  +0x11D spare[15], +0x12C checksum           0x130 bytes
                                                  (+0x11D u8 refills_applied[4] since the refills of
                                                  2026-11-11, by kind: blue eggs, red feathers, gold
                                                  feathers, the less full feather; spare[11] after it)
The record size of a build comes from the build itself: the spacing of gameFile_saveData[4] and the
gameFile_GameIdToFileIdMap behind it (src/core2/code_B5E00.c:8-9), both in bk-fork.json and in an image's
info block (tools/bk_fork_info.py, SAVE_SYMBOLS). A size this module does not know is refused, so that a
later change of SaveData shows up as a refusal and not as records read at the wrong place.

The save device, the way emulators and the EverDrive pick it: SRAM 256k when the header of the ROM that is
played declares it ('ED' at 0x3C, 0x3 in the high nibble of 0x3F: tools/ed64romconfig.py), EEPROM 4k
otherwise. On SRAM BK's bytes start at 0x7000 (the border with the Tooie hack's save, bkbt_sram_offset in
hack/bk/decomp/manual_syms.us.v10.txt, hack/DUALBOOT.md "The save device"): the dual-boot image, whose
header is the Tooie hack's, and the fork's ROM by itself since 2026-10-25 (hack/build_bk_rom.sh writes the
header into the export; src/core1/eeprom.c has no EEPROM path left in the hack build). On EEPROM they start
at 0: older fork ROMs by themselves, 512 bytes (4 * 0x78 + 0x20).

    4 * 0x78 + 0x20 = 0x200: files at 0x000, 0x078, 0x0F0, 0x168, global at 0x1E0 (EEPROM block 60)
    4 * 0x90 + 0x20 = 0x260: files at 0x000, 0x090, 0x120, 0x1B0, global at 0x240 (SRAM 0x7000..0x725F)
    4 * 0xA0 + 0x20 = 0x2A0: files at 0x000, 0x0A0, 0x140, 0x1E0, global at 0x280 (SRAM 0x7000..0x729F)
    4 * 0x120 + 0x20 = 0x4A0: files at 0x000, 0x120, 0x240, 0x360, global at 0x480 (SRAM 0x7000..0x749F)
    4 * 0x130 + 0x20 = 0x4E0: files at 0x000, 0x130, 0x260, 0x390, global at 0x4C0 (SRAM 0x7000..0x74DF)

A module of tools/dualboot_save_check.py, tools/bk_save_model.py, tools/sra_tool.py, the check tools that
plant saves and tools/make_dualboot_image.py, and a reader of its own. It reads the files it is given and
writes nothing:

    py -3.12 -I -B tools/bk_eeprom.py <file>... [--offset N] [--swap32] [--record 0x130|0x120|0xA0|0x90|0x78]
        describe BK's save bytes at N of each save file (--offset 0x7000 for SRAM; --swap32 when the file
        keeps SRAM as little-endian words, like mupen64plus's and Project64's .sra); --record is the size
        of SaveData, default 0x130 (the current hack build), 0x120, 0xA0, 0x90 and 0x78 for older saves
"""
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

M64 = (1 << 64) - 1
SLOTS, GLOBAL_SIZE = 4, 0x20
EEPROM_SIZE = 0x200                     # EEPROM 4k: the save file of an older fork ROM by itself
SRAM_SIZE, SRAM_BORDER = 0x8000, 0x7000  # SRAM 256k; from the border on, the bytes are Banjo-Kazooie's
# sizeof(SaveData): retail; the hack build with seed and move locations (2026-10-25); with the Jinjos too; with
# the notes too; and with the traps played too, the current hack build (the link, 2026-11-10)
RECORD_RETAIL, RECORD_SEED, RECORD_JINJOS, RECORD_NOTES, RECORD_LINK = 0x78, 0x90, 0xA0, 0x120, 0x130
RECORD_AP = RECORD_LINK
KNOWN_RECORDS = (RECORD_RETAIL, RECORD_SEED, RECORD_JINJOS, RECORD_NOTES, RECORD_LINK)
DATA_END = 0x72                         # +0x02..+0x71: the game's data; +0x72 padding[2]
JIGGIES_GIVEN_AT = 0x72                 # include/save.h under #if BKBT, since 2026-10-27: SaveData.jiggies_given
TOKENS_GIVEN_AT = 0x73                  # include/save.h under #if BKBT, since the Mumbo tokens: SaveData.tokens_given
SEED_AT, LOCATIONS_AT, LOCATION_COUNT = 0x74, 0x78, 20     # include/save.h under #if BKBT; BKBT_AP_MOVE_COUNT
# The Jinjos picked up (include/save.h under #if BKBT, since the Jinjos' build): bkbt_jinjos_checked[10], one
# mask per enum level_e - 1 (levels 1..0xA; the Lair's, 6, never set) of the colours' bits, the game's own bit
# order (include/bkbt.h, BKBT_AP_JINJO_INDEX): blue 0x01, green 0x02, orange 0x04, pink 0x08, yellow 0x10.
JINJOS_AT, JINJO_LEVELS, SPARE_AT, SPARE_SIZE = 0x8C, 10, 0x96, 6    # SPARE_*: the Jinjos' build's spare bytes
# The notes picked up (include/save.h under #if BKBT, since the notes' build): bkbt_notes_collected[125], a bit
# per note index (enum level_e - 1) * 100 + n, byte index >> 3, bit index & 7 (include/bkbt.h,
# BKBT_AP_NOTE_INDEX); the Lair's 500..599 never set. Then the spare bytes of that build.
NOTES_AT, NOTE_BYTES, NOTES_SPARE_AT, NOTES_SPARE_SIZE = 0x96, 125, 0x113, 9
# The link to the game's Tooie file (include/save.h under #if BKBT, SaveData.link, since the links' build of
# 2026-11-02; the hub door, dual-boot contract 4): a big-endian u32 in four of those spare bytes, 0 for none. The
# record stays 0x120 bytes, so a record of the notes' build reads as one with no link.
LINK_AT = 0x114
# The traps played (include/save.h under #if BKBT, SaveData.traps_applied, since the link's build): a count per kind,
# Tooie's order (include/bkbt.h, BKBT_AP_TRAP_*): trip, slip, transform, squish, tip. The record grew to 0x130
# bytes for them, and its spare bytes are then +0x113 (pad) and +0x11D..+0x12B. The refills applied (SaveData.
# refills_applied, since the refills' build of 2026-11-11) took the first four: a link build's record reads 0 there,
# none applied, so the two builds share the size, and the spare bytes are +0x113 and +0x121..+0x12B.
TRAPS_APPLIED_AT, TRAP_KINDS = 0x118, 5
REFILLS_APPLIED_AT, REFILL_KINDS, LINK_SPARE_AT, LINK_SPARE_SIZE = 0x11D, 4, 0x121, 11
TRAP_NAMES = ("trip", "slip", "transform", "squish", "tip")
REFILL_NAMES = ("blue eggs", "red feathers", "gold feathers", "feather")
JINJO_COLOURS = ("blue", "green", "orange", "pink", "yellow")
# The empty honeycombs picked up, retail's own bytes in every record: sHoneycombScore[3]
# (src/core2/honeycombscore.c) copied verbatim to honeycombOffset = 2 + the 0x0D jiggy bytes
# (src/core2/code_B5040.c:116-126, src/core2/jiggyscore.c:107-110). Honeycomb n (enum honeycomb_e, 1..0x18)
# is bit n & 7 of byte (n - 1) // 8, so 8, 16 and 24 are bit 0 of their byte (honeycombscore.c:24-46).
HONEYCOMBS_AT, HONEYCOMB_IDS = 0x0F, range(1, 0x19)
# The jiggies picked up, retail's own bytes: jiggyscore.D_803832C0[0xD] (src/core2/jiggyscore.c:11-14,
# 107-110) copied verbatim to jiggyOffset = 2 (src/core2/code_B5040.c:126). Jiggy n (enum jiggy_e, 1..0x64,
# include/enums.h:1514-1616) is bit n & 7 of byte (n - 1) // 8, as for the honeycombs (jiggyscore.c:38-61).
JIGGIES_AT, JIGGY_IDS = 0x02, range(1, 0x65)
# The held (unspent) jiggies, ITEM_26_JIGGY_TOTAL: the fifth of the saved items (src/core2/code_BEF20.c:
# 489-499) at savedItemsOffset = 0x65 (code_B5040.c:129-131), a u8.
HELD_JIGGIES_AT = 0x69
# The Mumbo tokens picked up, retail's own bytes: sMumboTokenScore[16] (src/core2/mumboscore.c:5-11, 56-59)
# copied verbatim to mumbotokenOffset = honeycombOffset + 3 = 0x12 (src/core2/code_B5040.c:126-127). Token
# n (enum mumbotoken_e, 1..0x73, include/enums.h) is bit n & 7 of byte (n - 1) // 8 (mumboscore.c:22-44).
TOKENS_AT, TOKEN_IDS = 0x12, range(1, 0x74)
# The held (unspent) tokens, ITEM_1C_MUMBO_TOKEN: the first of the saved items (code_BEF20.c:501), a u8.
HELD_TOKENS_AT = 0x65
# The worlds' best note counts, retail's own bytes: notescore_getSizeAndPtr (src/core2/code_BEF20.c:440-453)
# packs sItemscoreNoteScores into one big-endian u64 at notescoresOffset = mumbotokenOffset + 16 = 0x22
# (src/core2/code_B5040.c:119-128): 7 bits per level for levels 1..5 and 7..10 (enum level_e, include/enums.h;
# the Lair, 6, skipped), level 1 shifted in first, so Mumbo's Mountain is in bits 62..56 and Mad Monster
# Mansion in bits 6..0. Loading masks each to 7 bits (code_BEF20.c:510-528).
NOTE_SCORES_AT = 0x22
NOTE_LEVELS = (("MM", 1), ("TTC", 2), ("CC", 3), ("BGS", 4), ("FP", 5), ("GV", 7), ("CCW", 8), ("RBB", 9), ("MMM", 10))
# The Lair's note doors: retail's costs by selector - 1 (note_door_cost_data, src/lair/lairspawnqueue.c:481;
# the hack's copy is bkbt_note_door_costs, src/core1/code_0.c), and each door's open flag, FILEPROG_39 +
# selector, FILEPROG_3A_NOTE_DOOR_50_OPEN .. FILEPROG_45_NOTE_DOOR_882_OPEN (include/enums.h:67-78), set by the
# door when it has faded out (lairspawnqueue.c:1001).
NOTE_DOOR_COSTS = (50, 180, 260, 350, 450, 640, 765, 810, 828, 846, 864, 882)
NOTE_DOOR_FLAG_BASE = 0x39
# Mumbo's "paid" flags, FILEPROG_90..94 (include/enums.h): termite, pumpkin, walrus, croc, bee
# (src/core2/ch/mumbo.c:93-95, set at :395 once the transformation is paid for).
PAID = {"termite": 0x90, "pumpkin": 0x91, "walrus": 0x92, "croc": 0x93, "bee": 0x94}
# The file progress flags, gFileProgressFlags (0x25 bytes, src/core2/code_98CB0.c:136-139) at
# progressflagsOffset = 0x40 (code_B5040.c:128-130). Flag f is bit f & 7 of byte f // 8; a field of n bits
# from flag f has its lowest bit at f (bitfieldarray_getNBits/setNBits, code_98CB0.c:146-174).
FLAGS_AT = 0x40
# The Lair's puzzles: PICTURE_INFO (src/lair/jigsawpicture.c:40-52): name -> (cost, bits, first flag of
# the pieces-placed count, FILEPROG_5D..7F in include/enums.h).
PUZZLES = {
    "MM": (1, 1, 0x5D), "TTC": (2, 2, 0x5E), "CC": (5, 3, 0x60), "BGS": (7, 3, 0x63), "FP": (8, 4, 0x66),
    "GV": (9, 4, 0x6A), "MMM": (10, 4, 0x6E), "RBB": (12, 4, 0x72), "CCW": (15, 4, 0x76),
    "Grunty": (25, 5, 0x7A), "DoubleHealth": (4, 3, 0x7F),
}


def jiggy_bit(n: int) -> tuple[int, int]:
    """(byte offset in the record, bit mask) of jiggy n's bit."""
    assert n in JIGGY_IDS, f"jiggy ids are 1..0x64, not {n}"
    return JIGGIES_AT + (n - 1) // 8, 1 << (n & 7)


def jiggies_in(rec: bytes) -> list:
    """The jiggies a record says were picked up."""
    return [n for n in JIGGY_IDS if rec[jiggy_bit(n)[0]] & jiggy_bit(n)[1]]


def token_bit(n: int) -> tuple[int, int]:
    """(byte offset in the record, bit mask) of Mumbo token n's bit."""
    assert n in TOKEN_IDS, f"Mumbo token ids are 1..0x73, not {n}"
    return TOKENS_AT + (n - 1) // 8, 1 << (n & 7)


def tokens_in(rec: bytes) -> list:
    """The Mumbo tokens a record says were picked up."""
    return [n for n in TOKEN_IDS if rec[token_bit(n)[0]] & token_bit(n)[1]]


def note_scores_in(rec: bytes) -> dict:
    """The best note count of each world a record holds, by name, in the record's order."""
    packed = int.from_bytes(rec[NOTE_SCORES_AT:NOTE_SCORES_AT + 8], "big")
    out = {}
    for i, (name, _) in enumerate(NOTE_LEVELS):
        out[name] = packed >> (7 * (len(NOTE_LEVELS) - 1 - i)) & 0x7F
    return out


def note_doors_open_in(rec: bytes) -> list:
    """The note doors (selectors 1..12) a record says have opened."""
    return [d for d in range(1, len(NOTE_DOOR_COSTS) + 1) if flag(rec, NOTE_DOOR_FLAG_BASE + d)]


def paid_in(rec: bytes) -> list:
    """The transformations a record says Mumbo was paid for."""
    return [name for name, f in PAID.items() if flag(rec, f)]


def flag(rec: bytes, f: int) -> bool:
    """File progress flag f of a record."""
    return bool(rec[FLAGS_AT + f // 8] & 1 << (f & 7))


def flag_field(rec: bytes, f: int, bits: int) -> int:
    """The n-bit field of file progress flags from flag f, lowest bit first."""
    return sum(flag(rec, f + i) << i for i in range(bits))


def pieces_in(rec: bytes) -> dict:
    """The pieces placed in each of the Lair's puzzles, by name, the puzzles with none left out."""
    out = {}
    for name, (_cost, bits, f) in PUZZLES.items():
        n = flag_field(rec, f, bits)
        if n:
            out[name] = n
    return out


def honeycomb_bit(n: int) -> tuple[int, int]:
    """(byte offset in the record, bit mask) of honeycomb n's bit."""
    assert n in HONEYCOMB_IDS, f"honeycomb ids are 1..0x18, not {n}"
    return HONEYCOMBS_AT + (n - 1) // 8, 1 << (n & 7)


def honeycombs_in(rec: bytes) -> list:
    """The honeycombs a record says were picked up."""
    return [n for n in HONEYCOMB_IDS if rec[honeycomb_bit(n)[0]] & honeycomb_bit(n)[1]]


def jinjos_in(rec: bytes) -> dict:
    """The Jinjos a record of the Jinjos' build says were picked up: {level name: [colours]}, in the record's
    order, the levels with none left out."""
    out = {}
    for name, level in NOTE_LEVELS:
        mask = rec[JINJOS_AT + level - 1]
        if mask:
            out[name] = [c for i, c in enumerate(JINJO_COLOURS) if mask >> i & 1]
    return out


def jinjos_odd(rec: bytes) -> dict:
    """Bytes of a record's Jinjo masks that the hack never writes: the Lair's row, bits above the five colours
    and, in a record of the Jinjos' build, the spare bytes, {name: value}; empty for a record the hack wrote."""
    out = {}
    for i in range(JINJO_LEVELS):
        mask = rec[JINJOS_AT + i]
        if i + 1 == 6 and mask:
            out["Lair"] = mask
        elif mask & ~0x1F:
            out[f"level {i + 1}"] = mask
    for i in range(SPARE_SIZE if len(rec) == RECORD_JINJOS else 0):
        if rec[SPARE_AT + i]:
            out[f"spare +0x{SPARE_AT + i:02X}"] = rec[SPARE_AT + i]
    return out


def note_bit(index: int) -> tuple[int, int]:
    """(record offset, mask) of note `index`'s bit in a record of the notes' build."""
    return NOTES_AT + (index >> 3), 1 << (index & 7)


def notes_in(rec: bytes) -> dict:
    """The notes a record of the notes' build says were picked up: {level name: [n...]}, the levels with none
    left out."""
    out = {}
    for name, level in NOTE_LEVELS:
        got = [n for n in range(100) if rec[note_bit((level - 1) * 100 + n)[0]] & note_bit((level - 1) * 100 + n)[1]]
        if got:
            out[name] = got
    return out


def spare_bytes(rec: bytes) -> list:
    """The offsets of a record's spare bytes, by its size: those the hack keeps 0."""
    if len(rec) == RECORD_LINK:
        return [NOTES_SPARE_AT] + list(range(LINK_SPARE_AT, LINK_SPARE_AT + LINK_SPARE_SIZE))
    return [NOTES_SPARE_AT + i for i in range(NOTES_SPARE_SIZE) if not LINK_AT <= NOTES_SPARE_AT + i < LINK_AT + 4]


def notes_odd(rec: bytes) -> dict:
    """Bits and bytes of a record of the notes' build (or later) that the hack never writes: the Lair's row and the
    spare bytes (spare_bytes), {name: value}; empty for a record the hack wrote."""
    out = {}
    lair = [n for n in range(100) if rec[note_bit(500 + n)[0]] & note_bit(500 + n)[1]]
    if lair:
        out["Lair notes"] = len(lair)
    for at in spare_bytes(rec):
        if rec[at]:
            out[f"spare +0x{at:03X}"] = rec[at]
    return out


def _step(seed: int) -> tuple[int, int]:
    """func_8025C29C: returns (new seed, the s32 it returns as an unsigned 32-bit value)."""
    a2 = ((seed << 63) & M64) >> 31
    a1 = ((seed << 31) & M64) >> 32
    a3 = ((seed << 44) & M64) >> 32
    a2 = (a2 | a1) ^ a3
    a3 = ((a2 >> 20) & 0xFFF) ^ a2
    return a3, a3 & 0xFFFFFFFF


def checksum(data: bytes) -> int:
    """crc1 ^ crc2 of glcrc_calcChecksum over `data` (the record without its last four bytes)."""
    seed, shift, crc1, crc2 = 0x8F809F473108B3C1, 0, 0, 0
    for b in data:
        seed = (seed + (b << (shift & 15))) & M64
        seed, out = _step(seed)
        shift += 7
        crc1 ^= out
    for b in reversed(data):
        seed = (seed + (b << (shift & 15))) & M64
        seed, out = _step(seed)
        shift += 3
        crc2 ^= out
    return crc1 ^ crc2


def sealed(record: bytes) -> bytes:
    """`record` with its last four bytes replaced by its checksum."""
    return record[:-4] + struct.pack(">I", checksum(record[:-4]))


def valid(record: bytes) -> bool:
    return struct.unpack(">I", record[-4:])[0] == checksum(record[:-4])


def swap32(data: bytes) -> bytes:
    """N64 byte order <-> little-endian words (its own inverse)."""
    return b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


def header_declares_sram(rom: bytes) -> bool:
    """The ROM header's save type is SRAM 256k (tools/ed64romconfig.py: 'ED' at 0x3C, 0x30 in 0x3F's high nibble)."""
    return len(rom) >= 0x40 and rom[0x3C:0x3E] == b"ED" and rom[0x3F] >> 4 == 3


@dataclass(frozen=True)
class Layout:
    """Where Banjo-Kazooie's save bytes are in the save file, and how they are cut up."""
    record: int                         # sizeof(SaveData)
    sram: bool                          # SRAM 256k (BK's bytes from 0x7000) or EEPROM 4k (from 0)

    @property
    def global_at(self) -> int:         # the global record, right behind the four game records
        return SLOTS * self.record

    @property
    def size(self) -> int:              # BK's bytes: 4 records and the global one
        return self.global_at + GLOBAL_SIZE

    @property
    def offset(self) -> int:            # where they start in the save file
        return SRAM_BORDER if self.sram else 0

    @property
    def file_size(self) -> int:
        return SRAM_SIZE if self.sram else EEPROM_SIZE

    @property
    def ext(self) -> str:               # mupen64plus's extension for the save file
        return "sra" if self.sram else "eep"

    @property
    def has_seed(self) -> bool:         # the record carries the seed and the move locations
        return self.record in (RECORD_SEED, RECORD_JINJOS, RECORD_NOTES, RECORD_LINK)

    @property
    def has_jinjos(self) -> bool:       # the record carries the Jinjos picked up
        return self.record in (RECORD_JINJOS, RECORD_NOTES, RECORD_LINK)

    @property
    def has_notes(self) -> bool:        # the record carries the notes picked up (and the link to its Tooie file)
        return self.record in (RECORD_NOTES, RECORD_LINK)

    @property
    def has_traps(self) -> bool:        # the record carries the traps played
        return self.record == RECORD_LINK

    def text(self) -> str:
        where = f"SRAM 0x{self.offset:04X}..0x{self.offset + self.size - 1:04X}" if self.sram else f"EEPROM 0x000..0x{self.size - 1:03X}"
        return (f"{where}: 4 records of 0x{self.record:X} bytes"
                + (" (with seed, move locations, Jinjos, notes and traps played)" if self.has_traps
                   else " (with seed, move locations, Jinjos and notes)" if self.has_notes
                   else " (with seed, move locations and Jinjos)" if self.has_jinjos
                   else " (with seed and move locations)" if self.has_seed else "")
                + f", the global record at +0x{self.global_at:03X}")

    def rec(self, img: bytes, n: int) -> bytes:
        return img[n * self.record:(n + 1) * self.record]

    def recs(self, img: bytes) -> list:
        return [self.rec(img, n) for n in range(SLOTS)]

    def glob(self, img: bytes) -> bytes:
        return img[self.global_at:self.global_at + GLOBAL_SIZE]

    def seed(self, rec: bytes):
        """The seed a record was saved with, None for a layout without it."""
        return struct.unpack_from(">I", rec, SEED_AT)[0] if self.has_seed else None

    def locations(self, rec: bytes):
        return rec[LOCATIONS_AT:LOCATIONS_AT + LOCATION_COUNT] if self.has_seed else None

    def jinjos(self, rec: bytes):
        """The ten Jinjo masks of a record (by level - 1), None for a layout without them."""
        return rec[JINJOS_AT:JINJOS_AT + JINJO_LEVELS] if self.has_jinjos else None

    def notes(self, rec: bytes):
        """The 125 bytes of a record's note bits, None for a layout without them."""
        return rec[NOTES_AT:NOTES_AT + NOTE_BYTES] if self.has_notes else None

    def link(self, rec: bytes):
        """The link of a record to its Tooie file (0: none), None for a layout without it (LINK_AT)."""
        return struct.unpack_from(">I", rec, LINK_AT)[0] if self.has_notes else None

    def traps(self, rec: bytes):
        """The traps a record has played, by kind (TRAP_NAMES), None for a layout without them."""
        return tuple(rec[TRAPS_APPLIED_AT:TRAPS_APPLIED_AT + TRAP_KINDS]) if self.has_traps else None

    def refills(self, rec: bytes):
        """The refills a record has applied, by kind (REFILL_NAMES), None for a layout without them (a 0x130-byte
        record of the link's build reads none applied)."""
        return tuple(rec[REFILLS_APPLIED_AT:REFILLS_APPLIED_AT + REFILL_KINDS]) if self.has_traps else None

    def area(self, save_file):
        """BK's bytes out of a save file in N64 byte order; None when there is none or it is too short."""
        if save_file is None or len(save_file) < self.offset + self.size:
            return None
        return save_file[self.offset:self.offset + self.size]

    def embed(self, area: bytes, base=None) -> bytes:
        """A whole save file (N64 byte order) with `area` as BK's bytes; the rest from `base`, else 0xFF."""
        assert len(area) == self.size, f"{len(area)} bytes, not the layout's 0x{self.size:X}"
        img = bytearray(base if base is not None else b"\xff" * self.file_size)
        assert len(img) == self.file_size
        img[self.offset:self.offset + self.size] = area
        return bytes(img)

    def where(self, i: int) -> str:
        """Which record byte i of BK's bytes belongs to."""
        return f"file {i // self.record} +0x{i % self.record:02X}" if i < self.global_at else f"global +0x{i - self.global_at:02X}"

    def describe(self, image: bytes) -> list:
        assert len(image) == self.size
        lines = []
        for n in range(SLOTS):
            rec = self.rec(image, n)
            if rec == b"\xff" * self.record or rec == bytes(self.record):
                kind = "all 0xFF" if rec[0] == 0xFF else "all 0x00"
            else:
                kind = (f"magic 0x{rec[0]:02X} slotIndex {rec[1]} checksum {'ok' if valid(rec) else 'BAD'} "
                        f"({sum(1 for b in rec[2:DATA_END] if b)} non-zero data bytes")
                if self.has_seed and valid(rec):
                    loc = self.locations(rec)
                    kind += (f"; seed 0x{self.seed(rec):08X}"
                             + (f", link 0x{self.link(rec):08X}" if self.has_notes and self.link(rec) else "")
                             + ", move locations "
                             + (", ".join(f"{i}" for i in range(LOCATION_COUNT) if loc[i]) or "none"))
                if valid(rec):
                    kind += "; honeycombs " + (", ".join(f"0x{n:X}" for n in honeycombs_in(rec)) or "none")
                    jig = jiggies_in(rec)
                    kind += ("; jiggies " + (", ".join(f"0x{n:X}" for n in jig) if len(jig) <= 12 else f"{len(jig)} of them")
                             if jig else "; jiggies none")
                    kind += f", {rec[HELD_JIGGIES_AT]} held"
                    if self.has_seed:
                        kind += f", {rec[JIGGIES_GIVEN_AT]} given"
                    pcs = pieces_in(rec)
                    if pcs:
                        kind += "; puzzle pieces " + ", ".join(f"{k} {v}" for k, v in pcs.items())
                    tok = tokens_in(rec)
                    kind += ("; tokens " + (", ".join(f"0x{n:X}" for n in tok) if len(tok) <= 12 else f"{len(tok)} of them")
                             if tok else "; tokens none")
                    kind += f", {rec[HELD_TOKENS_AT]} held"
                    if self.has_seed:
                        kind += f", {rec[TOKENS_GIVEN_AT]} given"
                    paid = paid_in(rec)
                    if paid:
                        kind += "; Mumbo paid for " + ", ".join(paid)
                    notes = {k: v for k, v in note_scores_in(rec).items() if v}
                    if notes:
                        kind += ("; notes " + ", ".join(f"{k} {v}" for k, v in notes.items())
                                 + f" (total {sum(notes.values())})")
                    doors = note_doors_open_in(rec)
                    if doors:
                        kind += "; note doors open " + ", ".join(f"{d} ({NOTE_DOOR_COSTS[d - 1]})" for d in doors)
                    if self.has_jinjos:
                        jin = jinjos_in(rec)
                        kind += "; Jinjos " + ("; ".join(f"{k} " + "+".join(v) for k, v in jin.items()) or "none")
                        odd = jinjos_odd(rec)
                        if odd:
                            kind += " (never written by the hack: " + ", ".join(f"{k} 0x{v:02X}" for k, v in odd.items()) + ")"
                    if self.has_notes:
                        kept = notes_in(rec)
                        kind += "; notes kept " + (", ".join(f"{k} {len(v)}" for k, v in kept.items()) or "none")
                        odd = notes_odd(rec)
                        if odd:
                            kind += " (never written by the hack: " + ", ".join(f"{k} 0x{v:02X}" for k, v in odd.items()) + ")"
                    if self.has_traps and any(self.traps(rec)):
                        kind += "; traps played " + ", ".join(f"{n} {c}" for n, c in zip(TRAP_NAMES, self.traps(rec)) if c)
                    if self.has_traps and any(self.refills(rec)):
                        kind += "; refills applied " + ", ".join(f"{n} {c}" for n, c in zip(REFILL_NAMES, self.refills(rec))
                                                                 if c)
                kind += ")"
            lines.append(f"file {n} @0x{n * self.record:03X}: {kind}")
        rec = self.glob(image)
        kind = ("all 0xFF" if rec == b"\xff" * GLOBAL_SIZE else "all 0x00" if rec == bytes(GLOBAL_SIZE) else
                f"snsItems 0x{struct.unpack('>I', rec[:4])[0]:08X} checksum 0x{struct.unpack('>I', rec[-4:])[0]:08X} "
                f"{'ok' if valid(rec) else 'BAD'}")
        lines.append(f"global @0x{self.global_at:03X}: {kind}")
        return lines


def record_size(info: dict) -> int:
    """sizeof(SaveData) of a fork build, from the spacing of gameFile_saveData[4] and the
    gameFile_GameIdToFileIdMap behind it (`info`: bk-fork.json or an image's info block). Raises ValueError
    for a size this module does not know."""
    syms = info["symbols"]
    span = int(syms["gameFile_GameIdToFileIdMap"], 16) - int(syms["gameFile_saveData"], 16)
    if span % SLOTS or span // SLOTS not in KNOWN_RECORDS:
        raise ValueError(f"gameFile_saveData[4] spans 0x{span:X} bytes in this build: a SaveData of "
                         f"{'0x%X' % (span // SLOTS) if span % SLOTS == 0 else 'no whole number of'} bytes, which the tools do not "
                         f"know (they know " + ", ".join(f"0x{r:X}" for r in KNOWN_RECORDS) + "): tools/bk_eeprom.py has to learn it")
    return span // SLOTS


def layout_of(info: dict, rom: bytes) -> Layout:
    """The layout of BK's save for a fork build (`info`) in the ROM file that is played (`rom`: the image
    or the fork's ROM by itself; its header names the save device). Raises ValueError for a record size
    the tools do not know, and for a build with seed and locations whose header does not declare SRAM:
    such a build saves only to SRAM, and an emulator that goes by the header would give it an EEPROM."""
    record = record_size(info)
    sram = header_declares_sram(rom)
    if record in (RECORD_SEED, RECORD_JINJOS, RECORD_NOTES, RECORD_LINK) and not sram:
        raise ValueError("this build keeps seed and locations in its records and saves only to SRAM, but the ROM's header does "
                         "not declare SRAM 256k ('ED' at 0x3C, 0x30 at 0x3F): hack/build_bk_rom.sh writes that header into the "
                         "export (tools/ed64romconfig.py -w sram256k)")
    return Layout(record, sram)


if __name__ == "__main__":
    argv = sys.argv[1:]
    opts = {}
    for name in ("--offset", "--record"):
        if name in argv:
            at = argv.index(name)
            opts[name] = int(argv[at + 1], 0)
            del argv[at:at + 2]
    swap = "--swap32" in argv
    args = [a for a in argv if not a.startswith("--")]
    record = opts.get("--record", RECORD_AP)
    if record not in KNOWN_RECORDS:
        sys.exit(f"--record: 0x{record:X} is not a SaveData size the tools know")
    offset = opts.get("--offset", 0)
    lay = Layout(record, offset != 0)
    for arg in args:
        data = Path(arg).read_bytes()
        if swap:
            data = swap32(data[:len(data) & ~3])
        chunk = data[offset:offset + lay.size]
        print(f"{arg} (+0x{offset:X}, {len(data)} bytes in the file; records of 0x{record:X} bytes)")
        if len(chunk) < lay.size:
            print(f"  only {len(chunk)} bytes there")
            continue
        for line in lay.describe(chunk):
            print("  " + line)
