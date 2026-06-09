#!/usr/bin/env python3
"""
Build firmware_26_nop-and-ring-log.bin:

  1. Keep the NOP at 0x0800BFAA (bl post_event_type0 → nop nop)
     — prevents IR-power from triggering standby (HardFault-safe).

  2. Install a notify() trampoline that *passively* logs every call
     into a ring buffer in unused top-of-SRAM. GDB dumps the ring
     non-intrusively to see what notify() actually receives.

Layout:

  Ring buffer at 0x20003E00 (top-of-SRAM, well above MSP=0x20002C18):
    +0x000  MAGIC   = 0xC1BAFEED
    +0x004  WRITE_IDX (byte offset 0..480, wraps)
    +0x008  COUNT   (monotonic call counter)
    +0x00C  -
    +0x010  60 entries × 8 bytes = 480 bytes
              entry: cmd_id (u8) + 3 pad + value (u32)

  Trampoline at 0x0801E8A0 (after fw_23's Shim 3):
    Replace notify()@0x0800BBDC's first 4 bytes (push + ldr) with
    a b.w to the trampoline. The trampoline:
      - stores (r0=channel, r1=value) into ring
      - emulates the displaced push + ldr-of-g_notify_struct
      - b.w back into notify() at 0x0800BBE0

  We initialize MAGIC at boot time by detecting a fresh start.
  Easier: just write MAGIC on every notify call (cheap, idempotent).
"""

import struct, sys

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_26_nop-and-ring-log.bin"

NOTIFY      = 0x0800BBDC
NOTIFY_NEXT = 0x0800BBE0          # instruction after the displaced bytes
G_NOTIFY    = 0x200023BC          # ptr loaded by displaced ldr (per symbols.md)

TRAMP_ADDR  = 0x0801E8A0          # in free flash after Shim 3 (~22 bytes at 0x0801E880)
RING_BASE   = 0x20003E00
RING_ENTRIES_OFF = 0x10
RING_SIZE_BYTES  = 480
ENTRY_BYTES = 8


def enc_bw(src_addr, tgt_addr):
    """Encode a 4-byte b.w branch from src_addr to tgt_addr (Thumb-2)."""
    offset = tgt_addr - (src_addr + 4)
    assert -(1 << 24) <= offset < (1 << 24), f"offset {offset:x} out of range"
    # Encode 25-bit signed offset (always even)
    o = offset >> 1
    if o < 0:
        o += (1 << 24)
        S = 1
    else:
        S = 0
    imm11 = o & 0x7FF
    imm10 = (o >> 11) & 0x3FF
    I2 = (o >> 21) & 1
    I1 = (o >> 22) & 1
    # I1 = NOT(J1 XOR S), I2 = NOT(J2 XOR S)  =>  J1 = NOT(I1) XOR S, J2 = NOT(I2) XOR S
    J1 = (1 ^ I1) ^ S
    J2 = (1 ^ I2) ^ S
    hw1 = (0b11110 << 11) | (S << 10) | imm10
    # For B.W (no link): bits 15-14 = 10, bit 12 = 1
    hw2 = (0b10 << 14) | (J1 << 13) | (1 << 12) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def le16(v): return struct.pack("<H", v & 0xFFFF)


