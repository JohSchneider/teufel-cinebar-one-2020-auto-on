#!/usr/bin/env python3
"""
firmware_36_pa0-low-and-eeprom-bypass.bin

Experimental — forces the bar into the PA0-LOW service-mode path AT BOOT
(no external PA0 wiring needed) and bypasses the EEPROM handshake check
(since this bar has no EEPROM at I²C2 address 0x50).

Built on top of fw_34 so the productive features (auto-on, wake-on-SPDIF,
clean DSP standby) are still there.

Two patch sites, 5 bytes total:

  1. read_pa0() always returns 1 (= "PA0 is LOW")
     File offset 0xF14B: 0xD0 -> 0xE0  (BEQ.N -> B.N, single byte)

     Disasm:
       0x0800F148: cmp r0, #0
       0x0800F14A: beq.n 0x0800F150  (was)
       0x0800F14A: b.n   0x0800F150  (now — unconditional)
       0x0800F14C: movs r0, #0     (dead code)
       0x0800F150: movs r0, #1
       0x0800F152: pop {r4, pc}

  2. service_mode_handshake() at 0x0800ED10 — early-return 0 (success)
     File offset 0xED10: b5 f8       -> 00 20    (push -> movs r0,#0)
     File offset 0xED12: 25 00       -> 70 47    (movs r5,#0 -> bx lr)
     (4 bytes total)

     Effect: no I²C transaction is attempted; no buffer is read; caller
     (service_outer) sees r0=0 and proceeds to call service_inner(r0=5)
     which does the USB-related setup work.

     Downstream: state[+22] is normally written by handshake's success
     epilogue from buf[4..5]. We skip that. state+22 remains at its
     init value (0 on a freshly booted bar). The downstream call at
     0x0800E9B8 will read state+22 as 0 and pass it to 0x0800B9DC —
     probably benign (likely a state-broadcast that just queues 0).

This is an experimental build; it's NOT a productive variant. Flashing
this will cause the bar to immediately try to enter MSC service mode.
For the full test you ALSO need T211 pulled HIGH externally (1 kΩ to
3.3 V).

Verification status: not yet flashed. Two-patch hypothesis derived from
GDB live tracing on 2026-06-08 that confirmed:
  - The PA0-LOW path executes when PA0 is physically driven LOW
  - The service-mode peripheral init does run (I²C2 enabled,
    PB10/PB11 configured as AF)
  - No device ACKs at I²C2 addr 0x50 (handshake stuck in retry loop)
  - State at +9 stays 0 = "first-time path" never completes
"""
import struct

SRC = "/tmp/firmware/firmware_34_pc15-only-keepalive.bin"
DST = "/tmp/firmware/firmware_36_pa0-low-and-eeprom-bypass.bin"

with open(SRC, "rb") as f:
    img = bytearray(f.read())

print(f"=== Loaded {SRC} ({len(img)} bytes) ===\n")

# --- Patch A: read_pa0() always returns LOW ---
PATCH_A_OFFSET = 0xF14B
EXPECTED_A = 0xD0  # BEQ.N high byte
NEW_A      = 0xE0  # B.N high byte (unconditional)

actual = img[PATCH_A_OFFSET]
print(f"Patch A (read_pa0 always LOW):")
print(f"  File offset 0x{PATCH_A_OFFSET:05X}: 0x{actual:02X} -> 0x{NEW_A:02X}")
assert actual == EXPECTED_A, f"unexpected byte 0x{actual:02X} at 0x{PATCH_A_OFFSET:05X}; expected 0x{EXPECTED_A:02X}. Wrong base firmware?"
img[PATCH_A_OFFSET] = NEW_A

# --- Patch B: handshake early-return success ---
PATCH_B_OFFSET = 0xED10
EXPECTED_B = bytes.fromhex("f8b50025")   # little-endian: 0xb5f8 push; 0x2500 movs r5,#0
NEW_B      = bytes.fromhex("00207047")   # little-endian: 0x2000 movs r0,#0; 0x4770 bx lr

actual_b = bytes(img[PATCH_B_OFFSET:PATCH_B_OFFSET+4])
print(f"\nPatch B (handshake early-return 0):")
print(f"  File offset 0x{PATCH_B_OFFSET:05X}: {actual_b.hex()} -> {NEW_B.hex()}")
assert actual_b == EXPECTED_B, f"unexpected bytes {actual_b.hex()} at 0x{PATCH_B_OFFSET:05X}; expected {EXPECTED_B.hex()}"
img[PATCH_B_OFFSET:PATCH_B_OFFSET+4] = NEW_B

# Diff summary
total_changed = 1 + 4
print(f"\nTotal bytes changed: {total_changed}")

# Write output
with open(DST, "wb") as f:
    f.write(img)

import hashlib
sha = hashlib.sha256(img).hexdigest()
print(f"\nWrote {DST}")
print(f"SHA256: {sha}")

# Show patch sites in context
print(f"\n=== Patch A region (file offset 0x{PATCH_A_OFFSET-3:05X}..0x{PATCH_A_OFFSET+4:05X}) ===")
import subprocess
subprocess.run(["xxd", "-s", str(PATCH_A_OFFSET-3), "-l", "8", DST])

print(f"\n=== Patch B region (file offset 0x{PATCH_B_OFFSET:05X}..0x{PATCH_B_OFFSET+8:05X}) ===")
subprocess.run(["xxd", "-s", str(PATCH_B_OFFSET), "-l", "8", DST])
