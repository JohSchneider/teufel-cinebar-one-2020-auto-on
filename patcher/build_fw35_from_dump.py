#!/usr/bin/env python3
"""
build_fw35_from_dump.py — Teufel Cinebar One firmware patcher:
                          fw_34 (auto-on + wake-on-SPDIF) PLUS preloaded
                          user state (vol=35, bass=+8, Music mode)

This is the **recommended end-state** — supersedes fw_34 for users who want
the bar to come up at a specific, sensible volume/mode/bass without having
to first remote-control it. Inherits all of fw_34's behaviours:

  1. Bar boots directly into the *active* state on AC restore (Goal #1).
  2. Toslink receiver stays powered in standby; SPDIF activity can be sensed
     without a full wake.
  3. Idle-loop shim wakes the bar within ~25 ms of SPDIF returning, and
     puts it back to standby after ~16 consecutive monotone samples
     (no biphase transitions).
  4. DSP IC is fully powered down in standby (PB7-LOW restored).
  5. **NEW vs fw_34**: vEEPROM page 1 has two extra entries appended,
     overriding the latest persisted values for volume (35) and bass (+8).
     mode and modeExtend already default to the desired values in the
     vanilla dump (Music / ON), so they don't need explicit overrides.

What this script does to your dump:

  Step 1 (same as fw_34): apply the 4 code patches (PC15-LOW NOP,
          two shim BL retargets, two shim bodies at 0x0801E800).

  Step 2 (new for fw_35): scan your vEEPROM page 1 (file offset 0x07000)
          for the first free slot, and append two entries:
            (value=35,  id=0x2222)  ← volume
            (value=8,   id=0x3333)  ← bass
          The bar's vEEPROM read logic returns the **latest** entry per
          ID, so these overrides win on the next boot.

  Step 3: write the patched dump to <output>.

About vEEPROM and per-bar state:
  vEEPROM page 1 (0x07000-0x077FF) is an append-only log of 4-byte entries
  `(value u16, id u16)`. Each bar accumulates its own log over its lifetime
  (every volume/bass/mode change is appended). When this script runs on
  YOUR dump, it detects YOUR first free slot dynamically. If your bar has
  more history than the vanilla reference, the free slot will be deeper
  into the page — but the script handles that transparently.

  If page 1 is full (>=256 entries logged): the bar would need a page-swap
  to page 0 (0x06800-0x06FFF). This script doesn't currently implement that
  — it bails with an error so you don't silently lose state. In practice
  the page rarely fills (it's resized on each swap), and a full page is a
  sign of unusual wear; SWD-reflashing with a fresh fw_35 is then simplest.

How to use:
  1) Dump your bar's firmware:
       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "init; reset halt; flash read_bank 0 mydump.bin; exit"

  2) Patch:
       python3 build_fw35_from_dump.py mydump.bin firmware_35.bin

  3) Flash back via SWD:
       openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\
               -c "program firmware_35.bin verify reset exit 0x08000000"

  Note: the USB-MSC firmware-update path can NOT deliver fw_35's vEEPROM
  preload — the bootloader's MSC upload only writes the app region
  (0x08008000+), leaving vEEPROM untouched. So MSC-uploading fw_35 would
  give you fw_34 behaviour + whatever vEEPROM is already in your bar.
  For the preload to take effect, you must SWD-flash.

License/attribution:
  Reverse-engineering and patch design: this RE work.
  The firmware itself is © Teufel — this script does NOT redistribute it.
  Each user runs this on their own dump.

Expected code-only SHA256 (vEEPROM at 0x07000-0x077FF masked to 0xFF;
identical to fw_34's because the code patches are exactly the same — fw_35
only adds vEEPROM bytes, and those are masked when hashing code):
  input  (vanilla dump): 1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059
  output (fw_35 code):   699a9f4178d5b3aa161daeebefd797951a335485c27c872f0c7f1edfb4bdb4f1
"""

import argparse
import hashlib
import struct
import sys
from pathlib import Path


