#!/usr/bin/env bash
# Build the Banjo-Tooie AP ROM hack from hack/bt on Windows (Git Bash) with the libdragon GCC 16 toolchain.
# See hack/BT-BUILD.md for the one-time setup of hack/bt/n64/tools and hack/bt/n64/rom.
#
# Usage:  bash hack/build_bt.sh            # build patched ROM + bsdiff
#         bash hack/build_bt.sh clean      # remove objects first
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
FORK="$HERE/bt"
N64="$FORK/n64"
T="$N64/tools/mips64/opt/libdragon"
VENV="$HERE/../Archipelago/.venv/Scripts"

[ -x "$T/bin/mips64-elf-gcc.exe" ] || { echo "missing toolchain at $T (see hack/BT-BUILD.md)"; exit 1; }
[ -x "$N64/tools/armips/armips.exe" ] || { echo "missing armips at $N64/tools/armips"; exit 1; }
[ -f "$N64/rom/Banjo-Tooie.z64" ] || { echo "missing $N64/rom/Banjo-Tooie.z64 (US, big-endian)"; exit 1; }

export PATH="$T/bin:$N64/tools/armips:$VENV:$PATH"
python -c "import bsdiff4" 2>/dev/null || { echo "python on PATH lacks bsdiff4 (pip install bsdiff4)"; exit 1; }

# The Makefile hardcodes GCC 14.2.0 soft-float multilib paths that GCC 16 does not have. Ask the compiler
# where its libraries are instead. The soft-float ABI mismatch this would cause is covered by
# n64/src/compat/softfloat (compiler-rt) and n64/src/compat/libc_min.c being part of the bundle.
# -mabi=32: the game is o32. The toolchain's default o64 ABI lets GCC 16 spill incoming arguments into a
# 32-byte home area in the *caller's* frame; o32 callers (the game) only reserve 16 bytes, so hook
# wrappers with 3-4 arguments corrupted the game's stack and the game never rendered a frame.
ABI="-mabi=32"
LIBGCC_DIR=$(dirname "$(mips64-elf-gcc $ABI -msoft-float -march=vr4300 -print-libgcc-file-name)")
LIBC_DIR=$(dirname "$(mips64-elf-gcc $ABI -msoft-float -march=vr4300 -print-file-name=libc.a)")

# GCC 15+ defaults to C23, where `void f();` means `void f(void)` and conflicts with the hack's definitions.
CFLAGS="-std=gnu17 $ABI -O1 -G0 -fno-reorder-blocks -march=vr4300 -mtune=vr4300 -mno-gpopt -mdivide-breaks -mexplicit-relocs -msoft-float -I ../shared/include -I src -D NDEBUG ${EXTRA_CFLAGS:-}"
LDFLAGS="-L . -L $LIBC_DIR -L $LIBGCC_DIR"
# No host C compiler on this machine, so the Everdrive header tool is the Python port in tools/.
ED64="python $(cygpath -m "$HERE/../tools/ed64romconfig.py")"

cd "$N64"
if [ "${1:-}" = "clean" ]; then make clean CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS" ED64ROMCONFIG="$ED64"; fi
make -j4 CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS" ED64ROMCONFIG="$ED64"
make patch CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS" ED64ROMCONFIG="$ED64"
ls -la rom/Banjo-Tooie-Patched.z64 rom/Banjo-Tooie.patch
