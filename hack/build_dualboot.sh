#!/usr/bin/env bash
# Build dual-boot images (hack/DUALBOOT.md) from scratch. An image is made of three builds that have to
# agree with each other, and one of them, the Tooie hack, is built differently for every test image: this
# runs the steps in order, so that none is forgotten and the Tooie hack is not left as a test build.
#
# Usage:  bash hack/build_dualboot.sh [--skip-bk] [--keep-test-build] <variant> [<variant> ...]
#
#   normal          roms/bkbt2-normal.z64          the image to play: L + R + Start on Tooie's title screen
#   autotest        roms/bkbt2-autotest.z64        goes to Banjo-Kazooie by itself and stays (-DDUALBOOT_AUTOTEST):
#                                                  what tools/bk_antitamper_check.py and
#                                                  tools/dualboot_roundtrip_check.py --return-after / --chord-after take
#   roundtrip       roms/bkbt2-roundtrip.z64       ... and BK comes back by itself after 300 main-loop iterations
#   soak3           roms/bkbt2-soak3.z64           ... three times in a row (--trips 3)
#   retail-control  roms/bkbt2-retail-control.z64  the autotest Tooie hack with the unmodified retail BK and no
#                                                  payload: the control for the launcher's cold-boot residue
#   door            roms/bkbt2-door.z64            the hub door without a player, twice (-DDUALBOOT_DOOR_TEST):
#                                                  Tooie loads a file into Spiral Mountain, goes through the door
#                                                  300 frames later, BK takes its Lair exit 200 iterations after it is
#                                                  in the Lair (BK flag BKBT_FLAG_DOOR_TEST); what
#                                                  tools/dualboot_door_check.py takes
#   cross           roms/bkbt2-cross.z64           the doors between the games without a player (-DDUALBOOT_CROSS_TEST
#                                                  too): Tooie takes an exit_map entry into BK 300 frames after it is in
#                                                  its map, BK does nothing by itself (the check puts Banjo on a warp
#                                                  or a pad); what tools/dualboot_door_check.py --scenario cross-*
#                                                  takes
#   cheato          roms/bkbt2-cheato.z64          Cheato in King Jingaling's zombified throne room
#                                                  (-DDUALBOOT_DOOR_TEST and -DDUALBOOT_CHEATO_TEST): the check's
#                                                  first arrival is the throne
#                                                  room, every map's spawns are in a record, Banjo is moved next to
#                                                  Cheato 120 frames after he is spawned; what
#                                                  tools/dualboot_cheato_check.py takes
#
# Steps:
#   1. bash hack/build_bk_rom.sh        the fork's hack build, exported to hack/bk/build/bk-fork.*
#                                       (--skip-bk reuses the export that is there; saves the make run)
#   2. bash hack/build_bk.sh            the Banjo-Kazooie payload, hack/bk/build/bk-payload.bin
#   then for every variant named:
#   3. bash hack/build_bt.sh clean      the Tooie hack with the variant's flags; always clean, because its
#                                       Makefile does not track CFLAGS
#   4. tools/make_dualboot_image.py     the image; it refuses parts that do not belong together, and a
#                                       Tooie hack whose BKBTAUTO record is not the variant's (--expect-auto):
#                                       if the flags of step 3 did not reach the compiler, no image is written
#   and at the end:
#   5. bash hack/build_bt.sh clean      the normal Tooie hack again, so that hack/bt/n64/rom/Banjo-Tooie-Patched.z64
#                                       and the .patch are never left as a test build. Not needed, and not done,
#                                       when the last variant was `normal`; --keep-test-build leaves it out.
#   6. tools/make_patches.py            when `normal` was built (and no one-off flags): the apworld's patch files,
#                                       worlds/banjo_kazooie/assets and worlds/banjo_kazooie_tooie/assets, from
#                                       this build, so that the committed patch is always the image the checks ran on.
#                                       It runs in Archipelago's interpreter (bsdiff4): PATCH_PYTHON, by default
#                                       Archipelago/.venv/Scripts/python. Only in a tree that has the tool and the
#                                       worlds: the public image repository has neither, and skips it.
#
# For a one-off test image: DUALBOOT_EXTRA_CFLAGS adds flags to the variant's (say -DDUALBOOT_BK_FLAGS=1),
# and DUALBOOT_OUT then has to name the file to write, so that a roms/bkbt2-<variant>.z64 is always what its
# name says. Only one variant can be named then. If the extra flags change what the BKBTAUTO record says
# (-DDUALBOOT_AUTOTEST_TRIPS=5, say), DUALBOOT_EXPECT_AUTO has to give the new record as
# autotest,trips,return (1,5,300): step 4 compares the ROM with it.
# PYTHON names the interpreter for the tools (default: py -3.12); hack/build_bk_rom.sh has its own knobs.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
PY="${PYTHON:-py -3.12}"
TOOIE_ROM="$HERE/bt/n64/rom/Banjo-Tooie-Patched.z64"

