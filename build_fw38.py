#!/usr/bin/env python3
"""
firmware_38_bootloader-msc-mode.bin

Layers on top of fw_37 with the KEY new insight: 0x080039D4 is the
BOOTLOADER's main, not the application's main. The bootloader normally
calls bl 0x08002DB8 at 0x08003A92 (a boot-jump that loads app vector
table from 0x08008000 and transfers control to the app). The USB MSC
init code at 0x08003AD0 onwards is only reached when the bootloader
DECIDES NOT to jump to the app.

The decision happens at 0x08003A88:
  bne 0x08003A98   (skip to USB-MSC path if condition not met)

We flip that bne to unconditional b — single byte: 0xD1 → 0xE0.

After this:
  - Bootloader's validation ALWAYS FAILS
  - Bootloader runs the 10-iter delay loop (5 seconds)
  - Bootloader waits for PA1 HIGH
  - Bootloader calls bl 0x08003AD0 (= our patched bl to shim)
  - Shim sets USBEN, calls original USB init
  - Bootloader continues with USB/MSC class setup
  - Bar enumerates as MSC (PID 0x0004) on USB

With T211 externally pulled HIGH (mux to STM32), host should see
"TEUFEL CBO" FAT12 volume.

Side effect: the application NEVER RUNS. No audio, no IR, no normal
operation. Just MSC firmware update mode. After successful test,
reflash fw_34 to restore normal operation.

Patches relative to fw_37:
  + 1-byte change at file offset 0x3A89: 0xD1 → 0xE0 (bne → b)

Total bytes changed vs baseline:
  fw_36: 5 bytes (PA0 + EEPROM bypass — irrelevant here since app never runs)
  fw_37: + 32 bytes (shim) + 4 bytes (BL retarget) = 36 bytes
  fw_38: + 1 byte (bne → b) = 1 byte
  Grand total: 42 bytes
"""
import struct

SRC = "/tmp/firmware/firmware_37_usben-forced.bin"
DST = "/tmp/firmware/firmware_38_bootloader-msc-mode.bin"

with open(SRC, "rb") as f:
    img = bytearray(f.read())

print(f"Loaded base: {SRC} ({len(img)} bytes)")

# Verify fw_37 base is in place
assert img[0xF14B] == 0xE0, "fw_36 PA0 patch missing — wrong base?"
assert bytes(img[0xED10:0xED14]) == bytes.fromhex("00207047"), "fw_36 EEPROM patch missing"
assert bytes(img[0x3AD0:0x3AD4]) == bytes([0x1a, 0xf0, 0xd6, 0xfe]), "fw_37 BL retarget missing"
assert bytes(img[0x1E880:0x1E884]) == bytes([0x07, 0xb5, 0x07, 0x48]), "fw_37 shim missing"
print("fw_37 base patches all verified")

# --- New patch: force bootloader to skip the app and enter MSC mode ---
PATCH_OFFSET = 0x3A89
EXPECTED = 0xD1   # high byte of `bne.n` (0xD1 = condition=NE, low byte=0x06=offset)
NEW      = 0xE0   # high byte of `b.n`   (0xE0 = unconditional, low byte=0x06=offset, same target)

actual = img[PATCH_OFFSET]
print(f"\nPatch site 0x{PATCH_OFFSET:05X}: 0x{actual:02X} -> 0x{NEW:02X}")
assert actual == EXPECTED, f"unexpected byte 0x{actual:02X} at 0x{PATCH_OFFSET:05X}"
img[PATCH_OFFSET] = NEW

print(f"Total bytes changed vs fw_37: 1")

with open(DST, "wb") as f:
    f.write(img)

import hashlib
sha = hashlib.sha256(img).hexdigest()
print(f"\nWrote {DST}")
print(f"SHA256: {sha}")

# Verify the patch site context
print(f"\n=== Patch site context (file 0x{PATCH_OFFSET-3:05x}..0x{PATCH_OFFSET+5:05x}) ===")
import subprocess
subprocess.run(["xxd", "-s", str(PATCH_OFFSET-3), "-l", "10", DST])
