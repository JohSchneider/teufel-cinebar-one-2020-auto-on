# Plan: Reverse-engineer Teufel Cinebar One firmware to add auto-on

## Context

You have a 128 KB firmware dump (`/tmp/firmware/firmware_01_original-dump.bin`) extracted from the STM32F072CBT6 inside a Teufel Cinebar One soundbar. Goals, in priority order:

1. **Auto-on at AC power** — currently it boots into standby and waits for IR/button.
2. **Auto-on when SPDIF audio appears** — wake out of standby on detected input.

You have the board, SWD reflash path via ST-Link, an analog multimeter, and a Saleae-clone logic analyzer. Option bytes confirm RDP was off (`AA`) so the dump is the full, valid flash image. The firmware is built on **Keil RTX V5.2.3** (CMSIS-RTOS) — known task/mutex names ("I2C System", "LED Timer", "vEEPROM") give you anchor points. The USB stack presents a FAT12 "TEUFEL CBO" volume with a `VERSION.TXT`, i.e. the vendor's own firmware-update channel.

## Feasibility summary

| Goal                          | Feasibility | Reason                                                                                                                                                                                  |
| ----------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auto-on at AC power           | **High**    | Just patch the boot path: either skip the "enter standby" transition or invoke the power-on routine after init. The hard part is finding the right instruction, not enabling the change. |
| Auto-on on SPDIF audio detect | **High** (was Medium) | The SPDIF Toslink output is wired directly to the STM32 via a small SOT-23-5 buffer — no external SPDIF receiver IC. The MCU does presence detection itself (TIM14 input capture and/or EXTI4 on PA4). Toslink Vcc is gated by an STM32-controlled rail in standby — pure firmware can keep it enabled. Cost: standby power increases by the audio rail's quiescent draw. |

Both are realistic for a single STM32F072 with 128 KB of code — small enough codebase that static RE is tractable in a weekend or two.

## Findings so far (live — updated as we learn)

### Observed behavior
- **Power up → standby** (LED red). Bar waits for IR remote.
- **IR wake** → active state (LED purple — likely red + blue mixed). Plays audio from SPDIF.
- **SPDIF silence for ~2 minutes → auto-standby**. The firmware therefore *already* tracks SPDIF presence/absence and acts on it. The detect machinery on PA4 is proven to work and the auto-standby decision logic exists.
- **Architectural inferences from this**:
  - STM32 stays alive in standby (must be, to receive IR). Almost certainly in STOP mode with IR pin as an EXTI wake source (consistent with the 5 `PWR_BASE` references in firmware).
  - The IR-wake interrupt path is a **working template for the SPDIF-wake path** — copy its structure for PA4/EXTI4.
  - The auto-standby timer (SPDIF-loss → standby) is the **mirror image of goal #2** — we just need to add the inverse arm: "SPDIF detected while in standby → wake".
  - For goal #1, IR-press already drives a standby→active transition. The boot path just needs to post the same event that the IR ISR posts.

