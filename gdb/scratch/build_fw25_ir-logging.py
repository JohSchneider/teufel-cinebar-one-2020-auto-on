#!/usr/bin/env python3
"""
Build firmware_24_ir-logging.bin from firmware_23_music-mode-default.bin.

Patches notify() at 0x0800BBDC to detour through a logging shim. The shim:
  1. Replicates notify's original first 4 instructions (push, ldr r4, mov r5, mov r6)
  2. Logs (channel, caller_lr) into a ring buffer at 0x20003C00
  3. Tail-jumps to notify+8 to continue normally

No GDB breakpoints. Bar runs at full speed. notify is called from 19+ sites,
including the IR decoder — all get logged transparently.

Ring buffer at 0x20003C00:
  Offset 0: u32 idx (current write position, wraps at 64)
  Offset 4..511: 64 entries of (u32 channel, u32 lr) = 8 bytes each

Read from GDB:
  (gdb) printf "idx=%d\n", *(unsigned*)0x20003C00
  (gdb) x/128wx 0x20003C04   # 64 entries (128 words)

Or use /tmp/firmware/gdb/read_ir_log.sh (built in companion).

Patches vs fw_23:
  - 8 bytes at 0x0800BBDC..0x0800BBE3 (notify's first 4 instructions → detour)
  - ~60 bytes at 0x0801E8C0 (the shim itself, in unused patch space)
"""
import struct
from pathlib import Path

SRC = Path('/tmp/firmware/firmware_23_music-mode-default.bin')
DST = Path('/tmp/firmware/firmware_25_ir-logging-v2.bin')

FLASH_BASE         = 0x08000000
NOTIFY_ADDR        = 0x0800BBDC   # function entry — first 8 bytes to overwrite
NOTIFY_PLUS_8      = 0x0800BBE4   # where shim returns to (after replicating the 4 original instructions)
SHIM_ADDR          = 0x0801E8C0   # in patch space, after fw_23 wrapper which ends ~0x0801E898
G_NOTIFY_STRUCT    = 0x200023BC   # value originally loaded by `ldr r4, [pc, #48]`
LOG_BUF_ADDR       = 0x20002700   # ring buffer in RAM
                                  # 0x20002700-0x20002BFF probed empirically: all-zero, between
                                  # known globals and the RTX5 TCB at 0x20002C00. Safe for ~1.2 KB.
                                  # fw_24 used 0x20003C00 which collided with stack memory.

# ---- Assembler helpers ----

def hw(value):
    """Return 2-byte LE encoding of a 16-bit halfword."""
    return value.to_bytes(2, 'little')

def encode_ldr_pc_relative(rt, offset):
    """ldr Rt, [pc, #offset] — Rt in r0..r7, offset is byte offset to literal (multiple of 4)."""
    assert 0 <= rt <= 7
    assert offset % 4 == 0 and 0 <= offset <= 1020
    imm8 = offset // 4
    return hw(0x4800 | (rt << 8) | imm8)

def encode_ldr_imm(rt, rn, imm5):
    """ldr Rt, [Rn, #imm5*4] — Rt, Rn in r0..r7."""
    assert 0 <= rt <= 7 and 0 <= rn <= 7 and 0 <= imm5 <= 31
    return hw(0x6800 | (imm5 << 6) | (rn << 3) | rt)

def encode_str_imm(rt, rn, imm5):
    """str Rt, [Rn, #imm5*4]"""
    assert 0 <= rt <= 7 and 0 <= rn <= 7 and 0 <= imm5 <= 31
    return hw(0x6000 | (imm5 << 6) | (rn << 3) | rt)

def encode_movs_imm(rd, imm8):
    """movs Rd, #imm8"""
    assert 0 <= rd <= 7 and 0 <= imm8 <= 255
    return hw(0x2000 | (rd << 8) | imm8)

def encode_cmp_imm(rn, imm8):
    """cmp Rn, #imm8"""
    assert 0 <= rn <= 7 and 0 <= imm8 <= 255
    return hw(0x2800 | (rn << 8) | imm8)