EXPECTED_INPUT_SIZE = 131072  # 128 KB

VEEPROM_PAGE1_BASE = 0x07000
VEEPROM_PAGE1_SIZE = 0x800  # 2 KB

EXPECTED_INPUT_CODE_SHA  = "1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059"
EXPECTED_OUTPUT_CODE_SHA = "699a9f4178d5b3aa161daeebefd797951a335485c27c872f0c7f1edfb4bdb4f1"

# IDs we override on top of whatever the user's bar last persisted.
PRELOAD_ENTRIES = [
    (35, 0x2222, "volume = 35"),
    (8,  0x3333, "bass   = +8"),
]


def code_sha256(data):
    """SHA256 of the firmware with vEEPROM page 1 masked to 0xFF."""
    masked = bytearray(data)
    masked[VEEPROM_PAGE1_BASE:VEEPROM_PAGE1_BASE + VEEPROM_PAGE1_SIZE] = (
        b"\xFF" * VEEPROM_PAGE1_SIZE
    )
    return hashlib.sha256(bytes(masked)).hexdigest()


# Same 4 code patches as fw_34 (= 5 patch sites because Shim 1 and Shim 2 are
# two separate entries inside the same "patch 0x1E800" tuple split into D1/D2).
CODE_PATCHES = [
    (
        0x0A836,
        "02 f0 12 ff",
        "00 bf 00 bf",
        "Standby path: NOP bl PC15-LOW (Toslink stays alive)",
    ),
    (
        0x0ACAC,
        "00 f0 e4 f8",
        "13 f0 a8 fd",
        "Redirect event-loop init bl → Shim 1 @ 0x0801E800",
    ),
    (
        0x0ACBC,
        "fe f7 5a f8",
        "13 f0 b0 fd",
        "Redirect event-loop second bl → Shim 2 @ 0x0801E820",
    ),
    (
        0x1E800,
        "ff " * 22,
        "00 b5 ec f7 39 fb 02 20 eb f7 9a ff"
        "01 46 00 20 ed f7 e4 f9 00 bd",
        "Shim 1 body (22 bytes): transition_state x2 + notify(0,1) + return",
    ),
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
            f"{EXPECTED_INPUT_SIZE} (128 KB)."
        )

    sha = code_sha256(data)
    if sha != EXPECTED_INPUT_CODE_SHA:
        print(f"WARNING: input code-SHA256 ({sha}) differs from the reference",
              file=sys.stderr)
        print(f"         vanilla dump ({EXPECTED_INPUT_CODE_SHA}).",
              file=sys.stderr)
        print(f"         (vEEPROM page 1 is masked before hashing — so volume/",
              file=sys.stderr)
        print(f"          bass/mode history doesn't affect this hash. A mismatch",
              file=sys.stderr)
        print(f"          means the code itself diverges from the known baseline.",
              file=sys.stderr)
        print(f"          Continuing with per-site byte verification...)",
              file=sys.stderr)

    failed = []
    for off, before_hex, _, comment in CODE_PATCHES:
        expected = parse_hex(before_hex)
        actual = data[off:off + len(expected)]
        if actual != expected:
            failed.append((off, expected, actual, comment))

    if failed:
        sys.exit(
            "ERROR: input doesn't match expected vanilla baseline at:\n" +
            "\n".join(
                f"  0x{off:05X}  expected {expected.hex()}, got {actual.hex()}"
                f"\n             ({comment})"
                for off, expected, actual, comment in failed
            )
        )


def apply_code_patches(data):
    img = bytearray(data)
    print(f"\nStep 1: Applying {len(CODE_PATCHES)} code patches (= same as fw_34):")
    for off, _, after_hex, comment in CODE_PATCHES:
        new = parse_hex(after_hex)
        img[off:off + len(new)] = new
        print(f"  0x{off:05X}  ({len(new):>3} bytes)  {comment}")
    return img


