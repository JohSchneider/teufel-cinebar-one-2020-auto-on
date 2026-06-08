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

The full MSC firmware-update gesture requires **two concurrent physical inputs**:

1. **`T211` pulled HIGH** — a test pad on the PCB that drives the **USB mux SEL pin**. HIGH routes the USB connector to the STM32 baseboard side; LOW (its default) routes to the DSP daughter board. **No STM32 GPIO is wired to T211** — it's a pure-hardware override (probably accessed by a service jig pogo pin in the factory). Confirmed bench-verified 2026-06-08: pulling T211 to 3.3 V via 1 kΩ caused `dmesg` to report `USB disconnect → new full-speed USB device → "Device not responding to setup address" → error -71`, exactly the signature of "mux switched but the new endpoint isn't talking back" (because STM32 USB isn't enabled yet).

2. **`PA0` pulled LOW** — STM32-side service-mode entry. When the firmware's polling function at `0x0800ED10` sees PA0 LOW, it:
   - Waits 100 ms for debounce
   - Reads I²C device `0xA0` (= 7-bit `0x50`) on **I²C1** (PB8/PB9), separate from the DSP bus on I²C2
   - Validates the response (bytes `[0]=2, [1]=3, [2]≠0 and ≠4`)
   - Then proceeds with further service-mode work (presumably enabling the STM32 USB clock + initializing the USB peripheral)
   - Result: bar enumerates as MSC with PID `0x0004`, mounting the FAT12 "TEUFEL CBO" volume with VERSION.TXT

With **only T211 HIGH** (no PA0 trigger), the mux switches but STM32 USB stays dormant → host gets a "phantom" device that doesn't respond. With **only PA0 LOW** (no T211), the firmware's service-mode runs but the USB connector is still routed to the DSP, so host sees nothing change. Both conditions need to be met.

## What is NOT the mux SEL (ruled out)

- **PA15** initially looked like a candidate (one trace from the PCB seemed to head that way). Live bisection 2026-06-08: PA15 driven LOW via GDB had no effect on USB enumeration. **PA15 actually goes to the daughter board** (not the mux). Currently held HIGH by something on the daughter board, never read or written by the STM32 firmware that we can locate — function unknown but not the mux SEL.
- **PB8/PB9**: these are the I²C1 SCL/SDA — used for talking to the EEPROM on the same bus, not for muxing.
- No other STM32 GPIO currently identified as driving T211. Best guess: T211 is wired ONLY to a strap and a pogo-pin test point.

## Verification status

