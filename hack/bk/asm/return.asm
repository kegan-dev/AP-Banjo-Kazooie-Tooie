; bk_launch_bt: warm-start Tooie from inside Banjo-Kazooie. Never returns. It is the entry the payload
; header names: Banjo-Kazooie calls it from its main thread, interrupts on, through a C function pointer
; (bkbt_frame in the fork). It expects nothing in any register and assumes nothing about the map, the
; game mode or what BK's threads are doing; it names no Banjo-Kazooie address.
;
; It does not imitate what Tooie's IPL3 leaves behind. It stands in for the PIF and runs the real
; CIC-6105 IPL3 again, the way a soft reset does on an emulator and a flashcart menu does on a console
; (mupen64plus src/device/pif/bootrom_hle.c; N64FlashcartMenu src/boot/boot.c and reboot.S). The IPL3
; then verifies the header checksum, loads Tooie's first MiB, leaves its own residue in low RDRAM,
; sets osCicId and jumps to Tooie's entry, whose boot stub reloads the AP payload.
;
; What Tooie's IPL3 takes from whoever starts it (disassembled from the US ROM, a40000xx = ROM 0x00xx):
;   - IMEM[0..7] = eight instruction words of the PIF's IPL2. a4000040..a4000060 XORs them with its own
;     words at 0x84 into the RSP program it runs later; the eighth ends the loop.
;   - sp = 0xA4001FF0 and t3 = 0xA4000040, the pointers that loop walks.
;   - ra negative (a4000074: bltz ra), else it runs into junk.
;   - RI_SELECT != 0 selects the path that skips RDRAM initialisation (a40000cc); it is non-zero from
;     the cold boot on.
;   - s3 (osRomType), s4 (osTvType), s5 (osResetType), s7 (osVersion) are only stored (a4000740..a4000750),
;     and s6 is the checksum seed (a400060c).
;   - RDRAM 0x3F0 holds the RDRAM size from the cold boot; it is copied to osMemSize on every boot
;     (a400076c..a4000774).

bk_launch_bt:
  ; interrupts off
  mfc0  t0, $12
  lui   t1, 0xFFFF
  ori   t1, t1, 0xFFFE
  and   t0, t0, t1
  mtc0  t0, $12
  nop
  nop
  ; private stack at the top of the Expansion Pak window, as in the Tooie launcher (nothing here uses it)
  lui   sp, 0x8060
  addiu sp, sp, -0x400
  jal   dualboot_quiesce
  nop
  lui   t9, 0xA060
  ori   t8, zero, 0x11
  sw    t8, -0xF0(t9)                   ; trace stage -> 0xA05FFF10
  ; In a level a controller, rumble or EEPROM transfer may still be on the SI bus. Bounded wait.
  lui   t1, 0xA480
  lui   t5, 0x0020
@@si_wait:
  lw    t4, 0x18(t1)                    ; SI_STATUS
  andi  t4, t4, 0x0003                  ; DMA busy | IO busy
  beqz  t4, @@si_done
  addiu t5, t5, -1
  bnez  t5, @@si_wait
  nop
