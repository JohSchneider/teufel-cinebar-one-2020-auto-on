# Teufel Cinebar One — USB modes & service entry

## TL;DR

The Cinebar One's single USB connector is fed through a **USB mux IC** (small SMD near the connector — marking guess "2WG 89J P7LL", exact part unconfirmed). The mux routes USB to one of two endpoints:

1. **DSP daughter board** (default route) — the Renesas D2-92634-LR has its own USB-Audio engine that enumerates as **USB Audio Class** with PID `0x0005`, product string "Teufel Cinebar One", bcdDevice `0x1084`. This is the normal "play music from your PC" mode.
2. **STM32 baseboard** (service route) — the STM32 has dormant **USB MSC** code (a FAT12 image at flash `0x08003E42`, MSC interface descriptors, SCSI inquiry "TEUFEL CINEBAR COMPACT 0.01", flash unlock keys for self-programming). Enters this only when triggered.

The STM32-USB persona is what you'd use for firmware update via the USB port.

## Trigger: PA0 LOW

`PA0` is configured as INPUT with no internal pull (`HAL_GPIO_Init` at flash `0x0800F0FC` — file offset `0xF0FC`). Reads HIGH idle (live-confirmed). The firmware contains:

- **`0x0800F13C` — `read_pa0()`**: returns `1` if PA0 is LOW, `0` if HIGH.
- **`0x0800ED10` — `wait_for_pa0_low_then_eeprom_handshake()`**: spins in a tight polling loop calling `read_pa0()`, then on first LOW reading:
  - waits 100 ms (debounce, via `0x0800F0F4`)
  - writes `0x80` to a RAM buffer
  - calls I²C transactions at device address `0xA0` (= 7-bit `0x50` = standard 24Cxx EEPROM address) on **I²C1** (PB8/PB9):
    - `bl 0x0800F0D0` — I²C write (probably issuing register address to read from)
    - `bl 0x0800F0AC` — I²C read (returns EEPROM payload into the RAM buffer)
  - retries up to 6 times on I²C error
  - validates the EEPROM payload: bytes `[0]==2`, `[1]==3`, `[2]` ∈ valid range
  - if valid → proceeds to further service-mode processing (likely MSC-USB persona switch)

## What this means

When `PA0` is held LOW (probably via a test pad on the PCB; possibly via the mux's host-detect or the daughter board's BT module), the firmware enters service mode:

1. Reads an I²C EEPROM at `0x50` on I²C1 (separate from the DSP bus, which is on I²C2)
2. The EEPROM contents include a recognizable header (`[0]=2, [1]=3, [2]=non-zero non-4`)
3. The firmware then likely:
   - Switches the USB mux to STM32 side (the mux SEL GPIO has not yet been positively identified, but PB8/PB9 are not it — PB8/PB9 are the I²C1 lines themselves)
   - Enables the STM32 USB clock (`RCC_APB1ENR` bit 23; currently `0` in normal operation — confirmed live)
   - Enumerates as MSC with the descriptors at `0x08003F8E` (PID `0x0004`)
   - Mounts the FAT12 image — the host sees "TEUFEL CBO" volume with VERSION.TXT

## Verification status

| Claim | Verified |
|---|---|
| Audio class enumeration normally (PID `0x0005`) | ✓ live (`lsusb -v` shows audio class, no MSC) |
| `RCC_APB1ENR` bit 23 = 0 in normal operation | ✓ live |
| MSC code present in flash (FAT12 image, descriptors) | ✓ static |
| PA0 init as INPUT no-pull at `0x0800F0FC` | ✓ static |
| PA0 idle HIGH | ✓ live (GPIOA IDR bit 0 = 1) |
| `0x0800ED10` polls PA0 then reads I²C @0xA0 | ✓ static disasm |
| Forcing PC into `0x0800ED10` enters the polling loop | ✓ live (verified by halting; PC stuck at 0x0800ED1E spinning) |
| **PA0 LOW actually causes MSC enumeration** | ✗ NOT YET — needs physical PA0→GND wire on PCB |
| Mux SEL GPIO identified | ✗ NOT YET — likely needs PCB trace from mux IC's SEL pin |
| EEPROM IC physically located on PCB | ✗ NOT YET — likely on daughter board (the chassis-button trace also went there) |

## The remaining unknowns

- **The mux SEL GPIO**: The USB mux must be told to route to STM32 side. PB8/PB9 are I²C1 lines (not it). Looking at the GPIO_Init call sites, the most-likely-unused output candidates haven't been pinned to a function yet. Possible candidates: `PA5` (configured as `AF_OD` at `0x0800EECC` — could be a USART/I²S signal), or some pin we haven't mapped. The cleanest discovery path: PCB trace from the mux's SEL pin (typically labeled "SEL" or "OE" in the datasheet).
- **What calls `0x0800E7E8` / `0x0800ED10` from outside**: only one direct caller (`0x0800E98C` inside `0x0800E8A0`), and `0x0800E8A0` has only `0x0800E800` as a caller — which is inside the same function family. The actual top-level entry into this whole region is unclear; it may be invoked via a function pointer (no literal references to these addresses found in flash) or by an indirect call. GDB-injection (forcing PC) crashes because the stack frame isn't set up properly.
- **EEPROM location**: standard 24C32 / 24C64 / 24C256 would all answer at `0x50`. Since I²C1 lines (PB8/PB9) are routed somewhere, the EEPROM is likely accessible from STM32 — but might also be on the daughter board, since the SUB PAIRING button trace went there.

## Practical test (next session)

The simplest way to verify the PA0 hypothesis: a temporary wire from PA0 on the STM32 to GND, power the bar, then run `lsusb -v`. Expected behaviour if hypothesis is right:

- USB enumerates as `2cc2:0004` (vs the normal `2cc2:0005`)
- A "TEUFEL CBO" FAT12 volume mounts on the PC
- VERSION.TXT shows the bar's firmware/DSP/bootloader versions
- (Possibly) a writable file slot exists for firmware update

If `lsusb` still shows audio class, then:
- Either the mux defaults to STM32 only when an additional condition is met (e.g., USB host detected AND PA0 LOW)
- Or PA0 LOW is necessary but not sufficient — the EEPROM contents matter, and the EEPROM might not be in the expected state
- Or the trigger is via a different mechanism entirely

## Cross-references

- `symbols.md` — function addresses
- `IR_CODES.md` — separate concern (IR-decoder mapping); included here because `notify(12, ...)` and the dispatch helper at `0x080108E2` were heavily used by the same RE work
- `FIRMWARE_VARIANTS.md` — productive firmware lineage; no MSC-targeting variant exists
