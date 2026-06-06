# Goal #2 — Wake-on-SPDIF for Teufel Cinebar One

## Status

| Sub-goal | Status | Binary |
|---|---|---|
| Step 1 — keep audio rail powered through standby | ✓ Verified | `firmware_12_autoboot-active-rail-on.bin` (subsumed by fw_22) |
| Step 2 — wake bar from standby when fiber lights | ★ ✓ Verified 2026-06-06 | `firmware_22_wake-on-spdif.bin` |

**End-to-end UX achieved**: source mute → ~15 min → auto-suspend; source unmute → ~25 ms → auto-wake. **No IR remote needed in normal use.**

## User's UX goal (verbatim from 2026-06-06 session)

> "my ultimate goal is to do away with the IR remote, and have the speaker autosuspend normally (the ~15min after the toslink goes dark = the source either muted or went away). but have the speaker auto-wake when there is activity on the toslink ('the lights are on')."

So: bar should auto-suspend when fiber goes dark (mute or unplug), and auto-wake when fiber lights up. No IR remote needed.

## How each half is handled

### Auto-suspend — handled by stock firmware (no patches needed)

User verified on stock fw_01: muting the source caused auto-suspend in **13min 30sec** (with run-to-run variance). The mechanism, traced through the bench data:

1. Source mutes → Toslink LED goes dark (user observed directly).
2. The SOT-23-5 chip on the bar (next to Toslink module, output to PA3) has its **own silence-detect hysteresis** — it doesn't immediately reflect "no carrier" on PA3. PA3 stays LOW for some minutes while the chip's internal timer counts.
3. After the chip's hysteresis (~13 min, variable), PA3 flips LOW → HIGH.
4. STM32 firmware's `auto_standby_check()` (at `0x08011524`) sees `is_audio_active()` (which reads PA3) returning 1 sustained for 1000 ticks = **1 second at 1ms tick rate**.
5. `auto_standby_check` returns decision=2, event_loop posts `post_event_type7(1)`, which dispatches as `transition_state(1)` → bar enters standby.

The 13.5 min comes from the chip, not the firmware. The firmware's role is just the 1-second confirmation debounce on top.

