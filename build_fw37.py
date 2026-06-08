#!/usr/bin/env python3
"""
firmware_37_usben-forced.bin

Layers on top of fw_36 (PA0-LOW path + EEPROM-bypass) by adding a tiny
shim in patch-space that enables RCC_APB1ENR.USBEN (bit 23) BEFORE main()
calls the existing USB stack init at 0x080030B0.

The static analysis (2026-06-09) revealed:
  - main() at 0x080039D4 already calls bl 0x080030B0 at 0x08003AD0
  - 0x080030B0 → 0x08003254 sets up the USB peripheral handle struct
    (Instance = 0x40005C00, endpoints, etc.)
  - But NO instruction in firmware ever sets RCC_APB1ENR bit 23 (USBEN)
  - So the USB struct init writes to a peripheral with no clock = dead

This patch redirects the BL at 0x08003AD0 from 0x080030B0 to a shim at
0x0801E800 (in g_patch_space). The shim:
  1. Saves caller's r0, r1 (the args for the original USB init call)
  2. Sets RCC_APB1ENR |= (1 << 23) (USBEN)
  3. Readback for ordering
  4. Restores r0, r1
  5. Calls the original 0x080030B0 (USB stack init)
  6. Returns to main()'s next instruction

If everything else (PLL config for 48 MHz, USB descriptor callbacks,
endpoint setup) is intact, this should give us:
  - Bar boots, main() runs, USBEN gets set, USB peripheral is alive
  - USB descriptors are now meaningful — bar enumerates as PID 0x0004 (MSC)
  - With T211 externally pulled HIGH (mux to STM32 side), the host sees
    a "TEUFEL CBO" FAT12 volume

If MSC still doesn't enumerate, the next layer to investigate is the USB
clock source (PLL @ 48 MHz vs HSI48). SystemInit at 0x08002EA0 configures
the PLL — would need to verify the output is exactly 48 MHz for USB.

Total bytes changed: 32 bytes (shim) + 4 bytes (BL retarget) = 36 bytes
on top of fw_36's 5 bytes.
"""
import struct

SRC = "/tmp/firmware/firmware_36_pa0-low-and-eeprom-bypass.bin"
DST = "/tmp/firmware/firmware_37_usben-forced.bin"

# --- Helpers ---
def encode_bl(src_addr, dst_addr):
    """Encode a Thumb-2 BL instruction.

    Returns (h1, h2) where each is a 16-bit halfword in native int form
    (stored as bytes in little-endian to flash).
    """
    pc = src_addr + 4
    offset = dst_addr - pc
    assert offset % 2 == 0
    val = offset & 0x1FFFFFF  # 25-bit signed view
    imm11 = (val >> 1) & 0x7FF
    imm10 = (val >> 12) & 0x3FF
    i2 = (val >> 22) & 1
    i1 = (val >> 23) & 1
    s_bit = (val >> 24) & 1
    j1 = (~(i1 ^ s_bit)) & 1
    j2 = (~(i2 ^ s_bit)) & 1
    h1 = 0xF000 | (s_bit << 10) | imm10
    h2 = 0xD000 | (j1 << 13) | (1 << 12) | (j2 << 11) | imm11
    return h1, h2

# Sanity check the encoder against the original BL
h1, h2 = encode_bl(0x08003AD0, 0x080030B0)
assert h1 == 0xF7FF and h2 == 0xFAEE, f"BL encoder broken: got {h1:04x} {h2:04x}"
print(f"BL encoder verified (original BL = f7ff faee)")

# --- Load fw_36 base ---
with open(SRC, "rb") as f:
    img = bytearray(f.read())
print(f"\nLoaded base: {SRC} ({len(img)} bytes)")

# Verify base is fw_36 (PA0 patch + EEPROM patch in place)
assert img[0xF14B] == 0xE0, "fw_36 PA0 patch byte missing — wrong base?"
assert bytes(img[0xED10:0xED14]) == bytes.fromhex("00207047"), "fw_36 EEPROM patch missing"
print("fw_36 base patches verified")

# --- Patch space check ---
SHIM_ADDR = 0x0801E880  # 0x0801E800 already has existing shims in fw_36 base
SHIM_OFFSET = SHIM_ADDR - 0x08000000  # = 0x1E880
SHIM_LEN = 0x20  # 32 bytes
existing = img[SHIM_OFFSET:SHIM_OFFSET+SHIM_LEN]
assert existing == b'\xff' * SHIM_LEN, f"Patch space at 0x{SHIM_ADDR:08x} not erased: {existing.hex(' ')}"
print(f"Patch space at 0x{SHIM_ADDR:08x} ({SHIM_LEN} bytes) is clean (0xFF)")

