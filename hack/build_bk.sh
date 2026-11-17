#!/usr/bin/env bash
# Build the Banjo-Kazooie payload (hack/bk/asm: the return to Tooie) with the armips that comes with the
# Tooie hack's tools. The payload includes the shared quiesce from hack/bt/n64/asm, so hack/bt must be
# checked out. It contains no Banjo-Kazooie address, so it does not have to be rebuilt for a new BK build.
#
# Usage:  bash hack/build_bk.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ARMIPS="$HERE/bt/n64/tools/armips/armips.exe"
QUIESCE="$HERE/bt/n64/asm/dualboot_quiesce.asm"
OUT="$HERE/bk/build"

[ -x "$ARMIPS" ] || { echo "missing armips at $ARMIPS (see hack/BT-BUILD.md)"; exit 1; }
[ -f "$QUIESCE" ] || { echo "missing $QUIESCE (git submodule update --init hack/bt)"; exit 1; }

mkdir -p "$OUT"
"$ARMIPS" payload.asm -root "$(cygpath -m "$HERE/bk/asm")" -sym2 "$(cygpath -m "$OUT/bk-payload.sym")" \
  -strequ outfile "$(cygpath -m "$OUT/bk-payload.bin")" -strequ quiescefile "$(cygpath -m "$QUIESCE")"
ls -la "$OUT/bk-payload.bin"
