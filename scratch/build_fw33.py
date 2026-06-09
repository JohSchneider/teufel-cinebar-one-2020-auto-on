#!/usr/bin/env python3
"""
firmware_33_pa2-only-keepalive.bin

Goal: keep the Toslink receiver powered in standby (so wake-on-SPDIF still
works), but actually power down the DSP and audio amp.

Theory: of the three "LOW writes in standby" calls that fw_22 NOPs
  - 0x0800A81A:  bl 0x8011500 → spdif_subsystem_init → drives PA2 LOW
                  (Toslink rail master)
  - 0x0800A81E:  bl 0x800c48c → 0x800c9a0 → drives PB7 LOW
                  (suspect: DSP-IC power enable / regulator)
  - 0x0800A836:  bl 0x800d65e directly → drives PC15 LOW
                  (suspect: audio amp / second rail)

Only the PA2 LOW kills the Toslink-receiver rail (per fw_06/fw_07/fw_08
bench history). So if we let PB7 and PC15 go LOW in standby but keep PA2
NOPed, we should keep the Toslink rail alive while letting the DSP and
amp actually power down — which solves task #59.

Patches relative to fw_22:
  - Restore the bl at 0x0800A81E (PB7 LOW) — unNOPed
  - Restore the bl at 0x0800A836 (PC15 LOW) — unNOPed
  - Keep 0x0800A81A NOPed (PA2 stays HIGH = Toslink alive)
"""
import struct

SRC = "/tmp/firmware/firmware_22_wake-on-spdif.bin"
DST = "/tmp/firmware/firmware_33_pa2-only-keepalive.bin"

with open(SRC, "rb") as f:
    img = bytearray(f.read())

patches = [
    # Restore PB7 LOW BL (was: nop nop, now: bl 0x800c48c)
    (0x0A81E, b"\x00\xbf\x00\xbf", b"\x01\xf0\x35\xfe",
     "Restore bl 0x800c48c (PB7 LOW, DSP power off)"),
    # Restore PC15 LOW BL (was: nop nop, now: bl 0x800d65e for PC15-LOW)
    (0x0A836, b"\x00\xbf\x00\xbf", b"\x02\xf0\x12\xff",
     "Restore bl 0x800d65e (PC15 LOW, aux/amp rail off)"),
]

print(f"Patching {SRC} → {DST}")
for off, want_before, new_bytes, desc in patches:
    actual = bytes(img[off:off+len(new_bytes)])
    print(f"  0x{off:05X}  ({len(new_bytes)} bytes)  {desc}")
    print(f"           was: {actual.hex(' ')}")
    if actual != want_before:
        print(f"  WARNING: expected {want_before.hex(' ')} at 0x{off:05X}, got {actual.hex(' ')}")
        print(f"           This isn't fw_22 with the expected NOPs — proceeding anyway")
    img[off:off+len(new_bytes)] = new_bytes
    print(f"           now: {new_bytes.hex(' ')}")

with open(DST, "wb") as f:
    f.write(img)
print(f"\nWrote {DST}")
