#!/usr/bin/env bash
# Build Banjo-Kazooie from our decomp fork (hack/bk/decomp, branch bkbt) inside the WSL1 distro "bkdecomp".
# The fork's own notes are in hack/bk/decomp/BKBT.md; what the spike found is in hack/bk/README.md.
#
# Usage:  bash hack/build_bk_rom.sh              # the hack: make BKBT=1
#         bash hack/build_bk_rom.sh matching     # the matching build: must come out as the retail ROM
# Going from one to the other recompiles everything (about two minutes).
# BK_DECOMP_TREE names another checkout of the fork, BK_WSL_DISTRO another distro, JOBS the -j value,
# PYTHON the interpreter for the export step (default: py -3.12).
#
# This script judges the result itself instead of taking make's word: make's own exit code, a ROM written
# by this run, 16 MiB, a build directory stamped with the switches asked for, and the sha1 (retail's for
# the matching build, anything else for the hack). It does not test the ROM; the tools for that are in
# tools/ and, for now, with the spike's files (hack/bk/README.md, "Where the spike's files are").
#
# A hack build is then exported to hack/bk/build/ (git-ignored) for the dual-boot image:
#   bk-fork.z64   the ROM, with its header declaring SRAM 256k (below)
#   bk-fork.map   its linker map
#   bk-fork.json  what tools/bk_fork_info.py takes from the two: the ROM's sha1, the dual-boot contract
#                 number and the addresses the check tools need
# tools/make_dualboot_image.py picks them up from there. The matching build exports nothing and leaves an
# earlier export alone.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
TREE="${BK_DECOMP_TREE:-$HERE/bk/decomp}"
DISTRO="${BK_WSL_DISTRO:-bkdecomp}"
RETAIL_SHA1=1fe1632098865f639e22c11b9a81ee8f29c75d7a      # Banjo-Kazooie (USA) v1.0, .z64
RETAIL_ROM="$HERE/../roms/Banjo-Kazooie (USA).z64"
EXPORT="$HERE/bk/build"                                    # git-ignored; the payload's build directory too
PY="${PYTHON:-py -3.12}"                                   # for tools/bk_fork_info.py (standard library only)

fail() { echo "FAILED: $*"; exit 1; }
sha1() { sha1sum "$1" | cut -c1-40; }

case "${1:-hack}" in
  hack)     MODE=hack;     MAKE_ARGS="BKBT=1"; STAMP=flags.BKBT1.AT0.AP0.stamp ;;
  matching) MODE=matching; MAKE_ARGS="BKBT=0"; STAMP=flags.BKBT0.AT1.AP1.stamp ;;
  *) echo "usage: bash hack/build_bk_rom.sh [hack|matching]"; exit 2 ;;
esac