def encode_adds_imm(rd, imm8):
    """adds Rd, #imm8"""
    assert 0 <= rd <= 7 and 0 <= imm8 <= 255
    return hw(0x3000 | (rd << 8) | imm8)

def encode_lsls_imm(rd, rm, imm5):
    """lsls Rd, Rm, #imm5"""
    assert 0 <= rd <= 7 and 0 <= rm <= 7 and 0 <= imm5 <= 31
    return hw(0x0000 | (imm5 << 6) | (rm << 3) | rd)

def encode_mov_reg(rd, rm):
    """mov Rd, Rm — both can be low or high registers."""
    assert 0 <= rd <= 15 and 0 <= rm <= 15
    return hw(0x4600 | ((rd & 0x8) << 4) | (rm << 3) | (rd & 0x7))

def encode_add_reg(rd, rm):
    """add Rd, Rm (the high-reg form, supports r0-r15 for both)."""
    assert 0 <= rd <= 15 and 0 <= rm <= 15
    return hw(0x4400 | ((rd & 0x8) << 4) | (rm << 3) | (rd & 0x7))

def encode_push(reg_mask, include_lr=False):
    """push register-list (Thumb-1: only low regs r0-r7 plus optional lr)."""
    assert 0 <= reg_mask <= 0xFF
    return hw(0xB400 | (1 << 8 if include_lr else 0) | reg_mask)

def encode_pop(reg_mask, include_pc=False):
    """pop register-list (Thumb-1: only low regs r0-r7 plus optional pc)."""
    return hw(0xBC00 | (1 << 8 if include_pc else 0) | reg_mask)

def encode_bx(rm):
    """bx Rm"""
    assert 0 <= rm <= 15
    return hw(0x4700 | (rm << 3))

def encode_bls(target_offset_halfwords):
    """bls imm8 — branch if lower-or-same (unsigned)."""
    imm = target_offset_halfwords
    assert -128 <= imm <= 127
    if imm < 0: imm += 256
    return hw(0xD900 | (imm & 0xFF))

def encode_bl(pc, target):
    """Encode a 32-bit Thumb-2 BL instruction from `pc` to `target`."""
    offset = target - (pc + 4)
    assert offset % 2 == 0
    assert -(1 << 24) <= offset < (1 << 24)
    imm = offset >> 1
    S = (imm >> 23) & 1
    imm_masked = imm & ((1 << 24) - 1)
    I2 = (imm_masked >> 22) & 1
    I1 = (imm_masked >> 23) & 1
    imm10 = (imm_masked >> 11) & 0x3FF
    imm11 = imm_masked & 0x7FF
    J1 = (1 - I1) ^ S
    J2 = (1 - I2) ^ S
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = 0xD000 | (J1 << 13) | (J2 << 11) | imm11
    return struct.pack('<HH', hw1, hw2)


# ---- Build the shim ----

# Layout of shim at SHIM_ADDR:
#   Code instructions (assembled below)
#   Then 4-byte-aligned literal pool with 3 words:
#     .word G_NOTIFY_STRUCT
#     .word LOG_BUF_ADDR
#     .word NOTIFY_PLUS_8 | 1   (Thumb bit)
#
# The shim:
#   1. push {r3, r4, r5, r6, r7, lr}            ; replicate notify's prologue
#   2. ldr r4, [pc, #X1]                         ; r4 = G_NOTIFY_STRUCT (orig ldr did *(0x800BC10))
#   3. mov r5, r1                                ; r5 = value
#   4. mov r6, r0                                ; r6 = channel
#   5. -- now logging --
#   5. ldr r0, [pc, #X2]                         ; r0 = LOG_BUF_ADDR
#   6. ldr r1, [r0]                              ; r1 = current idx
#   7. cmp r1, #63
#   8. bls .Lno_wrap
#   9. movs r1, #0
#   .Lno_wrap:
#  10. lsls r2, r1, #3                           ; r2 = idx*8
#  11. adds r2, #4                               ; r2 = idx*8 + 4
#  12. add r2, r0                                ; r2 = buf + idx*8 + 4 (high-reg add OK)
#  13. str r6, [r2, #0]                          ; entry.channel = r6
#  14. mov r3, lr                                ; r3 = caller_return
#  15. str r3, [r2, #4]                          ; entry.lr = r3
#  16. adds r1, #1                               ; idx++
#  17. str r1, [r0]                              ; save idx
#  18. -- restore + tail-jump --
#  18. mov r0, r6
#  19. mov r1, r5
#  20. ldr r2, [pc, #X3]                         ; r2 = NOTIFY_PLUS_8 | 1
#  21. bx r2

