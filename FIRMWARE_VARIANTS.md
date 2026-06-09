# Teufel Cinebar One — Firmware Variants

Index of every firmware binary produced during this RE work, with status and rationale. **`firmware_22_wake-on-spdif.bin`** is the productive base (auto-on + wake-on-SPDIF, no extra shims). Everything else layers on top for either an extra feature or for instrumentation.

All binaries are 128 KB, load at `0x08000000`. Flash via:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "program <file> verify reset exit 0x08000000"
```

Rollback to factory: `firmware_01_original-dump.bin`.

## Productive lineage

| File | Layers on | Status | Purpose |
|---|---|---|---|
| `firmware_01_original-dump.bin` | — | ★ Baseline | Factory dump, RDP=AA verified. Rollback target. |
| `firmware_05_autoboot-active-on-power.bin` | 01 | ✓ Goal #1 | Bar boots to active state on AC restore (vs factory standby). |
| `firmware_12_autoboot-active-rail-on.bin` | 01 | ✓ Goal #1+rail | fw_05 + NOPs of `PA2/PB7/PC15 LOW` in standby path. Audio rail stays up across standby. |
| `firmware_22_wake-on-spdif.bin` | 01 | ✓ Working (over-conservative) | Goal #1 + Goal #2 complete: auto-on + wake-on-SPDIF + auto-suspend on silence ~15 min. Functional but DSP stays powered in standby (PB7 stays HIGH) — superseded by fw_34. |
| **`firmware_34_pc15-only-keepalive.bin`** | 22 | ★ **Productive** (bench-verified 2026-06-08) | Minimal-NOP version of fw_22. Bench bisection (direct GPIO toggling) showed PC15 alone is the Toslink-rail master, so the PA2-LOW and PB7-LOW writes in the standby path don't need to be NOPed. fw_34 NOPs only `0x0A836` (PC15-LOW) and lets PA2/PB7 go LOW normally — so the DSP actually powers down in standby (PB7 LOW kills the DSP rail), while Toslink stays alive for wake-on-SPDIF (PC15 HIGH). End-to-end verified: bar auto-suspends on silence and auto-wakes when SPDIF returns. Resolves task #59. |
| `firmware_23_music-mode-default.bin` | 22 | ✓ Optional | + 24-byte Shim 3 at `0x0801E880`: after every `transition_state(2)` (wake), calls `set_audio_mode(0)` to force Music. Useful only if the bar auto-switches mode on detected audio format. Hasn't yet been rebuilt on fw_34 base — would be straightforward. |
| `firmware_32_preloaded-music-vol35.bin` | 22 | ✓ Legacy | fw_22 with vEEPROM page appended: `vol=35, bass=8, modeExtend=1, mode=Music`. Superseded by fw_35 (same idea on the better fw_34 base). |
| `firmware_35_preloaded-music-vol35.bin` | 34 | ✓ Optional | Same vEEPROM append as fw_32, but on the productive fw_34 base. Bar boots with `vol=35, bass=8, modeExtend=ON, mode=Music`, gets fw_34's "DSP fully off in standby" behaviour as well. |

## Diagnostic / probe variants (kept around — still flashable)

| File | Layers on | Purpose |
|---|---|---|
| `firmware_03_redirect-shim-noop.bin` | 01 | Sanity test: proves the shim-redirect mechanism works (NO-OP shim). |
| `firmware_04_autoboot-partial-no-notify.bin` | 01 | First Goal #1 attempt — booted with audio on but LED stuck red (no notify). Led to fw_05. |
| `firmware_06_keep-audio-rail-in-standby.bin` | 01 | Goal #2 Step 1 v1: NOP PC15-LOW only. Rail still dropped. |
| `firmware_07_keep-audio-rail-pb7-pc15.bin` | 01 | + PB7. Rail still dropped. |
| `firmware_08_keep-audio-rail-pa2-pb7-pc15.bin` | 01 | + PA2. Rail stays up, but cold-boot quirk. Superseded by fw_12. |
| `firmware_13_combo-5min-standby.bin` | 12 | Single-byte experiment to reduce auto-standby timer. Lands in cyan/intermediate state. Deferred (see task #29). |
| `firmware_25_nop-ir-power-post.bin` | 22 | NOPs `bl post_event_type0` at `0x0800BFAA` (inside IR-power's sub=1 handler). Lets IR-power dispatch be observed via GDB BPs/trampoline without the bar entering standby and HardFaulting during the transition. |
| `firmware_29_notify-trap-v2.bin` | 25 | + minimal `notify()` trampoline that logs `{channel, value}` to a single RAM slot at `0x20003E00`/`0x20003E04` before tail-calling notify+4. This is what found `IR-power = notify(13, 0x0201)`. See IR_CODES.md. |
| `firmware_36_pa0-low-and-eeprom-bypass.bin` | 34 | **Experimental USB-MSC test build.** Two patches, 5 bytes total: (A) flips BEQ→B in `read_pa0()` at `0x0800F14A` so it always returns LOW, (B) replaces the first two instructions of `service_mode_handshake()` at `0x0800ED10` with `movs r0,#0; bx lr` so the EEPROM check immediately succeeds. Bench-tested 2026-06-08: state[+9]=1 confirms service init completes, BUT RCC_APB1ENR bit 23 (USBEN) is never set so USB never enumerates. Service mode turns out to be HDMI-CEC-driven; EEPROM is unrelated to USB. |
| `firmware_37_usben-forced.bin` | 36 | **Experimental USB-MSC test build, layer 2.** fw_36 + a 48-byte shim at `0x0801E880`. The shim writes a telltale `0xDEADBEEF` to RAM `0x20003FFC`, sets `RCC_APB1ENR \|= (1 << 23)` (USBEN), then tail-calls the original USB init at `0x080030B0`. Bench-tested 2026-06-09: telltale was NOT written → **shim never ran**. The reason: `0x080039D4` is the BOOTLOADER's main, NOT the app's main. The bootloader normally jumps to the app at `0x08008000` via `bl 0x08002DB8` (at `0x08003A92`) and never reaches `0x08003AD0`. The MSC init at `0x08003AD0` is the bootloader's USB-MSC-firmware-update code, only reached if the bootloader decides NOT to jump. |
| `firmware_38_bootloader-msc-mode.bin` | 37 | **Experimental USB-MSC test build, layer 3.** fw_37 + a 1-byte patch at `0x03A89` (`0xD1` → `0xE0`) that flips the `bne` at `0x08003A88` to unconditional `b`. This forces the bootloader's app-validity check to always "fail" → bootloader skips the boot-jump → continues to the USB MSC init path. **Side effect: the application NEVER RUNS.** No audio, no IR, no normal operation. Bar is in MSC update mode permanently until reflashed. For full MSC test, ALSO requires T211 externally pulled HIGH (1 kΩ → 3.3 V). Reflash fw_34 to restore normal operation. |

