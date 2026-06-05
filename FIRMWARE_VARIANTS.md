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
| `firmware_06_keep-audio-rail-in-standby.bin`  |             4 | ⏳ Pending test | **Goal #2 Step 1**: keep audio rail powered in standby |

(Goal #2 Step 2 — the wake-on-SPDIF polling — will be
`firmware_07_wake-on-spdif.bin` once we build it, after Step 1 is bench-validated.)


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


## `firmware_06_keep-audio-rail-in-standby.bin` — Goal #2 Step 1: keep audio rail powered in standby ⏳

**Purpose**: stop the firmware from gating off PC15 (audio rail enable) during the standby transition. This keeps the Toslink SPDIF receiver alive in standby, so PA3 (the SPDIF activity input pin) continues to reflect signal presence — necessary infrastructure for Goal #2 Step 2.

**Changes from baseline**:

| File offset | Original         | New              | Why                                      |
| ----------- | ---------------- | ---------------- | ---------------------------------------- |
| `0x0A836`   | `f0 02 ff 12`*   | `00 bf 00 bf`    | NOP the `bl GPIO_WriteBit(GPIOC, 0x8000, val=0)` in standby path — keeps PC15 HIGH |

*Actual bytes in the file: `02 f0 12 ff` (the Thumb-2 BL encoding, little-endian).
What the *disassembly* shows: `bl 0x0800D65E`.

**Status**: ⏳ Pending bench test.

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

**For now, test goalD standalone**: bar will still need IR to turn on (no auto-boot), but standby should keep the rail alive.


## Cumulative diff summary

```
firmware_01_original-dump.bin       (baseline)
    │
    ├─ firmware_02_swd-write-test.bin     [+4]   DEADBEEF marker — diagnostic only
    │
    ├─ firmware_03_redirect-shim-noop.bin    [+11]  NO-OP redirect — diagnostic only
    │
    ├─ firmware_04_autoboot-partial-no-notify.bin    [+16]  Goal #1 partial — superseded by C
    │
    ├─ firmware_05_autoboot-active-on-power.bin    [+24]  Goal #1 ★ PRODUCTION
    │
    └─ firmware_06_keep-audio-rail-in-standby.bin    [+4]   Goal #2 Step 1 ⏳ pending test
```


## Coming next

- `firmware_07_wake-on-spdif.bin` (planned): combines `05_autoboot-active-on-power`
  + `06_keep-audio-rail-in-standby` + adds the SPDIF-wake polling logic.
  Goal: bar boots into standby OR into active, depending on whether SPDIF is present at boot;
  always wakes from standby when SPDIF returns; still respects IR.
- Possible `firmware_08_autoboot-plus-rail-on.bin`: clean merge of `05` + `06`
  (auto-boot + standby-rail-on) without the wake polling, if you decide that's the
  right always-on configuration.
