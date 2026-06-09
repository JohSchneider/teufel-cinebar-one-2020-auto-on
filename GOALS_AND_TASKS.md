# Goals, phases, and tasks — Cinebar One RE project log

The work is a mix of two stated user goals plus 60+ smaller tasks that accumulated as we investigated. This document keeps them straight: **goals** are the original "why we started," **phases** are the chronological progression, and **tasks** are the numbered items we tracked.

---

## Goals (the original "why")

These two goals were stated up front and drove the bulk of the work:

| Goal | Description | Status |
|---|---|---|
| **Goal #1** | Bar auto-boots to active state on AC restore (no need to press the power button) | ✅ Done — `firmware_05_autoboot-active-on-power.bin` |
| **Goal #2** | Bar wakes on SPDIF activity and auto-suspends when source goes silent | ✅ Done — `firmware_22_wake-on-spdif.bin`, refined into `firmware_34_pc15-only-keepalive.bin` |

A third implicit goal emerged later:

| Goal | Description | Status |
|---|---|---|
| **Goal #3 (emergent)** | Understand the bar's USB MSC firmware-update mode | ✅ Done — full protocol decoded in `MSC_PROTOCOL.md`; entry gesture (TV remote button at boot) identified |

Everything else became individual tasks.

---

## Phases — chronological progression

### Phase A — Initial RE setup
*Approximate task range: #1-#13 (not all preserved in current context)*

- Hardware setup: ST-Link clipped to internal SWD pads; OpenOCD config dialed in
- First firmware dump via `flash read_bank` → `firmware_01_original-dump.bin`
- Verified RDP=AA (no readout protection)
- objdump disassembly → `disasm.txt`
- Initial pinmap built from `HAL_GPIO_Init` call sites
- Identified RTX5 (CMSIS-RTOS2) and named threads/mutexes from string table
- Found vector table, Reset_Handler, SystemInit
- Identified `transition_state @ 0x0800A740` as the state-machine dispatch

### Phase B — Goal #1: auto-boot to active
- **`fw_03`** Sanity test: shim mechanism (NO-OP redirect) → proved patch infrastructure
- **`fw_04`** First attempt — audio on but LED stuck red (no notify) → instructive partial
- **`fw_05`** ★ Working: shim posts `notify(0, 4)` from `app_main` → event-loop calls `transition_state(2)`
- **`fw_24`** Tempting "fix" — NOP `transition_state` → boot HardFault (dead-end lesson)

