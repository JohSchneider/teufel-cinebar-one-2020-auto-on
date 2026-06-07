#!/usr/bin/env python3
"""
Build firmware_23_music-mode-default.bin from firmware_22_wake-on-spdif.bin.

Adds a wrapper shim at flash 0x0801E880 that intercepts BOTH transition_state
call sites in the firmware:
- 0x0801E808 (shim 1, fires on cold boot / AC restore)
- 0x0800AD12 (event-loop dispatch, fires on IR on/off + auto-wake from shim 2)

The wrapper:
  - Calls transition_state(action) with the caller's r0 argument
  - If action == 2 (transitioning to active), additionally calls set_audio_mode(0)
    to force Music mode
  - Preserves and returns transition_state's return value
  - Skips set_audio_mode if action != 2 (avoid calling it while bar is heading
    to standby, where I²C-to-DSP may be torn down)

Net effect: every "→ active" transition forces Music mode, regardless of which
path triggered it (AC restore, IR-on, auto-wake from fiber).

This is reversible: re-flash firmware_22_wake-on-spdif.bin to revert.

Tested addresses (from fw_22 static RE):
- transition_state(action)@ 0x0800A740
- set_audio_mode(mode)    @ 0x0800C560
- shim 1 BL site          @ 0x0801E808
- event-dispatch BL site  @ 0x0800AD12
- patch space free        @ 0x0801E880..0x0801FFFF (~5.9 KB)
"""
import struct, sys
from pathlib import Path

MODE_NAMES = {0: 'music', 1: 'movie', 2: 'voice'}
mode_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 0
assert mode_arg in MODE_NAMES, f"mode must be 0 (music), 1 (movie), or 2 (voice)"

# fw_23 stays as the Music variant; new IDs for the others to keep the index sane
DST_ID_MAP = {0: 23, 1: 24, 2: 25}
fw_id   = DST_ID_MAP[mode_arg]
name    = MODE_NAMES[mode_arg]
SRC  = Path('/tmp/firmware/firmware_22_wake-on-spdif.bin')
DST  = Path(f'/tmp/firmware/firmware_{fw_id}_force-{name}-mode.bin')

FLASH_BASE         = 0x08000000
SHIM1_BL_ADDR      = 0x0801E808
DISPATCH_BL_ADDR   = 0x0800AD12
WRAPPER_ADDR       = 0x0801E880
TRANSITION_STATE   = 0x0800A740
SET_AUDIO_MODE     = 0x0800C560
DESIRED_MODE       = mode_arg

def encode_bl(pc: int, target: int) -> bytes:
    """Encode a Cortex-M0 Thumb-2 BL instruction calling `target` from address `pc`."""
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

def decode_bl(hw_bytes: bytes, pc: int) -> int:
    hw1, hw2 = struct.unpack('<HH', hw_bytes)
    S = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    J1 = (hw2 >> 13) & 1
    J2 = (hw2 >> 11) & 1
    imm11 = hw2 & 0x7FF
    I1 = (1 - J1) ^ S
    I2 = (1 - J2) ^ S
    imm = (S << 23) | (I1 << 22) | (I2 << 21) | (imm10 << 11) | imm11
    if S: imm -= (1 << 24)
    return pc + 4 + (imm << 1)

# Load
data = bytearray(SRC.read_bytes())

# Verify both BL sites currently target transition_state
for name, addr in [('shim1', SHIM1_BL_ADDR), ('dispatch', DISPATCH_BL_ADDR)]:
    off = addr - FLASH_BASE
    bl_bytes = bytes(data[off:off+4])
    tgt = decode_bl(bl_bytes, addr)
    print(f"{name} BL @ 0x{addr:08X}: {bl_bytes.hex()} → 0x{tgt:08X}")
    assert tgt == TRANSITION_STATE, f"{name} doesn't call transition_state!"

# Verify wrapper space is clear
wrapper_off = WRAPPER_ADDR - FLASH_BASE
WRAPPER_BUDGET = 32
assert all(b == 0xFF for b in data[wrapper_off : wrapper_off + WRAPPER_BUDGET]), \
    f"Wrapper space @ 0x{WRAPPER_ADDR:08X} is not clear"

# Assemble the wrapper:
#   push {r4, r5, lr}     ; 30 b5      — preserve r4 (action), r5 (retval)
#   mov r4, r0            ; 04 46      — r4 = action (saved across BL)
#   bl transition_state   ; ...        — call with r0 = action
#   mov r5, r0            ; 05 46      — r5 = retval
#   cmp r4, #2            ; 02 2c      — was action == active?
#   bne skip              ; 01 d1      — if not, jump past set_audio_mode
#   movs r0, #DESIRED_MODE; XX 20
#   bl set_audio_mode     ; ...
# skip:
#   mov r0, r5            ; 28 46      — restore retval
#   pop {r4, r5, pc}      ; 30 bd
wrapper = bytearray()
wrapper += b'\x30\xb5'                                          # push {r4, r5, lr}
wrapper += b'\x04\x46'                                          # mov r4, r0
bl_pc = WRAPPER_ADDR + len(wrapper)
wrapper += encode_bl(bl_pc, TRANSITION_STATE)                  # bl transition_state
wrapper += b'\x05\x46'                                          # mov r5, r0
wrapper += b'\x02\x2c'                                          # cmp r4, #2
wrapper += b'\x01\xd1'                                          # bne skip (+2 halfwords)
wrapper += bytes([DESIRED_MODE, 0x20])                          # movs r0, #DESIRED_MODE
bl_pc = WRAPPER_ADDR + len(wrapper)
wrapper += encode_bl(bl_pc, SET_AUDIO_MODE)                    # bl set_audio_mode
# skip:
wrapper += b'\x28\x46'                                          # mov r0, r5
wrapper += b'\x30\xbd'                                          # pop {r4, r5, pc}

assert len(wrapper) <= WRAPPER_BUDGET
print(f"\nwrapper: {len(wrapper)} bytes @ 0x{WRAPPER_ADDR:08X}")
print(f"  hex: {wrapper.hex()}")

# Place wrapper
data[wrapper_off : wrapper_off + len(wrapper)] = wrapper

# Redirect both BL sites
for name, addr in [('shim1', SHIM1_BL_ADDR), ('dispatch', DISPATCH_BL_ADDR)]:
    new_bl = encode_bl(addr, WRAPPER_ADDR)
    print(f"redirect {name} BL @ 0x{addr:08X}: {new_bl.hex()}")
    data[addr - FLASH_BASE : addr - FLASH_BASE + 4] = new_bl

# Write
DST.write_bytes(bytes(data))
print(f"\nwrote {DST}")
print(f"net diff vs fw_22: {len(wrapper) + 4 + 4} bytes")
print(f"mode forced on every →active transition: {DESIRED_MODE} ({name.capitalize()})")
print(f"\nFlash with:")
print(f"  openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\")
print(f"    -c 'program {DST.name} verify reset exit 0x08000000'")
