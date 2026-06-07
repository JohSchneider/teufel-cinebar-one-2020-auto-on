#!/usr/bin/env python3
"""
build_fw22_from_dump.py — Teufel Cinebar One firmware patcher:
                          Goal #1 (auto-on) + Goal #2 (wake-on-SPDIF)

Patches a vanilla 128 KB STM32F072CBT6 firmware dump from a Teufel Cinebar One
soundbar to produce the productive "firmware_22_wake-on-spdif.bin".

What it does:
  1. Bar boots directly into the *active* state on AC restore (Goal #1).
  2. Bar keeps the audio rail (PA2/PB7/PC15) powered even in standby, so
     SPDIF activity can be detected without a full wake.
  3. A small polling shim in the idle loop watches PA4 (the actual SPDIF
     data carrier — yes, *PA4*, not PA3 as the firmware's own
     `is_audio_active()` claims). When SPDIF returns after a stretch of
     silence, the bar transitions to active.
  4. When SPDIF goes silent (~16 consecutive HIGH-or-LOW monotone samples
     = no biphase transitions), the bar transitions back to standby.

Net effect: AC restore → bar plays audio. Source going silent → bar
suspends. Audio returning → bar wakes within ~25 ms. **IR remote is no
longer needed in normal use.**

How to use:
  1) Dump your bar's firmware from flash via SWD + OpenOCD + ST-Link:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "init; reset halt; flash read_bank 0 mydump.bin; exit"

     Expected file: 131072 bytes (128 KB).

  2) Run this script:

       python3 build_fw22_from_dump.py mydump.bin firmware_22.bin

  3) Flash the output back:

       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "program firmware_22.bin verify reset exit 0x08000000"

Patches (4 sites, 122 bytes total):

  A. NOP the standby-path GPIO writes (PA2, PB7, PC15 → LOW)        @ 0x0800A81A, 0x0800A836
     Three `bl GPIO_WriteBit(..., LOW)` calls in `transition_state(1)`
     are replaced with `nop nop`. The audio rail stays at 3.3V across
     the standby transition. This is what enables PA4 to still sense
     SPDIF activity while the bar is "off."

  B. Auto-on shim redirect                                          @ 0x0800ACAC
     Retarget a 4-byte `bl` at the event-loop init to Shim 1 (same
     mechanism as firmware_05).

  C. Wake-on-SPDIF shim redirect                                    @ 0x0800ACBC
     Retarget a second `bl` at the event-loop init to Shim 2.

  D. Shim 1 (22 bytes) + Shim 2 (84 bytes)                          @ 0x0801E800
     Both shims live in previously-unused (factory-erased) flash.
     - Shim 1 calls `transition_state(2)` to wake at boot.
     - Shim 2 polls 16 samples of PA4 in the idle loop. If all 16
       are monotone (= no biphase transitions = no audio), increments
       a counter; when the counter passes the silence threshold, calls
       `post_event_type0(2)` to wake/standby-toggle (which, when the
       bar is already active and the source stays silent, sets the
       auto-suspend timer). The same shim also wakes the bar from
       standby when activity returns.

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
  output (firmware_22):  8a3a8532496d007ffbfb06f8ca6f03d4794e9900704574a0cc70f0287520e4d8
"""

import argparse
import hashlib
import sys
from pathlib import Path


EXPECTED_INPUT_SIZE = 131072  # 128 KB

# The vEEPROM region at 0x07000-0x077FF holds user-specific state (volume,
# bass, mode, etc., as a ST-style append-only log). It diverges between two
# bars even on identical "code" firmware, so we hash the file with that
# region masked to 0xFF. This "code-only" hash is the same across all bars
# running the same firmware revision.
VEEPROM_START = 0x07000
VEEPROM_END   = 0x07800  # exclusive

EXPECTED_INPUT_CODE_SHA  = "1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059"
EXPECTED_OUTPUT_CODE_SHA = "8a3a8532496d007ffbfb06f8ca6f03d4794e9900704574a0cc70f0287520e4d8"


def code_sha256(data):
    """SHA256 of the firmware with the vEEPROM region masked to 0xFF."""
    masked = bytearray(data)
    masked[VEEPROM_START:VEEPROM_END] = b"\xFF" * (VEEPROM_END - VEEPROM_START)
    return hashlib.sha256(bytes(masked)).hexdigest()


PATCHES = [
    # ── (A1) NOP the two `bl GPIO_WriteBit(PA2/PB7, LOW)` in transition_state(1) ──
    (
        0x0A81A,
        "06 f0 71 fe 01 f0 35 fe",
        "00 bf 00 bf 00 bf 00 bf",
        "Standby path: NOP bl PA2-LOW + bl PB7-LOW",
    ),
    # ── (A2) NOP the `bl GPIO_WriteBit(PC15, LOW)` in transition_state(1) ──
    (
        0x0A836,
        "02 f0 12 ff",
        "00 bf 00 bf",
        "Standby path: NOP bl PC15-LOW",
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
    # ── (D1) Shim 1: same as in fw_05 (auto-on at boot) ──
    (
        0x1E800,
        "ff " * 22,
        "00 b5 ec f7 39 fb 02 20 eb f7 9a ff"
        "01 46 00 20 ed f7 e4 f9 00 bd",
        "Shim 1 body (22 bytes): transition_state x2 + notify(0,1) + return",
    ),
    # ── (D2) Shim 2: wake-on-SPDIF polling shim (84 bytes incl. 2 alignment-FF bytes) ──
    #
    # Function pointer encoded at 0x0801E821 (Thumb-bit set), code starts at 0x0801E820.
    #
    # Pseudocode:
    #   void shim2() {
    #       push {r0-r7, lr}
    #       state = *state_ptr;              // 0x200025DC
    #       autostandby = *autostandby_ptr;  // 0x20002504
    #       if (state[0] != 1) goto wake_check;  // only active path matters
    #       gpioa_idr_ptr = (uint32_t*)0x48000010;
    #       monotone_count = 0;
    #       sample_bit = 1 << 4;             // bit 4 = PA4
    #       last = (*gpioa_idr & sample_bit);
    #       for (i = 0; i < 15; i++) {
    #           cur = (*gpioa_idr & sample_bit);
    #           if (cur != last) goto not_silent;
    #           // wait a few cycles, etc.
    #       }
    #       autostandby[silence_seen] = 1;   // silence latch
    #     not_silent:
    #       autostandby[last_toggle_sample] = (sample_bit ? 1 : 0);
    #     wake_check:
    #       if (autostandby[silence_seen]) {
    #           autostandby[silence_seen] = 0;
    #           post_event_type0(2);          // toggle: wake-from-standby OR start
    #                                         //   auto-suspend countdown
    #       }
    #       pop {r0-r7, pc}
    #
    # See SHIMS.md for the annotated Thumb disassembly.
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
        description="Patch a vanilla Cinebar One firmware dump → fw_22 "
                    "(auto-on + wake-on-SPDIF).",
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
