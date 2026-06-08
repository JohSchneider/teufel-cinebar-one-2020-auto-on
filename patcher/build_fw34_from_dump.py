#!/usr/bin/env python3
"""
build_fw34_from_dump.py — Teufel Cinebar One firmware patcher:
                          Goal #1 (auto-on) + Goal #2 (wake-on-SPDIF)
                          with minimal NOP set (DSP actually off in standby)

This is the **productive** variant — supersedes the older fw_22 patcher.

What it does:
  1. Bar boots directly into the *active* state on AC restore (Goal #1).
  2. The Toslink receiver stays powered in standby (PC15 stays HIGH), so
     SPDIF activity can be sensed without a full wake.
  3. A small polling shim in the idle loop watches PA4 (the actual SPDIF
     data carrier). When SPDIF returns after silence, bar wakes within
     ~25 ms.
  4. When SPDIF goes silent (~16 consecutive monotone samples = no biphase
     transitions), bar transitions back to standby.
  5. In standby the DSP IC is **fully powered down** (its power rail goes
     LOW via the original PB7-LOW write), not just held in reset like the
     older fw_22.

Why fw_34 instead of fw_22:
  The original fw_22 (predecessor) NOPed three "→ LOW" writes in the
  standby path (PA2, PB7, PC15) on the working hypothesis that all three
  were needed to keep the Toslink rail alive. That hypothesis turned out
  to be over-broad: bench bisection (2026-06-08, via direct GDB GPIO
  toggling on a live bar) showed that PC15 alone is the Toslink-rail
  master. PA2 has no observable effect on the rail or audio. PB7 controls
  the DSP IC's power rail — so by NOPing PB7-LOW, fw_22 was keeping the
  DSP powered (just held in reset) instead of letting it actually power
  down.

  fw_34 fixes this by NOPing only the PC15-LOW write at file offset
  0x0A836, restoring the PA2-LOW and PB7-LOW writes at 0x0A81A/0x0A81E.
  Result: Toslink stays alive, DSP fully off, current draw in standby
  is materially lower than fw_22.

How to use:
  1) Dump your bar's firmware from flash via SWD + OpenOCD + ST-Link:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "init; reset halt; flash read_bank 0 mydump.bin; exit"

     Expected file: 131072 bytes (128 KB).

  2) Run this script:

       python3 build_fw34_from_dump.py mydump.bin firmware_34.bin

  3) Flash the output back:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "program firmware_34.bin verify reset exit 0x08000000"

Patches (4 sites, 114 bytes total — vs fw_22's 122):

  A. NOP the PC15-LOW write in transition_state(1)              @ 0x0800A836
     Replaces 4-byte `bl GPIO_WriteBit(GPIOC, 0x8000, 0)` with `nop nop`.
     PC15 stays HIGH in standby, keeping the Toslink-receiver rail at 3V
     so PA4 (the SPDIF data line) still receives biphase signal.

  B. Auto-on shim redirect                                      @ 0x0800ACAC
     Retargets a 4-byte `bl` at the event-loop init to Shim 1.

  C. Wake-on-SPDIF shim redirect                                @ 0x0800ACBC
     Retargets a second `bl` at the event-loop init to Shim 2.

  D. Shim 1 (22 bytes) + Shim 2 (84 bytes)                      @ 0x0801E800
     Both shims live in previously-unused (factory-erased) flash.
     - Shim 1 calls `transition_state(2)` at boot to come up active.
     - Shim 2 polls PA4 in the idle loop and posts a state-toggle event
       on silence (auto-suspend) or activity (wake).

The PA2-LOW and PB7-LOW writes in the standby path are LEFT INTACT — that's
the key difference from fw_22.

Safety:
  * Input is verified byte-for-byte at every patch site before any output
    is written. If the input is already modified, or is a different
    firmware revision, the script aborts cleanly.
  * SHA256 of the output is printed for verification.

License/attribution:
  Reverse-engineering and patch design: this RE work.
  The firmware itself is © Teufel — this script does NOT redistribute it.
  Each user runs this on their own dump.

Expected code-only SHA256 (with vEEPROM at 0x07000-0x077FF masked to 0xFF;
the vEEPROM region holds per-bar user state and is not part of the code):
  input  (vanilla dump): 1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059
  output (firmware_34):  699a9f4178d5b3aa161daeebefd797951a335485c27c872f0c7f1edfb4bdb4f1
"""

import argparse
import hashlib
import sys
from pathlib import Path


EXPECTED_INPUT_SIZE = 131072  # 128 KB

VEEPROM_START = 0x07000
VEEPROM_END   = 0x07800  # exclusive

EXPECTED_INPUT_CODE_SHA  = "1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059"
EXPECTED_OUTPUT_CODE_SHA = "699a9f4178d5b3aa161daeebefd797951a335485c27c872f0c7f1edfb4bdb4f1"


def code_sha256(data):
    """SHA256 of the firmware with the vEEPROM region masked to 0xFF."""
    masked = bytearray(data)
    masked[VEEPROM_START:VEEPROM_END] = b"\xFF" * (VEEPROM_END - VEEPROM_START)
    return hashlib.sha256(bytes(masked)).hexdigest()