### Hardware
- **SPDIF input chain**: optical Toslink receiver (3-pin module) → SOT-23-5 part marked `Z045`/`Z04S` (almost certainly a single-gate Schmitt buffer or inverter like 74LVC1G14/G17, or a tri-state buffer like 74LVC1G125) → **STM32 pin 14 = PA4**.
- **DSP**: **Renesas D2-92634-LR** on the daughter board — part of Renesas's D2-family soundbar SoCs. Has integrated SPDIF receivers labelled SPDIFRX0/SPDIFRX1, so the audio path goes directly into the DSP, *not* through the STM32. The SPDIF data trace must branch between the SOT-23-5 buffer output and the DSP's SPDIFRX pin — one branch to PA4 (for STM32 presence detection), one branch to the DSP (for audio decoding). Finding the DSP branch is in progress; continuity testing is currently confused by power/ground plane connections (see Phase A note below).
- **Bluetooth module** (daughter board): CSR (Qualcomm) **A64215** with sticker `33b17a`; CSR family chips support A2DP audio receive. **Labeled SPI header** sits next to it on the daughter board — likely the CSR chip's SPI debug/programming port, useful for future BT-related work but off the critical path for auto-on.
- **Wireless subwoofer link** (separate sub-board): **SWA12-TX** module (FCC ID `NKR-SWA12`) — proprietary 2.4 GHz wireless audio link to a paired subwoofer. The STM32 likely controls its pairing/standby via I²C, UART, or GPIO.
- **Toslink Vcc in standby**: **gated off by the STM32**. Active state: ~3.0V on the Vcc pin. Standby state: ~0.8V (leakage measured through an analog multimeter's input impedance). Implication: SPDIF auto-on is achievable in pure firmware by patching whichever GPIO/path the STM32 uses to gate the Toslink rail — *no hardware mod needed*. Trade-off: standby power increases by the Toslink module's quiescent current (typically a few mA) once that rail is kept on. The same gated rail likely powers other audio chips (5-pin buffer, possibly DSP), so the full standby-current cost depends on what else hangs off it — worth tracing the rail.
- **No dedicated SPDIF receiver IC** (e.g. CS8416/DIR9001) in the chain — the MCU handles SPDIF presence detection on PA4, and the DSP handles SPDIF audio decoding internally.
- **No I²S/SPI peripheral usage in firmware** (see below) — confirms the STM32 is *not* re-streaming SPDIF audio to the DSP over a digital audio bus. PA4 is presence-detect only.

### PA4 alternate functions on STM32F072 (relevant ones)
- **TIM14_CH1** (AF4) — single-channel input capture. Good for measuring edge intervals → SPDIF bit rate.
- **EXTI4** (GPIO mode) — interrupt on edges; wakes from STOP. Routed through `EXTI4_15_IRQn` (vector slot 23).
- **ADC_IN4** / DAC_OUT1 — not used (DAC base address has 0 hits in the firmware).
- **SPI1_NSS / I2S1_WS** (AF0) — not used (SPI1/I2S base addresses have 0 hits).

### Firmware-side evidence (from peripheral base-address hits in `firmware_01_original-dump.bin`)
| Peripheral | Base       | Hits | Note                                                  |
| ---------- | ---------- | ---- | ----------------------------------------------------- |
| GPIOA      | 0x48000000 | 1    | Used; the one literal is enough — RAM-mirrored access |
| TIM14      | 0x40002000 | 1    | **Likely the SPDIF edge-capture timer for PA4**       |
| TIM1       | 0x40012C00 | 6    | General-purpose, PWM-capable                          |
| TIM2       | 0x40000000 | 6    | General-purpose                                       |
| TIM3       | 0x40000400 | 2    | General-purpose                                       |
| EXTI       | 0x40010400 | 4    | Multiple EXTI lines configured                        |
| SYSCFG     | 0x40010000 | 5    | `SYSCFG_EXTICR` writes — maps EXTI lines to GPIO ports |
| RCC        | 0x40021000 | 36   | Heavy clock-gating activity (expected)                |
| PWR        | 0x40007000 | 5    | **Low-power mode (STOP/STANDBY) almost certainly in use** |
| SPI1       | 0x40013000 | 0    | Not used                                              |
| I2S/SPI2   | 0x40003800 | 0    | Not used                                              |
| DAC        | 0x40007400 | 0    | Not used                                              |

### Flash layout (mapped)
- Code/data extends `0x08000000`–`0x08004007` and `0x08007000` (vEEPROM)–`0x0801E7B7` (end of code).
- **vEEPROM**: `0x08007000`–`0x08007FFF` (pages 14+15, 2× 2 KB, AN4061 layout). Constants in literal pool at `0x0800CB74`.
- **Reserved/unused gap**: `0x040D8`–`0x07000` (5 pages, ~10 KB). Likely linker padding below vEEPROM. Usable but awkward.
- **Patch space**: `0x0801E7B8`–`0x0801FFFF` (~6.2 KB). Confirmed unused. **Target this region for all patch code, page-aligned to `0x0801E800`.**
- RTX object names at file offset `0x1E5B0..0x1E5F0` include: "Mutex I2C System", "LED Timer", "Mutex vEEPROM", "CEC RX", "CEC TX". **HDMI-CEC support exists** — a possible third wake source alongside IR and SPDIF, though not needed for goals #1 and #2.

## What you need

### Toolchain
- **Ghidra** (free, handles Cortex-M0 well) + **SVD-Loader** extension to auto-label STM32F072 peripheral registers. Alternative: IDA Free or Binary Ninja.
- **STM32F072 SVD** from `cmsis-svd` or ST's CubeMX install.
- **OpenOCD** + **ST-Link V2** (clone is fine) for SWD read/write/debug.
- Optional: **arm-none-eabi-gdb** if you want to single-step on the live device.
- Optional: **Keil RTX5 source** (in CMSIS-FreeRTOS / CMSIS_5 on GitHub) — lets you fingerprint the kernel functions in the dump.

### Documentation
- STM32F0 reference manual **RM0091** (peripheral register definitions).
- STM32F072CBT6 datasheet **DS9826** (pinout).
- Cortex-M0 **Architecture Reference / Technical Reference Manual** (Thumb-2 subset only — easier to disassemble than M3/M4).

### Hardware setup
- Identify SWD pads on the PCB (look for SWDIO/SWCLK/GND/3V3 test points near the MCU).
- Logic analyzer on the **I²C bus** is the highest-value hardware step: it reveals which chips the MCU talks to and the read/write patterns for the SPDIF receiver, the DSP, and likely an EEPROM/codec.
- Logic analyzer on **GPIOs** during a manual power-on (press the button while capturing) reveals which pin enables the amplifier, which drives source-mux relays, etc.

## Loading and orienting in Ghidra

- Base load address: **`0x08000000`** (flash), size 128 KB.
- RAM region: `0x20000000`–`0x20003FFF` (16 KB, initial SP at `0x20001ce8`).
- Peripheral region starts at `0x40000000` (SVD covers this).
- Vector table is at `0x08000000`. Confirmed entry points from the dump:
  - Reset: `0x080000d4`
  - HardFault: `0x080020d8`
  - SVCall: `0x08002db4`
  - PendSV: `0x080027c4`
  - NMI: `0x08002400`
- Mark the vector table, then let Ghidra auto-analyze. PendSV + SVCall handlers are the **RTX context switch / system call gateway** — they're your fingerprint for the RTOS, and the kernel data structures dangle off them. Tasks ("threads" in RTX5) are created with `osThreadNew`; the third argument is the entry function. Tag those entries — each one is a state machine (power, UI/LEDs, USB, I²C, etc.) and one of them owns standby.

## Step-by-step approach

### Phase 0 — Toolchain verification (do this FIRST, before any behavior-changing patch)
Goal: prove the SWD read/write loop works end-to-end with a change that cannot affect device behavior.

**Important context discovered**: when plugged in, the bar enumerates as a USB *audio* device (no MSC volume by default), with:
- `idVendor=0x2cc2` (Teufel), `idProduct=0x0005`, `bcdDevice=10.84`, `iManufacturer=0`, `iProduct=2`=`Teufel Cinebar One`, `iSerialNumber=3`=`ABCDEF0123456789`.

The `firmware_01_original-dump.bin` dump's device descriptor at file offset `0x3F8E` shows `idProduct=0x0004`, `bcdDevice=0x0200`, `iManufacturer=0x01`. Static-RE finds:
- Only one device descriptor in the entire 128 KB image (no alternate descriptor table).
- No UTF-16LE encoded copy of `Teufel`, `Cinebar`, `ABCDEF`, or `01234` anywhere.
- No 8-byte source pattern `AB CD EF 01 23 45 67 89` that would hex-encode to the visible serial.
- Last non-`0xFF` byte at `0x0801E7B7`; the entire upper flash region `0x0801E7B8`–`0x0801FFFF` is erased (no vEEPROM data initialized there yet — or vEEPROM lives elsewhere).

**Conclusion**: the USB descriptor's variable fields are almost certainly **substituted at runtime from an external source** — most likely an external I²C EEPROM (consistent with the I²C bus + "vEEPROM" naming we already see) and/or STM32's 96-bit unique ID at `0x1FFFF7AC`. The in-flash descriptor template at `0x3F8E` is overridden before USB enumeration.

This means we cannot validate the SWD flash workflow by changing a descriptor byte — the changed byte may simply get overwritten at runtime. We need a verification target that is provably static.

#### Phase 0 — Step 1: Prove SWD-write works (zero behavior risk) — ✅ DONE
Wrote a `DE AD BE EF` marker into erased upper flash and reflashed via OpenOCD:
```sh
cp firmware_01_original-dump.bin firmware_02_swd-write-test.bin
printf '\xde\xad\xbe\xef' | dd of=firmware_02_swd-write-test.bin bs=1 seek=$((0x1ff00)) conv=notrunc
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_02_swd-write-test.bin verify reset exit 0x08000000"
```
Bar still works post-flash. **SWD read/modify/write toolchain proven.** Note: the marker landed inside the likely vEEPROM region (last two pages) so it may be overwritten later — fine for verification, not appropriate for real patch code.

#### Phase 0 — Step 1.5: vEEPROM mapped via static RE ✅
Disassembling with `arm-none-eabi-objdump -D -b binary -m arm -M force-thumb` and tracing FLASH_AR writes revealed the vEEPROM module. The generic `FLASH_PageErase(uint32_t page_addr)` function lives at `0x0800CF94`; the vEEPROM module's erase-loop driver is at `0x0800D340`, and the vEEPROM page-address constants sit in a literal pool at flash address `0x0800CB74`:

```
0x0800CB74: 0x08007000   ← vEEPROM page A
0x0800CB78: 0x08007800   ← vEEPROM page B
0x0800CB7C: 0x0000EEEE   ← RECEIVE_DATA marker (textbook ST AN4061)
```

**vEEPROM lives in the MIDDLE of flash at `0x08007000`–`0x08007FFF` (2× 2 KB pages, 14 + 15).** It does NOT use the upper flash sectors. Confirmed by inspecting the live image: page `0x7000` starts with `00 00 ff ff` (VALID_PAGE marker from AN4061) followed by real `{key,value}` entries; page `0x7800` is all `0xFF` (erased spare).

**Implications for patch placement**:
- The previously-feared 2 KB conservative envelope is wrong. **The entire `0x0801E7B8`–`0x0801FFFF` region (~6.2 KB) is unused/reserved flash, completely safe for patch code.**
- The DEADBEEF marker the user wrote at `0x1FF00` is safe — vEEPROM will never touch it.
- A second large `0xFF` gap exists at file offset `0x040D8`–`0x07000` (5 pages, ~10 KB) — likely linker-reserved space below the vEEPROM pages. Also potentially usable but more awkward (must avoid clipping into vEEPROM page boundaries).

Conclusion: **target the tail `0x0801E800`–`0x0801FFFF` for all patch code** — page-aligned, no vEEPROM conflict, large enough for everything we need.

**Additional reads from non-user-flash regions** (one-time, per-unit interesting data):
- `0x1FFFF7AC`, 12 bytes — STM32 96-bit Unique Device ID. Candidate source for the runtime-generated USB `iSerialNumber`. `dump_image uid.bin 0x1FFFF7AC 0x0c` in OpenOCD.
- `0x1FFFEC00`, 3 KB — factory bootloader ROM. Read-only, identical across chips; only worth dumping if we end up reverse-engineering the system bootloader.

#### Phase 0 — Step 2: Reach a host-visible verification (post-investigation)
Once we know where the descriptor variable fields come from, we can choose a host-visible target. Primary investigation route is **static RE of the USB GET_DESCRIPTOR handler** in firmware: find writes to the STM32 USB peripheral's data register (`USB_FS_BASE = 0x40005C00`), walk back to where the descriptor buffer is filled, and identify the source of each variable field. This is purely a Ghidra exercise — no hardware probing needed.

Likely findings (hypotheses to validate):
- `iProduct` "Teufel Cinebar One" is built at runtime by concatenating the ASCII fragments `Teufel` (file `0x3558`) and `Cinebar One` (file `0x3574`) and converting to UTF-16LE. The space character between them is the obvious join. Patching either ASCII fragment changes the visible product string.
- `bcdDevice = 0x1084` is loaded from a literal-pool word (`84 10 00 00`) somewhere in flash — likely a build version constant. Patching that word changes the visible bcdDevice.
- `iSerialNumber` "ABCDEF0123456789" is generated by hex-encoding 8 source bytes (`AB CD EF 01 23 45 67 89`) using the lookup table at file offset `0x3F7A` ("0123456789ABCDEF"). The source bytes are either: (a) in flash but stored as something other than that exact byte sequence (e.g., reversed, XOR'd, swapped halves), (b) read from the CSR Bluetooth module's MAC over UART/SPI at boot, (c) from STM32 UID at `0x1FFFF7AC` — though astronomically unlikely to be exactly `ABCDEF0123456789`. Tracing the function that uses the `0x3F7A` lookup table will tell us.

Secondary route (only if static RE is blocked): logic analyzer on I²C/SPI/UART at boot to capture serial reads from external chips. The CSR BT module is a likely source for a MAC-based serial; that bus would be either UART or SPI rather than I²C.

If a host-visible static target is found, repeat Step 1's flash-and-redump pattern but target that byte, and confirm via `dmesg` / `lsusb -v`.

### Phase A — Identify the hardware (in progress)
1. Find SWD pads, solder leads, verify you can read flash with OpenOCD (`stm32f0x.cfg`). Save a second dump for diff.
2. With the unit in standby and the logic analyzer on SCL/SDA: capture a few seconds. Decode I²C addresses (DSP, EEPROM if external, possibly codec). The vendor's "Mutex I2C System" task confirms an I²C bus exists.
3. Capture I²C again while pressing the power button. Diff: writes that *only* happen in the on-transition are your "wake the audio path" sequence.
4. Note which GPIO pins toggle on power-on. Those are amp-enable / mute / source-select lines.
5. **Critical data point for goal #2 — still open**: with the Toslink module's Vcc trace identified, measure with multimeter whether it is live in standby. If 0V, SPDIF auto-on needs a small hardware mod (jumper the Toslink's Vcc to an always-on rail). If at its operating voltage (3.3V or 5V), pure-firmware path works.
6. **Identify the SOT-23-5 marked `Z045`/`Z04S`**: cross-reference an SMD-marking database, OR just probe its function with the logic analyzer (input vs output: same edges → buffer; inverted → inverter; output disabled when a 5th pin goes low → tri-state buffer). The tri-state case is interesting because it would mean firmware can gate SPDIF off PA4 — a clue to where the detect logic lives.
7. **Trace the audio path to the DSP** (Renesas D2-92634-LR): the buffer output trace should branch and reach one of the DSP's SPDIFRX0/SPDIFRX1 input pins. Continuity testing is currently noisy because many DSP pins read low-Ω to adjacent pins due to shared ground/power planes and on-die ESD diodes. Tips to cut through that:
   - **Power the board off and wait 1–2 minutes** for bulk caps to discharge; otherwise residual voltage spoofs readings.
   - **Use resistance-mode (Ω), not beep-mode**. Calibrate first: probe two known-good ground pads — note the reading; then a known signal trace — they'll differ. ESD-diode-only "connections" usually show 10s–100s of Ω, real net connections show <2Ω.
   - **Test both probe polarities** — ESD diodes conduct asymmetrically, real traces don't.
   - **Look for inline discrete parts** between the buffer output and the DSP: an SPDIF input usually has a small series resistor (often 100Ω) or ferrite bead within a few mm of the DSP pin. Find that component first, then trace from it to the DSP — that's far easier than probing from the DSP side.
   - If the DSP daughter board has a connector to the main board, the SPDIF likely comes in on one of those pins. Trace the buffer output to the connector, identify the pin, then look up where that connector lands on the daughter board side.

**Confirmed**: SPDIF lands on **STM32 pin 14 = PA4**. DSP is **Renesas D2-92634-LR** with integrated SPDIFRX0/1 inputs (audio decoded there, not in the STM32).

### Phase B — Locate the power state machine and the IR-wake template (static RE)
6. In Ghidra, find the RTX kernel entry (`osKernelStart`) — it's near the end of `main()`. Walk back: everything before it is hardware init; the threads spawned just before it are the application logic.
7. **Find the IR receiver ISR — this is the most valuable anchor.** It's a working example of "interrupt fires while in standby → MCU wakes → power-on event posted". Heuristics:
   - It's an EXTI handler (one of `EXTI0_1`, `EXTI2_3`, `EXTI4_15`).
   - It does pulse-width decoding (NEC/RC5/RC6 protocols — TIM2/TIM3 input capture or just SysTick deltas).
   - It ends by calling an RTX event/queue API (`osEventFlagsSet`, `osMessageQueuePut`, `osSemaphoreRelease`) — that target *is* the power-on event we want to reuse.
8. **Find the SPDIF-tracking code on PA4 / TIM14.** The auto-standby timer means this code definitely exists and runs in active mode. Look for:
   - TIM14 init: walk back from the `TIM14_BASE` literal at file offset `0x10688`.
   - A RAM "SPDIF lock" / "audio present" flag that flips based on TIM14 captures.
   - An "audio absent for N minutes → enter standby" decision somewhere in the power thread. The "N minutes" constant will be a recognizable tick count (e.g. `120000` ms = `0x1D4C0`).
9. Find the thread that owns power state. Heuristics:
   - It will write to the amplifier-enable GPIO identified in Phase A step 4.
   - It will read button GPIOs.
   - It will receive the same RTX event the IR ISR posts (target of step 7).
10. Inside that thread, identify the **standby → on** transition function (constants written to the amp-enable GPIO BSRR/BRR will jump out) and the **initial state** assignment after boot (either a constant written to a RAM state variable in init, or a direct call to "enter standby" right before `osKernelStart`).

### Phase C — Patch for goal #1 (auto-on at AC power)
Now that we know the IR-press triggers a standby→active transition via an RTX event, the cleanest patch is to post that same event from the boot path.

- **Preferred**: after `osKernelStart` is called (i.e. once threads are running), have the power thread itself post the wake event to itself on its first iteration — or post it from the IR ISR's target queue right before `osKernelStart` (RTX queues accept items before the scheduler starts; the receiving thread sees it on its first scheduled tick).
- **Alternative**: change the initial-state RAM constant from `STANDBY` to `ON` (single-byte `MOVS Rn, #imm` patch). Slightly more brittle because it bypasses the standard transition routine and might skip side effects (LED color set, DSP I²C wake-up sequence, etc.).
- **Avoid**: forging a fake button-press in interrupt context before the RTOS is running — it'll race the scheduler.

### Phase D — Patch for goal #2 (SPDIF auto-on)
**Pre-req has been resolved**: Toslink Vcc is STM32-gated in standby (3.0V on, 0.8V leakage off). Keeping it on is a pure firmware change — identify and skip the gate-off write in the standby-entry path.

Updated architecture model: the SPDIF signal is on PA4, fed by a small buffer. No external SPDIF receiver IC. The MCU does presence detection itself — TIM14_CH1 input capture and/or EXTI4. The detect code is *proven to run in active mode* (the auto-standby timer uses it). The IR ISR is a working example of "wake from STOP and post a power-on event" — copy its structure.

Patch outline (refined):
- Find the GPIO write that turns off the audio rail in the standby-entry sequence. The pin is somewhere on PORTA/B/C/F (LQFP48 has those ports). Easiest path: trace the Toslink Vcc on the board to its load switch / LDO, identify the enable pin, follow that net back to an STM32 GPIO, then search the firmware for `GPIOx_BSRR`/`BRR` writes that toggle that pin's BSRR bit.
- Once located: either NOP the gate-off write entirely, OR replace it with the gate-on write (preferred — semantically explicit).
- Configure EXTI4 (PA4) as a STOP wake source: `EXTI_IMR` bit 4 set, `EXTI_RTSR`/`EXTI_FTSR` bit 4 set, `SYSCFG_EXTICR2` EXTI4 source = PA. NVIC line `EXTI4_15_IRQn` (#7) enabled.
- In the `EXTI4_15_IRQHandler` (or by extending the existing handler if one is already used for IR), post the same RTX event the IR ISR posts to drive the standby→active transition.

10. **Find the PA4 / TIM14 / EXTI4 configuration in firmware**, in this order of likelihood:
    a. **TIM14 init** — `TIM14_BASE` (`0x40002000`) is referenced once in the dump (around file offset `0x10688`). Walk from that LDR back to the function head and forward to identify: capture channel mode, prescaler, ARR. If `CCMR1` is set for input-capture and `CCER` has CC1E set, this is the SPDIF edge-timer. The captured ARR/period value tells you what bit rate the firmware expects (44.1 kHz SPDIF biphase → ~5.64 Mbit/s; 48 kHz → ~6.14 Mbit/s).
    b. **EXTI4 setup** — look for writes to `SYSCFG_EXTICR2` (`0x40010008`) that set EXTI4's source to port A (bits 3:0 = `0x0`). The handler is `EXTI4_15_IRQHandler` at vector slot 23 (file offset `0x5C`).
    c. **GPIOA MODER bits 9:8 for PA4**: AF mode is `10`. The init function writing `GPIOA_MODER` and `GPIOA_AFRL` (bits 19:16 for PA4) sets PA4 to its alternate function.
11. **Find the source-detect / lock-state variable**. A RAM byte/word that flips when SPDIF locks/unlocks. The TIM14 interrupt handler (or the thread that polls TIM14_SR) updates it. Cross-reference: which thread reads this variable and posts an RTX event when SPDIF becomes valid.
12. **Determine whether SPDIF detect runs in standby**:
    - If TIM14/EXTI4 stay enabled in standby (peripheral clock not gated, IRQ unmasked), detect already works — you only need to make the resulting "SPDIF lock" event power the bar on instead of being ignored.
    - If they're disabled in standby (likely if the MCU enters STOP mode — see Risks), you need to either keep them enabled or use EXTI4 as a STOP wake source.
13. **Apply the patch**. Pick the smallest-impact option:
    - **Route A (preferred if detect runs in standby)**: in the state-machine arm that handles "SPDIF lock event in standby", change a branch from "ignore" to "post power-on event". Likely a one-instruction change.
    - **Route B (if MCU enters STOP)**: ensure EXTI4 is configured as a STOP wake source (`EXTI_IMR` bit 4 set, `EXTI_RTSR` bit 4 set) before `__WFE`/`__WFI`. The ISR posts the power-on event on resume. Use the 6216 bytes of free flash at `0x0801E7B8` for any new code; replace a single instruction in the standby entry path with a `BL` thunk to it.
14. Don't try to fully decode SPDIF frames just for detection — edge presence + plausible bit timing is enough. The firmware's existing TIM14 logic almost certainly already does this.

### Phase E — Flash and iterate
13. Flash via SWD using OpenOCD or STM32CubeProgrammer. Keep the original `firmware_01_original-dump.bin` as your rollback.
14. Don't touch the USB MSC update path until you've confirmed via SWD that the patch works — the vendor updater likely checks a signature or CRC. SWD bypasses that.
15. After a confirmed-good build, optionally reverse the vendor's MSC update format (look for the CRC/length check near the file-write handler in firmware) so you can ship the modified firmware to others without SWD.

## Critical files / artifacts / addresses

- `/tmp/firmware/firmware_01_original-dump.bin` — the dump. Load at `0x08000000`.
- `/tmp/firmware/optionbyts.txt` — confirms RDP=AA (no protection).
- Vector table (file offset 0, mapped to `0x08000000`): your entry-point map.
- Anchor functions for analysis: PendSV at `0x080027c4`, SVCall at `0x08002db4` (RTX kernel fingerprint), Reset at `0x080000d4`, EXTI4_15 handler from vector slot 23 at file offset `0x5C`.
- TIM14_BASE constant at file offset **`0x10688`** (= flash `0x080145A8` constant pool entry) — walk back to find the TIM14 init function.
- Free flash for new patch code: **`0x0801E7B8`–`0x0801FFFF`** (6216 bytes available).

## Risks and unknowns

- **Power sequencing**: the amplifier likely needs a deliberate enable order (rails up → DAC un-mute → amp un-mute) to avoid pops or stressing the supply. Re-use the existing on-transition routine; don't recreate the sequence from scratch.
- **Watchdog / brownout**: if init takes longer with auto-on, IWDG might bite. Check whether IWDG is enabled in early init (`IWDG_KR` writes).
- **Standby almost certainly uses STOP mode**: `PWR_BASE` (`0x40007000`) has 5 hits in the firmware. Bias Phase D toward Route B (EXTI4 as STOP wake source) rather than Route A (active polling). Confirm exact mode by reading the `PWR_CR` write near a `__WFE`/`__WFI` in the standby thread.
- **Vendor firmware-signing**: only matters if you go via USB MSC update. SWD path ignores it.
- **Bricking**: SWD remains accessible even after a bad flash unless option bytes are changed. Don't touch option bytes.

## Verification

- **Phase A check**: I²C captures show distinct on-vs-standby register traffic; you've named the SPDIF receiver and amp-enable GPIO.
- **Goal #1 check**: pull AC, restore AC, the bar comes up in the active state, sound plays without pressing anything. LED behavior matches normal power-on. Test 10× to rule out a timing race.
- **Goal #2 check**: from standby, start playback on the connected source; the bar wakes within a few hundred ms of audio appearing. Stop playback for ≥ vendor's auto-standby timeout and confirm it returns to standby normally (don't break that path).
- **Regression checks**: IR remote still works, USB MSC update still mounts, volume/source buttons still work, HDMI input still works, no audible pops on the new transitions.
- Keep `firmware_01_original-dump.bin` as the rollback image throughout.
