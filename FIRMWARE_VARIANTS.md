# Teufel Cinebar One — Firmware Variants

Tracking every firmware binary we've built, what it does, why we built it,
and current status (working / superseded / etc.).

All binaries are 128 KB and load at flash `0x08000000`. Flash via:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program <file> verify reset exit 0x08000000"
```

To roll back to stock behavior:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_01_original-dump.bin verify reset exit 0x08000000"
```

## Binary index

| File                  | Bytes changed | Status       | Purpose                                          |
| --------------------- | -------------:| ------------ | ------------------------------------------------ |
| `firmware_01_original-dump.bin`      |             0 | ★ Baseline   | Original dump (RDP=AA verified)                  |
| `firmware_02_swd-write-test.bin`   |             4 | ✓ Verified   | Phase 0 SWD-write proof: `DEADBEEF` at `0x1FF00` |
| `firmware_03_redirect-shim-noop.bin`  |            11 | ✓ Diagnostic | NO-OP shim verifies redirect mechanism works     |
| `firmware_04_autoboot-partial-no-notify.bin`  |            16 | ✗ Partial    | Goal #1 attempt: transition_state without notify |
| `firmware_05_autoboot-active-on-power.bin`  |            24 | ★ ✓ Production | **Goal #1 WORKING**: boot to active state      |
| `firmware_06_keep-audio-rail-in-standby.bin`  |             4 | ✗ Insufficient | **Goal #2 Step 1 v1**: NOP'd PC15-LOW only. Toslink Vcc still drops to 0.8V in standby — PC15 alone isn't the gate. |
| `firmware_07_keep-audio-rail-pb7-pc15.bin`  |             8 | ✗ Insufficient | **Goal #2 Step 1 v2**: NOP'd both PB7-LOW + PC15-LOW. Toslink Vcc STILL dropped to 0.8V — Recipe D found the actual killer (PA2). |
| `firmware_08_keep-audio-rail-pa2-pb7-pc15.bin` | 12 | ✓ Verified (partial) | **Goal #2 Step 1 v3**: NOP of the PA2-LOW path at `0x0800A81A`. Toslink Vcc stays at 3V in standby after one IR-on/IR-off cycle. **Cold-boot quirk**: rail starts at 0.8V (boot init at `0x0800A5D0` sets PA2=LOW); first IR-on brings it up, then it stays. |
| `firmware_09_boot-rail-up-in-standby.bin` | 27 | ✗ Failed | **Goal #2 Step 1 v4**: fw_08 + boot shim calling 0x08011508. Rail stayed at 0.8V from cold boot. Disproved theory that PA2 alone is the rail gate. |
| `firmware_10_boot-rail-up-minimal.bin` | 34 | ✗ Failed | Minimal direct PA2-HIGH shim (skipping 0x08011508 side effects). Verified via GDB: shim ran, PA2 ODR=1, Output_PP mode. Yet Toslink Vcc still 0.8V. Proved PA2 alone is **not sufficient** for rail-up. |
| `firmware_11_boot-rail-up-pa2-pb7.bin` | 38 | ✗ Failed | PA2 + PB7 (via `0x0800C4EC`). GDB confirmed PB7 HIGH after shim. But `0x0800C4EC` triggered `notify(19, 0)` (audio error) because the embedded I²C check (`0x0800CA70`) fails when DSP isn't running. Bar entered fast-red-blink error state. Rail still 0.8V. Proved PA2+PB7 also insufficient and that calling firmware code outside the natural transition_state context is unsafe. |
| `firmware_12_autoboot-active-rail-on.bin` | 36 | ✓ Verified | **★ COMBO**: fw_05 (auto-boot to active) + fw_08 (NOPs preserve rail in standby). Bench-verified 2026-06-06: bar auto-boots active (purple), reaches auto-standby in ~9-15 min, rail stays at 3V in standby, IR cycles work. |
| `firmware_13_combo-5min-standby.bin` | 37 | ✗ Side effect | fw_12 + single-byte patch at 0x1154a (125→42) to reduce silent timer 1000→336 ticks. Standby fires faster (~3 min) but lands in cyan/intermediate state instead of red. Deferred — see [task #29]. |
| `firmware_14_wake-on-spdif.bin` | 85 | ⏳ Pending test | **★ Goal #2 Step 2**: fw_12 + wake-on-SPDIF polling shim. event_loop's standby idle now also polls PA3 (~22 sec cadence). When audio appears, posts wake event → bar transitions to active automatically. Full Goal #2. |


---

## `firmware_01_original-dump.bin` — original dump

- 128 KB extracted via SWD with RDP=AA
- All other variants apply changes to this baseline
- **Always keep this around as the rollback image**


## `firmware_02_swd-write-test.bin` — toolchain verification (Phase 0)

**Purpose**: confirm the SWD read → modify → flash → re-dump loop works.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x1FF00`   | `ff ff ff ff`    | `de ad be ef`    | Visible marker in unused flash           |

**Status**: ✓ Verified. Bar still works after flash. Marker reads back correctly.

**Notes**: `0x1FF00` lands inside the upper-flash patch region (`0x1E800`–`0x1FFFF`) which the vEEPROM never touches. Safe to leave but no functional effect.


## `firmware_03_redirect-shim-noop.bin` — NO-OP diagnostic

**Purpose**: confirm the thread-entry-redirect mechanism works before attempting any real patch.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x10274`   | `a5 ac 00 08`    | `01 e8 01 08`    | Thread entry pointer → patch shim         |
| `0x1E800`   | `ff ff ff ff …` (8 bytes) | `00 48 00 47 a5 ac 00 08` | Shim that just BX'es back to original `0x0800ACA5` |

**Status**: ✓ Verified. Bar boots normally to standby, IR toggle works. Mechanism is sound.


## `firmware_04_autoboot-partial-no-notify.bin` — Goal #1 attempt 1 (partial)

**Purpose**: first try at Goal #1 — call `transition_state(2)` from the event-loop thread to auto-power-on.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0ACAC`   | `00 f0 e4 f8`    | `13 f0 a8 fd`    | Thread's `bl 0x0800AE78` → `bl 0x0801E800` (our shim) |
| `0x1E800`   | `ff ff …` (14 bytes) | `00 b5 ec f7 39 fb 02 20 eb f7 9a ff 00 bd` | Shim: original init 2, then transition_state(2) |

**Status**: ✗ Partial — bar booted with audio ON but LED stuck red. Diagnosis: missing `notify(0, retval)` broadcast after `transition_state(2)`. Led to `goalC`.

**Disassembly of the shim**:
```
0x0801E800: push  {lr}
0x0801E802: bl    0x0800AE78    ; original init 2
0x0801E806: movs  r0, #2
0x0801E808: bl    0x0800A740    ; transition_state(2)
0x0801E80C: pop   {pc}
```


## `firmware_05_autoboot-active-on-power.bin` — Goal #1 production patch ★

**Purpose**: bar auto-boots to active state at AC power-on, IR remote behavior preserved.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0ACAC`   | `00 f0 e4 f8`    | `13 f0 a8 fd`    | Thread's `bl 0x0800AE78` → `bl 0x0801E800` (our shim) |
| `0x1E800`   | `ff ff …` (22 bytes) | `00 b5 ec f7 39 fb 02 20 eb f7 9a ff 01 46 00 20 ed f7 e4 f9 00 bd` | Shim: original init 2, then transition_state(2), then notify(0, retval) |

**Status**: ★ Production-ready. Bar boots to purple LED + audio in one shot. IR toggle still works normally.

**Disassembly of the shim** (`set_active_on_boot_shim`):
```
0x0801E800: push  {lr}                  ; save thread return
0x0801E802: bl    0x0800AE78             ; original init 2 (preserve thread setup)
0x0801E806: movs  r0, #2
0x0801E808: bl    0x0800A740             ; transition_state(2) → returns new state
0x0801E80C: mov   r1, r0                 ; r1 = new state
0x0801E80E: movs  r0, #0                 ; r0 = channel 0
0x0801E810: bl    0x0800BBDC             ; notify(0, new_state) → updates LED, etc.
0x0801E814: pop   {pc}                   ; return to thread
```

**Apply with**:
```bash
cp firmware_01_original-dump.bin firmware_05_autoboot-active-on-power.bin
printf '\x00\xb5\xec\xf7\x39\xfb\x02\x20\xeb\xf7\x9a\xff\x01\x46\x00\x20\xed\xf7\xe4\xf9\x00\xbd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x1E800)) conv=notrunc
printf '\x13\xf0\xa8\xfd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x0ACAC)) conv=notrunc
```


## `firmware_06_keep-audio-rail-in-standby.bin` — Goal #2 Step 1 v1 ✗ insufficient

**Purpose** (original hypothesis): stop the firmware from gating off PC15 during the standby transition, in the belief that PC15 was the Toslink Vcc gate.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | NOP `bl GPIO_WriteBit(GPIOC, 0x8000, 0)` |

**Status**: ✗ **Bench-tested 2026-06-06. Toslink Vcc still drops to 0.8V in standby; only goes to 3V after IR-on.** PC15 alone is NOT what gates the Toslink rail. Superseded by `firmware_07`.

**What we learned**: deeper trace of `transition_state` standby path revealed another GPIO write hidden in a wrapper chain: `bl 0x0800C48C` at `0x0800A81E` calls `0x0800C9A0` which sets **PB7 LOW**. PB7 is almost certainly the actual audio rail gate (probably controls a load-switch / PMIC). PC15 may be an auxiliary signal but isn't the primary gate. The mirror in the active path is `bl 0x0800C4EC` at `0x0800A796` which calls a power-up sequence including `bl 0x0800CA44` (pulses PB7: LOW for 30 ms then HIGH — classic "reset" pulse for a PMIC).

**Expected behavior**:
- Bar still functionally goes to standby (LED red, amps muted via other writes, DSP held in reset via PF0=LOW)
- BUT PC15 stays HIGH → audio rail stays at 3V → Toslink receiver still powered
- PA3 should still show SPDIF activity (HIGH when audio source connected and playing)
- Standby current draw goes up by a few mA (Toslink module + SOT-23-5 buffer quiescent current)
- IR-on / IR-off still work normally

**How to verify after flash**:
1. Power-cycle bar (will go to standby — red LED)
2. With multimeter, probe the Toslink Vcc pin: should read ~3 V (was ~0.8 V on baseline)
3. With audio source connected & playing, probe **PA3** (pin 13 — but bar still needs to be assembled to do this): should read HIGH
4. Disconnect SPDIF source → PA3 should drop LOW within a few ticks
5. IR-on the bar → should go active (LED purple, audio after DSP boot delay)
6. IR-off the bar → should go back to red, PA3 should still be readable

**Apply with**:
```bash
cp firmware_01_original-dump.bin firmware_06_keep-audio-rail-in-standby.bin
printf '\x00\xbf\x00\xbf' | \
    dd of=firmware_06_keep-audio-rail-in-standby.bin bs=1 seek=$((0x0A836)) conv=notrunc
```

**Important note about combining with `firmware_05_autoboot-active-on-power.bin`**:
This patch does NOT include the Goal #1 (auto-boot-to-active) changes. If you want **both** auto-boot AND keep-rail-on, we'd build a combined binary (e.g. `firmware_08_autoboot-plus-rail-on.bin`) that applies both patch sets to the baseline. Or just decide which is more valuable to test first.

**Standalone**: bar will still need IR to turn on (no auto-boot included), but standby should now keep the rail alive.


## `firmware_07_keep-audio-rail-pb7-pc15.bin` — Goal #2 Step 1 v2 ✗ insufficient

**Purpose**: keep the audio rail powered through standby by NOPping BOTH PB7-LOW (the actual primary gate) AND PC15-LOW (auxiliary signal) writes during standby transition.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0A81E`   | `01 f0 35 fe`    | `00 bf 00 bf`    | NOP `bl 0x0800C48C` → was calling chain to PB7=LOW |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | NOP `bl GPIO_WriteBit(GPIOC, 0x8000, 0)` → PC15=LOW |

**Status**: ✗ **Bench-tested. Toslink Vcc still drops to 0.8V in standby.** PB7+PC15 are NOT the audio rail gate either. Recipe D (GDB breakpoint inside `GPIO_WriteBit`) found the real one — see `firmware_08`.

**Apply with**:
```bash
cp firmware_01_original-dump.bin firmware_07_keep-audio-rail-pb7-pc15.bin
printf '\x00\xbf\x00\xbf' | \
    dd of=firmware_07_keep-audio-rail-pb7-pc15.bin bs=1 seek=$((0x0A81E)) conv=notrunc
printf '\x00\xbf\x00\xbf' | \
    dd of=firmware_07_keep-audio-rail-pb7-pc15.bin bs=1 seek=$((0x0A836)) conv=notrunc
```


## `firmware_08_keep-audio-rail-pa2-pb7-pc15.bin` — Goal #2 Step 1 v3 ⏳

**Purpose**: keep the audio rail powered through standby. Adds the missing NOP at `0x0800A81A` (the BL to `0x08011500` → `spdif_init` at `0x080103bc` which actively writes PA2=LOW). PA2 is the SPDIF-buffer / Toslink-load-switch enable — driving it LOW shuts off Toslink Vcc.

**How we found it**: Recipe D set a GDB code breakpoint inside `GPIO_WriteBit` on the BRR-write path (`0x0800d666`), logging every clear-LOW call during IR-off. The log showed PA2 going LOW from caller `lr=0x080103e1` — a path we'd never traced. ODR snapshots confirmed:
- pre-standby: GPIOA->ODR = `0x84` (PA2 + PA7 HIGH)
- post-standby: GPIOA->ODR = `0x80` (PA2 LOW, PA7 still HIGH)

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0A81A`   | `06 f0 71 fe`    | `00 bf 00 bf`    | NOP `bl 0x08011500` → was calling `spdif_init` (PA2=LOW + reconfigures PA2/PA3) ★ the actual rail killer |
| `0x0A81E`   | `01 f0 35 fe`    | `00 bf 00 bf`    | NOP `bl 0x0800C48C` → PB7-LOW chain (kept from fw_07 — defensive) |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | NOP `bl GPIO_WriteBit(GPIOC, 0x8000, 0)` → PC15-LOW (kept from fw_07 — defensive) |

**Status**: ✓ **Verified (partial) — bench-tested 2026-06-05.**
- After IR-on→IR-off cycle: Toslink Vcc stays at **3V** in standby ✓ (was 0.8V on baseline + fw_06/07)
- After cold boot (AC restore, no IR yet): rail starts at **0.8V**, requires one IR-on to bring up
- Once brought up by IR, rail stays at 3V across subsequent standby cycles ✓

The cold-boot quirk is because `spdif_subsystem_init` is ALSO called from boot init at `0x0800A5D0`, which writes PA2=LOW once during system bring-up. fw_08 only NOPs the standby-entry call (`0x0800A81A`), not the boot-init call. For "rail always up from AC restore", combine with Goal #1 (auto-boot-to-active) — see `firmware_10_...` planned below.

**Call chain we just neutralised**:
```
transition_state(1)               ; standby entry
  ...
  0x0800A81A:  bl  0x08011500    ; ← NOP'd
                 0x08011500 → 0x080103bc:
                   - GPIO_WriteBit(GPIOA, 4, 0)     ; PA2 = LOW  (rail kill!)
                   - HAL_GPIO_Init(GPIOA, PA2, Output_PP)
                   - HAL_GPIO_Init(GPIOA, PA3, Input)
                   - *cached_spdif_state = -1
```

**Side effects of the NOP**:
- PA2 stays HIGH → SOT-23-5 / load switch stays enabled → Toslink Vcc stays at 3V ✓
- PA2 mode reconfigure: skipped, but it's already Output_PP from previous init — no-op anyway ✓
- PA3 mode reconfigure: skipped, but it's already Input — no-op anyway ✓
- Cached SPDIF state stays at whatever it was (not reset to -1) — `is_audio_active()` reads PA3 fresh anyway, so harmless ✓

**How to verify after flash**:
1. Power-cycle bar — goes to standby (red LED)
2. Probe Toslink Vcc with multimeter: should read **~3 V** (was 0.8 V on baseline and fw_06/07)
3. IR-on → bar goes active normally
4. IR-off → bar back to standby; Toslink Vcc should stay at 3 V
5. Probe PA3 (pin 13) with logic analyzer while playing SPDIF audio: should toggle (= still reading SPDIF activity in standby — the basis for Step 2 wake-on-SPDIF)

**If 08 still fails**: candidates would be the I²C1-shutdown (`0x0800F2B8`) — though it only reconfigures PB8/PB9 to Analog, not audio related — or the sub-state machine in `0x0800A8DC(0)`. We'd add more breakpoints in Recipe D.

**Apply with**:
```bash
cp firmware_01_original-dump.bin firmware_08_keep-audio-rail-pa2-pb7-pc15.bin
for off in 0x0A81A 0x0A81E 0x0A836; do
    printf '\x00\xbf\x00\xbf' | \
        dd of=firmware_08_keep-audio-rail-pa2-pb7-pc15.bin bs=1 seek=$((off)) conv=notrunc
done
```


## `firmware_12_autoboot-active-rail-on.bin` — combo fw_05 + fw_08 ⏳ ★

**Purpose**: combine Goal #1 (auto-boot to active state) with Goal #2 Step 1
(preserve audio rail through standby transitions). Most reliable approach
because it doesn't try to manually replicate the active-entry GPIO sequence —
instead the bar follows the OEM's natural path 1 startup at every boot.

**Why this works when fw_09/10/11 didn't**: rail-up isn't gated by PA2 alone,
or even PA2+PB7. The Recipe-D-era assumption that "PA2 is the rail" was
incomplete — it's actually PA2 + PB7 + something else (likely DSP-mediated
or PMIC I²C state). Trying to set rail-up GPIOs manually triggers an error
LED (`notify(19, 0)` from `0x0800CA70`'s I²C check failing). The only path
the firmware reliably brings the rail up is the full transition_state path 1.

**Behavior**:
- AC restore → bar boots straight to active state (LED purple, audio enabled)
- Either IR-off OR auto-standby (after ~2 min SPDIF silence) → bar standby (LED red)
- Rail stays at 3V in standby (fw_08 NOPs prevent the LOW writes)
- IR-on/off cycles work normally

**Changes from baseline (36 bytes)**:

| File offset | Original         | New              | From            | Why                                      |
| ----------- | ---------------- | ---------------- | --------------- | ---------------------------------------- |
| `0x0A81A`   | `06 f0 71 fe`    | `00 bf 00 bf`    | fw_08           | NOP standby-path PA2-LOW                 |
| `0x0A81E`   | `01 f0 35 fe`    | `00 bf 00 bf`    | fw_08           | NOP standby-path PB7-LOW                 |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | fw_08           | NOP standby-path PC15-LOW                |
| `0x0ACAC`   | `00 f0 e4 f8`    | `13 f0 a8 fd`    | fw_05           | BL redirect to autoboot shim              |
| `0x1E800`   | `ff ff …` (22b)  | `00 b5 ec f7 39 fb 02 20 eb f7 9a ff 01 46 00 20 ed f7 e4 f9 00 bd` | fw_05 | Shim: orig init + transition_state(2) + notify(0,retval) |

**Status**: ⏳ Pending bench test.

**How to verify after flash**:
1. Power-cycle bar (AC restore)
2. Bar should boot to active state — purple LED, output enabled
3. Either send IR-off OR wait ~2 min for auto-standby
4. Bar should go to red LED but **Toslink Vcc should stay at 3V**
5. Subsequent IR-on/off cycles should preserve rail
6. (Future Step 2): SPDIF reappearance should auto-wake bar

**Apply with**:
```bash
cp firmware_05_autoboot-active-on-power.bin firmware_12_autoboot-active-rail-on.bin
for off in 0x0A81A 0x0A81E 0x0A836; do
    printf '\x00\xbf\x00\xbf' | \
        dd of=firmware_12_autoboot-active-rail-on.bin bs=1 seek=$((off)) conv=notrunc
done
```


## `firmware_14_wake-on-spdif.bin` — Goal #2 Step 2 ⏳ ★

**Purpose**: bar in standby (state[0]==1) auto-wakes when SPDIF audio appears on PA3.
Builds on fw_12: with the rail kept up in standby (fw_08's NOPs), the SOT-23-5
SPDIF buffer is alive, so PA3 still reflects audio activity even when LED is red.

**Mechanism**:
- NOP the `bne 0x800acb4` at `0x0800ACC8` so the BL at `0x0800ACCA` runs in
  *all* states (not just active).
- Redirect that BL from `auto_standby_check` (0x08011524) to a new shim at
  `0x0801E820`.
- Shim dispatches on `state[0]`:
  - `state[0]==2` (active) → calls original `auto_standby_check` (preserves auto-standby behavior)
  - `state[0]==1` (standby) → reads `is_audio_active()` (PA3 IDR). If audio
    present (returns 0), calls `post_event_type0(2)` to trigger wake transition.
  - Other states → returns 0 (no action)

Polling cadence is the existing event_loop's `osMessageQueueGet` timeout
(25 ticks ≈ 22.5 s at the ~1.1 Hz tick rate). Wake latency is up to ~22 s.

**Changes from baseline (85 bytes)**:

| File offset | Original         | New              | From    | Why                                      |
| ----------- | ---------------- | ---------------- | ------- | ---------------------------------------- |
| `0x0A81A`   | `06 f0 71 fe`    | `00 bf 00 bf`    | fw_08   | NOP PA2-LOW (standby)                    |
| `0x0A81E`   | `01 f0 35 fe`    | `00 bf 00 bf`    | fw_08   | NOP PB7-LOW (standby)                    |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | fw_08   | NOP PC15-LOW (standby)                   |
| `0x0ACAC`   | `00 f0 e4 f8`    | `13 f0 a8 fd`    | fw_05   | BL redirect → autoboot shim              |
| `0x0ACC8`   | `f4 d1`          | `00 bf`          | **new** | NOP BNE so BL at +0x02 runs in all states |
| `0x0ACCA`   | `06 f0 2b fc`    | `13 f0 a9 fd`    | **new** | Redirect BL → wake-on-SPDIF shim          |
| `0x1E800`   | `ff …` (22 b)    | autoboot shim    | fw_05   | (unchanged from fw_12)                    |
| `0x1E820`   | `ff …` (44 b)    | wake-on-SPDIF shim | **new** | dispatches state[0]                     |

**Shim body at 0x0801E820 (44 bytes)**:
```
0x0801E820: push  {r4, lr}
0x0801E822: ldr   r4, [pc, #36]   ; r4 = &g_system_state (0x200025DC)
0x0801E824: ldrb  r0, [r4, #0]     ; r0 = state[0]
0x0801E826: cmp   r0, #2
0x0801E828: bne   skip_active      ; not active, go to wake check
0x0801E82A: bl    0x08011524        ; original auto_standby_check
0x0801E82E: b     done

skip_active:
0x0801E830: cmp   r0, #1
0x0801E832: bne   return_zero       ; not standby either → return 0
0x0801E834: bl    0x0801041C        ; is_audio_active() (PA3 read)
0x0801E838: cmp   r0, #0
0x0801E83A: bne   return_zero       ; if 1 (silent), no wake
0x0801E83C: movs  r0, #2
0x0801E83E: bl    0x0800AB00        ; post_event_type0(2) → wake

return_zero:
0x0801E842: movs  r0, #0

done:
0x0801E844: pop   {r4, pc}
0x0801E846: nop                      ; alignment
0x0801E848: .word 0x200025DC          ; literal
```

**Status**: ⏳ Pending bench test.

**How to verify after flash**:
1. AC restore → bar boots to active (purple) as in fw_12
2. **With audio source silent/paused**: IR-off → bar goes to standby (red), Vcc=3V
3. Wait ~30 sec to confirm bar stays in standby (no spurious wakes)
4. **Resume audio on the SPDIF source** → bar should auto-wake within ~22 sec, going active (purple)
5. Stop audio again → bar should auto-standby normally (15 min)
6. Restart audio → bar auto-wakes again

**Apply with**:
```bash
cp firmware_12_autoboot-active-rail-on.bin firmware_14_wake-on-spdif.bin
printf '\x00\xbf' | dd of=firmware_14_wake-on-spdif.bin bs=1 seek=$((0x0ACC8)) conv=notrunc
printf '\x13\xf0\xa9\xfd' | dd of=firmware_14_wake-on-spdif.bin bs=1 seek=$((0x0ACCA)) conv=notrunc
printf '\x10\xb5\x09\x4c\x20\x78\x02\x28\x02\xd1\xf2\xf7\x7b\xfe\x09\xe0\x01\x28\x06\xd1\xf1\xf7\xf2\xfd\x00\x28\x02\xd1\x02\x20\xec\xf7\x5f\xf9\x00\x20\x10\xbd\x00\xbf\xdc\x25\x00\x20' | \
    dd of=firmware_14_wake-on-spdif.bin bs=1 seek=$((0x1E820)) conv=notrunc
```


## `firmware_09_boot-rail-up-in-standby.bin` — Goal #2 Step 1 v4 ⏳

**Purpose**: keep audio rail powered through standby AND bring it up from cold
boot, eliminating fw_08's "first IR-on required" quirk. Bar still boots to
standby (NOT auto-active — for that combine with fw_05's Goal #1 patch).

**How it works**: combines fw_08's NOP at `0x0800A81A` (prevents PA2-LOW in
standby path) with a boot-time shim that calls `spdif_powerup_wrapper` at
`0x08011508`. The shim is invoked through the fw_05-style BL redirect at
`0x0800ACAC`. `spdif_powerup_wrapper` reconfigures PA2 as Output_OD+pull-up,
pulses it LOW for 50 ms (reset), then HIGH, then waits 500 ms.

**PA2-HIGH chain (located via static analysis after fw_08 verification)**:
```
0x0800A7F4 (transition_state path 1, just before state[0]=2)
  └─ bl 0x08011508 (spdif_powerup_wrapper)
       ├─ bl 0x08010430  ; reconfig PA2 as Output_OD + Pull-up, write LOW
       └─ bl 0x0801049C  ; pulse PA2 LOW(50ms) → HIGH, 500ms settle, reconfig PA3
            └─ 0x080104CE: GPIO_WriteBit(GPIOA, 0x04, 1)  ; ★ PA2 = HIGH
```

**Changes from baseline (27 bytes)**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0A81A`   | `06 f0 71 fe`    | `00 bf 00 bf`    | NOP standby-path PA2-LOW (from fw_08)    |
| `0x0A81E`   | `01 f0 35 fe`    | `00 bf 00 bf`    | NOP PB7-LOW chain (from fw_08, defensive) |
| `0x0A836`   | `02 f0 12 ff`    | `00 bf 00 bf`    | NOP PC15-LOW (from fw_08, defensive)     |
| `0x0ACAC`   | `00 f0 e4 f8`    | `13 f0 a8 fd`    | BL redirect: `bl 0x0800AE78` → `bl 0x0801E800` (same as fw_05) |
| `0x1E800`   | `ff ff …` (12 bytes) | `00 b5 ec f7 39 fb f2 f7 7f fe 00 bd` | Shim: push{lr}; bl orig init 2; bl spdif_powerup; pop{pc} |

**Shim disassembly**:
```
0x0801E800: push  {lr}                  ; save thread return
0x0801E802: bl    0x0800AE78             ; original target (init 2) — preserve
0x0801E806: bl    0x08011508             ; spdif_powerup → PA2 LOW(50ms) → HIGH
0x0801E80A: pop   {pc}                   ; return to thread
```

**Status**: ⏳ Pending bench test.

**How to verify after flash**:
1. Power-cycle bar (AC restore) — expect ~550 ms extra "thinking" delay before LED settles to red (the PA2 pulse + 500 ms stabilize)
2. Bar settles in standby (red LED) — NOT active, this is the goal
3. **Probe Toslink Vcc with multimeter: should read ~3 V from boot (no IR needed!)**
4. IR-on/IR-off cycles still work normally
5. Auto-standby (~2 min SPDIF silence) still triggers

**If firmware_09 fails (unlikely)**:
- The 0x08011508 path may have unintended side effects when called outside transition_state context
- Fallback would be a more surgical shim that does only the PA2=HIGH write (direct GPIO_WriteBit) without the full spdif_powerup

**Apply with**:
```bash
cp firmware_08_keep-audio-rail-pa2-pb7-pc15.bin firmware_09_boot-rail-up-in-standby.bin
printf '\x00\xb5\xec\xf7\x39\xfb\xf2\xf7\x7f\xfe\x00\xbd' | \
    dd of=firmware_09_boot-rail-up-in-standby.bin bs=1 seek=$((0x1E800)) conv=notrunc
printf '\x13\xf0\xa8\xfd' | \
    dd of=firmware_09_boot-rail-up-in-standby.bin bs=1 seek=$((0x0ACAC)) conv=notrunc
```


## Cumulative diff summary

```
firmware_01_original-dump.bin       (baseline)
    │
    ├─ firmware_02_swd-write-test.bin              [+4]   DEADBEEF marker — diagnostic only
    │
    ├─ firmware_03_redirect-shim-noop.bin          [+11]  NO-OP redirect — diagnostic only
    │
    ├─ firmware_04_autoboot-partial-no-notify.bin  [+16]  Goal #1 partial — superseded by 05
    │
    ├─ firmware_05_autoboot-active-on-power.bin    [+24]  Goal #1 ★ PRODUCTION
    │
    ├─ firmware_06_keep-audio-rail-in-standby.bin       [+4]   Goal #2 Step 1 v1 ✗ insufficient
    │
    ├─ firmware_07_keep-audio-rail-pb7-pc15.bin         [+8]   Goal #2 Step 1 v2 ✗ insufficient
    │
    ├─ firmware_08_keep-audio-rail-pa2-pb7-pc15.bin     [+12]  Goal #2 Step 1 v3 ✓ verified (partial)
    │
    ├─ firmware_09_boot-rail-up-in-standby.bin          [+27]  Goal #2 Step 1 v4 ✗ failed
    │
    ├─ firmware_10_boot-rail-up-minimal.bin             [+34]  Goal #2 Step 1 v5 ✗ failed (PA2 alone not sufficient)
    │
    ├─ firmware_11_boot-rail-up-pa2-pb7.bin             [+38]  Goal #2 Step 1 v6 ✗ failed (PA2+PB7 not sufficient, error LED)
    │
    ├─ firmware_12_autoboot-active-rail-on.bin          [+36]  ★ COMBO fw_05 + fw_08 ✓ verified
    │
    ├─ firmware_13_combo-5min-standby.bin               [+37]  Goal #2 Step 1+ ✗ cyan side effect
    │
    └─ firmware_14_wake-on-spdif.bin                    [+85]  ★ Goal #2 Step 2 ⏳ pending test
```


## Coming next

- After fw_14 verifies: cleanup pass (rename, archive non-production variants),
  attempt clean standby-timer reduction (deferred task #29).
