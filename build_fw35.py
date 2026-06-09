#!/usr/bin/env python3
"""
firmware_35_preloaded-music-vol35.bin

Same idea as the old fw_32, but built on the new productive fw_34 base
(so the bar gets fw_34's "DSP actually off in standby" behaviour
alongside the preloaded vEEPROM values).

Appends two vEEPROM entries on top of fw_34:
  - volume = 35   (ID 0x2222)
  - bass   = +8   (ID 0x3333)

modeExtend=1 (ID 0x4444) and mode=0/Music (ID 0x5555) are already the
latest values in the inherited vEEPROM log, so no extra writes needed.

The vEEPROM is an append-only log; the bar reads the latest entry per
ID at boot. So we just append two new (value, id) pairs at the first
free slot.
"""
import struct

SRC = "/tmp/firmware/firmware_34_pc15-only-keepalive.bin"
DST = "/tmp/firmware/firmware_35_preloaded-music-vol35.bin"

PAGE1_BASE = 0x7000  # file offset of vEEPROM page 1

with open(SRC, "rb") as f:
    img = bytearray(f.read())

# Find first free slot + decode existing latest values
print("Existing latest values per ID (in fw_34's vEEPROM):")
latest = {}
first_free = None
for off in range(4, 0x400, 4):
    val, id_ = struct.unpack_from("<HH", img, PAGE1_BASE + off)
    if id_ == 0xFFFF and val == 0xFFFF:
        first_free = off
        break
    latest[id_] = val
else:
    raise SystemExit("Page is full!")

for id_, val in sorted(latest.items()):
    print(f"  ID 0x{id_:04X} = {val} (0x{val:04X})")
print(f"\nFirst free slot: page1 + 0x{first_free:03X} (= flash 0x{0x08007000+first_free:08X})")

new_entries = [
    (35, 0x2222),
    (8,  0x3333),
]

print("\nAppending:")
off = first_free
for val, id_ in new_entries:
    print(f"  page1 + 0x{off:03X}: value=0x{val:04X} ({val}), id=0x{id_:04X}")
    struct.pack_into("<HH", img, PAGE1_BASE + off, val, id_)
    off += 4

with open(DST, "wb") as f:
    f.write(img)
print(f"\nWrote {DST}")

# Show the modified region
print("\n=== Region around the append ===")
import subprocess
ofs = PAGE1_BASE + (first_free & ~0xF)
subprocess.run(["xxd", "-s", str(ofs), "-l", "64", DST])