# ------------------------------------------------------------------
# Trampoline: lay out Thumb-1 (Cortex-M0) instructions and a literal pool.
# All registers used: r0..r4 (r0/r1 are channel/value, restored before resume).
# ------------------------------------------------------------------
#
# Layout in flash (offsets are relative to TRAMP_ADDR):
#
#   off  bytes  asm                                          notes
#   00   4a07   ldr r2, [pc, #28]                            ; r2 = &ring_write_idx
#   02   6813   ldr r3, [r2, #0]                             ; r3 = idx
#   04   2cf0?  cmp r3, #240                                 ; not enough imm range; instead:
#          (use a literal compare via a tmp register)
#
# Cortex-M0 cmp r3, #imm only supports imm8 (0..255). 480 > 255, so use the
# trick: load 240 in a reg, lsl by 1 to get 480, then cmp r3 against that.
#
# Re-plan (with byte offsets) — note all branches/literals computed below:
#
#  +0x00  push {r0,r1,r2,r3,r4,lr}        ; b5 1f
#  +0x02  ldr  r2, [pc, lit_widx]         ; r2 = &write_idx
#  +0x04  ldr  r3, [r2]                    ; r3 = idx
#  +0x06  movs r4, #240
#  +0x08  lsls r4, r4, #1                  ; r4 = 480
#  +0x0A  cmp  r3, r4
#  +0x0C  blt  +2                          ; if idx < 480, skip
#  +0x0E  movs r3, #0                      ; else idx = 0
#  +0x10  ldr  r4, [pc, lit_base]          ; r4 = ring_entries_base
#  +0x12  add  r4, r3                      ; r4 = entry_addr
#  +0x14  ldr  r0, [sp, #0]                ; r0 = saved channel
#  +0x16  ldr  r1, [sp, #4]                ; r1 = saved value
#  +0x18  strb r0, [r4, #0]                ; entry.cmd = channel
#  +0x1A  str  r1, [r4, #4]                ; entry.value = value
#  +0x1C  adds r3, #8                      ; idx += 8
#  +0x1E  str  r3, [r2]                    ; write_idx = idx
#  +0x20  ldr  r2, [pc, lit_count]         ; r2 = &count
#  +0x22  ldr  r3, [r2]
#  +0x24  adds r3, #1
#  +0x26  str  r3, [r2]
#  +0x28  ldr  r2, [pc, lit_magic_addr]    ; (write magic on each call - idempotent)
#  +0x2A  ldr  r3, [pc, lit_magic_val]
#  +0x2C  str  r3, [r2]
#  +0x2E  pop  {r0,r1,r2,r3,r4,lr}         ; bd 1f (note: LR not popped to PC)
#  +0x30  push {r3,r4,r5,r6,r7,lr}         ; b5 f8  ← displaced original push
#  +0x32  ldr  r4, [pc, lit_gn]            ; r4 = g_notify_struct  ← displaced ldr
#  +0x34  b.w  NOTIFY_NEXT                 ; jump into notify()+4
#  +0x38  (pad to align literal pool to 4 bytes)
#  +0x3C  literals: widx, base, count, magic_addr, magic_val, gn
# ------------------------------------------------------------------

def le_word(v): return struct.pack("<I", v & 0xFFFFFFFF)

LIT_OFF = 0x3C        # literal pool starts here (4-byte aligned)
LITS = [
    ("widx",        RING_BASE + 0x04),
    ("base",        RING_BASE + RING_ENTRIES_OFF),
    ("count",       RING_BASE + 0x08),
    ("magic_addr",  RING_BASE + 0x00),
    ("magic_val",   0xC1BAFEED),
    ("gn",          G_NOTIFY),
]
LIT = {n: (LIT_OFF + 4*i) for i, (n, _) in enumerate(LITS)}