## Dead-ends (lessons learned)

These binaries either boot-faulted or didn't accomplish their goal. Kept on disk (cheap, ~128 KB each) for traceability. **Do NOT flash these — they will brick the bar until you reflash a productive variant.**

### `firmware_24_nop-transition-state.bin` — boot HardFault

**Goal**: NOP the entire `transition_state` function (`0x0800A740: b5f8 → 4770` = bx lr immediate return) so injected IR-power couldn't reach the standby transition and HardFault.

**Why it failed**: `transition_state(2)` is called during boot init to bring the bar up from cold/standby into the active state. NOP'ing it left DSP/GPIOs uninitialized → first instruction in the bar's main loop that touches uninitialized hardware → HardFault at `0x08008CB8` (the SVC return).

**Lesson**: NOP'ing a function is only safe if it's never called during boot. A targeted NOP at the specific BL inside the IR-power handler (`0x0800BFAA`) is safer — done in fw_25.

### `firmware_26_nop-and-ring-log.bin`, `_27_simple-notify-log.bin`, `_28_passthrough-tramp.bin` — all boot HardFault

**Goal**: Trampoline at `0x0801E8A0` patched into `notify()` entry (via 4-byte `b.w trampoline` at `0x0800BBDC`) to log every notify call to a RAM ring buffer.

**Why they all failed (same root cause)**: I encoded a Thumb-2 **`B.W`** (unconditional 32-bit branch) for the patch and the trampoline's tail-jump. **B.W (encoding T4) is in ARMv7-M but NOT in ARMv6-M / Cortex-M0.** The CPU decoded `0xF012 0xBE60` (my "b.w") as an UNDEFINED instruction → HardFault on the first notify() call (which happens early in boot).

**Diagnostic that pinned it**: fw_28 was a pass-through trampoline with **no logging at all** — just displaced push+ldr + b.w back. Still HardFaulted. That proved the issue was the redirect mechanics, not the logging code.

**Lesson**: On Cortex-M0, the only valid 32-bit Thumb-2 instructions are **BL, MRS, MSR, ISB, DSB, DMB**. For long-distance unconditional branches without saving LR, use `ldr Rd, [pc, #imm]; bx Rd` and clobber a caller-saved register (r0-r3, r12). Fix lives in fw_29 (using `ldr r2, [pc, #48]; bx r2` + a repurposed literal at `0x0800BC10`).

### `firmware_30_notify-ring.bin`, `_31_ring-no-magic.bin` — fw_30 boot-faulted, fw_31 never tested

