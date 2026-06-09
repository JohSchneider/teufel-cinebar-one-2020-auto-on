# Teufel Cinebar One — USB MSC firmware-update protocol

This document captures the complete reverse-engineered USB-MSC firmware-upload protocol on the Teufel Cinebar One (STM32F072CBT6, bootloader 1.1, firmware 0.49 build 5100). All findings were live-validated on 2026-06-09 by:

- (Boot stage) entering MSC mode via the fw_38 bootloader patch
- (Upload stage) writing a 96 KB self-identifying test pattern and verifying via SWD that every byte landed at its expected flash address
- (Reset stage) confirming the type-0 file trigger fires `SCB->AIRCR = SYSRESETREQ`

## TL;DR — what works

| Step | Mechanism | Verified |
|---|---|---|
| Enter MSC mode | Bootloader sees PA1 LOW at boot (or app-validity check fails) | ✓ via fw_38 patch and live-tested |
| MSC enumerates | USB device class MSC, VID `0x2CC2`, PID `0x0004`, SCSI vendor "TEUFEL", model "CINEBAR COMPACT" | ✓ via `lsusb -v` |
| Volume mounts | 264 KB FAT12 volume labeled "Teufel CBO" | ✓ via `mount` |
| Upload a firmware | Drop a properly-structured `.bin` file on the volume | ✓ 96 KB transferred byte-perfect |
| Reset to new firmware | Drop a separate 1-byte file containing `0x00` | ✓ triggers SCB->AIRCR SYSRESETREQ |

## Bootloader / Application split

```
Flash 0x08000000-0x08007FFF    BOOTLOADER       (32 KB, never erased by MSC)
Flash 0x08008000-0x0801FFFF    APPLICATION      (96 KB, erased+rewritten by MSC update)
```

The bootloader at `0x08000000` is the chip's reset target. Its `main()` lives at flash `0x080039D4` and either jumps to the application (`bl 0x08002DB8` at `0x08003A92`) or enters the USB-MSC firmware-update path (`bl 0x08003AD0`+) based on:

1. **PA1 read at boot (`0x08003A6C`):** if LOW → skip app, enter wait loop then MSC
2. **App validity check (`*(0x08008000) & mask == 0x20000000`):** if FAILS → enter MSC; if PASSES → `boot_jump` to app

To force MSC mode by firmware patch, fw_38 flips the conditional `bne` at `0x08003A88` to unconditional `b` (one byte: `0xD1 → 0xE0` at file offset `0x3A89`).

## Storage layer — synthesized FAT12

The bootloader implements just enough FAT12 to expose a single read-only `VERSION.TXT` containing runtime-filled firmware/bootloader/DSP version strings.

```
FAT12 layout:
  BytsPerSec   = 512
  SecPerClus   = 1
  NumFATs      = 1   (unusual — normally 2 for redundancy)
  RootEntCnt   = 16
  TotSec       = 516 (= 264 KB)
  Cluster size = 512 bytes

  Sector 0       Boot sector (BPB + boot code stub)
  Sector 1-2     FAT (2 sectors)
  Sector 3       Root directory (16 entries × 32 B)
  Sector 4       Data cluster 2 → VERSION.TXT (synthesized template at runtime)
  Sector 5+      Data area — for sectors < 5 reads pull from baked flash image;
                 for sector >= 5, READ returns synthesized 0x30 ('0') fill while
                 WRITE goes through the firmware-update state machine.
```

The "FAT12 image" the bootloader returns for sectors 0-4 lives in RAM at `~0x2000043D` (initialized by `__scatterload` at boot from a decompression source in flash).

### Storage backend (function-pointer table)

When the USB MSC class handler dispatches READ(10) or WRITE(10), it calls function pointers from a table at RAM `0x20000130`:

```
offset +0   0x08002D7E  init (calls 0x08000384)
offset +4   0x08002D6C  is_ready helper
offset +8   0x08002D88  NO-OP — always returns 0
offset +12  0x08002D8C  NO-OP — always returns 0
offset +16  0x08002D90  READ wrapper (calls 0x08000234)
offset +20  0x08002DA2  WRITE wrapper (calls 0x0800025C)
offset +24  0x08002D7A  NO-OP — always returns 0
```