# We'll emit two passes: first assemble assuming 0 for ldr offsets,
# then patch up the ldr-pc offsets once we know the literal pool position.

code = b''
ldr_patch_sites = []  # (code-offset, label_name)

def emit(b):
    global code
    code += b

# 1
emit(encode_push(0b11111000, include_lr=True))  # push {r3, r4, r5, r6, r7, lr}

# 2: ldr r4, [pc, #X1] — to be patched
ldr_patch_sites.append((len(code), 'g_notify'))
emit(encode_ldr_pc_relative(4, 0))

# 3: mov r5, r1
emit(encode_mov_reg(5, 1))

# 4: mov r6, r0
emit(encode_mov_reg(6, 0))

# 5: ldr r0, [pc, #X2]
ldr_patch_sites.append((len(code), 'buf'))
emit(encode_ldr_pc_relative(0, 0))

# 6: ldr r1, [r0, #0]
emit(encode_ldr_imm(1, 0, 0))

# 7: cmp r1, #63
emit(encode_cmp_imm(1, 63))

# 8: bls .Lno_wrap (skip 1 halfword — the movs)
emit(encode_bls(1))

# 9: movs r1, #0
emit(encode_movs_imm(1, 0))

# .Lno_wrap: (label points here)

# 10: lsls r2, r1, #3
emit(encode_lsls_imm(2, 1, 3))

# 11: adds r2, #4
emit(encode_adds_imm(2, 4))

# 12: add r2, r0 (high-reg form)
emit(encode_add_reg(2, 0))

# 13: str r6, [r2, #0]
emit(encode_str_imm(6, 2, 0))

# 14: mov r3, lr (r14)
emit(encode_mov_reg(3, 14))

# 15: str r3, [r2, #4]
emit(encode_str_imm(3, 2, 1))   # imm5*4 = 4 → imm5 = 1

# 16: adds r1, #1
emit(encode_adds_imm(1, 1))

# 17: str r1, [r0, #0]
emit(encode_str_imm(1, 0, 0))

# 18: mov r0, r6
emit(encode_mov_reg(0, 6))

# 19: mov r1, r5
emit(encode_mov_reg(1, 5))

# 20: ldr r2, [pc, #X3]
ldr_patch_sites.append((len(code), 'notify_p8'))
emit(encode_ldr_pc_relative(2, 0))

# 21: bx r2
emit(encode_bx(2))

# --- Literal pool (4-byte aligned within the shim) ---
# Pad to 4-byte alignment
while len(code) % 4 != 0:
    emit(b'\x00\x00')

lit_offsets = {}
lit_offsets['g_notify']  = len(code); emit(struct.pack('<I', G_NOTIFY_STRUCT))
lit_offsets['buf']       = len(code); emit(struct.pack('<I', LOG_BUF_ADDR))
lit_offsets['notify_p8'] = len(code); emit(struct.pack('<I', NOTIFY_PLUS_8 | 1))

