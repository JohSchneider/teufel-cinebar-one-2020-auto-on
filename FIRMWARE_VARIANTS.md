# Teufel Cinebar One — Firmware Variants

Index of every firmware binary built during this RE work. **fw_22** is the proven-stable production binary (auto-on + wake-on-SPDIF). **fw_23** and **fw_24** are experimental layers on top of fw_22 (audio mode forcing, IR-event logging). Binaries the user has deleted from disk after they were proven obsolete are listed at the bottom under "Archived/removed".

All binaries are 128 KB, load at flash `0x08000000`. Flash via:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program <file> verify reset exit 0x08000000"
```

Rollback:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_01_original-dump.bin verify reset exit 0x08000000"
```

## Status summary

| File | Bytes changed | Status | Purpose |
|------|---:|---|---|
| `firmware_01_original-dump.bin` | 0 | ★ Baseline | Original 128 KB dump (RDP=AA verified) |
| `firmware_03_redirect-shim-noop.bin` | 11 | ✓ Diagnostic | NO-OP shim — verified the redirect mechanism works |
| `firmware_04_autoboot-partial-no-notify.bin` | 16 | ✗ Partial | Goal #1 attempt 1 — bar booted with audio on but LED stuck red |
| `firmware_05_autoboot-active-on-power.bin` | 24 | ✓ Production (Goal #1) | Bar auto-boots to active state, IR remote still works |
| `firmware_06_keep-audio-rail-in-standby.bin` | 4 | ✗ Insufficient | Goal #2 Step 1 v1: NOP'd PC15-LOW only |
| `firmware_07_keep-audio-rail-pb7-pc15.bin` | 8 | ✗ Insufficient | Goal #2 Step 1 v2: NOP'd PB7+PC15 |
| `firmware_08_keep-audio-rail-pa2-pb7-pc15.bin` | 12 | ✓ Verified (cold-boot quirk) | Goal #2 Step 1 v3: NOP'd PA2+PB7+PC15. Rail stays at 3V after IR-on/off cycle; needs first IR-on to come up at cold boot. |
| `firmware_12_autoboot-active-rail-on.bin` | 36 | ★ ✓ Production (Goal #2 Step 1) | fw_05 + fw_08 combo. Bar auto-boots active, rail stays at 3V across standby cycles. **No cold-boot quirk** — active runs first, then rail is already up when standby happens. |
| `firmware_13_combo-5min-standby.bin` | 37 | ⏸ Deferred | fw_12 + single-byte timeout reduction. Reaches standby in ~3 min but lands in cyan intermediate state instead of red. Deferred until gating mechanism understood. |
| `firmware_22_wake-on-spdif.bin` | 86 | ★ ✓ Production (Goal #1 + Goal #2 complete) | Same design as fw_21 but with **2-byte fix to LDR offsets** in the shim. fw_21 had off-by-one in `ldr r5` and `ldr r6` PC-relative offsets — r5 loaded state struct instead of autostandby, r6 loaded autostandby instead of GPIOA->IDR. Bug discovered via GDB confirming shim invocation but silence_seen at 0x20002506 never updated; manual `post_event_type0(2)` via PC manipulation wake the bar, isolating the issue to the shim's reads/writes. Bench-verified 2026-06-06: AC restore auto-boots active; muted source auto-suspends in ~15 min; unmute wakes within ~25 ms. **IR remote no longer needed in normal use.** |
| `firmware_23_music-mode-default.bin` | +32 from fw_22 | ✓ Experimental (audio mode tuning) | fw_22 + a 24-byte wrapper at `0x0801E880` invoked from both `transition_state` call sites. After every `→active` transition, the wrapper calls `set_audio_mode(0)` to force Music mode (vs whatever the DSP blob defaults to, likely Voice for source 2). Used for A/B testing audio character. `gdb/switch_mode.sh` provides live mode switching on top of this. |
| ~~`firmware_24_ir-logging.bin`~~ | (deleted) | ✗ Broken | First IR-logging build. Buffer placed at RAM `0x20003C00` — turned out to overlap with active task-stack memory. Caused first-call corruption and IR-decoder/event-loop malfunction (bar appeared alive but unresponsive). Empirical RAM probe found `0x20002700-0x20002BFF` is zero-filled and unused; superseded by fw_25. |
| ~~`firmware_25_ir-logging-v2.bin`~~ | (deleted) | ✗ Also broken | Same shim design as fw_24 but with buffer moved to `0x20002700` (found "zero" under fw_24's broken-state RAM probe). Still crashed the bar — apparently the "zero" was a yet-unallocated task stack region that gets used later in fw_25's deeper boot. Lesson: RTX5 stacks aren't zeroed at boot, so "all-zero RAM under a broken firmware" doesn't prove "free." Approach blocked until we get the bar's linker map or use a non-RAM logging channel (SWO, semihosting). See task #58. |

---

## Goal #2 Step 2 iteration history (fw_14 through fw_21)

We iterated quite a bit on Step 2. Key learnings (worth recording so future-you doesn't repeat them):

- **fw_14** (level-triggered PA3 polling): bar wake-looped because PA3 always reads LOW in active-state with Toslink connected. Fundamental misread of PA3's semantics.
- **fw_15/16/17/18** attempts: tried various NOPs (PF0, I²C1) and edge-triggering. The NOP of BNE at `0x0ACC8` (intended to expose the wake-check BL in standby) caused an IR-off error because it newly exposed the post-shim periodic-timer code (state[8]=10 write + conditional BLs) to standby state, triggering some downstream side effect.
- **fw_19** (wrap osMessageQueueGet at `0x0ACBC` instead of the BNE NOP approach): cleared the IR-off error. But "silent = all 16 PA4 samples LOW" was too strict — muted source produces all-HIGH PA4 (Toslink receiver idle), so silence_seen never flipped.
- **fw_20** (added active-state auto-suspend via `last_toggle_tick`): tick-rate misestimate (we'd assumed ~1.1 Hz; it's actually 1 kHz / 1ms tick), making auto-suspend threshold 1 second instead of 15 min. PA3 also read anomalously, possibly because we touched RAM at offset +4..+7 of the autostandby struct that may not be unused. Reverted.
- **fw_21**: fw_19's wrap-around-osMessageQueueGet design + monotone detection. But had off-by-one in LDR PC-relative offsets — r5/r6 each loaded the wrong literal. Shim was invoked but read/wrote wrong memory addresses, silently failing. Discovered via GDB: shim entry BP fired correctly, but silence_seen at 0x20002506 never updated, and manual `post_event_type0(2)` via PC manipulation DID wake the bar (confirming wake path works, isolating the issue to the shim's logic).
- **fw_22**: 2-byte fix on fw_21's LDR offsets (file offsets 0x1E82A and 0x1E82C, `0x0F` → `0x10`). All other shim logic unchanged.

Truth tables (post-2026-06-06):
- **PA4**: directly reflects Toslink fiber state. Toggles ~50/100 when fiber transmits data; stuck HIGH when fiber dark (mute); stuck LOW when receiver not driven (cable unplugged).
- **PA3**: reflects the SOT-23-5 chip's "carrier detected" state with significant hysteresis (some minutes). Cable unplugged → PA3 quickly HIGH. Fiber goes dark but cable still in → PA3 eventually transitions HIGH after the chip's internal silence-detect timer expires.
- **Tick rate**: ~1 kHz (RTX5 default 1ms ticks). The "15 min" auto-standby observation actually comes from the SOT-23-5 chip's hysteresis (not a 1000-tick firmware threshold). The `auto_standby_check`'s 1000-tick threshold fires within 1 sec once PA3 has been HIGH, but the chip's hysteresis dominates total observed delay.


## Production binaries (detailed)

### `firmware_05_autoboot-active-on-power.bin` — Goal #1 ★

**Behavior**: bar auto-boots to active state at AC power-on. IR remote behaves normally.

**Mechanism**: hijacks the BL at `0x0800ACAC` (`bl 0x0800AE78` inside event_loop_thread, normally calls "init 2") to instead call a 22-byte shim in patch space, which calls the original target, then `transition_state(2)`, then `notify(0, retval)`.

**Patches (24 bytes total)**:
| File offset | Original | New | Why |
|---|---|---|---|
| `0x0ACAC` | `00 f0 e4 f8` | `13 f0 a8 fd` | BL redirect: `bl 0x0800AE78` → `bl 0x0801E800` |
| `0x1E800` | `ff …` × 22 | `00 b5 ec f7 39 fb 02 20 eb f7 9a ff 01 46 00 20 ed f7 e4 f9 00 bd` | 22-byte shim |

**Shim disassembly**:
```
0x0801E800: push  {lr}
0x0801E802: bl    0x0800AE78    ; original init 2
0x0801E806: movs  r0, #2
0x0801E808: bl    0x0800A740    ; transition_state(2)
0x0801E80C: mov   r1, r0
0x0801E80E: movs  r0, #0
0x0801E810: bl    0x0800BBDC    ; notify(0, retval)
0x0801E814: pop   {pc}
```

**Apply**:
```bash
cp firmware_01_original-dump.bin firmware_05_autoboot-active-on-power.bin
printf '\x13\xf0\xa8\xfd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x0ACAC)) conv=notrunc
printf '\x00\xb5\xec\xf7\x39\xfb\x02\x20\xeb\xf7\x9a\xff\x01\x46\x00\x20\xed\xf7\xe4\xf9\x00\xbd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x1E800)) conv=notrunc
```

### `firmware_12_autoboot-active-rail-on.bin` — Goal #2 Step 1 ★

**Behavior**: bar auto-boots to active state (purple LED). Auto-standby fires after ~9-15 min of silence → bar to red LED. **Toslink Vcc stays at 3V** in standby. IR cycles work normally.

**Mechanism**: combines fw_05 (auto-boot shim + BL redirect) with three NOPs in `transition_state` path 2 that prevent the standby-entry GPIO writes that would drive PA2/PB7/PC15 LOW.

**Patches (36 bytes total)** — all of fw_05 plus:
| File offset | Original | New | Why |
|---|---|---|---|
| `0x0A81A` | `06 f0 71 fe` | `00 bf 00 bf` | NOP `bl 0x08011500` — prevents `spdif_subsystem_init` from driving PA2=LOW in standby path |
| `0x0A81E` | `01 f0 35 fe` | `00 bf 00 bf` | NOP `bl 0x0800C48C` — prevents PB7=LOW chain |
| `0x0A836` | `02 f0 12 ff` | `00 bf 00 bf` | NOP `bl GPIO_WriteBit(GPIOC, 0x8000, 0)` — prevents PC15=LOW |

**Apply**:
```bash
cp firmware_05_autoboot-active-on-power.bin firmware_12_autoboot-active-rail-on.bin
for off in 0x0A81A 0x0A81E 0x0A836; do
    printf '\x00\xbf\x00\xbf' | \
        dd of=firmware_12_autoboot-active-rail-on.bin bs=1 seek=$((off)) conv=notrunc
done
```

### `firmware_22_wake-on-spdif.bin` — Goal #1 + Goal #2 production ★

**Behavior** (intended): everything fw_12 does, plus the bar auto-wakes when the Toslink fiber returns from a "dark" state in standby (audio resumes or source unmutes or cable plugged back in). Wake fires within ~22 sec of fiber lighting back up (one event_loop poll cycle). IR-off while audio is still playing does **not** cause a wake-loop because the wake gate requires observing fiber-dark first.

**Mechanism**:
1. **NOP at `0x0A828`** (4 bytes) — prevents PF0=LOW in standby path, keeping DSP alive. With DSP alive, the Toslink module driver keeps signaling PA4 with raw SPDIF data. Without this, PA4 reads stuck-LOW in standby and there's nothing to detect (verified via Phase D2 bench session 2026-06-06).
2. **NOP BNE at `0x0ACC8`** (2 bytes) + **redirect BL at `0x0ACCA`** (4 bytes) → 84-byte shim at `0x0801E820`. The shim dispatches:
   - `state[0]==2` (active): call original `auto_standby_check` (preserves auto-standby behavior)
   - `state[0]==1` (standby): take 16 quick reads of PA4. If all LOW → set `silence_seen=1`. If any HIGH AND silence_seen was already 1 → post wake event; reset silence_seen.
   - Other states: no-op

**Patches (93 bytes vs fw_12)**:
| File offset | Original | New | Why |
|---|---|---|---|
| `0x0A828` | `02 f0 19 ff` | `00 bf 00 bf` | NOP `bl GPIO_WriteBit(GPIOF, 1, 0)` — DSP stays alive in standby |
| `0x0ACC8` | `f4 d1` | `00 bf` | NOP `bne 0x800acb4` — BL at `0x0ACCA` runs in all states, not just active |
| `0x0ACCA` | `06 f0 2b fc` | `13 f0 a9 fd` | Redirect `bl auto_standby_check` → `bl 0x0801E820` (our shim) |
| `0x1E820` | `ff …` × 84 | (shim) | 84-byte polling+debounce+silence-gate shim |

**Shim layout** (84 bytes at `0x0801E820`):
```
push  {r4, r5, r6, r7, lr}
ldr   r4, =0x200025DC          ; main state struct
ldr   r5, =0x20002504          ; auto_standby_check struct (silence_seen at +2)
ldrb  r0, [r4, #0]              ; state[0]
cmp   r0, #2
bne   not_active
bl    0x08011524                ; auto_standby_check (active path)
b     done
not_active:
cmp   r0, #1
bne   return_zero               ; transitioning, no-op
ldr   r3, =0x48000010           ; GPIOA->IDR
movs  r7, #16                   ; PA4 mask (bit 4)
movs  r0, #0                    ; saw_high = 0
movs  r1, #16                   ; loop count
poll_loop:
ldr   r6, [r3, #0]              ; r6 = IDR
ands  r6, r7
beq   next_iter
movs  r0, #1                    ; saw HIGH this round
next_iter:
subs  r1, #1
bne   poll_loop
cmp   r0, #0
bne   saw_audio
;; all 16 samples were LOW → silence
movs  r1, #1
strb  r1, [r5, #2]              ; silence_seen = 1
b     return_zero
saw_audio:
ldrb  r1, [r5, #2]
cmp   r1, #0
beq   return_zero               ; no prior silence: just IR-offed with audio playing, don't wake
;; silence_seen was 1 and now audio appeared: WAKE
movs  r1, #0
strb  r1, [r5, #2]              ; reset silence_seen
movs  r0, #2
bl    0x0800AB00                ; post_event_type0(2)
return_zero:
movs  r0, #0
done:
pop   {r4, r5, r6, r7, pc}
.word 0x200025DC
.word 0x20002504
.word 0x48000010
```

**Why the silence_seen gate**: this solves fw_14's wake-loop bug. After IR-off with audio still playing on the SPDIF source, PA4 toggles continuously — so the shim sees mixed HIGH/LOW samples, never reaches "all-LOW", and silence_seen stays 0. Wake won't fire. Only when audio stops (PA4 goes all-LOW for one poll cycle) does silence_seen flip to 1; subsequent audio resumption triggers the wake.

**Verification (intended bench test)**:
1. AC restore → bar auto-boots active (purple) — regression test ✓
2. IR-off **while audio is playing on source** → bar to standby (red) and **stays** — no wake-loop
3. Pause TV in standby → bar stays in standby
4. Resume TV → bar wakes within ~22 sec → active (purple)
5. Auto-standby after 15 min silence → bar to standby ✓
6. Resume TV after auto-standby → bar wakes ✓

**Apply**:
```bash
cp firmware_12_autoboot-active-rail-on.bin firmware_17_wake-on-spdif.bin
printf '\x00\xbf\x00\xbf' | \
    dd of=firmware_17_wake-on-spdif.bin bs=1 seek=$((0x0A828)) conv=notrunc
printf '\x00\xbf' | \
    dd of=firmware_17_wake-on-spdif.bin bs=1 seek=$((0x0ACC8)) conv=notrunc
printf '\x13\xf0\xa9\xfd' | \
    dd of=firmware_17_wake-on-spdif.bin bs=1 seek=$((0x0ACCA)) conv=notrunc
# Shim bytes
printf '\xf0\xb5\x11\x4c\x11\x4d\x20\x78\x02\x28\x02\xd1\xf2\xf7\x7a\xfe\x19\xe0\x01\x28\x16\xd1\x0e\x4b\x10\x27\x00\x20\x10\x21\x1e\x68\x3e\x40\x00\xd0\x01\x20\x01\x39\xf9\xd1\x00\x28\x02\xd1\x01\x21\xa9\x70\x07\xe0\xa9\x78\x00\x29\x04\xd0\x00\x21\xa9\x70\x02\x20\xec\xf7\x4e\xf9\x00\x20\xf0\xbd\xdc\x25\x00\x20\x04\x25\x00\x20\x10\x00\x00\x48' | \
    dd of=firmware_17_wake-on-spdif.bin bs=1 seek=$((0x1E820)) conv=notrunc
```

---

### `firmware_23_music-mode-default.bin` — Force Music mode at every wake

**Behavior**: identical to fw_22, plus every `→active` transition (cold boot, IR-on, wake-on-SPDIF) calls `set_audio_mode(0)` to override the DSP blob's default mode (which appears to be Voice for source 2 = Toslink). Built to test whether mode is the source of the rare metallic click — verdict: Music vs Voice barely differ for stereo PCM (Movie goes silent on stereo). Side-effect: companion `gdb/switch_mode.sh` script lets you live-switch modes during playback.

**Mechanism**: 24-byte wrapper at `0x0801E880` that calls `transition_state(action)` then, if `action==2`, calls `set_audio_mode(0)`. Both `transition_state` BL sites (shim 1 @ `0x0801E808` and event-dispatch @ `0x0800AD12`) are redirected to the wrapper.

**Patches (32 bytes vs fw_22)**:
| Offset | Original | New | Why |
|---|---|---|---|
| `0x0801E808` | `eb f7 9a ff` (→ 0x800A740) | `00 f0 3a f8` (→ 0x0801E880) | shim 1 BL redirect |
| `0x0800AD12` | `ff f7 15 fd` (→ 0x800A740) | `13 f0 b5 fd` (→ 0x0801E880) | event-dispatch BL redirect |
| `0x0801E880` | `ff …` × 24 | 24-byte wrapper | the wrapper itself |

See `SHIMS.md` for the wrapper's full assembly. Build script: `/tmp/firmware/build_fw_force-mode.py` — takes mode (0/1/2) as arg, can rebuild Music/Movie/Voice variants from fw_22.

### `firmware_25_ir-logging-v2.bin` — Notify() call logging shim ★

**Behavior**: identical to fw_23 (Music mode forced), plus an inline call to a logging shim on every `notify(channel, value)` invocation. Each call records `(channel, caller_lr)` into a 64-entry ring buffer at RAM `0x20002700`. Used to find the IR decoder by capturing where `notify(channel=2, ...)` originates (the IR-power button maps to channel 2).

**Mechanism**: 8-byte detour overwrites notify's first 4 instructions; jumps to a 56-byte shim in patch space that replicates the prologue, logs to the ring buffer, then tail-jumps to `notify+8`. No GDB breakpoints needed; bar runs at full speed.

**Patches (64 bytes vs fw_23)**:
| Offset | Original | New | Why |
|---|---|---|---|
| `0x0800BBDC` | `f8 b5 0c 4c 0d 46 06 46` | `00 4b 18 47 c1 e8 01 08` | `ldr r3, =shim+1; bx r3` — preserves LR (unlike BL) |
| `0x0801E8C0` | `ff …` × 56 | 56-byte shim | replicate prologue + log + tail-call notify+8 |

**Ring buffer layout** at `0x20002700`:
- offset 0: `u32 idx` (write pointer, wraps at 64)
- offset 4 + i*8: `u32 channel`, `u32 caller_lr`

**Why `0x20002700`?** fw_24 originally placed the buffer at `0x20003C00` which collided with a task's stack memory — the first write corrupted live task state and the bar appeared alive but unresponsive (event_loop stopped processing IR). Empirical RAM probe under fw_24 found `0x20002700–0x20002BFF` is all-zero and sits between known globals (ending ~`0x200026AC`) and the RTX5 TCB at `0x20002C00` (which contains `osRtxInfo` pointer). Safe ~1.2 KB region.

Read via `gdb/read_ir_log.sh`. Build script: `/tmp/firmware/build_fw25_ir-logging.py`.

---

## Diagnostics / earlier waypoints (kept for archeology)

### `firmware_03_redirect-shim-noop.bin`
NO-OP shim at `0x0801E800` proved the redirect mechanism works before risking real logic. 11 bytes changed.

### `firmware_04_autoboot-partial-no-notify.bin`
First Goal #1 attempt — called transition_state(2) but didn't follow with notify. Bar booted with audio enabled but LED stuck red. Led to fw_05.

### `firmware_06`, `firmware_07`, `firmware_08`
The three iterations on the "keep audio rail powered in standby" puzzle. Each one NOPped a different combination of standby-entry GPIO writes:
- fw_06 (PC15 only): rail still dropped
- fw_07 (PB7 + PC15): rail still dropped
- fw_08 (PA2 + PB7 + PC15): rail stays up after first IR cycle. The cold-boot quirk (PA2 written LOW by separate boot init at `0x0800A5D0`) made this only partially useful; fw_12 supersedes by going active first.

### `firmware_13_combo-5min-standby.bin`
Single-byte experiment to reduce the auto-standby timer (`0x801154a`: `7d → 2a` reducing 1000 → 336 ticks). Reaches a decision-2 state at ~3 min but the bar ends up in a cyan/intermediate LED state, not full standby. There's another gating timer we'd need to also adjust. Deferred.

---

## Archived / removed (failed experiments — binaries deleted, history kept here)

These were intermediate dead-ends from the iteration on Goal #2 Step 2 before the Phase D2 bench session corrected our model. Listed for context.

| Removed file | Reason |
|---|---|
| `firmware_09_boot-rail-up-in-standby.bin` | Shim called `0x08011508` (full spdif_powerup) at boot. PA2 went HIGH per disasm but rail didn't come up. First disproof that "PA2 alone" was the rail gate. |
| `firmware_10_boot-rail-up-minimal.bin` | Minimal direct PA2-HIGH GPIO_WriteBit. GDB confirmed PA2 ODR=1 and Output_PP mode — yet rail still 0.8V. Confirmed PA2 alone is insufficient. |
| `firmware_11_boot-rail-up-pa2-pb7.bin` | PA2 + PB7 via `0x0800C4EC`. Triggered `notify(19, 0)` because the embedded I²C check (`0x0800CA70`) fails without DSP running → fast-blink error LED. |
| `firmware_14_wake-on-spdif.bin` | Level-triggered PA3 polling. Wake-loop on IR-off — because PA3 reads LOW (always — *not* due to audio activity) and our shim interpreted that as "audio active". |
| `firmware_15_wake-on-spdif-edge.bin` | Edge-triggered on `state[1]` tracking. Discarded because root cause wasn't level-vs-edge — it's that PA3 is dead-wired in this firmware. |
| `firmware_16_wake-on-spdif-keep-i2c1.bin` | fw_15 + NOP I²C1 shutdown (hypothesis was that PB8/PB9 controlled SOT-23-5's EN). Discarded after Phase D2 showed I²C1 wasn't the gating signal — PF0 was. |

## Critical lessons from the iteration

1. **Always read the actual IDR for a pin under varied conditions before assuming what it indicates.** We followed the firmware's `is_audio_active()` to PA3 for many sessions before noticing PA3 reads stuck-LOW. The PCB-trace hypothesis (PA4 = SPDIF) was right; the firmware reads the wrong pin.
2. **GPIO outputs you THINK you control might not be the actual gating signal.** Rail-up needed PA2 *and* PB7 *and* PC15; missing any of them and the rail stays off. And PF0 turned out to also be required for PA4 to track SPDIF in standby.
3. **Calling firmware functions outside their natural context can trigger error LEDs / unintended state.** `0x0800C4EC`'s embedded I²C check (fw_11) and `0x08011508`'s PA3-EXTI reconfig (fw_09) both had side effects we didn't predict. When patching, prefer the simplest direct GPIO operations or call the natural state-machine entry points (transition_state(2)).
4. **The bar's RTX uses the default 1 kHz tick rate** (we initially miscalculated as ~1.1 Hz and built fw_20 around that — wrong). 1000 ticks = 1 second. The observed "~15 min" auto-standby actually comes from the SOT-23-5 chip's hysteresis (PA3 carrier-detect), not a firmware timer. The firmware's `auto_standby_check` adds only a 1-second debounce on top.
