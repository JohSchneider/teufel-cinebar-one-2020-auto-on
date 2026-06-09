#!/usr/bin/env python3
"""
firmware_34_pc15-only-keepalive.bin

The CORRECT minimal NOP set for "keep Toslink alive in standby, power down
DSP and other subsystems". Supersedes fw_22 as the productive variant.

Bench-verified pin-master mapping (2026-06-08):
  - PC15 LOW alone drops the Toslink rail (3V → 0.8V) → PC15 is the rail master
  - PB7 LOW alone stops audio (Toslink rail unaffected)    → PB7 = DSP power
  - PA2 LOW alone:   no effect on rail or audio            → PA2 = unknown/aux

Conclusion: fw_22's three NOPs (PA2 + PB7 + PC15) were over-broad. The PA2
and PB7 NOPs were "load-bearing only by accident" — the rail would have
stayed up with just the PC15 NOP, AND the DSP would have actually powered
down (because PB7-LOW was reaching the DSP rail).

fw_34 = fw_22 minus the PA2 and PB7 NOPs:
  - Keep 0x0A836 NOPed   → PC15 stays HIGH → Toslink rail stays at 3V
  - Restore 0x0A81A      → PA2 LOW fires (no observable effect, but matches
                            stock standby sequence)
  - Restore 0x0A81E      → PB7 LOW fires → DSP power actually off in standby

In standby, fw_34 leaves:
  - PA2  = LOW   (was 1 in fw_22; no functional impact either way)
  - PB7  = LOW   (was 1 in fw_22 → DSP IC stayed powered; now actually off)
  - PC15 = HIGH  (Toslink Vcc stays at 3V → wake-on-SPDIF still works)
  - PF0  = LOW   (DSP held in reset, same as fw_22)
  - I²C1 = down  (PB8/PB9 → Analog, same as fw_22)

Wake-on-SPDIF (fw_22's Shim 2) still works because PA4 (SPDIF data) still
receives biphase signal from the Toslink receiver (which is powered via
PC15).
"""
import struct

SRC = "/tmp/firmware/firmware_22_wake-on-spdif.bin"
DST = "/tmp/firmware/firmware_34_pc15-only-keepalive.bin"

with open(SRC, "rb") as f:
    img = bytearray(f.read())

patches = [
    # Restore PA2 LOW BL — was NOPed in fw_22, was not actually needed.
    (0x0A81A, b"\x00\xbf\x00\xbf", b"\x06\xf0\x71\xfe",
     "Restore bl 0x8011500 (PA2 LOW, harmless side effect)"),
    # Restore PB7 LOW BL — this is what actually cuts DSP power in standby.
    (0x0A81E, b"\x00\xbf\x00\xbf", b"\x01\xf0\x35\xfe",
     "Restore bl 0x800c48c (PB7 LOW, DSP power off)"),
    # Leave 0x0A836 NOPed (PC15 stays HIGH = Toslink rail up).
]

print(f"Patching {SRC} → {DST}")
for off, want_before, new_bytes, desc in patches:
    actual = bytes(img[off:off+len(new_bytes)])
    if actual != want_before:
        print(f"  WARNING: 0x{off:05X} expected {want_before.hex(' ')}, got {actual.hex(' ')}")
    img[off:off+len(new_bytes)] = new_bytes
    print(f"  0x{off:05X}  ({len(new_bytes)} bytes)  {desc}")

# Sanity check: 0x0A836 should still be NOPed (PC15 LOW stays out)
pc15_bytes = bytes(img[0x0A836:0x0A836+4])
assert pc15_bytes == b"\x00\xbf\x00\xbf", \
    f"PC15-LOW NOP missing at 0x0A836 (got {pc15_bytes.hex(' ')}). " \
    "Refusing to write a binary that would drop the Toslink rail in standby."

with open(DST, "wb") as f:
    f.write(img)
print(f"\nWrote {DST}")