(Note: my earlier interpretation that the firmware's "1000 ticks" was a 15-min timer was based on a wrong tick-rate estimate of 1.1 Hz. Wall-clock measurement during the 2026-06-06 session — 9706 ticks in ~10 sec — pins the actual tick rate to ~1 kHz / 1ms. So 1000 ticks = 1 sec.)

So nothing to patch for auto-suspend. Stock behavior (with our fw_12 base) already does what the user wants.

### Auto-wake — handled by our fw_22 shim

When in standby, the firmware doesn't have any wake-on-SPDIF path of its own (apart from IR / button). We add this via a shim that wraps `osMessageQueueGet` in event_loop, polls PA4 each iteration, and posts a wake event when PA4 transitions from "monotone" (dark fiber) to "toggling" (fiber re-lit).

**Why PA4, not PA3, for wake detection**: PA4 is the Toslink module's data output. It directly reflects fiber state:
- Fiber dark (mute, unplugged, TV off): PA4 monotone — stuck HIGH if cable connected (Toslink receiver's idle output), stuck LOW if cable unplugged (receiver not driven).
- Fiber lit with data: PA4 toggles at biphase rate.

PA3 (the SOT-23-5 chip output) has hysteresis that's good for auto-suspend timing but too slow for wake — we want instant wake when fiber lights up.

**Polling cadence**: the shim runs at every event_loop iteration (top of loop, before `osMessageQueueGet`'s 25-tick timeout). So roughly every 25 ms when idle, more often if messages arrive. Wake latency from fiber lighting ≤ ~25 ms — effectively instant.

## firmware_22 design

Patches on top of fw_12:

| Offset | Original | New | Why |
|---|---|---|---|
| `0x0ACBC` | `f7fe f85a` | `13 f0 b0 fd` | `bl 0x8008d74` (osMessageQueueGet) → `bl 0x0801e820` (our shim) |
| `0x1E820` | `ff …` × 84 | shim | 84-byte wrapper |

### Shim (84 bytes at `0x0801E820`)

```
push {r0-r7, lr}                  ; save osMessageQueueGet args + lr
ldr r4, =0x200025DC                ; main state struct
ldrb r0, [r4, #0]
cmp r0, #1                         ; standby?
bne wrap_call                      ; if not, fall through

ldr r5, =0x20002504                ; autostandby struct
ldr r6, =0x48000010                ; GPIOA->IDR
movs r2, #16                       ; PA4 mask = 0x10

ldr r3, [r6, #0]                   ; first sample
ands r3, r2                        ; r3 = first PA4 (0 or 0x10)
movs r4, #0                        ; toggled flag
movs r1, #15                       ; 15 more samples
poll_loop:
ldr r0, [r6, #0]
ands r0, r2
cmp r0, r3
beq next
movs r4, #1                        ; saw a different sample → toggling
next:
subs r1, #1
bne poll_loop

cmp r4, #0
bne saw_toggling
;; monotone (all 16 same): fiber is dark
movs r0, #1
strb r0, [r5, #2]                  ; silence_seen = 1
b wrap_call

saw_toggling:
ldrb r0, [r5, #2]
cmp r0, #0
beq wrap_call                      ; no prior silence — don't wake (avoids wake-loop on IR-off with audio)
movs r0, #0
strb r0, [r5, #2]                  ; reset silence_seen
movs r0, #2
bl 0x0800AB00                       ; post_event_type0(2) → wake

wrap_call:
pop {r0-r7}
bl 0x08008D74                       ; original osMessageQueueGet
pop {pc}

;; literals
.word 0x200025DC
.word 0x20002504
.word 0x48000010
```

State stored in `g_auto_standby_state[+2]` (byte at `0x20002506`):
- `silence_seen = 1`: shim has observed monotone PA4 at least once recently
- `silence_seen = 0`: never seen monotone, or just consumed (after wake)

Offset +2 verified to be unused by all known firmware functions touching this struct (auto_standby_check, 0x08011508, 0x08011590 use offsets 0, 1, 4-7, 8-11, 12-15 — leaving +2 and +3 free).

## Verification protocol for fw_22

Flash with:
```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_22_wake-on-spdif.bin verify reset exit 0x08000000"
```

Tests:
1. **Cold-boot regression**: AC restore → bar auto-boots active (purple). ✓ inherited from fw_05/fw_12.
2. **IR-off cleanliness**: IR-off while audio playing → bar → standby (red), STAYS there. No error LED. ✓ inherited from fw_19 design (BNE not NOPped, post-shim code keeps original BNE-skipped behavior in standby).
3. **Auto-suspend on mute**: source playing → mute source → ~13-15 min later → bar auto-suspends (firmware's PA3 path).
4. **★ Auto-wake on unmute**: bar in standby (from #3) → unmute source → bar should wake within ~25 ms (one poll cycle).
5. **Auto-suspend on unplug**: source unplug Toslink → ~15 min later → bar auto-suspends.
6. **★ Auto-wake on replug**: bar in standby (from #5) → replug Toslink with audio playing → bar wakes within ~25 ms.

## Critical addresses

| Address | Symbol | Notes |
|---|---|---|
| `0x0800A740` | `transition_state(action)` | action 1 = standby, action 2 = wake |
| `0x0800AB00` | `post_event_type0(action)` | what our shim calls to post wake |
| `0x0800ACBC` | BL osMessageQueueGet (redirected in fw_22) | our shim entry point |
| `0x08008D74` | `osMessageQueueGet` | called by our shim transparently |
| `0x08011524` | `auto_standby_check` | firmware's auto-suspend, reads PA3 |
| `0x0801041C` | `is_audio_active` | reads PA3 |
| `0x08011590` | edge-timing function | PA3 EXTI dispatch target, uses autostandby +0,+4,+12 |
| `0x200025DC` | `g_system_state.state[0]` | power state byte |
| `0x20002504` | `g_auto_standby_state` | decision +0, mode +1, silence_seen +2 (ours), last_tick +4, activity_tick +8 |
| `0x48000010` | GPIOA->IDR | PA4 polled at bit 4 |

## Earlier missteps (record of what didn't work)

See `FIRMWARE_VARIANTS.md` "Goal #2 Step 2 iteration history" section. Briefly:

- fw_14: level-triggered PA3 polling, wake-loop bug
- fw_15-18: various PF0/I²C1 NOPs and BNE NOP — the BNE NOP at `0x0ACC8` caused IR-off error by exposing post-shim periodic-timer code to standby state
- fw_19: wrap osMessageQueueGet (cleared IR-off error), but "silent = all-LOW" too strict
- fw_20: added auto-suspend with `last_toggle_tick` — corrupted autostandby +4 which `0x08011590` actually uses; auto-suspend threshold of "1000 ticks" was 1 sec instead of 15 min at the correct tick rate
- fw_22: same wrap-osMessageQueueGet as fw_19, but monotone detection (catches fiber-dark in both polarities); no auto-suspend logic
