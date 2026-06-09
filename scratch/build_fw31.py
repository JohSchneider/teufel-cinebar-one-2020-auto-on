#!/usr/bin/env python3
"""
fw_31 = fw_30 but WITHOUT the magic write.
Same ring buffer logic minus the 3 instructions for magic.
If this boots, the bug is in those instructions.
"""
import struct

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_31_ring-no-magic.bin"

NOTIFY        = 0x0800BBDC
NOTIFY_PLUS4  = 0x0800BBE0
G_NOTIFY      = 0x200023BC
TRAMP         = 0x0801E8A0
RING_BASE     = 0x20003E00
LITERAL_AT    = 0x0800BC10


def enc_bl(src, tgt):
    offset = tgt - (src + 4)
    o = offset >> 1
    if o < 0: o += (1 << 24); S = 1
    else: S = 0
    imm11 = o & 0x7FF
    imm10 = (o >> 11) & 0x3FF
    I2 = (o >> 21) & 1; I1 = (o >> 22) & 1
    J1 = (1 ^ I1) ^ S; J2 = (1 ^ I2) ^ S
    return struct.pack("<HH",
                       (0b11110<<11)|(S<<10)|imm10,
                       (0b11<<14)|(J1<<13)|(1<<12)|(J2<<11)|imm11)


def le16(v): return struct.pack("<H", v & 0xFFFF)
def le32(v): return struct.pack("<I", v & 0xFFFFFFFF)


def pcrel_ldr_imm(insn_off, lit_off):
    pc = ((insn_off + 4) // 4) * 4
    delta = lit_off - pc
    assert 0 <= delta and delta % 4 == 0 and delta < 1024
    return delta >> 2


LIT_OFF = 0x20  # smaller pool since no magic
LITS = [
    ("widx", RING_BASE + 0x04),
    ("base", RING_BASE + 0x10),
    ("gn",   G_NOTIFY),
]
LIT = {n: LIT_OFF + 4*i for i, (n, _) in enumerate(LITS)}

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
# +0x0E uxtb r3, r3
T += le16(0xB2DB)
# +0x10 ldr r2, [pc, lit_widx]
T += le16((0x4A << 8) | pcrel_ldr_imm(0x10, LIT["widx"]))
# +0x12 strb r3, [r2, #0]
T += le16(0x7013)
# +0x14 push {r3,r4,r5,r6,r7,lr}     ; displaced
T += le16(0xB5F8)
# +0x16 ldr r4, [pc, lit_gn]
T += le16((0x4C << 8) | pcrel_ldr_imm(0x16, LIT["gn"]))
# +0x18 bl notify+4
T += enc_bl(TRAMP + 0x18, NOTIFY_PLUS4)
# +0x1C pad
T += le16(0xBF00)
T += le16(0xBF00)
# +0x20 literals
for name, val in LITS:
    assert len(T) == LIT[name]
    T += le32(val)

print(f"Trampoline = {len(T)} bytes")

with open(SRC, "rb") as f:
    img = bytearray(f.read())

img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = le16((0x4A << 8) | 12) + le16(0x4710)
img[LITERAL_AT - 0x08000000 : LITERAL_AT - 0x08000000 + 4] = le32(TRAMP | 1)
img[TRAMP - 0x08000000 : TRAMP - 0x08000000 + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST}")