def pcrel_ldr_imm(insn_off, lit_off):
    """Compute imm8 for ldr Rd, [pc, #imm] where PC = (insn_addr+4) & ~3."""
    pc = ((insn_off + 4) // 4) * 4
    delta = lit_off - pc
    assert 0 <= delta and delta % 4 == 0 and delta < 1024, f"ldr lit out of range: {delta:#x}"
    return delta >> 2


# Build the trampoline as halfwords (16-bit Thumb).
# Each instruction is a comment + bytes.
T = bytearray()

def emit(asm, hw):
    T.extend(le16(hw))

# +0x00: push {r0,r1,r2,r3,r4,lr}        encoding: B5 1F  (PUSH form: 1011 010M reglist)
emit("push {r0,r1,r2,r3,r4,lr}", 0xB51F)
# +0x02: ldr r2, [pc, #imm]
emit("ldr r2, [pc, lit_widx]",   (0x4A << 8) | pcrel_ldr_imm(0x02, LIT["widx"]))
# +0x04: ldr r3, [r2, #0]                encoding: 68 13
emit("ldr r3, [r2, #0]",         0x6813)
# +0x06: movs r4, #240                   encoding: 24 F0
emit("movs r4, #240",            0x24F0)
# +0x08: lsls r4, r4, #1                 encoding: 00 64
emit("lsls r4, r4, #1",          0x0064)
# +0x0A: cmp r3, r4                      encoding: 42 A3
emit("cmp r3, r4",               0x42A3)
# +0x0C: blt +2  (skip next 2 bytes)     encoding: DB 00
emit("blt +2",                   0xDB00)
# +0x0E: movs r3, #0                     encoding: 23 00
emit("movs r3, #0",              0x2300)
# +0x10: ldr r4, [pc, lit_base]
emit("ldr r4, [pc, lit_base]",   (0x4C << 8) | pcrel_ldr_imm(0x10, LIT["base"]))
# +0x12: add r4, r3                      encoding: 19 1C  (adds r4, r4, r3)
emit("adds r4, r4, r3",          0x191C)
# +0x14: ldr r0, [sp, #0]                encoding: 98 00
emit("ldr r0, [sp, #0]",         0x9800)
# +0x16: ldr r1, [sp, #4]                encoding: 99 01
emit("ldr r1, [sp, #4]",         0x9901)
# +0x18: strb r0, [r4, #0]               encoding: 70 20
emit("strb r0, [r4, #0]",        0x7020)
# +0x1A: str r1, [r4, #4]                encoding: 60 61
emit("str r1, [r4, #4]",         0x6061)
# +0x1C: adds r3, #8                     encoding: 33 08
emit("adds r3, #8",              0x3308)
# +0x1E: str r3, [r2]                    encoding: 60 13
emit("str r3, [r2]",             0x6013)
# +0x20: ldr r2, [pc, lit_count]
emit("ldr r2, [pc, lit_count]",  (0x4A << 8) | pcrel_ldr_imm(0x20, LIT["count"]))
# +0x22: ldr r3, [r2]
emit("ldr r3, [r2]",             0x6813)
# +0x24: adds r3, #1
emit("adds r3, #1",              0x3301)
# +0x26: str r3, [r2]
emit("str r3, [r2]",             0x6013)
# +0x28: ldr r2, [pc, lit_magic_addr]
emit("ldr r2, [pc, lit_magic_addr]", (0x4A << 8) | pcrel_ldr_imm(0x28, LIT["magic_addr"]))
# +0x2A: ldr r3, [pc, lit_magic_val]
emit("ldr r3, [pc, lit_magic_val]",  (0x4B << 8) | pcrel_ldr_imm(0x2A, LIT["magic_val"]))
# +0x2C: str r3, [r2]
emit("str r3, [r2]",             0x6013)
# +0x2E: pop {r0,r1,r2,r3,r4} (NOT lr — we still need original lr in lr)
# Actually we pushed lr at +0x00 because push {r0..r4, lr} is a single hw form.
# Pop format: 1011 110M reglist  (pop). If M=1, pops PC.
# pop {r0,r1,r2,r3,r4}: encoding BC 1F
emit("pop {r0,r1,r2,r3,r4}",     0xBC1F)
# We also pushed lr → need to pop lr without writing to PC.
# Workaround: pop {r4} again? That doesn't restore lr.
# Better workaround: at the start, push {r0,r1,r2,r3,r4} (no lr) since lr
# isn't clobbered by anything between push and pop. Re-emit.

# REWRITE: don't push lr.

T = bytearray()
# +0x00: push {r0,r1,r2,r3,r4}           encoding: B4 1F  (PUSH form without lr)
emit("push {r0,r1,r2,r3,r4}",    0xB41F)
# +0x02: ldr r2, [pc, lit_widx]
emit("ldr r2, [pc, lit_widx]",   (0x4A << 8) | pcrel_ldr_imm(0x02, LIT["widx"]))
# +0x04: ldr r3, [r2, #0]
emit("ldr r3, [r2, #0]",         0x6813)
# +0x06: movs r4, #240
emit("movs r4, #240",            0x24F0)
# +0x08: lsls r4, r4, #1
emit("lsls r4, r4, #1",          0x0064)
# +0x0A: cmp r3, r4
emit("cmp r3, r4",               0x42A3)
# +0x0C: blt +2
emit("blt +2",                   0xDB00)
# +0x0E: movs r3, #0
emit("movs r3, #0",              0x2300)
# +0x10: ldr r4, [pc, lit_base]
emit("ldr r4, [pc, lit_base]",   (0x4C << 8) | pcrel_ldr_imm(0x10, LIT["base"]))
# +0x12: adds r4, r4, r3
emit("adds r4, r4, r3",          0x191C)
# +0x14: ldr r0, [sp, #0]
emit("ldr r0, [sp, #0]",         0x9800)
# +0x16: ldr r1, [sp, #4]
emit("ldr r1, [sp, #4]",         0x9901)
# +0x18: strb r0, [r4, #0]
emit("strb r0, [r4, #0]",        0x7020)
# +0x1A: str r1, [r4, #4]
emit("str r1, [r4, #4]",         0x6061)
# +0x1C: adds r3, #8
emit("adds r3, #8",              0x3308)
# +0x1E: str r3, [r2]
emit("str r3, [r2]",             0x6013)
# +0x20: ldr r2, [pc, lit_count]
emit("ldr r2, [pc, lit_count]",  (0x4A << 8) | pcrel_ldr_imm(0x20, LIT["count"]))
# +0x22: ldr r3, [r2]
emit("ldr r3, [r2]",             0x6813)
# +0x24: adds r3, #1
emit("adds r3, #1",              0x3301)
# +0x26: str r3, [r2]
emit("str r3, [r2]",             0x6013)
# +0x28: ldr r2, [pc, lit_magic_addr]
emit("ldr r2, [pc, lit_magic_addr]", (0x4A << 8) | pcrel_ldr_imm(0x28, LIT["magic_addr"]))
# +0x2A: ldr r3, [pc, lit_magic_val]
emit("ldr r3, [pc, lit_magic_val]",  (0x4B << 8) | pcrel_ldr_imm(0x2A, LIT["magic_val"]))
# +0x2C: str r3, [r2]
emit("str r3, [r2]",             0x6013)
# +0x2E: pop {r0,r1,r2,r3,r4}
emit("pop {r0,r1,r2,r3,r4}",     0xBC1F)
# +0x30: push {r3,r4,r5,r6,r7,lr}        encoding: B5 F8  (displaced original push)
emit("push {r3,r4,r5,r6,r7,lr}", 0xB5F8)
# +0x32: ldr r4, [pc, lit_gn]
emit("ldr r4, [pc, lit_gn]",     (0x4C << 8) | pcrel_ldr_imm(0x32, LIT["gn"]))
# +0x34: b.w NOTIFY_NEXT
T.extend(enc_bw(TRAMP_ADDR + 0x34, NOTIFY_NEXT))
# +0x38: padding
while len(T) < LIT_OFF:
    T.extend(le16(0xBF00))   # NOP for padding

# Literal pool
for name, val in LITS:
    assert len(T) == LIT[name]
    T.extend(le_word(val))

print(f"Trampoline size: {len(T)} bytes")
assert len(T) <= 0x60, "trampoline too long for the budgeted space"

# ------------------------------------------------------------------
# Apply patches to a copy of fw_25
# ------------------------------------------------------------------
with open(SRC, "rb") as f:
    img = bytearray(f.read())

# 1. Replace notify() entry's first 4 bytes with b.w trampoline
patch_branch = enc_bw(NOTIFY, TRAMP_ADDR)
print(f"Patch at 0x{NOTIFY:08X}: {patch_branch.hex()} (b.w 0x{TRAMP_ADDR:08X})")
img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = patch_branch

# 2. Lay down trampoline at TRAMP_ADDR
tramp_file_off = TRAMP_ADDR - 0x08000000
img[tramp_file_off : tramp_file_off + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST} ({len(img)} bytes)")
