#!/usr/bin/env python3
"""
fw_28 = fw_25 + minimal pass-through trampoline (no logging).
Sanity check: does the patch-and-redirect approach work at all?
"""
import struct

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_28_passthrough-tramp.bin"

NOTIFY      = 0x0800BBDC
NOTIFY_NEXT = 0x0800BBE0
G_NOTIFY    = 0x200023BC
TRAMP       = 0x0801E8A0


def enc_bw(src, tgt):
    offset = tgt - (src + 4)
    o = offset >> 1
    if o < 0:
        o += (1 << 24); S = 1
    else: S = 0
    imm11 = o & 0x7FF
    imm10 = (o >> 11) & 0x3FF
    I2 = (o >> 21) & 1
    I1 = (o >> 22) & 1
    J1 = (1 ^ I1) ^ S
    J2 = (1 ^ I2) ^ S
    return struct.pack("<HH",
                       (0b11110<<11) | (S<<10) | imm10,
                       (0b10<<14) | (J1<<13) | (1<<12) | (J2<<11) | imm11)


T = bytearray()
# Just the displaced original push + ldr, then b.w back
# +0x00: b5f8  push {r3-r7, lr}
T += struct.pack("<H", 0xB5F8)
# +0x02: 4c00  ldr r4, [pc, #0]   → pc=(0x02+4)&~3=4; target=4+0=4? need offset to gn-literal
# Plan: literal at +0x08. So pc=4, target=8 → delta=4 → imm8=1.
T += struct.pack("<H", (0x4C << 8) | 1)
# +0x04: b.w  NOTIFY_NEXT
T += enc_bw(TRAMP + 0x04, NOTIFY_NEXT)
# +0x08: literal g_notify_struct
T += struct.pack("<I", G_NOTIFY)

print(f"Trampoline = {len(T)} bytes:", T.hex())

with open(SRC, "rb") as f:
    img = bytearray(f.read())

img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = enc_bw(NOTIFY, TRAMP)
img[TRAMP - 0x08000000 : TRAMP - 0x08000000 + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST}")
