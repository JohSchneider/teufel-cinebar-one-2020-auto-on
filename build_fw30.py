#!/usr/bin/env python3
"""
fw_30 = fw_29 + proper ring buffer.

32-entry ring at 0x20003E00:
  +0x00  magic 0xC1BAFEED
  +0x04  write_idx (byte offset 0..248, wraps via uxtb)
  +0x08  count (lower 32 bits, optional, written every call)
  +0x0C  pad
  +0x10  start of 32 entries × 8 bytes
            +0  channel (u8) + 3 pad
            +4  value   (u32)

Trampoline at 0x0801E8A0 uses only r2, r3 (both caller-saved).
Order: read idx → compute entry addr → store {r0,r1} → update idx → write magic
   → displaced push → displaced ldr → BL tail-call to notify+4.
"""
import struct

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_30_notify-ring.bin"

NOTIFY        = 0x0800BBDC
NOTIFY_PLUS4  = 0x0800BBE0
G_NOTIFY      = 0x200023BC
TRAMP         = 0x0801E8A0
RING_BASE     = 0x20003E00
LITERAL_AT    = 0x0800BC10  # repurposed (was g_notify_struct ptr, original ldr is displaced)


def enc_bl(src, tgt):
    offset = tgt - (src + 4)
    o = offset >> 1
    if o < 0: o += (1 << 24); S = 1
    else: S = 0
    imm11 = o & 0x7FF
    imm10 = (o >> 11) & 0x3FF
    I2 = (o >> 21) & 1; I1 = (o >> 22) & 1
    J1 = (1 ^ I1) ^ S;  J2 = (1 ^ I2) ^ S
    return struct.pack("<HH",
                       (0b11110<<11)|(S<<10)|imm10,
                       (0b11<<14)|(J1<<13)|(1<<12)|(J2<<11)|imm11)


def le16(v): return struct.pack("<H", v & 0xFFFF)
def le32(v): return struct.pack("<I", v & 0xFFFFFFFF)


def pcrel_ldr_imm(insn_off, lit_off):
    pc = ((insn_off + 4) // 4) * 4
    delta = lit_off - pc
    assert 0 <= delta and delta % 4 == 0 and delta < 1024, f"out of range: insn=0x{insn_off:x} lit=0x{lit_off:x} delta=0x{delta:x}"
    return delta >> 2


# Plan literal pool layout first
LIT_OFF = 0x30
LITS = [
    ("widx",   RING_BASE + 0x04),
    ("base",   RING_BASE + 0x10),
    ("magic_a",RING_BASE + 0x00),
    ("magic_v",0xC1BAFEED),
    ("gn",     G_NOTIFY),
]
LIT = {name: LIT_OFF + 4*i for i, (name, _) in enumerate(LITS)}

T = bytearray()

# +0x00 ldr r2, [pc, lit_widx]
T += le16((0x4A << 8) | pcrel_ldr_imm(0x00, LIT["widx"]))
# +0x02 ldrb r3, [r2, #0]
T += le16(0x7813)
# +0x04 ldr r2, [pc, lit_base]
T += le16((0x4A << 8) | pcrel_ldr_imm(0x04, LIT["base"]))
# +0x06 adds r2, r2, r3
T += le16(0x18D2)
# +0x08 strb r0, [r2, #0]
T += le16(0x7010)
# +0x0A str r1, [r2, #4]
T += le16(0x6051)
# +0x0C adds r3, #8
T += le16(0x3308)
# +0x0E uxtb r3, r3       (mod 256 wrap)
T += le16(0xB2DB)
# +0x10 ldr r2, [pc, lit_widx]
T += le16((0x4A << 8) | pcrel_ldr_imm(0x10, LIT["widx"]))
# +0x12 strb r3, [r2, #0]
T += le16(0x7013)
# +0x14 ldr r2, [pc, lit_magic_a]
T += le16((0x4A << 8) | pcrel_ldr_imm(0x14, LIT["magic_a"]))
# +0x16 ldr r3, [pc, lit_magic_v]
T += le16((0x4B << 8) | pcrel_ldr_imm(0x16, LIT["magic_v"]))
# +0x18 str r3, [r2, #0]
T += le16(0x6013)
# +0x1A push {r3,r4,r5,r6,r7,lr}     (displaced original)
T += le16(0xB5F8)
# +0x1C ldr r4, [pc, lit_gn]
T += le16((0x4C << 8) | pcrel_ldr_imm(0x1C, LIT["gn"]))
# +0x1E bl notify+4
T += enc_bl(TRAMP + 0x1E, NOTIFY_PLUS4)

# Pad to literal pool
while len(T) < LIT_OFF:
    T += le16(0xBF00)

for name, val in LITS:
    assert len(T) == LIT[name], f"misalign at {name}"
    T += le32(val)

print(f"Trampoline = {len(T)} bytes:", T.hex())

with open(SRC, "rb") as f:
    img = bytearray(f.read())

# Patch notify entry: ldr r2, [pc, #48]; bx r2
img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = le16((0x4A << 8) | 12) + le16(0x4710)
# Set literal at 0x0800BC10 to trampoline addr | 1
img[LITERAL_AT - 0x08000000 : LITERAL_AT - 0x08000000 + 4] = le32(TRAMP | 1)
# Lay trampoline
img[TRAMP - 0x08000000 : TRAMP - 0x08000000 + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST}")