[ -f "$TREE/Makefile" ] || fail "no decomp tree at $TREE (git submodule update --init hack/bk/decomp, then git -C hack/bk/decomp submodule update --init --recursive)"
TREE=$(cd "$TREE" && pwd)
case "$TREE" in
  /[a-zA-Z]/*) MNT="/mnt/$(echo "$TREE" | sed -E 's|^/([a-zA-Z])/|\L\1/|')" ;;
  *) fail "cannot turn $TREE into a /mnt/<drive>/ path for WSL" ;;
esac
DISTROS=$(wsl -l -q 2>/dev/null | tr -d '\0\r' || true)
echo "$DISTROS" | grep -Fqx "$DISTRO" || fail "no WSL distro named '$DISTRO' (docs/DEVELOPMENT.md, ROM hack build)"
# (inside one quoted string: Git Bash would rewrite a bare /mnt/... argument into a Windows path)
wsl -d "$DISTRO" -u root -- bash -lc "test -f '$MNT/Makefile'" || fail "WSL does not see the tree at $MNT"

# The decomp takes the game's assets from the retail ROM. It is git-ignored in the fork (*.z64).
BASEROM="$TREE/baserom.us.v10.z64"
if [ ! -f "$BASEROM" ]; then
  [ -f "$RETAIL_ROM" ] || fail "no $BASEROM, and no $RETAIL_ROM to copy it from"
  [ "$(sha1 "$RETAIL_ROM")" = "$RETAIL_SHA1" ] || fail "$RETAIL_ROM is not the US v1.0 ROM: sha1 $(sha1 "$RETAIL_ROM"), expected $RETAIL_SHA1"
  cp "$RETAIL_ROM" "$BASEROM"
fi
[ "$(sha1 "$BASEROM")" = "$RETAIL_SHA1" ] || fail "$BASEROM is not the US v1.0 ROM: sha1 $(sha1 "$BASEROM"), expected $RETAIL_SHA1"

BUILD="$TREE/build/us.v10"
ROM="$BUILD/banjo.us.v10.z64"
# A failed link leaves the previous build's files in place: never mistake the old ROM for this run's.
rm -f "$ROM" || fail "cannot remove the previous ROM $ROM (is it open in an emulator?)"
reject() { rm -f "$ROM"; fail "$@"; }
# The same goes for what a hack build exports (below): a hack build that fails leaves no older set behind.
if [ "$MODE" = hack ]; then
  mkdir -p "$EXPORT"
  rm -f "$EXPORT"/bk-fork.z64 "$EXPORT"/bk-fork.map "$EXPORT"/bk-fork.json || fail "cannot remove the previous export in $EXPORT"
fi

START=$(date +%s)
set +e
wsl -d "$DISTRO" -u root -- bash -lc "cd '$MNT' && . \"\$HOME/.cargo/env\" && make -j${JOBS:-4} $MAKE_ARGS"
RC=$?
set -e
[ "$RC" -eq 0 ] || reject "make $MAKE_ARGS exited with $RC"
[ -f "$ROM" ] || fail "make exited 0 but wrote no ROM"
SIZE=$(stat -c %s "$ROM")
[ "$SIZE" -eq 16777216 ] || reject "the ROM is $SIZE bytes, not 16777216"
[ -f "$BUILD/$STAMP" ] || reject "the build directory is not stamped $STAMP, so this is not a $MODE build"
SHA1=$(sha1 "$ROM")
if [ "$MODE" = matching ]; then
  [ "$SHA1" = "$RETAIL_SHA1" ] || reject "the matching build differs from retail (sha1 $SHA1)"
else
  [ "$SHA1" != "$RETAIL_SHA1" ] || reject "the hack build equals retail: BKBT=1 did not take effect"
fi
echo "OK ($MODE, $(( $(date +%s) - START )) s): $ROM  sha1 $SHA1"

# The dual-boot tools take the hack ROM together with what its map says about it. Export the three as one
# set, so that a later build in the tree (the matching one, say) cannot pull them apart:
# tools/make_dualboot_image.py refuses a ROM whose sha1 is not the one in the JSON.
#
# The exported ROM's header declares the cartridge's save device as SRAM 256k (32 KiB), the device the
# hack saves to, also when it runs by itself: tools/ed64romconfig.py writes 'ED' at 0x3C..0x3D and the
# save type into 0x3F (the EverDrive's advanced homebrew header, the same tool and setting as the Tooie
# hack's Makefile). Emulators and flashcarts that read that header take the save type from it: ares gives
# the dual-boot image, whose header is the Tooie hack's, a 32 KiB .ram, and mupen64plus logs "Save type: 2"
# with the header and "Save type: 0" (EEPROM 4k) without it, though its SRAM answers either way, so a
# missing header does not show on mupen64plus. The header is outside the
# range the boot code's checksum covers (0x1000..0x101000), so nothing else changes. Only the export is
# patched: the build tree keeps make's own output, and the matching build is never touched. So is the header's
# name, "Banjo-Kazooie AP" since 2026-11-12 (tools/rom_name.py --bk; retail's is "Banjo-Kazooie"), which emulators
# show and Project64 names its save after; the patch's description carries it to the clients (tools/make_patches.py).
if [ "$MODE" = hack ]; then
  cp "$ROM" "$EXPORT/bk-fork.z64"
  $PY -I -B "$(cygpath -m "$HERE/../tools/ed64romconfig.py")" -w sram256k "$(cygpath -m "$EXPORT/bk-fork.z64")"     || { rm -f "$EXPORT"/bk-fork.z64 "$EXPORT"/bk-fork.map "$EXPORT"/bk-fork.json "$EXPORT"/bk-fork.uncompressed.z64; fail "tools/ed64romconfig.py could not write the save type; nothing exported"; }
  $PY -I -B "$(cygpath -m "$HERE/../tools/rom_name.py")" "$(cygpath -m "$EXPORT/bk-fork.z64")" --bk     || { rm -f "$EXPORT"/bk-fork.z64 "$EXPORT"/bk-fork.map "$EXPORT"/bk-fork.json "$EXPORT"/bk-fork.uncompressed.z64; fail "tools/rom_name.py could not write the header's name; nothing exported"; }
  cp "$BUILD/banjo.us.v10.map" "$EXPORT/bk-fork.map"
  # and the build before compression, from which tools/make_patches.py makes the apworld's patch: a diff between
  # uncompressed ROMs holds only the hack's changes, where one between compressed ROMs would carry BK's whole code
  cp "$BUILD/banjo.us.v10.uncompressed.z64" "$EXPORT/bk-fork.uncompressed.z64"
  $PY -I -B "$(cygpath -m "$HERE/../tools/bk_fork_info.py")" "$(cygpath -m "$EXPORT/bk-fork.z64")" \
    "$(cygpath -m "$EXPORT/bk-fork.map")" -o "$(cygpath -m "$EXPORT/bk-fork.json")" \
    || { rm -f "$EXPORT"/bk-fork.z64 "$EXPORT"/bk-fork.map "$EXPORT"/bk-fork.json "$EXPORT"/bk-fork.uncompressed.z64; fail "tools/bk_fork_info.py refused the build; nothing exported"; }
  echo "exported: $EXPORT/bk-fork.z64 (header: SRAM 256k, \"Banjo-Kazooie AP\", sha1 $(sha1 "$EXPORT/bk-fork.z64")), bk-fork.map, bk-fork.json, bk-fork.uncompressed.z64"
fi
