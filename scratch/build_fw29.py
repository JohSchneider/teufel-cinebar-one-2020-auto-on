#!/usr/bin/env python3
"""
fw_29 = fw_25 + Cortex-M0-correct notify trampoline.

Key insight: B.W (unconditional 32-bit) is NOT in ARMv6-M.
Use `ldr r2, [pc, #imm]; bx r2` instead. The literal at 0x0800BC10
(originally the address of g_notify_struct, loaded by the ldr at
notify+2) gets REPURPOSED to hold the trampoline address. Since
we're replacing both the push and the ldr at notify+0/2, nothing
in the original code path still reads that literal.

Trampoline at 0x0801E8A0:
  1. log r0, r1 to RAM
  2. execute the displaced push + load-g_notify_struct
  3. BL to notify+4 — a TAIL CALL.
     - BL clobbers LR (we don't care; the displaced push already
       saved the caller's LR onto the stack)
     - When notify's own `pop {r3-r7, pc}` runs at its end, it
       pops the saved LR (= caller's return) into PC → returns
       to caller, bypassing whatever LR points at after our BL.

  trampoline @ 0x0801E8A0:
    +0x00  4a04   ldr r2, [pc, #16]      ; r2 = 0x20003E00
    +0x02  7010   strb r0, [r2, #0]
    +0x04  6051   str  r1, [r2, #4]
    +0x06  b5f8   push {r3,r4,r5,r6,r7,lr}   ; displaced
    +0x08  4c03   ldr r4, [pc, #12]      ; r4 = 0x200023BC
    +0x0A  f000 f??? bl 0x0800BBE0       ; tail call to notify+4
    +0x0E  (pad)
    +0x10  (pad)
    +0x14  .word 0x20003E00
    +0x18  .word 0x200023BC
"""
import struct

SRC = "/tmp/firmware/firmware_25_nop-ir-power-post.bin"
DST = "/tmp/firmware/firmware_29_notify-trap-v2.bin"

NOTIFY      = 0x0800BBDC
NOTIFY_PLUS4= 0x0800BBE0
G_NOTIFY    = 0x200023BC
TRAMP       = 0x0801E8A0
LOG_ADDR    = 0x20003E00
LITERAL_LOC = 0x0800BC10   # repurposed to hold trampoline addr | 1


def enc_bl(src, tgt):
    """BL (with link) — Thumb-2, supported on Cortex-M0."""
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
                       (0b11110 << 11) | (S << 10) | imm10,
                       (0b11 << 14) | (J1 << 13) | (1 << 12) | (J2 << 11) | imm11)


def le16(v): return struct.pack("<H", v & 0xFFFF)
def le32(v): return struct.pack("<I", v & 0xFFFFFFFF)


# Build trampoline
T = bytearray()
# +0x00 ldr r2, [pc, #16]   PC=(0x00+4)&~3=4; target=4+16=0x14 (LOG literal)
T += le16((0x4A << 8) | 4)
# +0x02 strb r0, [r2, #0]
T += le16(0x7010)
# +0x04 str  r1, [r2, #4]
T += le16(0x6051)
# +0x06 push {r3,r4,r5,r6,r7,lr}
T += le16(0xB5F8)
# +0x08 ldr r4, [pc, #12]   PC=(0x08+4)&~3=0x0C; target=0x0C+12=0x18 (gn literal)
T += le16((0x4C << 8) | 3)
# +0x0A bl 0x0800BBE0  (tail call to notify+4)
T += enc_bl(TRAMP + 0x0A, NOTIFY_PLUS4)
# +0x0E padding
T += le16(0xBF00)
# +0x10 padding
T += le16(0xBF00)
T += le16(0xBF00)
# +0x14 literal LOG_ADDR
assert len(T) == 0x14, len(T)
T += le32(LOG_ADDR)
# +0x18 literal gn
assert len(T) == 0x18, len(T)
T += le32(G_NOTIFY)

print(f"Trampoline = {len(T)} bytes:", T.hex())

# Build the notify() entry patch:
#   0x0800BBDC: ldr r2, [pc, #48]   (target = 0x0800BC10 = LITERAL_LOC)
#   0x0800BBDE: bx r2
notify_patch = bytearray()
# ldr r2, [pc, #imm]: PC=(0x0800BBDC+4)&~3=0x0800BBE0; delta=0x0800BC10-0x0800BBE0=0x30 → imm8=12
notify_patch += le16((0x4A << 8) | 12)   # 0x4A0C
notify_patch += le16(0x4710)              # bx r2
print(f"notify() patch (4 bytes): {bytes(notify_patch).hex()}")

with open(SRC, "rb") as f:
    img = bytearray(f.read())

# 1. Patch notify() entry
img[NOTIFY - 0x08000000 : NOTIFY - 0x08000000 + 4] = notify_patch
# 2. Repurpose the literal at 0x0800BC10 → trampoline addr | 1 (Thumb bit)
img[LITERAL_LOC - 0x08000000 : LITERAL_LOC - 0x08000000 + 4] = le32(TRAMP | 1)
# 3. Lay down trampoline
off = TRAMP - 0x08000000
img[off : off + len(T)] = T

with open(DST, "wb") as f:
    f.write(img)
print(f"Wrote {DST}")
