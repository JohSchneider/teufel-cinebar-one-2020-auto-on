#!/usr/bin/env python3
"""
Construct a Cinebar One MSC firmware-upload file.

Input:  a full 128 KB firmware image (e.g., firmware_34_pc15-only-keepalive.bin)
Output: a file that, when dropped on the bar's MSC volume in update mode,
        causes the bootloader to flash the app region (0x08008000..0x0801FFFF).

File format (reverse-engineered from bootloader 2026-06-09):

  Sector 0 (bytes 0..511):
    [0]      = 0x02                 ← type 2 = BEGIN_FLASH_UPDATE
    [1..4]   = BE32 payload_length  ← number of payload bytes to follow (must be ≤ 96 KB, 4-aligned)
    [5..8]   = BE32 (value)         ← purpose unknown — try 0 first; may be CRC
    [9..511] = 0xFF (ignored)

  Sectors 1..N (bytes 512..512+length-1):
    Raw app bytes (firmware_34's bytes 0x8000..0x1FFFF = 96 KB)

Drop this file on /media/.../Teufel\ CBO/, sync, then drop a separate 1-byte
file containing 0x00 to trigger bootloader-reset.

WARNING: The bootloader erases the entire 96 KB app region BEFORE programming.
If anything interrupts the upload mid-way, the app is corrupted and the bar
boots only into the bootloader's MSC mode again until you SWD-reflash.
"""
import struct
import sys
import os

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <input_full_firmware.bin> <output_msc_upload.bin>")
    sys.exit(1)

SRC, DST = sys.argv[1], sys.argv[2]

# Load the full firmware (128 KB)
with open(SRC, "rb") as f:
    full = f.read()
assert len(full) == 0x20000, f"input must be 128 KB, got {len(full)} bytes"

# Extract the app region (offset 0x8000..0x1FFFF = 96 KB)
APP_OFFSET = 0x8000
APP_LEN = 0x18000   # 96 KB
app = full[APP_OFFSET:APP_OFFSET + APP_LEN]
assert len(app) == APP_LEN

# --- Build the upload file ---
# Sector 0: header
header = bytearray(512)
header[0]    = 0x02                                     # type = BEGIN_FLASH_UPDATE
header[1:5]  = struct.pack(">I", APP_LEN)              # BE32 length = 0x00018000
header[5:9]  = struct.pack(">I", 0)                    # unknown — try 0 first
# bytes 9-511 stay 0x00 (could also be 0xFF — doesn't matter since they're ignored)

# Sectors 1+: payload
payload = app

upload = bytes(header) + payload
assert len(upload) == 512 + 0x18000 == 98816

with open(DST, "wb") as f:
    f.write(upload)

print(f"Wrote {DST}")
print(f"  Size: {len(upload)} bytes ({len(upload)/1024:.1f} KB)")
print(f"  Header: type=0x02, payload_length=0x{APP_LEN:08x}")
print(f"  Payload: bytes 0x{APP_OFFSET:05X}..0x{APP_OFFSET+APP_LEN-1:05X} of {SRC}")
import hashlib
print(f"  SHA256: {hashlib.sha256(upload).hexdigest()}")

# Also produce the 1-byte reset trigger
reset_path = DST.replace(".bin", "_reset.bin")
if reset_path == DST:
    reset_path = DST + ".reset"
with open(reset_path, "wb") as f:
    f.write(b"\x00")
print(f"\nAlso wrote {reset_path} (1-byte reset trigger, content = 0x00)")
print("\nUsage:")
print(f"  1. cp {DST} /media/johannes/Teufel\\ CBO/UPLOAD.BIN")
print("  2. sync")
print("  3. wait for write to complete (LED may flash, ~few seconds)")
print(f"  4. cp {reset_path} /media/johannes/Teufel\\ CBO/RESET.BIN")
print("  5. sync")
print("  → bar reboots into the new firmware")
