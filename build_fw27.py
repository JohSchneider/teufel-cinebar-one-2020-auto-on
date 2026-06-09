#!/usr/bin/env python3
"""
firmware_27_simple-notify-log.bin

Minimal notify() instrumentation: no stack push, no ring loop.
Just store {channel, value} to a fixed RAM slot on every call.
GDB reads the slot to see the LAST notify() args.

Trampoline (12 bytes of code + 8 bytes of literals):

  0x0801E8A0: 4a04          ldr  r2, [pc, #16]       ; r2 = 0x20003E00
  0x0801E8A2: 7010          strb r0, [r2, #0]        ; *0x20003E00 = channel (byte)
  0x0801E8A4: 6051          str  r1, [r2, #4]        ; *0x20003E04 = value (word)
  0x0801E8A6: b5f8          push {r3,r4,r5,r6,r7,lr} ; displaced original
  0x0801E8A8: 4c02          ldr  r4, [pc, #8]        ; r4 = 0x200023BC (g_notify_struct)
  0x0801E8AA: f7ed b899     b.w  0x0800BBE0           ; jump to notify()+4

  0x0801E8AE: bf00          nop (alignment padding)
  0x0801E8B0: 003e0020      .word 0x20003E00
  0x0801E8B4: bc230020      .word 0x200023BC

Patch at notify()@0x0800BBDC: replace 4 bytes (b5f8 4c0c) with b.w 0x0801E8A0.
"""

import struct

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_27_simple-notify-log.bin"

NOTIFY      = 0x0800BBDC
NOTIFY_NEXT = 0x0800BBE0
G_NOTIFY    = 0x200023BC
TRAMP       = 0x0801E8A0
LOG_ADDR    = 0x20003E00


def enc_bw(src_addr, tgt_addr):
    offset = tgt_addr - (src_addr + 4)
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
    J1 = (1 ^ I1) ^ S
    J2 = (1 ^ I2) ^ S
    hw1 = (0b11110 << 11) | (S << 10) | imm10
    hw2 = (0b10 << 14) | (J1 << 13) | (1 << 12) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def le16(v): return struct.pack("<H", v & 0xFFFF)
def le32(v): return struct.pack("<I", v & 0xFFFFFFFF)


T = bytearray()
# +0x00 ldr r2, [pc, #16]      pc = (0x00+4) & ~3 = 4; target = 4+16 = 0x14
T += le16((0x4A << 8) | 4)     # 0x4A04
# +0x02 strb r0, [r2, #0]
T += le16(0x7010)
# +0x04 str  r1, [r2, #4]
T += le16(0x6051)
# +0x06 push {r3,r4,r5,r6,r7,lr}   = b5f8
T += le16(0xB5F8)
# +0x08 ldr r4, [pc, #8]       pc = (0x08+4) & ~3 = 0x0C; target = 0x0C+8 = 0x14? need 0x18 (gn)
# Recompute: I want r4 to load gn = 0x200023BC at literal_off 0x18.
# delta = 0x18 - 0x0C = 0x0C → imm8 = 3
T += le16((0x4C << 8) | 3)     # 0x4C03
# +0x0A b.w 0x0800BBE0
T += enc_bw(TRAMP + 0x0A, NOTIFY_NEXT)
# +0x0E padding to 4-byte boundary
T += le16(0xBF00)              # nop
# +0x10 — but we wanted literals at 0x14, 0x18. So add another nop pair.
T += le16(0xBF00)
T += le16(0xBF00)
# +0x14 .word 0x20003E00
assert len(T) == 0x14
T += le32(LOG_ADDR)
# +0x18 .word 0x200023BC
assert len(T) == 0x18
T += le32(G_NOTIFY)

print(f"Trampoline = {len(T)} bytes")
print("Bytes:", T.hex())

with open(SRC, "rb") as f:
    img = bytearray(f.read())

# Patch notify() entry
patch = enc_bw(NOTIFY, TRAMP)
print(f"notify() patch at 0x{NOTIFY:08X}: {patch.hex()}")
img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = patch

# Place trampoline
off = TRAMP - 0x08000000
img[off : off + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST}")