| Claim | Verified |
|---|---|
| Audio class enumeration normally (PID `0x0005`) | ✓ live |
| `RCC_APB1ENR` bit 23 (USBEN) = 0 in normal operation | ✓ live |
| MSC code present in flash (FAT12 image, descriptors) | ✓ static |
| PA0 init as INPUT no-pull at `0x0800F0FC` | ✓ static |
| PA0 idle HIGH | ✓ live |
| `0x0800ED10` polls PA0 then reads I²C @0xA0 on **I²C2** | ✓ live (corrected from earlier I²C1 claim — handle.Instance = 0x40005800) |
| Service-mode thread at `0x0800E928` enters LOW path when PA0 driven LOW | ✓ live (`state[+8] = 2` observed) |
| Service-mode peripheral init configures PA5 (AF1), PB10/PB11 (AF1 = I²C2), enables I²C2EN + CECEN | ✓ live |
| **T211 = USB mux SEL** | ✓ live (1 kΩ → 3.3 V causes mux switch; dmesg disconnect/reconnect) |
| No EEPROM responds at I²C2 addr `0x50` | ✓ live (NACKF=1 + STOPF=1 after manual probe; the firmware's HAL also NACKed — `ISR=0x31` sticky) |
| EEPROM handshake bypass via fw_36 patch lets `state[+9]` reach 1 (service init complete) | ✓ live |
| **USBEN ever gets set by firmware** | ✗ **Conclusively NO** — exhaustive search found no code path that sets RCC_APB1ENR bit 23 |
| Manually forcing USBEN via GDB causes MSC enumeration | ✗ live — host still sees `2cc2:0005` audio device; USB peripheral (CNTR/BCDR/DADDR) was never initialized either |

## Final assessment: MSC is dead code

After two days of static RE and live bench validation including a successful fw_36 (PA0+EEPROM-bypass) test:

**The firmware's MSC code is unreachable on shipped firmware.** There is no execution path that:
- Enables the USB peripheral clock (`RCC_APB1ENR` bit 23 / USBEN)
- Initializes the USB peripheral (CNTR, BTABLE, endpoints, DADDR, BCDR.DPPU)
- Registers the MSC class with the USB device stack

The components that ARE there:
- The FAT12 boot sector + "TEUFEL CBO" volume label + VERSION.TXT
- USB device descriptors with PID `0x0004` (MSC) at flash `0x08003F8E`
- The flash unlock keys (`0x45670123 / 0xCDEF89AB`) embedded so the bar could in principle self-program
- The PA0+EEPROM service-mode chain
- The hardware mux + T211 test pad
- I²C2 + EEPROM read code that walks "records" with a type+length encoding

All of this appears to be **infrastructure for a feature that was never finished or never shipped enabled**. The most plausible explanation is that the PCB is a shared design (Cinebar One vs other Teufel SKUs) and one variant uses MSC; or the factory programming jig uses MSC via a pogo-pin connection to T211 plus a programming-station EEPROM module, while the consumer firmware was stripped of the activation path.

## Why is the mux + dual-USB routing even there?

User's question, worth recording: if MSC is dead code, why does the PCB include the USB mux at all? Three possibilities:

1. **Factory programming jig requirement.** The mux + T211 pad lets a factory pogo-pin jig switch the USB to the STM32 side during manufacturing, then flash via MSC. The jig presumably had a hardware EEPROM module connected to I²C2 PB10/PB11 with the expected records. Consumer-shipped boards have the mux + the firmware scaffold but no EEPROM and no activation path.
2. **PCB sharing across SKUs.** Same baseboard used in multiple Teufel products; some variants have MSC, this one doesn't. Cheaper for Teufel to leave the mux populated than to maintain a second BOM.
3. **Originally planned consumer feature that never shipped.** Teufel may have intended MSC firmware updates for end users, started the implementation, stopped before the USB-activation path was wired in.

Most likely a combination of #1 and #2.

## The CEC hypothesis — CONFIRMED (2026-06-09, task #65)

Static analysis of the function at `0x0800EE9C` (called from the PA0-LOW peripheral-init chain via `0x0800F154 → 0x0800F130`) confirmed it is **CEC peripheral initialization**:

- Enables GPIOA clock + configures PA5 as AF1
- Sets **CECEN (RCC_APB1ENR bit 30)** via `lsls r0, r4, #18` where `r4 = 0x40021000` → `0x40000000` = exactly the CECEN bit (compiler trick that avoids the literal pool)
- Toggles APB1RSTR bit 30 to reset the CEC peripheral
- Initializes a CEC state struct at `0x200026F8` with `[+0] = 0x40007800` (CEC peripheral base)
- Calls the same `0x0800D064` / `0x0800D1EC` helpers that **`service_inner(r0=5)` calls** ← this is the cross-link
- Enables NVIC **IRQ 30 = CEC_CAN_IRQn** at priority 1

That means `service_inner(r0=5)` is a CEC operation working on the same state struct at `0x200026F8`. The "USB-driver-shaped" helpers (`0x0800D064`, `0x0800D1EC`, `0x0800D284`, `0x0800D0E0`) are ST HAL CEC functions, not USB driver functions. The buffer at state+0x88 is the CEC RX/TX message buffer. The EEPROM dispatch records (type 3-bit / length 5-bit) are CEC opcode entries.

**The service mode is HDMI-CEC-driven.** The factory programming/test station likely connects via the HDMI-ARC port, sends CEC opcodes, and uses the EEPROM-loaded opcode dispatch table to drive the bar's behavior (including possibly firmware programming via CEC vendor-specific opcodes).

### Curious wrinkle: vector table

Vector table slot 30 (CEC_CAN_IRQn) points to `Default_Handler` (the `0x080000E6` infinite-loop trap), while only the USB slot 31 has a real handler. So if the CEC peripheral actually raised an interrupt with this static vector table, the bar would HardFault. Possibilities:

1. CEC runs entirely in polled mode (the "CEC RX" / "CEC TX" named threads poll the CEC registers); the NVIC IRQ enable in `cec_peripheral_init` is harmless leftover code
2. The vector table is replaced at runtime via `SCB->VTOR` (RTX5 supports this)
3. CEC interrupt-enable bits in `CEC_CFGR` are never set, so no interrupt ever fires

Hasn't been verified live, but the bar's normal operation (no random HardFaults) is consistent with one of these.

## Cross-references

- `symbols.md` — function addresses (I²C bus labels corrected 2026-06-09: I²C1 = DSP control bus, I²C2 = EEPROM/service-mode bus)
- `IR_CODES.md` — IR-decoder mapping (separate concern)
- `FIRMWARE_VARIANTS.md` — productive firmware lineage; `firmware_36_*` is the experimental MSC-test build that produced the dead-code finding
