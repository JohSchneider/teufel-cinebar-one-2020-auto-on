#!/usr/bin/env python3
"""
Build a self-identifying TEST payload for the Cinebar MSC upload protocol.

Each 4-byte word at file offset (512+N) contains BE32(0x08008000 + N).
After upload, reading flash[A] for any A in [0x08008000..0x0801FFFF) should
return BE32(A). That makes diagnosing partial uploads, transformations,
or rejections trivial.

Bonus safety: the first 4 bytes of the payload (= would-be app SP at 0x08008000)
are BE32(0x08008000) which little-endian-reads as 0x00800008 — way outside RAM
range — so the bootloader's app-validity check FAILS even if its patches are
reverted, ensuring the bar stays in MSC mode (no risk of executing this junk
as code).
"""
import struct
import hashlib

DST = "/tmp/firmware/upload_test_pattern.bin"
APP_BASE = 0x08008000
APP_LEN = 0x18000   # 96 KB

# Build payload: each word = BE32(its flash destination address)
payload = bytearray(APP_LEN)
for i in range(0, APP_LEN, 4):
    flash_addr = APP_BASE + i
    payload[i:i+4] = struct.pack(">I", flash_addr)

# Build the upload header (first sector)
header = bytearray(512)
header[0]    = 0x02                              # type = BEGIN_FLASH_UPDATE
header[1:5]  = struct.pack(">I", APP_LEN)       # BE32 length = 0x00018000
header[5:9]  = struct.pack(">I", 0)             # unknown — try 0
# bytes 9-511 stay 0x00

upload = bytes(header) + bytes(payload)
assert len(upload) == 512 + APP_LEN == 98816

with open(DST, "wb") as f:
    f.write(upload)

print(f"Wrote {DST}")
print(f"  Total size:    {len(upload)} bytes ({len(upload)/1024:.1f} KB)")
print(f"  Header:        type=0x02, payload_length=0x{APP_LEN:08x}, bytes[5..8]=0")
print(f"  Payload:       96 KB self-identifying pattern")
print(f"  At flash 0x{APP_BASE:08x}, expect: {' '.join(f'{b:02x}' for b in struct.pack('>I', APP_BASE))}")
print(f"  At flash 0x{APP_BASE+4:08x}, expect: {' '.join(f'{b:02x}' for b in struct.pack('>I', APP_BASE+4))}")
print(f"  At flash 0x{APP_BASE+0x100:08x}, expect: {' '.join(f'{b:02x}' for b in struct.pack('>I', APP_BASE+0x100))}")
print(f"  At flash 0x{APP_BASE+APP_LEN-4:08x}, expect: {' '.join(f'{b:02x}' for b in struct.pack('>I', APP_BASE+APP_LEN-4))}")
print(f"  SHA256: {hashlib.sha256(upload).hexdigest()}")

# Reset trigger
reset = b"\x00"
reset_path = "/tmp/firmware/upload_test_reset.bin"
with open(reset_path, "wb") as f:
    f.write(reset)
print(f"\nReset trigger:  {reset_path} (1 byte 0x00)")
