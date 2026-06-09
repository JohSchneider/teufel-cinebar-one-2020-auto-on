#!/usr/bin/env python3
"""
firmware_32_preloaded-music-vol35.bin

Based on firmware_22_wake-on-spdif.bin (auto-on + wake-on-SPDIF, no force-mode
shim, no notify-trampoline). Append vEEPROM entries so the bar boots with:
  - volume   = 35   (ID 0x2222)
  - bass     = 8    (ID 0x3333, matching live value at time of build)
  - modeExtend = 1  (ID 0x4444, already present in fw_22's log)
  - mode     = 0    (ID 0x5555 = Music, already present in fw_22's log)
  - power    = 2    (ID 0x1111 = active, already present in fw_22's log)

The bar's vEEPROM driver scans the page and uses the LATEST entry per ID,
so we just append two new (value, id) entries at the first free slot.
"""

import struct

SRC = "/tmp/firmware/firmware_22_wake-on-spdif.bin"
DST = "/tmp/firmware/firmware_32_preloaded-music-vol35.bin"

PAGE1_BASE = 0x7000           # file offset (= flash 0x08007000)
PAGE_END   = 0x7400           # 1 KB page

with open(SRC, "rb") as f:
    img = bytearray(f.read())

# Decode current vEEPROM to find first free slot
print("Existing latest values per ID (in fw_22):")
latest = {}
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

# Entries to append: (value, id)
new_entries = [
    (35, 0x2222),   # volume → 35
    (8,  0x3333),   # bass   → 8  (matches live)
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
print(f"\n=== Region around the append ===")
ofs = PAGE1_BASE + (first_free & ~0xF)
import subprocess
subprocess.run(["xxd", "-s", str(ofs), "-l", "64", DST])