**Goal**: Extend the working fw_29 trampoline to a proper 32-entry ring buffer (so we'd capture multiple notify() calls per IR press, not just the most recent).

**Why fw_30 failed**: Boot-HardFaulted with the same `0x08008CB8` SVC-return signature. The trampoline encoding (BL, correct this time) was fine, but something in the multi-instruction ring logic clobbered a register state that caused a kernel SVC-return to find a bad PC on the stack. Root cause not fully diagnosed.

**fw_31** removed only the magic write to isolate the bug. It was built but **never flashed/tested** — the single-slot fw_29 was enough to verify the IR mapping, so we stopped here.

**Lesson**: When adding more state mutations inside a trampoline that runs from arbitrary RTX contexts, **r2 and r3 modifications affect the displaced original `push {r3, r4-r7, lr}` — the pushed r3 is the modified one, then `str r0, [sp, #0]` inside notify() overwrites that stack slot with the alloc result**. The cascading effect through subsequent SVC calls may land on a corrupted return-PC. Safer: avoid modifying r3 in the trampoline (push it to a side scratch, restore before the displaced push), or use only r2 as scratch.

---

## Goal #2 Step 2 iteration history (fw_14 through fw_21) — also dead-ends

We iterated quite a bit on Step 2 before fw_22. Key learnings worth recording so this isn't re-attempted:

- **fw_14** (level-triggered PA3 polling): bar wake-looped because PA3 always reads LOW in active state with Toslink connected. Fundamental misread of PA3's semantics — the actual SPDIF data carrier is PA4.
- **fw_15/16/17/18** attempts: tried various NOPs (PF0, I²C1) and edge-triggering. The NOP of BNE at `0x0ACC8` (intended to expose the wake-check BL in standby) caused an IR-off error because it newly exposed the post-shim periodic-timer code to standby state, triggering a downstream side effect.
- **fw_19** (wrap osMessageQueueGet at `0x0ACBC`): cleared the IR-off error. But "silent = all 16 PA4 samples LOW" was too strict — muted source produces all-HIGH PA4 (Toslink receiver idle), so silence_seen never flipped.
- **fw_20** (added active-state auto-suspend via `last_toggle_tick`): tick-rate misestimate (we'd assumed ~1.1 Hz; it's actually 1 kHz / 1ms tick), making auto-suspend threshold 1 second instead of 15 min. Reverted.
- **fw_21**: fw_19's design + monotone detection. But had off-by-one in LDR PC-relative offsets — r5/r6 each loaded the wrong literal. Discovered via GDB: shim entry BP fired correctly, but silence_seen at `0x20002506` never updated.
- **fw_22**: 2-byte fix on fw_21's LDR offsets (file offsets `0x1E82A` and `0x1E82C`, `0x0F → 0x10`). The Productive variant.

Binaries fw_09, _10, _11, _14, _15, _16, _17, _18, _19, _20, _21 were **deleted** when their issue was confirmed (kept in the lesson notes above).

---

## Cross-cutting lessons (project-wide)

Encoded here so a future RE-er doesn't repeat them.

1. **ARMv6-M instruction set is restricted.** Only Thumb-1 + a tiny Thumb-2 set (BL, MRS, MSR, ISB, DSB, DMB). No B.W, no CBZ/CBNZ, no IT, no TBB/TBH, no `ldr pc, [..]`. Encoders aimed at v7-M can produce code that decodes as UNDEFINED on Cortex-M0 — the silent failure mode is HardFault rather than a compile-time error.
2. **Always read the actual IDR for a pin under varied conditions before trusting `is_audio_active()`-style firmware functions.** PA3 reads stuck-LOW in this firmware; the actual SPDIF data carrier is PA4.
3. **The Toslink rail master is PC15 (alone)** — bench-bisected 2026-06-08 by direct GPIO toggling. PA2 has no observable effect on the rail or audio. PB7 controls the DSP power rail (audio stops when PB7 LOW, Toslink rail unaffected). The fw_06/07/08 sequential-NOP experiment that originally concluded "all three needed" was misled by the order of LOW writes in the firmware's standby path — see POWER_SEQUENCES.md for the full explanation. **Lesson: when a hypothesized pin is one of several writes happening in a fixed sequence, use direct GPIO toggling via GDB to isolate the actual master, not NOP-and-flash binary bisection.**
4. **The bar's RTX uses the default 1 kHz tick rate** (we initially mis-estimated as ~1.1 Hz). 1000 ticks = 1 second. The visible "~15 min auto-standby" comes from the SOT-23-5 chip's carrier-detect hysteresis, NOT a firmware timer — the firmware adds only a 1-second debounce.
5. **The dispatch helper at `0x080108E2` uses a LIMIT byte at offset 0 of its inline table; case offsets start at byte 1.** This is the cause of my initial off-by-one when reverse-engineering IR. `cmd_id=N` reads byte `(N+1)` of the inline data. Re-counted carefully: the top-level table has **five** `0x49` no-op bytes in a row (positions 5–9), which I initially miscounted as four — shifting every cmd_id ≥9's target.
6. **vEEPROM at `0x08007000-0x080077FF`** (two 1 KB pages, ST-style log of `(value u16, id u16)`). Persisted IDs: 0x1111 power, 0x2222 volume, 0x3333 bass, 0x4444 modeExtend, 0x5555 audio_mode, 0x6666 ?. Source NOT persisted (likely re-detected on boot).
7. **Audio mode encoding**: 0=Music, 1=Voice, 2=Movie. Earlier `switch_mode.sh` had Movie/Voice swapped — fixed 2026-06-07.
8. **GDB-injected `notify()` is observable but doesn't always cause the bar to react audibly** because the dispatch path can take a fallback exit at `0x0800C32C` when state[0] is in a transitional value. Use fw_29's single-slot logger to confirm the call was made, then check RAM state for the effect.