@@si_done:
  ; the console's own values, as the cold boot's IPL3 stored them; neither launcher nor BK writes them
  lui   t1, 0xA000
  lw    s4, 0x0300(t1)                  ; osTvType
  lw    s3, 0x0304(t1)                  ; osRomType
  lw    s7, 0x0314(t1)                  ; osVersion
  ; Handoff for the Tooie hack's dualboot_boot_check (hack/bt/n64/src/dualboot.h). Uncached, and the
  ; caches are written back right after: that is why the Banjo-Kazooie side may touch this block through
  ; KSEG1 only (the fork's include/bkbt.h). A line of it left dirty in BK's data cache would land on top
  ; of these words.
  lui   t8, 0x424B
  ori   t8, t8, 0x4254                  ; 'BKBT'
  sw    t8, -0x100(t9)                  ; +0x00 magic
  ori   t8, zero, 1
  sw    t8, -0xFC(t9)                   ; +0x04 game = Tooie
  lw    t8, -0xF4(t9)
  addiu t8, t8, 1
  sw    t8, -0xF4(t9)                   ; +0x0C Tooie launches
  sw    zero, -0xD8(t9)                 ; +0x28 autotest countdown, spent
  ; Write BK's dirty cache lines back before RAM is cleared, so none lands on it afterwards.
  ori   t8, zero, 0x12
  sw    t8, -0xF0(t9)
  jal   bk_flush_caches
  nop
  ; Zero BK's 4 MiB. Tooie then starts on the RAM an emulator cold boot gives it, and the picture goes
  ; black instead of showing BK's last frame through Tooie's video mode. 0x3F0 stays (see above); the
  ; IPL3 rewrites 0x004..0x338 and the OS globals itself.
  ; Through KSEG0, not KSEG1: mupen64plus's dynamic recompiler only drops a compiled block when a store
  ; goes to the address the block was compiled at, and with BK's blocks left standing Tooie's boot never
  ; reaches the hack (seen with the uncached clear and with no clear; the interpreter does not care).
  ori   t8, zero, 0x13
  sw    t8, -0xF0(t9)
  lui   t5, 0x8000
  ori   t6, t5, 0x03F0
@@zero_low:
  sw    zero, 0(t5)
  addiu t5, t5, 4
  bne   t5, t6, @@zero_low
  nop
  addiu t5, t5, 4                       ; skip 0x3F0
  lui   t6, 0x8040
@@zero_ram:
  sw    zero, 0(t5)
  addiu t5, t5, 4
  bne   t5, t6, @@zero_ram
  nop
  ; The cold boot's RDRAM sizing left 0xFFFFFFFF in the first two words of each 2 MiB module; put back
  ; the pair that lies in the cleared range (the Tooie launcher does the same for BK).
  lui   t1, 0x8020
  addiu t3, zero, -1
  sw    t3, 0(t1)
  sw    t3, 4(t1)
  ; Put the zeros in RAM. On this path the IPL3 would write the data cache back as well (a40004c0:
  ; cache 1) rather than drop it, but nothing here leans on that. No cached store may follow.
  jal   bk_flush_caches
  nop
  ; What the PIF's IPL2 does to the hardware before it enters the IPL3 (bootrom_hle.c, boot.c)
  ori   t8, zero, 0x14
  sw    t8, -0xF0(t9)
  lui   t1, 0xA404
  ori   t2, zero, 0x000A
  sw    t2, 0x10(t1)                    ; SP_STATUS: set halt, clear interrupt
  lui   t0, 0xA460
  ori   t2, zero, 0x0003
  sw    t2, 0x10(t0)                    ; PI_STATUS: reset, clear interrupt
  lui   t1, 0xA440
  ori   t2, zero, 0x03FF
  sw    t2, 0x0C(t1)                    ; VI_V_INTR
  sw    zero, 0x24(t1)                  ; VI_H_START
  sw    zero, 0x10(t1)                  ; VI_CURRENT: acknowledges the VI interrupt
  ; Not copied from them: AI_DRAM_ADDR = 0 and AI_LEN = 0. An AI_LEN write is a call into the audio
  ; plugin under Project64, and 3.0.1's never came back from this one (emulation thread asleep, launcher
  ; trace stuck at this stage). The quiesce has already cleared AI_CONTROL and the IPL3 acknowledges the
  ; AI interrupt itself.
  ; SP memory as an emulator has it at power-on, all zero, before the IPL3 and the IPL2 words go in:
  ; mupen64plus's HLE RSP tells the IPL3's own RSP program by a sum over IMEM (rsp-hle
  ; non_task_dispatching), and the quiesce has left IMEM full of `break`.
  lui   t2, 0xA400
  ori   t3, t2, 0x2000
@@zero_sp:
  sw    zero, 0(t2)
  addiu t2, t2, 4
  bne   t2, t3, @@zero_sp
  nop
  ; IPL3: cart 0x40..0x1000 -> DMEM 0x40..0x1000. The PI is idle, so the cart can be read directly.
  lui   t1, 0xB000
  lui   t2, 0xA400
  ori   t3, zero, 0x0040
  ori   t4, zero, 0x1000
@@ipl3:
  addu  t5, t1, t3
  lw    t6, 0(t5)
  addu  t5, t2, t3
  sw    t6, 0(t5)
  addiu t3, t3, 4
  bne   t3, t4, @@ipl3
  nop
  ; the IPL2 words at IMEM[0..7]
  la    t1, bk_ipl2_words
  ori   t2, t2, 0x1000
  ori   t3, zero, 8
@@ipl2:
  lw    t6, 0(t1)
  sw    t6, 0(t2)
  addiu t1, t1, 4
  addiu t2, t2, 4
  addiu t3, t3, -1
  bnez  t3, @@ipl2
  nop
  ori   t8, zero, 0x15
  sw    t8, -0xF0(t9)
  ; CPU state at the IPL3's entry
  lui   t0, 0x3400
  mtc0  t0, $12                         ; Status = CU1 | CU0 | FR, interrupts off
  or    s5, zero, zero                  ; osResetType = cold: Tooie starts as from power-on
  ori   s6, zero, 0x0091                ; CIC-6105 checksum seed
  lui   t3, 0xA400
  ori   t3, t3, 0x0040
  lui   sp, 0xA400
  ori   sp, sp, 0x1FF0
  lui   ra, 0xA400
  ori   t0, zero, 1
  bne   s4, t0, @@not_ntsc
  ori   ra, ra, 0x1554                  ; PAL and MPAL consoles (reboot.S)
  xori  ra, ra, 0x0004                  ; NTSC: 0xA4001550
@@not_ntsc:
  jr    t3
  nop

; Write back and invalidate both caches by index (16 KiB of index space covers either). Leaf, uses t1, t2.
bk_flush_caches:
  lui   t1, 0x8000
  ori   t2, zero, 0x400
@@flush:
  cache 0x00, 0(t1)                     ; Index_Invalidate_I
  cache 0x01, 0(t1)                     ; Index_Writeback_Invalidate_D
  addiu t1, t1, 0x10
  addiu t2, t2, -1
  bnez  t2, @@flush
  nop
  jr    ra
  nop

bk_ipl2_words:
.word 0x3C0DBFC0, 0x8DA807FC, 0x25AD07C0, 0x31080080, 0x5500FFFC, 0x3C0DBFC0, 0x8DA80024, 0x3C0BB000