# --- Build the shim ---
# Layout (offsets from SHIM_ADDR):
#   +0x00: push {r0, r1, lr}     b507  (save caller args + return addr)
#   +0x02: ldr r0, [pc, #20]     4805  (-> +0x18 = literal RCC_APB1ENR)
#   +0x04: ldr r1, [r0]           6801
#   +0x06: movs r2, #1            2201
#   +0x08: lsls r2, r2, #23      05d2  (r2 = 0x00800000 = USBEN bit)
#   +0x0A: orrs r1, r2            4311
#   +0x0C: str r1, [r0]           6001  (RCC_APB1ENR |= USBEN)
#   +0x0E: ldr r1, [r0]           6801  (readback for ordering)
#   +0x10: pop {r0, r1}           bc03  (restore caller's args)
#   +0x12: ldr r3, [pc, #8]      4b02  (-> +0x1C = literal target 0x080030B1)
#   +0x14: blx r3                 4798  (call original USB stack init)
#   +0x16: pop {pc}               bd00  (return to main)
#   +0x18: <literal 0x4002101C>   1C 10 02 40  (RCC_APB1ENR address)
#   +0x1C: <literal 0x080030B1>   B1 30 00 08  (USB init entry, Thumb bit set)
shim_halfwords = [
    0xb507,  # push {r0, r1, lr}
    0x4805,  # ldr r0, [pc, #20]
    0x6801,  # ldr r1, [r0]
    0x2201,  # movs r2, #1
    0x05d2,  # lsls r2, r2, #23
    0x4311,  # orrs r1, r2
    0x6001,  # str r1, [r0]
    0x6801,  # ldr r1, [r0]
    0xbc03,  # pop {r0, r1}
    0x4b02,  # ldr r3, [pc, #8]
    0x4798,  # blx r3
    0xbd00,  # pop {pc}
]
shim_bytes = b''.join(struct.pack('<H', hw) for hw in shim_halfwords)
shim_bytes += struct.pack('<I', 0x4002101C)   # literal: RCC_APB1ENR address
shim_bytes += struct.pack('<I', 0x080030B1)   # literal: USB init entry (Thumb)
assert len(shim_bytes) == 32, f"shim is {len(shim_bytes)} bytes, expected 32"

print(f"\nShim ({len(shim_bytes)} bytes at flash 0x{SHIM_ADDR:08x}):")
for i in range(0, len(shim_bytes), 4):
    chunk = shim_bytes[i:i+4]
    print(f"  +0x{i:02x}: {chunk.hex(' ')}")

# Write the shim
img[SHIM_OFFSET:SHIM_OFFSET + len(shim_bytes)] = shim_bytes

# --- Patch the BL at 0x08003AD0 to call the shim instead of 0x080030B0 ---
BL_SRC_ADDR = 0x08003AD0
BL_SRC_OFFSET = BL_SRC_ADDR - 0x08000000  # = 0x3AD0

# Verify the original BL bytes (f7ff faee) are there
orig_bl = bytes(img[BL_SRC_OFFSET:BL_SRC_OFFSET+4])
assert orig_bl == bytes.fromhex("fffffeae")[::-1] or orig_bl == bytes.fromhex("f7fffaee")[::-1] \
    or orig_bl == bytes([0xff, 0xf7, 0xee, 0xfa]), \
    f"Original BL bytes at 0x{BL_SRC_ADDR:08x} unexpected: {orig_bl.hex(' ')}"
# In LE-halfword form: 0xF7FF = bytes ff f7, 0xFAEE = bytes ee fa
assert orig_bl == bytes([0xff, 0xf7, 0xee, 0xfa]), f"Original BL bytes wrong: {orig_bl.hex(' ')}"
print(f"\nOriginal BL at 0x{BL_SRC_ADDR:08x} = {orig_bl.hex(' ')} (-> 0x080030B0) ✓")

# Compute new BL encoding
h1, h2 = encode_bl(BL_SRC_ADDR, SHIM_ADDR)
new_bl = struct.pack('<HH', h1, h2)
print(f"New BL bytes (-> 0x{SHIM_ADDR:08x}): {new_bl.hex(' ')}")

img[BL_SRC_OFFSET:BL_SRC_OFFSET+4] = new_bl

# --- Write output ---
with open(DST, "wb") as f:
    f.write(img)

import hashlib
sha = hashlib.sha256(img).hexdigest()
print(f"\nWrote {DST}")
print(f"SHA256: {sha}")

# --- Verify ---
print(f"\n=== Verification (re-read output) ===")
import subprocess
print(f"Shim region (32 bytes at file 0x{SHIM_OFFSET:05x}):")
subprocess.run(["xxd", "-s", str(SHIM_OFFSET), "-l", "32", DST])
print(f"\nBL patch site (8 bytes at file 0x{BL_SRC_OFFSET:05x}):")
subprocess.run(["xxd", "-s", str(BL_SRC_OFFSET), "-l", "8", DST])