# --- Patch the ldr-pc offsets ---
patched = bytearray(code)
for code_off, label in ldr_patch_sites:
    # The LDR's PC during execution is (SHIM_ADDR + code_off + 4), aligned to 4.
    pc_at_exec = SHIM_ADDR + code_off + 4
    pc_aligned = pc_at_exec & ~3
    lit_addr   = SHIM_ADDR + lit_offsets[label]
    pc_offset  = lit_addr - pc_aligned
    assert 0 <= pc_offset <= 1020 and pc_offset % 4 == 0, f"bad ldr offset {pc_offset} for {label}"
    imm8 = pc_offset // 4
    # The original encoded instruction at code_off has imm8=0. Patch its low byte.
    patched[code_off] = imm8  # ldr Rt, [pc, #imm8*4] — imm8 is the low byte of the encoding

shim_bytes = bytes(patched)
print(f"Shim assembled: {len(shim_bytes)} bytes at 0x{SHIM_ADDR:08X}")
print(f"  Code:    {len(code) - (sum(4 for _ in lit_offsets))*4} bytes of instructions")
print(f"  Literal: {len(lit_offsets) * 4} bytes ({list(lit_offsets.keys())})")
print(f"  Hex: {shim_bytes.hex()}")

# ---- Build the detour at notify ----
# 4 instructions (8 bytes) at notify entry are replaced with:
#   ldr r3, [pc, #0]     ; 0x4B00 = bytes "00 4B"
#   bx r3                ; 0x4718 = bytes "18 47"
#   .word SHIM_ADDR | 1  ; (Thumb bit)
#
# The ldr loads the SHIM address into r3, then bx jumps. LR is preserved
# (ldr and bx don't modify LR), so when shim chains to notify+8, the
# original caller_return is intact.
#
# Note: encode_ldr_pc_relative computes target = ((PC+4)&~3) + imm8*4
# At execution of `ldr r3, [pc, #0]`, PC = NOTIFY_ADDR + 0 = 0x0800BBDC,
# PC+4 = 0x0800BBE0, aligned = 0x0800BBE0, target = 0x0800BBE0 + 0 = 0x0800BBE0.
# So the literal is at NOTIFY_ADDR + 4 = 0x0800BBE0. ✓
detour = (
    encode_ldr_pc_relative(3, 0)    # ldr r3, [pc, #0]
    + encode_bx(3)                   # bx r3
    + struct.pack('<I', SHIM_ADDR | 1)  # literal: shim address with Thumb bit
)
assert len(detour) == 8
print(f"Detour at notify (0x{NOTIFY_ADDR:08X}, 8 bytes): {detour.hex()}")

# ---- Apply patches ----
data = bytearray(SRC.read_bytes())

# Sanity: verify the bytes we're about to overwrite match what we expect
existing = bytes(data[NOTIFY_ADDR - FLASH_BASE : NOTIFY_ADDR - FLASH_BASE + 8])
print(f"Original notify[0..7]: {existing.hex()}  (expect f8b50c4c0d460646)")

# Apply detour at notify entry
data[NOTIFY_ADDR - FLASH_BASE : NOTIFY_ADDR - FLASH_BASE + 8] = detour

# Place shim
shim_off = SHIM_ADDR - FLASH_BASE
assert all(b == 0xFF for b in data[shim_off:shim_off + len(shim_bytes)]), \
    f"Shim region 0x{SHIM_ADDR:08X}..+{len(shim_bytes)} is not all-0xFF"
data[shim_off:shim_off + len(shim_bytes)] = shim_bytes

# Write output
DST.write_bytes(bytes(data))
print(f"\nWrote {DST}")
print(f"Net diff vs fw_23: 8 + {len(shim_bytes)} = {8 + len(shim_bytes)} bytes")
print(f"\nFlash with:")
print(f"  openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\")
print(f"    -c 'program {DST.name} verify reset exit 0x08000000'")
print(f"\nThen press IR-power once, then dump the buffer:")
print(f"  (gdb) printf \"idx=%d\\n\", *(unsigned*)0x{LOG_BUF_ADDR:08X}")
print(f"  (gdb) x/128wx 0x{LOG_BUF_ADDR + 4:08X}")