fail() { echo "FAILED: $*"; exit 1; }
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 2; }

SKIP_BK=0
KEEP=0
VARIANTS=()
for arg in "$@"; do
  case "$arg" in
    --skip-bk) SKIP_BK=1 ;;
    --keep-test-build) KEEP=1 ;;
    normal|autotest|roundtrip|soak3|retail-control|door|cross|cheato) VARIANTS+=("$arg") ;;
    *) usage ;;
  esac
done
[ "${#VARIANTS[@]}" -gt 0 ] || usage
if [ -n "${DUALBOOT_EXTRA_CFLAGS:-}" ] || [ -n "${DUALBOOT_OUT:-}" ] || [ -n "${DUALBOOT_EXPECT_AUTO:-}" ]; then
  [ "${#VARIANTS[@]}" -eq 1 ] || fail "DUALBOOT_EXTRA_CFLAGS / DUALBOOT_OUT / DUALBOOT_EXPECT_AUTO are for one variant at a time"
  [ -n "${DUALBOOT_OUT:-}" ] || fail "DUALBOOT_EXTRA_CFLAGS needs DUALBOOT_OUT: a one-off build does not go to roms/bkbt2-${VARIANTS[0]}.z64"
  [ -z "${DUALBOOT_EXPECT_AUTO:-}" ] || [ -n "${DUALBOOT_EXTRA_CFLAGS:-}" ] || fail "DUALBOOT_EXPECT_AUTO is for a build with DUALBOOT_EXTRA_CFLAGS"
fi

# The flags behind each variant (hack/bt/n64/src/dualboot.h, "Test builds").
flags_for() {
  case "$1" in
    normal)         echo "" ;;
    autotest)       echo "-DDUALBOOT_AUTOTEST" ;;
    roundtrip)      echo "-DDUALBOOT_AUTOTEST -DDUALBOOT_AUTOTEST_RETURN=300" ;;
    soak3)          echo "-DDUALBOOT_AUTOTEST -DDUALBOOT_AUTOTEST_RETURN=300 -DDUALBOOT_AUTOTEST_TRIPS=3" ;;
    retail-control) echo "-DDUALBOOT_AUTOTEST" ;;
    door)           echo "-DDUALBOOT_DOOR_TEST=300 -DDUALBOOT_AUTOTEST_TRIPS=2 -DDUALBOOT_AUTOTEST_RETURN=200 -DDUALBOOT_BK_FLAGS=2" ;;
    cross)          echo "-DDUALBOOT_DOOR_TEST=300 -DDUALBOOT_CROSS_TEST=300 -DDUALBOOT_AUTOTEST_TRIPS=2" ;;
    cheato)         echo "-DDUALBOOT_DOOR_TEST=300 -DDUALBOOT_CHEATO_TEST=120" ;;
  esac
}
# What those flags make of the hack's BKBTAUTO record (hack/bt/n64/src/dualboot.c): autotest,trips,return.
# The image builder refuses a Tooie ROM that says anything else.
auto_for() {
  case "$1" in
    normal)         echo "0,1,0" ;;
    autotest)       echo "1,1,0" ;;
    roundtrip)      echo "1,1,300" ;;
    soak3)          echo "1,3,300" ;;
    retail-control) echo "1,1,0" ;;
    door)           echo "2,2,200" ;;
    cross)          echo "3,2,0" ;;
    cheato)         echo "2,1,0" ;;
  esac
}