def find_first_free_vEEPROM_slot(img):
    """Scan vEEPROM page 1 and return the offset (within the page) of the
    first 0xFFFFFFFF entry. Returns None if the page is full."""
    for off in range(4, VEEPROM_PAGE1_SIZE, 4):
        val, id_ = struct.unpack_from("<HH", img,
                                      VEEPROM_PAGE1_BASE + off)
        if val == 0xFFFF and id_ == 0xFFFF:
            return off
    return None


def dump_existing_state(img):
    """Read out the latest value per ID in vEEPROM page 1 — for the user's
    information so they can see what'll be overridden."""
    latest = {}
    for off in range(4, VEEPROM_PAGE1_SIZE, 4):
        val, id_ = struct.unpack_from("<HH", img,
                                      VEEPROM_PAGE1_BASE + off)
        if val == 0xFFFF and id_ == 0xFFFF:
            break
        latest[id_] = val

    if not latest:
        print("  (vEEPROM page 1 is empty — fresh bar?)")
        return

    id_names = {
        0x1111: "power_state",
        0x2222: "volume",
        0x3333: "bass",
        0x4444: "modeExtend",
        0x5555: "audio_mode",
        0x6666: "(unknown)",
    }
    for id_, val in sorted(latest.items()):
        name = id_names.get(id_, f"ID 0x{id_:04X}")
        print(f"  ID 0x{id_:04X} ({name:>12s}) = {val} (0x{val:04X})")


def append_preload(img):
    print(f"\nStep 2: vEEPROM preload — scanning page 1 for current state...")
    first_free = find_first_free_vEEPROM_slot(img)
    if first_free is None:
        sys.exit(
            "ERROR: vEEPROM page 1 is full. The bar would need a page-swap to\n"
            "       page 0 (0x06800-0x06FFF), which this script doesn't currently\n"
            "       implement. A full page is unusual — your bar may have been\n"
            "       heavily used. SWD-reflashing a fresh fw_35 (which won't have\n"
            "       any per-bar accumulated history) is the cleanest workaround.\n"
        )

    print(f"  Latest persisted values in YOUR dump's vEEPROM:")
    dump_existing_state(img)
    print(f"\n  First free slot: page1 + 0x{first_free:03X} "
          f"(flash 0x{0x08007000+first_free:08X})")

    print(f"\n  Appending {len(PRELOAD_ENTRIES)} new entries (these will override the latest):")
    off = first_free
    for val, id_, label in PRELOAD_ENTRIES:
        print(f"    page1 + 0x{off:03X}: value=0x{val:04X}, id=0x{id_:04X}  ← {label}")
        struct.pack_into("<HH", img, VEEPROM_PAGE1_BASE + off, val, id_)
        off += 4

    return img


def main():
    ap = argparse.ArgumentParser(
        description="Patch a vanilla Cinebar One firmware dump → fw_35 "
                    "(fw_34 + preloaded vol=35 / Music / bass=+8).",
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
    print(f"  ✓ baseline verification passed at all {len(CODE_PATCHES)} code-patch sites")

    img = apply_code_patches(data)
    img = append_preload(img)

    args.output.write_bytes(bytes(img))

    sha = code_sha256(img)
    print(f"\nWrote {len(img)} bytes to {args.output}")
    print(f"  Code SHA256 (vEEPROM masked): {sha}")
    if sha == EXPECTED_OUTPUT_CODE_SHA:
        print(f"  ✓ matches expected reference code SHA")
    else:
        print(f"  ! reference code SHA is {EXPECTED_OUTPUT_CODE_SHA}")
        print(f"    (mismatch means input code diverged outside patch sites;")
        print(f"     your bar may be a different firmware revision.)")

    print(f"\nReady to flash with:")
    print(f"  openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \\")
    print(f"          -c \"program {args.output} verify reset exit 0x08000000\"")
    print(f"\nNote: SWD-flash only. USB-MSC update would not deliver the vEEPROM")
    print(f"      preload (MSC only writes the app region at 0x08008000+).")


if __name__ == "__main__":
    main()