The two NO-OPs at +8 and +12 are vestigial — they're invoked by the WRITE(10) handler at `0x08002CD6` and `0x08002CEE` before the actual sector handling. Always returning 0 means "proceed".

### READ handler (`0x08000234`)

```c
read(uint32_t sector, void *dst, uint32_t length) {
    if (sector < 5) {
        // Sectors 0..4 = FAT12 image baked into RAM
        memcpy(dst, FAT12_IMAGE_RAM_BASE + sector*512, length*512);
    } else {
        // Sectors 5+ = synthesized — fill with 0x30 ('0') for length*512 bytes
        memset(dst, 0x30, length*512);
    }
    return 0;
}
```

The `0x30` synthesis is why any file the host creates appears to "contain" ASCII zeros when read back — the bootloader has no real storage for it. The data area is purely a write sink for the update protocol.

### WRITE handler (`0x0800025C`) — THE UPDATE PROTOCOL

For sectors 0-4, writes go to the FAT12 RAM image (so file metadata creation works at the FAT level — but the data sector content is not preserved between accesses).

For sectors >= 5, the bootloader's update state machine kicks in:

```
WRITE(sector >= 5):
  if state[+12] == 0xFFFFFFFF (-1, "initial"):
    // FIRST sector with type byte: parse header
    type_byte = data[0]
    val1      = BE32(data[1..4])   // length for type 2
    val2      = BE32(data[5..8])   // stored but never read by any handler
    state[+12] = val1               // becomes "remaining bytes"
    
    if type_byte == 0:
      // TYPE 0: REBOOT
      → bl 0x08000E0C — writes SCB->AIRCR = 0x05FA0004 → SYSRESETREQ
      (instruction at 0x08000E0C is `dsb sy; ldr r0, =0x05FA0004; ldr r1, =SCB_AIRCR; str r0, [r1, #12]; dsb sy; b .`)
      
    if type_byte == 2:
      // TYPE 2: BEGIN_FLASH_UPDATE
      → bl 0x08003C80 with arg = val1 (= length)
      - Validate: length ≤ 0x18000 (96 KB) AND 4-byte aligned, else error
      - state.mode = 2 (= WRITE_IN_PROGRESS)
      - state.length = val1
      - state.offset = 0
      - flash_unlock (0x08000B10)  → write KEY1=0x45670123, KEY2=0xCDEF89AB to FLASH_KEYR
      - flash_erase 48 pages × 2 KB at 0x08008000  (= the entire app region)
      → all 96 KB of app region now read as 0xFFFFFFFF
      
  if state[+12] != -1 AND byte at 0x20000434 == 2 (= "WRITE mode"):
    // Subsequent sectors: write to flash
    bl chunk_write @ 0x08003CD0(length, data):
      - flash_unlock (defensive)
      - for each 4-byte word:
          flash_program(WORD, 0x08008000 + state.offset, word)
          // Read-back verify (sets r5=2 on mismatch but doesn't abort)
          state.offset += 4
      - flash_lock
      - if state.offset == state.length:
          state.mode = 3 (= DONE)
          return 1 (= completion indicator)
```

### Key facts

- **No CRC, no magic.** Bytes 5-8 of the header are stored in RAM (at `0x20000434`) but never read by any handler. The protocol accepts the upload as long as the header has `type=0x02` and a valid length.
- **Read-back verification** happens per-word inside chunk_write — but a verify failure only sets a flag (`r5=2`), it doesn't halt the upload.
- **No alignment in user space.** The host FAT12 layer will allocate clusters sequentially; the bootloader processes sectors as they arrive; the cluster numbering doesn't matter to the bootloader.
- **Erase target hardcoded** to `0x08008000`. The literal `0x08003CCC = 0x08008000` is the only place the address appears.

## File format for an upload

The simplest way to upload a custom firmware: build a file with the header in its FIRST 512 bytes, followed by the 96 KB app payload:

```
File bytes 0..511 (= sector 0 of the file = first 512 bytes the bootloader sees):
  [0]      = 0x02              ← type = BEGIN_FLASH_UPDATE
  [1..4]   = BE32 length        ← = 0x00018000 (96 KB), must be ≤ 0x18000 and 4-byte aligned
  [5..8]   = BE32 value         ← unused; recommend 0
  [9..511] = ignored             ← can be anything; we use 0x00

File bytes 512..98815 (= 96 KB payload):
  Raw app data — exactly what gets programmed to flash 0x08008000+.
  Typically the bytes 0x8000..0x1FFFF of your full 128 KB firmware image.

Total file size: 512 + 0x18000 = 98816 bytes.
```

After dropping the upload file and `sync`-ing, drop a **separate 1-byte file** containing `0x00` to trigger the reset:

```
echo -ne '\x00' | sudo tee /media/.../Teufel\ CBO/RESET.BIN
sync
```

The bar's bootloader processes the 1-byte file's data sector (sector >= 5, `state[+12] == -1` since the upload sequence cleared it back to -1 on completion), sees `type_byte == 0`, dispatches type-0 handler → SYSRESETREQ → chip resets → freshly-flashed app boots.

Builder: `/tmp/firmware/build_msc_upload.py <input_full_firmware.bin> <output_upload.bin>`.

## Entering MSC mode without firmware modification

The bootloader's `main()` reads PA1 at `0x08003A6C`. **PA1 is the chassis SUB PAIRING button signal** (verified live 2026-06-09 via per-pin GPIO scan: PA1 toggles only when the sub-pairing button is pressed; the IR receiver pulses a different pin, PB1).

**End-user entry gesture:**

> **Hold the chassis SUB PAIRING button while powering on the bar.**

That's it — no remote, no disassembly, no firmware modification, no soldering. The button is on the daughter board, accessible from the bar's case exterior.

Mechanics:
- Idle: PA1 reads HIGH (external pull-up). Bootloader's PA1 read returns HIGH → app validity check → boot_jump to app.
- Button held during boot: PA1 reads LOW. Bootloader's PA1 read returns LOW → skip app-validity check → enter wait loop at `0x08003AB2` → loop exits as soon as PA1 goes HIGH (release the button after a moment) → USB MSC init begins.

Earlier we wrongly assumed PA1 was the IR receiver and proposed "hold any TV remote button" as the gesture. Live test invalidated that — IR activity doesn't toggle PA1.

## Recovery if a partial upload bricks the app region

If an upload starts but doesn't finish (USB drop, host crash, etc.), the app region will be partially erased — bar can't run the app. **Bootloader region is untouched**, so the bar can always be SWD-recovered:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "program firmware_34_pc15-only-keepalive.bin verify reset exit 0x08000000"
```

(or any other complete 128 KB image).

## Open questions / not yet investigated

- **Why PB1 toggles during IR but the STM32 doesn't seem to read it.** PB1 toggles on every IR burst (verified live 2026-06-09) but no GPIO init or read of PB1 was found in the firmware. Likely: PB1 carries the raw IR receiver output to the daughter board, which decodes it and forwards the decoded button event to the STM32 via another channel (PA7/PA15 also toggle during IR activity — those are more likely the inter-board signal carrying decoded events).
- **Bytes 5-8 of the header.** Stored but never read by any handler we traced. Possibly intended as a future CRC slot. Safe to leave at 0.
- **What pulls T211 HIGH in MSC mode.** Multimeter confirms ~3 V when the bar is in MSC mode. We couldn't statically identify a GPIO that drives it; either there's an STM32 pin we missed, or the USB mux IC auto-switches on D+ pull-up presence (DPPU) and T211 is just a status output of the mux. Practical impact: no external T211 wiring is needed — the bootloader's MSC code drives whatever causes the routing.
- **Whether `RESET.BIN` can be appended to the upload file in a single drop.** When `chunk_write` completes (state.offset == state.length), state.mode becomes 3 (DONE) but state[+12] is at 0 (last decrement), NOT -1. The next sector write would fail the `state[+12] == -1` header-parse gate, so the appended 0x00 byte wouldn't be processed as a type-0 reset trigger. Untested — separate file is the reliable recipe.
