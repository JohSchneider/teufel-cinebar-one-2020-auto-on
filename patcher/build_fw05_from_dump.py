#!/usr/bin/env python3
"""
build_fw05_from_dump.py — Teufel Cinebar One firmware patcher: Goal #1 (auto-on)

Patches a vanilla 128 KB STM32F072CBT6 firmware dump from a Teufel Cinebar One
soundbar to produce "firmware_05_autoboot-active-on-power.bin".

What it does:
  Makes the bar boot directly into the *active* (audio-playing) state on AC
  restore, instead of the factory behavior of waking up in standby and
  requiring an IR-power press.

How to use:
  1) Dump your bar's firmware from flash via SWD + OpenOCD + ST-Link, e.g.:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "init; reset halt; flash read_bank 0 mydump.bin; exit"

     Expected file: 131072 bytes (128 KB).

  2) Run this script:

       python3 build_fw05_from_dump.py mydump.bin firmware_05.bin

  3) Flash the output back:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "program firmware_05.bin verify reset exit 0x08000000"

What changes (3 small patches, 24 bytes total):

  - 0x0800ACAC (4 bytes): retarget the `bl XXX` at event-loop init from the
    original "no-op" callee to our new Shim 1 at 0x0801E800. (3 bytes of the
    BL encoding change; the 4th stays the same.)

  - 0x0801E800 (21 bytes): write Shim 1 — a small Thumb function that calls
    `transition_state(2)` (= go-active) and then `notify(0, 1)` so the rest
    of the firmware's event loop sees the bar as actively powered on.

There is NO change to the LED/IR logic — the IR remote still works normally
once the bar is up.

Safety:
  * Input file is verified byte-for-byte at each patch site BEFORE writing
    any output. If the bytes don't match the expected baseline, the script
    aborts without producing output. This protects against patching an
    already-modified dump, the wrong firmware version, or a corrupted file.
  * SHA256 of the output is printed for verification; share that hash with
    other users so they can confirm their patched image matches.

License/attribution:
  Reverse-engineering and patch design: this RE work.
  The firmware itself is © Teufel — this script does NOT redistribute it.
  Each user runs this on their own dump.

Expected code-only SHA256 (with vEEPROM at 0x07000-0x077FF masked to 0xFF;
the vEEPROM region holds per-bar user state and is not part of the code):
  input  (vanilla dump): 1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059
  output (firmware_05):  2e8694a79b49a288f071884ab4e31f11c6697a0b80c4cea962ca878e608bedc9
"""

import argparse
import hashlib
import sys
from pathlib import Path


# ----------------------------------------------------------------------------
# Patch definitions for fw_05 (= original + Goal #1: auto-on)
#
# Each entry: (file_offset, expected_bytes_before, new_bytes_after, comment)
# All byte sequences in hex strings, whitespace-tolerant.
# ----------------------------------------------------------------------------

EXPECTED_INPUT_SIZE = 131072  # 128 KB

# The vEEPROM region at 0x07000-0x077FF holds user-specific state (volume,
# bass, mode, etc., as a ST-style append-only log). It diverges between two
# bars even on identical "code" firmware, so we hash the file with that
# region masked to 0xFF. This "code-only" hash is the same across all bars
# running the same firmware revision.
VEEPROM_START = 0x07000
VEEPROM_END   = 0x07800  # exclusive

EXPECTED_INPUT_CODE_SHA  = "1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059"
EXPECTED_OUTPUT_CODE_SHA = "2e8694a79b49a288f071884ab4e31f11c6697a0b80c4cea962ca878e608bedc9"


def code_sha256(data):
    """SHA256 of the firmware with the vEEPROM region masked to 0xFF."""
    masked = bytearray(data)
    masked[VEEPROM_START:VEEPROM_END] = b"\xFF" * (VEEPROM_END - VEEPROM_START)
    return hashlib.sha256(bytes(masked)).hexdigest()

PATCHES = [
    # ── (1) Redirect the BL at the event-loop init to our shim ──
    #
    # Original: bl 0x0800AE7C (a no-op-ish callee in vanilla firmware)
    # New:      bl 0x0801E800 (Shim 1, in previously-unused flash)
    #
    # Note bytes 0 and 2..3 change; byte 1 (0xF0) is the same in both
    # encodings, so the 4-byte BL appears as two non-contiguous changes
    # in cmp output (1 byte at +0, 2 bytes at +2).
    (
        0x0ACAC,
        "00 f0 e4 f8",
        "13 f0 a8 fd",
        "Redirect event-loop init's first bl to Shim 1 @ 0x0801E800",
    ),
    # ── (2) Shim 1 in previously-unused flash at 0x0801E800 ──
    #
    # 22 bytes of Thumb code:
    #   push {lr}
    #   bl     transition_state         ; first call, r0=whatever — likely
    #                                   ;   no-ops because state already ==
    #                                   ;   what was passed; needed to align
    #                                   ;   the dispatcher's mode
    #   movs r0, #2
    #   bl     transition_state         ; second call, r0=2 → go ACTIVE
    #   mov r1, r0                      ; r1 = returned state
    #   movs r0, #0
    #   bl     notify                   ; notify(0, state) so event-loop sees
    #                                   ;   the active state
    #   pop {pc}
    #
    # Notice that the 12th byte (offset 11) of the new code is 0xFF — it's
    # the high byte of the BL halfword (0xFF9A) — which happens to be the
    # same as virgin/erased flash. That's not a bug; the verify+patch logic
    # writes the byte explicitly anyway for safety.
    (
        0x1E800,
        "ff " * 22,                            # 22 bytes of virgin flash
        "00 b5 ec f7 39 fb 02 20 eb f7 9a ff"  # push, bl, movs, bl
        "01 46 00 20 ed f7 e4 f9 00 bd",        # mov, movs, bl, pop
        "Shim 1 body (22 bytes): transition_state x2 + notify(0,1) + return",
    ),
]


def parse_hex(s):
    """Parse a hex byte sequence (whitespace-tolerant) into bytes."""
    return bytes.fromhex(s.replace(" ", "").replace("\n", ""))


def verify_input(data, src_path):
    """Verify the input matches the vanilla baseline at every patch site."""
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
    """Apply all patches in order. Returns the patched bytearray."""
    img = bytearray(data)
    print(f"\nApplying {len(PATCHES)} patch{'es' if len(PATCHES) != 1 else ''}:")
    for off, _, after_hex, comment in PATCHES:
        new = parse_hex(after_hex)
        img[off:off + len(new)] = new
        print(f"  0x{off:05X}  ({len(new):>3} bytes)  {comment}")
    return img


def main():
    ap = argparse.ArgumentParser(
        description="Patch a vanilla Cinebar One firmware dump to produce "
                    "fw_05 (auto-on at AC restore).",
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

    verify_input(data, args.input)
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