if [ "$SKIP_BK" -eq 1 ]; then
  for f in bk-fork.z64 bk-fork.map bk-fork.json; do
    [ -f "$HERE/bk/build/$f" ] || fail "--skip-bk, but there is no hack/bk/build/$f: run without it once"
  done
  echo "== 1. Banjo-Kazooie: reusing hack/bk/build/bk-fork.*"
else
  echo "== 1. Banjo-Kazooie from the fork"
  bash "$HERE/build_bk_rom.sh"
fi
echo "== 2. Banjo-Kazooie payload"
bash "$HERE/build_bk.sh"

TOOIE_IS=""
# A step that fails after a test build of the Tooie hack must not leave that build in hack/bt/n64/rom either.
restore_on_failure() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$TOOIE_IS" = test ] && [ "$KEEP" -eq 0 ]; then
    echo "== a step failed: building the normal Tooie hack again, so that hack/bt/n64/rom is not left as a test build"
    EXTRA_CFLAGS="" bash "$HERE/build_bt.sh" clean \
      || echo "FAILED: the normal Tooie hack did not build either; hack/bt/n64/rom/Banjo-Tooie-Patched.z64 may be a test build"
  fi
  exit "$rc"
}
trap restore_on_failure EXIT
for variant in "${VARIANTS[@]}"; do
  FLAGS="$(flags_for "$variant") ${DUALBOOT_EXTRA_CFLAGS:-}"
  OUT="${DUALBOOT_OUT:-$ROOT/roms/bkbt2-$variant.z64}"
  echo "== 3. Tooie hack for '$variant': EXTRA_CFLAGS=$FLAGS"
  TOOIE_IS="test"       # from here until a normal build has finished
  EXTRA_CFLAGS="$FLAGS" bash "$HERE/build_bt.sh" clean
  [ -z "${FLAGS// /}" ] && TOOIE_IS="normal"
  echo "== 4. image '$variant' -> $OUT"
  EXTRA=(--expect-auto "${DUALBOOT_EXPECT_AUTO:-$(auto_for "$variant")}")
  [ "$variant" = retail-control ] && EXTRA+=(--retail-control)
  rm -f "$OUT"          # a refused image must not leave an older one under this name
  $PY -I -B "$(cygpath -m "$ROOT/tools/make_dualboot_image.py")" "$(cygpath -m "$TOOIE_ROM")" "${EXTRA[@]}" \
    -o "$(cygpath -m "$OUT")" || fail "tools/make_dualboot_image.py refused the '$variant' image"
done

if [ "$TOOIE_IS" = normal ]; then
  echo "== 5. the Tooie hack in hack/bt/n64/rom is the normal build"
elif [ "$KEEP" -eq 1 ]; then
  echo "== 5. --keep-test-build: hack/bt/n64/rom/Banjo-Tooie-Patched.z64 and the .patch are a TEST build (${VARIANTS[-1]})"
else
  echo "== 5. Tooie hack, normal build again"
  EXTRA_CFLAGS="" bash "$HERE/build_bt.sh" clean
fi
for variant in "${VARIANTS[@]}"; do
  if [ "$variant" = normal ] && [ -z "${DUALBOOT_EXTRA_CFLAGS:-}" ] && [ -z "${DUALBOOT_OUT:-}" ] \
     && [ -f "$ROOT/tools/make_patches.py" ] && [ -d "$ROOT/worlds" ]; then
    PATCH_PY="${PATCH_PYTHON:-$ROOT/Archipelago/.venv/Scripts/python}"
    echo "== 6. the apworld's patch files, from this build"
    "$PATCH_PY" -I -B "$(cygpath -m "$ROOT/tools/make_patches.py")" || fail "tools/make_patches.py refused this build"
  fi
done
echo "OK: ${VARIANTS[*]}"
