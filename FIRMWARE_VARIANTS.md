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

(Goal #2 Step 2 — the wake-on-SPDIF polling — will be
`firmware_09_wake-on-spdif.bin` once we build it, after Step 1 is bench-validated.)


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
    └─ firmware_08_keep-audio-rail-pa2-pb7-pc15.bin     [+12]  Goal #2 Step 1 v3 ✓ verified (partial)
```


## Coming next

- `firmware_09_autoboot-plus-rail-on.bin` (recommended next): merge of fw_05
  (Goal #1: auto-boot to active) + fw_08 (Goal #2 Step 1: keep rail in standby).
  Active state runs on boot → PA2 goes HIGH → rail up. Subsequent IR-off / auto-
  standby leaves rail at 3V. Net effect: rail is up from AC restore, no IR needed.
- `firmware_10_wake-on-spdif.bin` (planned): adds PA3 polling + post wake-event.
  Requires PA2 to stay HIGH in standby → depends on fw_08 path.
- `firmware_11_full.bin`: Goal #1 + Step 1 + Step 2 — boots to active, rail
  always on, also wakes-on-SPDIF if standby is ever entered.

The right combination depends on the user's preference for standby vs always-on.
