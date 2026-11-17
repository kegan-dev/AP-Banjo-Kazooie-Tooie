"""Python port of libdragon's tools/ed64romconfig.c (GPL-2.0-or-later, Christopher Bonhage, 2021).

Sets the Advanced Homebrew ROM Header fields that the EverDrive-64 reads to pick a save type:
    0x3C..0x3D  cart id      'ED'
    0x3F        config      save type | rtc | region-free
    0x34..0x37  controller types (default: plain N64 controller in all four ports)
See https://n64brew.dev/wiki/ROM_Header#Advanced_Homebrew_ROM_Header

Only the save-type subset of the original's CLI is implemented, which is all the Tooie hack's
Makefile uses:  ed64romconfig -w sram256k <rom>
"""

import argparse
import sys
from pathlib import Path

SAVE_TYPES = {
    "none": 0x00,
    "eeprom4k": 0x10,
    "eeprom16k": 0x20,
    "sram256k": 0x30,
    "sram768k": 0x40,
    "flashram": 0x50,
    "sram1m": 0x60,
}
CART_ID_OFFSET = 0x3C
VERSION_OFFSET = 0x3F
CONTROLLER_OFFSET = 0x34
CONTROLLERTYPE_N64 = 0x00


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-w", "--savetype", choices=sorted(SAVE_TYPES), default="none")
    ap.add_argument("-c", "--rtc", action="store_true")
    ap.add_argument("-r", "--regionfree", action="store_true")
    ap.add_argument("rom", type=Path)
    args = ap.parse_args(argv)

    if args.rtc and args.savetype in ("eeprom4k", "eeprom16k"):
        print("WARNING: The combination of EEPROM + RTC does not work on EverDrive!", file=sys.stderr)

    config = SAVE_TYPES[args.savetype] | (1 if args.rtc else 0) | (2 if args.regionfree else 0)
    with open(args.rom, "r+b") as f:
        f.seek(CART_ID_OFFSET)
        f.write(b"ED")
        f.seek(VERSION_OFFSET)
        f.write(bytes([config]))
        f.seek(CONTROLLER_OFFSET)
        f.write(bytes([CONTROLLERTYPE_N64] * 4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
