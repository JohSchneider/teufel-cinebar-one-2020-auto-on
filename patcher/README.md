# Teufel Cinebar One — Firmware Patchers

Stand-alone Python scripts to patch your own vanilla firmware dump into
useful variants. Designed for sharing: each script is self-contained, has
no external dependencies (stdlib only), and never redistributes the
copyrighted firmware itself — you bring your own dump.

## What you need

* A Teufel Cinebar One soundbar (STM32F072CBT6 microcontroller).
* SWD wiring (the bar exposes the SWD pads internally; an ST-Link is the
  cheapest tool that works).
* `openocd` for flash read/write.
* Python 3.7+ (stdlib only).

## Step 1 — Dump your bar's firmware

Connect ST-Link to the bar's SWD pads, then:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "init; reset halt; flash read_bank 0 mydump.bin; exit"
```

Result: a 131072-byte file (128 KB). Keep this safe as your rollback.

**Verify the dump** — note: a raw `sha256sum` will NOT match between bars
because the **vEEPROM region** at `0x07000-0x077FF` holds per-bar user state
(volume history, bass/mode persistence, etc.) and varies even between
otherwise-identical bars. The patcher computes a "**code SHA256**" with that
region masked to `0xFF`, and that hash should match across all bars on the
same firmware revision:

```
code SHA256 vanilla dump: 1846aac934ee815b587a117e3885442ed5ce33dd3481ca6a187698360622c059
```

The patcher prints your input's code SHA and compares it to the reference.
If they differ, your bar may be a different firmware revision — the script
will then refuse to patch and tell you exactly which bytes diverge, so you
can decide whether to proceed.

## Step 2 — Patch

Two variants are available:

### `build_fw05_from_dump.py` — Goal #1: auto-boot to active

Smallest change. After AC restore, bar boots directly into the active
audio state instead of factory standby. IR remote still works normally.

```bash
python3 build_fw05_from_dump.py mydump.bin firmware_05.bin
```

26 bytes changed across 2 sites. Reversible by reflashing your original
dump.

### `build_fw22_from_dump.py` — Goal #1 + Goal #2: + wake-on-SPDIF

Includes everything from fw_05, plus:
- Audio rail stays powered in standby (so SPDIF can be sensed)
- A polling shim watches PA4 in the idle loop
- Bar auto-wakes within ~25 ms of audio returning after silence
- Bar auto-suspends after ~15 min of silence (uses the chip's own
  SPDIF carrier-detect hysteresis)

```bash
python3 build_fw22_from_dump.py mydump.bin firmware_22.bin
```

122 bytes changed across 6 sites. The IR remote is no longer needed for
day-to-day use — the bar follows your source.

## Step 3 — Flash

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "program firmware_22.bin verify reset exit 0x08000000"
```

(Replace `firmware_22.bin` with `firmware_05.bin` if you chose the smaller
patch.)

## Step 4 — Verify (optional)

Each script prints the SHA256 of its output. If yours matches the reference
hash printed by the script's `--help` output, you have a byte-identical
copy of the binary the author tested on their bar.

## Rollback

To return to factory behavior, reflash your original `mydump.bin`:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "program mydump.bin verify reset exit 0x08000000"
```

## Safety

* Each script verifies the input byte-for-byte at every patch site before
  writing any output. Wrong firmware version, already-patched dump, or a
  truncated file → script aborts without producing output.
* No connection to the bar is made by the patchers themselves; they're
  pure file-to-file transformations. The flashing step is a separate
  manual command, fully under your control.
* If something goes wrong during flashing (interrupted write, brownout):
  the bar's bootloader is in factory ROM and can't be bricked through
  this path. Reconnect ST-Link and reflash either the patched or the
  original dump.

## What the patches actually do

Open the Python files — each one has a detailed header explaining every
patch site, the original bytes, the new bytes, and why. The reverse-engineering
notes are in the project's `FIRMWARE_VARIANTS.md` and `SHIMS.md`.

## License

These patcher scripts are made available under the same terms as the
reverse-engineering work that produced them. The firmware itself is © Teufel
and is NOT redistributed — you bring your own dump.

No warranty. If it bricks your bar, you broke your bar.
