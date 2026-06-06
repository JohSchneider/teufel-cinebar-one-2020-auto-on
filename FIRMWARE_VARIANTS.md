# Teufel Cinebar One — Firmware Variants

Index of every firmware binary built during this RE work. **fw_17** is the current target for full Goal #2; **fw_12** is the proven-stable fallback. Binaries the user has deleted from disk after they were proven obsolete are listed at the bottom under "Archived/removed".

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
| `firmware_17_wake-on-spdif.bin` | 129 | ⏳ Pending test | **★ Goal #2 Step 2 candidate.** fw_12 + NOP PF0=LOW (DSP stays alive → PA4 reflects SPDIF) + polling shim with multi-sample debounce + silence-seen gate. Polls PA4 in event_loop's standby idle. |

---

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

### `firmware_17_wake-on-spdif.bin` — Goal #2 Step 2 candidate (⏳ pending bench test)

**Behavior** (intended): everything fw_12 does, plus the bar auto-wakes when SPDIF audio appears in standby. Audio resumption → bar transitions to active within ~22 sec (one event_loop poll cycle). IR-off while audio is still playing does **not** cause a wake-loop because the wake gate requires observing silence first.

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
4. **The bar's RTX uses a ~1.1 Hz tick rate** (not the RTX5 default 1 kHz). 1000 ticks ≈ 15 min. Affects all timing assumptions.