PATCHES = [
    # ── (A) NOP the PC15-LOW write in transition_state(1) ──
    # PC15 is the Toslink-receiver rail master (sole — confirmed via direct
    # GPIO bisection on bench 2026-06-08). Keeping PC15 HIGH in standby keeps
    # PA4 receiving SPDIF biphase data, enabling wake-on-SPDIF.
    (
        0x0A836,
        "02 f0 12 ff",
        "00 bf 00 bf",
        "Standby path: NOP bl PC15-LOW (Toslink stays alive)",
    ),
    # ── (B) Auto-on shim redirect ──
    (
        0x0ACAC,
        "00 f0 e4 f8",
        "13 f0 a8 fd",
        "Redirect event-loop init bl → Shim 1 @ 0x0801E800",
    ),
    # ── (C) Wake-on-SPDIF shim redirect ──
    (
        0x0ACBC,
        "fe f7 5a f8",
        "13 f0 b0 fd",
        "Redirect event-loop second bl → Shim 2 @ 0x0801E820",
    ),
    # ── (D1) Shim 1 (22 bytes): auto-on at boot ──
    (
        0x1E800,
        "ff " * 22,
        "00 b5 ec f7 39 fb 02 20 eb f7 9a ff"
        "01 46 00 20 ed f7 e4 f9 00 bd",
        "Shim 1 body (22 bytes): transition_state x2 + notify(0,1) + return",
    ),
    # ── (D2) Shim 2 (84 bytes): wake-on-SPDIF + auto-suspend ──
    (
        0x1E820,
        "ff " * 84,
        "ff b5 11 4c 20 78 01 28 1a d1 10 4d 10 4e 10 22"
        "33 68 13 40 00 24 0f 21 30 68 10 40 98 42 00 d0"
        "01 24 01 39 f8 d1 00 2c 02 d1 01 20 a8 70 07 e0"
        "a8 78 00 28 04 d0 00 20 a8 70 02 20 ec f7 50 f9"
        "ff bc ea f7 87 fa 00 bd dc 25 00 20 04 25 00 20"
        "10 00 00 48",
        "Shim 2 body (84 bytes): wake-on-SPDIF + auto-suspend on silence",
    ),
]


def parse_hex(s):
    return bytes.fromhex(s.replace(" ", "").replace("\n", ""))


def verify_input(data):
    if len(data) != EXPECTED_INPUT_SIZE:
        sys.exit(
            f"ERROR: input file size is {len(data)} bytes, expected "
            f"{EXPECTED_INPUT_SIZE} (128 KB). Are you sure this is a full "
            f"STM32F072CBT6 dump?"
        )

    sha = code_sha256(data)
    if sha != EXPECTED_INPUT_CODE_SHA:
        print(f"WARNING: input code-SHA256 ({sha}) does not match the reference",
              file=sys.stderr)
        print(f"         vanilla dump ({EXPECTED_INPUT_CODE_SHA}).", file=sys.stderr)
        print(f"         (Note: the vEEPROM region at 0x07000-0x077FF is masked",
              file=sys.stderr)
        print(f"          before hashing — so volume/bass/mode history doesn't",
              file=sys.stderr)
        print(f"          affect this hash. A mismatch means the actual code",
              file=sys.stderr)
        print(f"          diverges. Continuing with per-site byte verification...)",
              file=sys.stderr)

    failed = []
    for off, before_hex, _, comment in PATCHES:
        expected = parse_hex(before_hex)
        actual = data[off:off + len(expected)]
        if actual != expected:
            failed.append((off, expected, actual, comment))

    if failed:
        sys.exit(
            "ERROR: input file doesn't match the expected vanilla baseline at "
            "the following patch sites:\n" +
            "\n".join(
                f"  0x{off:05X}  expected {expected.hex()}, got {actual.hex()}"
                f"\n             ({comment})"
                for off, expected, actual, comment in failed
            ) +
            "\nRefusing to patch. The input dump may already be modified, "
            "or it may be from a different firmware version."
        )


def apply_patches(data):
    img = bytearray(data)
    print(f"\nApplying {len(PATCHES)} patches:")
    for off, _, after_hex, comment in PATCHES:
        new = parse_hex(after_hex)
        img[off:off + len(new)] = new
        print(f"  0x{off:05X}  ({len(new):>3} bytes)  {comment}")
    return img


def main():
    ap = argparse.ArgumentParser(
        description="Patch a vanilla Cinebar One firmware dump → fw_34 "
                    "(auto-on + wake-on-SPDIF + DSP off in standby).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input", type=Path,
                    help="Vanilla 128 KB firmware dump (your own, read via SWD)")
    ap.add_argument("output", type=Path,
                    help="Output file for the patched firmware")
    args = ap.parse_args()

    if not args.input.is_file():
        sys.exit(f"ERROR: input file not found: {args.input}")

    data = args.input.read_bytes()
    print(f"Read {len(data)} bytes from {args.input}")

    verify_input(data)
    print(f"  ✓ baseline verification passed at all {len(PATCHES)} patch sites")

    out = apply_patches(data)
    args.output.write_bytes(bytes(out))

    sha = code_sha256(out)
    print(f"\nWrote {len(out)} bytes to {args.output}")
    print(f"  Code SHA256 (vEEPROM masked): {sha}")
    if sha == EXPECTED_OUTPUT_CODE_SHA:
        print(f"  ✓ matches expected reference output")
    else:
        print(f"  ! reference code SHA256 is {EXPECTED_OUTPUT_CODE_SHA}")
        print(f"    (mismatch means input code diverges from the known baseline")
        print(f"     outside the patch sites — your bar may be a different")
        print(f"     firmware revision; flash with caution.)")

    print(f"\nReady to flash with:")
    print(f"  openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\")
    print(f"          -c \"program {args.output} verify reset exit 0x08000000\"")


if __name__ == "__main__":
    main()