### Phase C — Standby rail investigation (round 1)
- **`fw_06`** NOP only PC15-LOW write — rail still dropped
- **`fw_07`** + NOP PB7-LOW — still dropped
- **`fw_08`** + NOP PA2-LOW — rail stays up. Declared victory.
- **`fw_12`** Combined fw_05 + fw_08 patches — auto-boot + rail-stays-up
- **`fw_13`** Single-byte experiment to reduce 15-min auto-standby timeout → lands in cyan intermediate state, deferred (task #29)

This phase ended with a "victory" that was actually wrong — we had no baseline to bisect against. Came back to this in Phase F.

### Phase D — Goal #2 Phase 1: monotone/silence detection (tasks #14, #47-#51)
- **`fw_21`** Detect monotone source as "silence" and auto-suspend → boot-faulted due to LDR offset off-by-one
- **`fw_22`** ★ Fixed offsets, working: auto-on + wake-on-SPDIF + auto-suspend on silence (~15 min)
- Task **#51**: documented the two patch shims with annotated assembly

### Phase E — DSP control protocol RE (tasks #52-#57)
*Driven by user observation of "occasional crackle on certain tracks"*
- Phase 1 verification: confirmed `write_dsp_register @ 0x0800CAA0`, `set_audio_mode @ 0x0800C560`, mode preset table at `0x0800C5F4`, event dispatch at `0x0800ACA4`
- Phase 2: built `dsp_protocol.md` register map
- Phase 3: identified top crackle-candidate registers
- Phase 4: GDB recon + `fw_23` (force Music mode) bench test
- Outcome: register map complete; crackle is likely intersample peaks at DAC stage (post-DSP), not patchable from firmware

### Phase F — IR remote mapping (task #58)
- Original approach (single GDB BPs) caught nothing — IR runs too fast
- **`fw_25`** Prep work: NOP `bl post_event_type0` so bench could observe IR-power dispatches without triggering standby
- **`fw_26/27/28`** Three failed firmwares due to `B.W` Thumb-2 instruction on ARMv6-M (dead-ends in scratch/)
- **`fw_29`** ★ Working `notify()` trampoline + 1-slot RAM log → captured every IR button's `(channel, value)` tuple
- Cross-referenced with the dispatch helper at `0x080108E2` to map cmd_ids — caught and fixed an off-by-one in the LIMIT byte (user's pushback was the key signal)
- Result: complete `IR_CODES.md` covering all 14 remote buttons

### Phase G — Standby DSP investigation (task #59)
*Driven by user noticing the bar's red-LED standby still had the DSP warm and current draw was higher than expected*
- Bench bisection via live GDB writes to GPIO BSRR registers
- Found PC15 alone is the Toslink rail master — fw_22's three-pin NOP was over-conservative
- **`fw_34`** ★ Minimal NOP: only PC15-LOW, lets PB7 and PA2 go LOW normally
- Bench-verified: bar suspends cleanly, DSP truly off in standby, still wakes on SPDIF return

### Phase H — Preloaded user-state experiments
- **`fw_32`** vEEPROM page appended with vol=35, bass=8, mode=Music — on fw_22 base
- **`fw_35`** ★ Same idea on the better fw_34 base — productive variant

### Phase I — USB-MSC investigation (tasks #63-#68)
*The big detour: 3 days that pivoted twice*
- **Task #63**: Identified PA0+EEPROM service-mode chain in app (statically traced) — initial assumption: this is the MSC entry
- **Task #64**: Built `fw_36` (force PA0 LOW + bypass EEPROM check) → bench-tested → state[+9]=1 confirmed service init completes, but no USB activity. USBEN never set.
- **Task #67**: Built `fw_37` (added USBEN-enable shim at `0x0801E880`) → bench-tested → telltale showed shim runs but USB still doesn't enumerate
- **Task #65**: Investigated CEC hypothesis → confirmed: the PA0+EEPROM "service mode" is actually HDMI-CEC factory test, NOT USB MSC. Disasm of `cec_peripheral_init @ 0x0800EE9C` shows CECEN enable, IRQ 30 (= CEC_CAN), CEC handle struct setup.
- Eureka moment: `bootloader.main @ 0x080039D4` ≠ application main. The actual application is at `0x08008000`. The bootloader at `0x08000000-0x08007FFF` is a SEPARATE thing with its own MSC implementation.
- **Task #68**: Built `fw_38` (1-byte patch in bootloader: `bne→b`) → bench-tested → **MSC mode entered, bar enumerates as PID 0x0004**
- Decoded the full upload protocol via live BP tracing of the WRITE handler
- End-to-end validated by uploading a self-identifying 96 KB test pattern + reading back via SWD: every word matched
- Identified the end-user entry gesture: **hold the chassis SUB PAIRING button while powering on** (verified 2026-06-09 via per-pin GPIO scan — PA1 toggles only when the sub-pairing button is pressed; an earlier guess that PA1 was the IR receiver was disproved by the same scan)

### Phase J — Housekeeping and documentation
*Tasks: implicit*
- `MSC_PROTOCOL.md` — canonical protocol documentation
- `CEC_PROTOCOL.md` — the CEC subsystem we mistook for MSC
- `USB_MODES.md` — flagged as superseded; preserved for historical context
- `symbols.md`, `FIRMWARE_VARIANTS.md`, `IR_CODES.md`, `dsp_protocol.md` — final updates
- Reorganized scripts: top-level = productive, `scratch/` and `gdb/scratch/` = dead-ends and one-shot probes
- `RE_JOURNEY.md` — narrative tutorial walkthrough
- This file

---

## Task index

The earlier session work (tasks #1-#13) isn't fully preserved in current context; #14 onwards is exact. Status as of 2026-06-09.

### Completed

| # | Title | Phase | Notes |
|---|---|---|---|
| #14 | Goal #2 Step 2: wake-on-SPDIF polling injection | D | Became `fw_22` |
| #47 | Flash + bench-test `firmware_21` (monotone detection) | D | LDR offsets off-by-one, fixed in fw_22 |
| #48 | Investigate: where is the actual 15-min auto-standby mechanism? | D | Mapped via auto_standby_check @ 0x08011524 |
| #49 | Build `firmware_22` (fix off-by-one LDR offsets in fw_21 shim) | D | ★ |
| #50 | Flash + bench-test `firmware_22` (LDR offset fix) | D | ★ Productive |
| #51 | Document the two patch shims with annotated assembly | D | In SHIMS.md |
| #52 | Phase 1: Verify DSP register-writer @ 0x0800CAA0 | E | Confirmed |
| #53 | Phase 1: Verify mode-preset loader @ 0x0800C560 + table @ 0x0800C5F4 | E | Confirmed |
| #54 | Phase 1: Confirm event dispatch @ 0x0800ACA4 + per-handler addresses | E | Confirmed |
| #55 | Phase 2: Build `dsp_protocol.md` register map | E | Done |
| #56 | Phase 3: Identify top 3-5 crackle-candidate registers | E | Done |
| #57 | Phase 4: GDB recon + `fw_23` (force Music mode) bench test | E | Done |
| #58 | IR mapping — COMPLETE via ring buffer + static decode | F | ★ `IR_CODES.md` |
| #59 | Revisit DSP power-rail / I²C state in standby — DSP responsive in red-LED | G | ★ Led to `fw_34` |
| #63 | USB-MSC trigger identified statically (PA0 LOW + EEPROM) | I | **Initially "completed" — later found to be CEC, not MSC** |
| #64 | Build + bench-test `fw_36` (forced PA0-LOW path) | I | Revealed CEC truth |
| #65 | Verify CEC hypothesis for service mode | I | ★ Reframed Phase I |
| #67 | Bench-test `fw_37` (USBEN forced) | I | Demonstrated USB peripheral can be brought up |
| #68 | Bench-test `fw_38` (bootloader MSC mode) | I | ★ MSC works |

### Pending (open)

| # | Title | Priority | Notes |
|---|---|---|---|
| #29 | ★ [DEFERRED] Reduce standby timeout cleanly (5 min, no cyan state) | Medium | The fw_13 path landed in cyan intermediate state — needs cleaner approach |
| #60 | [LOW PRIO] Patch master output gain | Low | Hypothesis weakened by "rare metallic click" symptom (sounds like underrun, not headroom) |
| #61 | Investigate DSP register `0xB9 = 0x038E7A` (unique boot-time config constant) | Low | Anomaly in DSP register map |
| #62 | ★ Investigate occasional metallic click | High | Likely I²S underrun or biphase bit-slip — hardware-side, not firmware-patchable |
| #66 | Map the 6-pin ribbon cable to the front PCB (LED + IR receiver) | Low (revised) | The original motivation (find PA1 for MSC entry) is **resolved** — PA1 is the chassis SUB PAIRING button, not on the ribbon. Ribbon mapping still useful for completeness (identifying which ribbon pin is IR receiver, which are R/G/B LED) but no longer blocks any MSC-related work. PB1 = IR receiver output (verified via GPIO scan) and is probably routed via the ribbon. |

---

## Outcomes summary

**Productive firmware delivered:**
- `firmware_05_autoboot-active-on-power.bin` (Goal #1 only)
- `firmware_34_pc15-only-keepalive.bin` (Goal #1 + Goal #2, cleanest) ★ recommended
- `firmware_35_preloaded-music-vol35.bin` (fw_34 + preloaded vEEPROM state)

**Protocols / interfaces decoded:**
- DSP control register map (`dsp_protocol.md`)
- IR remote → cmd_id mapping (`IR_CODES.md`)
- HDMI-CEC subsystem (`CEC_PROTOCOL.md`)
- USB-MSC firmware-update (`MSC_PROTOCOL.md`)

**Open practical questions:**
- Task #62: the occasional metallic click — needs hardware-level investigation (logic analyzer on I²S lines, or scope on DAC output)
- Task #66: ribbon-cable PA1 mapping — multimeter, ~10 minutes, would enable end-user MSC entry without case removal

**Key reusable artifacts:**
- `patcher/` — shareable scripts that patch a user's own dump (no firmware redistribution)
- `build_msc_upload.py` — produces MSC upload files from any 128 KB firmware image
- `gdb/` — the productive GDB helpers (status.sh, switch_mode.sh, msc_trace.gdb, etc.)

---

## Lessons across the project

1. **Goals are stable, tasks proliferate.** We started with 2 goals and grew 68 tasks. That's healthy — each task is a falsifiable subgoal. The tasks that turned into red herrings (e.g., #63) still produced data.

2. **Phases are emergent, not planned.** Looking back, the phases divide cleanly into A-J — but at the time, they overlapped and ran in parallel. The phase view is post-hoc structuring.

3. **Numbered tasks made conversation efficient.** "Let's do #59" or "task #63 is reframing into CEC" were faster than re-explaining what we meant each time. The task list is also the audit trail — if you come back in 3 months, you can read down the list and reconstruct the work.

4. **Closing tasks honestly matters.** Task #63 was marked "completed" when we statically found PA0+EEPROM — but it was *wrong*. Better practice: a "completed" task should mean "delivered the actual outcome," not "we believe we've identified something." When we later realized PA0+EEPROM was CEC, we created task #65 ("verify CEC hypothesis") rather than re-opening #63. The chain of tasks tells the story.
