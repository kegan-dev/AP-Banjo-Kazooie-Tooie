; Banjo-Kazooie payload (BKBT). Loaded into Expansion Pak RAM by the Tooie hack's dual-boot launcher
; (hack/bt/n64/asm/dualboot.asm) just before it jumps to Banjo-Kazooie. Banjo-Kazooie itself uses 4 MiB,
; so nothing of it reaches up here.
;
; It holds one thing: the way back to Tooie (return.asm). When to go back is Banjo-Kazooie's decision,
; made in the fork's C (bkbt_frame, hack/bk/decomp/src/core1/code_0.c): the launcher tells BK through
; the handoff block where the header below is, and BK calls the entry it names. The payload contains no
; Banjo-Kazooie address, so it does not depend on the BK build: one payload serves every BK of the same
; dual-boot contract.
;
; Build:  bash hack/build_bk.sh   ->  hack/bk/build/bk-payload.bin
; armips matches `equ` names without regard to case: no label may be spelled like one of them.

.n64

; Where the payload runs: free while either game runs, above the megabyte the Tooie boot stub loads at
; 0x80400000 and below the launcher stack (0x805FFC00) and the handoff block (0x805FFF00). Only the
; header below knows this address. The launcher loads the payload where the header says and passes
; that on to Banjo-Kazooie (handoff + 0x24); tools/make_dualboot_image.py checks the range.
BK_PAYLOAD_RAM equ 0x80500000
; Dual-boot contract number, the one the launcher and the fork carry (DUALBOOT_CONTRACT in
; hack/bt/n64/src/dualboot.h and asm/dualboot.asm, bkbt_contract in the fork). Banjo-Kazooie calls the
; entry only if it equals its own, and the image builder compares all three.
BK_PAYLOAD_CONTRACT equ 5

; for the shared quiesce (hack/bt/n64/asm/dualboot_quiesce.asm)
DUALBOOT_TRACE equ 1
QUIESCE_POKE_CART equ 0x10000000  ; any 8 readable cart bytes: the image's header

.create outfile, BK_PAYLOAD_RAM

; Header. The launcher reads +0x00, +0x08 and +0x0C from the cart; Banjo-Kazooie's bkbt_init reads
; +0x00, +0x04 and +0x10 from RAM. A field never changes its meaning under the same magic: a header
; that has to differ gets a new magic. ('BKPL' was the payload whose second word BK called on every
; main-loop iteration; the launcher does not load one any more.)
bk_payload_header:
.ascii "BKP2"                           ; +0x00 magic
.word bk_launch_bt                      ; +0x04 entry: goes back to Tooie, never returns to its caller
.word BK_PAYLOAD_RAM                    ; +0x08 load address
.word bk_payload_end - BK_PAYLOAD_RAM   ; +0x0C length in bytes
.word BK_PAYLOAD_CONTRACT               ; +0x10 contract number

.include "return.asm"
.include quiescefile

.align 0x10
bk_payload_end:
.close
