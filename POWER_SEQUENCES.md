# Teufel Cinebar One — Power-state Transition Sequences

Reverse-engineered from the STM32 firmware. The bar has four power states encoded as `state[0]` at RAM `0x200025DC`:

| `state[0]` | Meaning |
|---:|---|
| 1 | Stable **standby** (red LED) |
| 2 | Stable **active** (audio playing, LED color = source) |
| 3 | Intermediate "going active" (transient during wake) |
| 4 | Intermediate "going standby" (transient during sleep) |

All transitions are driven by `transition_state(action)` at `0x0800A740`. The function takes one argument:
- `action=2` → wake (1→3→2)
- `action=1` → sleep (2→4→1)
- other values → no-op, returns error

The function reads the CURRENT state from `state[0]`, decides whether the requested transition is legal, and dispatches.

## Function 0x0800A740 — `transition_state(action)`

```
prologue:
  push {r3-r7, lr}
  r4 = &state            (= 0x200025DC)
  r1 = action            (caller's r0)
  r6 = 1 << 15 = 0x8000  (PC15 pin mask)
  r5 = GPIOF base        (= 0x48001400 — for PF0 = DSP reset)
  r7 = GPIOC base        (= 0x48000800 — for PC15)
  r0 = state[0]          (current state)
  if action == 2 → goto WAKE (0x0800A75A)
  if action == 1 → goto SLEEP (0x0800A7FC)
  else → error exit
```

GPIO bases used throughout the function (verified from literal pool):
| Reg | Holds | For |
|---|---|---|
| r4 | `0x200025DC` | state struct |
| r5 | `0x48001400` | GPIOF (PF0 = DSP reset) |
| r6 | `0x00008000` | PC15 pin mask |
| r7 | `0x48000800` | GPIOC (for PC15) |

---

## ★ Initial power-up (cold AC restore)

After AC is applied:

1. **STM32 reset.** Cortex-M0 fetches initial SP from `0x08000000` (= `0x20001CE8`) and initial PC from `0x08000004` (= `0x080000D5` = Reset_Handler).
2. **Reset_Handler** at `0x080000D4` runs:
   - `blx 0x08002EA0` — C runtime init (BSS clear, .data copy from flash)
   - `bx 0x080000C0` — jumps to startup code body
3. **Startup body** at `0x080000C0`:
   - `mov sp, #0x20001CE8`
   - `bl 0x080001AC` — additional init
   - `bx 0x080001D4` — jumps to `__main` (Arm Compiler entry)
4. `__main` eventually calls C `main()`, which:
   - Configures system clocks (HSI48 + CRS at `0x080019C8` for USB SOF-trim)
   - Initializes peripherals
   - `osKernelInitialize()`
   - Creates RTX5 threads via `0x08010530`
   - `osKernelStart()` — never returns
5. **Event-loop thread** at `0x0800ACA4` starts running. Its first work is the init prologue — including the BL at `0x0800ACAC` that fw_05+ redirects to **Shim 1**.
6. In **stock firmware**: state stays at `state[0]=1` (standby — red LED). Bar idles until user IR-presses power.
7. In **fw_05+** (auto-on): Shim 1 calls `transition_state(2)`, then `notify(0,1)` to wake the event loop. Bar proceeds to the WAKE sequence below.

---

## ★ WAKE sequence — `transition_state(2)` (action=2)

Triggered by: user IR-power press while in standby, Shim 1 at boot (fw_05+), or wake-on-SPDIF Shim 2 (fw_22) detecting audio activity.

Pre-condition: `state[0] == 1` (must be in standby; else returns error).

```
[0x0800A75A]
  cmp state[0], #1
  bne ERROR_EXIT             ; can only wake from standby
  state[0] = 3               ; ★ intermediate "going active" — observable via watchpoint

  ─── Toslink rail + DSP rails up ─────────────────────────────────
  bl 0x08011500              ; spdif_subsystem_init → drives PA2 HIGH (Toslink Vcc up)
  GPIO_WriteBit(GPIOF, PF0=0); ★ PF0 LOW — DSP held in reset during init
  GPIO_WriteBit(GPIOC, PC15=1); ★ PC15 HIGH — aux/amp rail up
  osDelay(50 ms)             ; rails settle

  ─── I²C2 (DSP bus) peripheral reset ─────────────────────────────
  RCC_APB1RSTR |= (1<<21)    ; assert I²C2 reset
  RCC_APB1RSTR &= ~(1<<21)   ; release I²C2 reset (clean cycle)

  ─── Peripheral & DSP firmware upload ────────────────────────────
  bl 0x0800F61C              ; init I²C1 (EEPROM bus on PB8/PB9)
  bl 0x0800C4EC              ; dsp_init_dispatcher — uploads 30 KB DSP blob
                             ; via I²C2 from flash 0x08011E48, then
                             ; sends post-init register writes
  bl 0x0800B350              ; (unknown — possibly LED init or notification setup)
  bl 0x0800C4E8              ; (unknown — paired with 0x0800C4EC)
  bl 0x080115F8              ; (unknown — likely audio subsystem init)

  ─── State restoration from vEEPROM ──────────────────────────────
  bl 0x0800A8DC(0)           ; restore from vEEPROM
  bl 0x0800C494(1)           ;
  bl 0x0800C6B8              ;
  r6 = state[+6] (bass, signed -8..+8)
  bl 0x0800A8A4(state[+4])   ; modeExt
  bl 0x0800A858(state[+5])
  bl 0x0800A8C8(0)
  bl 0x0800A9A8              ; read state[+3] = source
  bl 0x0800A664              ;
  state[+6] = r6 (re-write bass)
  bl 0x0800A648(r6)          ; apply bass to DSP
  bl 0x0800A8DC(state[+1])   ; apply volume

  ─── Bring DSP out of reset ──────────────────────────────────────
  GPIO_WriteBit(GPIOF, PF0=1); ★ PF0 HIGH — DSP CPU released from reset
  bl 0x08011508              ; spdif subsystem post-init / continue

  ─── Settle ──────────────────────────────────────────────────────
  return 2                    ; (then caller writes state[0] = 2)
```

Approximate wall-clock: ~50–200 ms depending on DSP blob upload time (the 30 KB I²C2 upload at ~400 kHz is the slow step).

### Pin states during WAKE (observable)

| Step | PA2 | PB7 | PC15 | PF0 |
|---|---:|---:|---:|---:|
| Before (standby) | 0 | 0 | 0 | 0 |
| After `spdif_subsystem_init` | 1 | 0 | 0 | 0 |
| After PF0 write | 1 | 0 | 0 | 0 (still LOW) |
| After PC15 write | 1 | 0 | 1 | 0 |
| After osDelay 50 ms | 1 | 0 | 1 | 0 |
| ... (DSP blob uploads via I²C2) | 1 | 0 | 1 | 0 |
| After PF0 release | 1 | ? | 1 | 1 |
| Settled (active) | 1 | 1 | 1 | 1 |

Note: PB7 must transition to 1 somewhere — it's HIGH in steady-state active. The WAKE sequence above doesn't show an explicit PB7 HIGH write, so it's likely set HIGH inside `spdif_subsystem_init` (`0x08011500`) along with PA2, or inside `dsp_init_dispatcher` as part of the DSP-power-up dance.

---

## ★ SLEEP sequence — `transition_state(1)` (action=1)

Triggered by: user IR-power press while active, auto-standby timer after ~15 min silence, or external standby request.

Pre-condition: `state[0] == 2` (must be active; else returns error).

```
[0x0800A7FC]
  cmp state[0], #2
  bne ERROR_EXIT             ; can only sleep from active
  state[0] = 4               ; ★ intermediate "going standby"

  ─── Mute / pre-shutdown ─────────────────────────────────────────
  bl 0x0800A8DC(0)           ; mute / clear volume (passes 0 = LOW level)

  if state[+3] (source) == 1:
      bl 0x0800B330          ; ★ source=1-specific shutdown (e.g., AUX-IN
                             ;   amp pre-mute). Skipped for other sources.

  osDelay(200 ms)            ; let audio settle / fadeout

  ─── Three rails down + DSP into reset ───────────────────────────
  bl 0x08011500              ; ★ NOPed in fw_22 — would drive PA2 LOW
                             ; (Toslink rail off)
  bl 0x0800C48C → 0x0800C9A0 ; ★ NOPed in fw_22 — drives PB7 LOW
                             ; (DSP-IC power off — strong suspect for the
                             ;  "DSP still drawing current in standby" issue)
  GPIO_WriteBit(GPIOF, PF0=0); ★ PF0 LOW — DSP into reset (NOT NOPed)
  bl 0x0800F2B8              ; I²C1 shutdown — reconfigure PB8/PB9 → Analog
                             ; (NOT NOPed; saves the EEPROM bus power)
  GPIO_WriteBit(GPIOC, PC15=0); ★ NOPed in fw_22 — PC15 LOW (aux/amp rail off)

  ─── Settle ──────────────────────────────────────────────────────
  state[0] = 1               ; settled standby
  return 1
```

Approximate wall-clock: ~250 ms (the 200 ms mute fade dominates).

### Pin states during SLEEP (stock firmware)

| Step | PA2 | PB7 | PC15 | PF0 |
|---|---:|---:|---:|---:|
| Before (active) | 1 | 1 | 1 | 1 |
| After `spdif_subsystem_init` | 0 | 1 | 1 | 1 |
| After PB7 LOW (via 0x0800C48C) | 0 | 0 | 1 | 1 |
| After PF0 LOW | 0 | 0 | 1 | 0 |
| After I²C1 shutdown | 0 | 0 | 1 | 0 |
| After PC15 LOW | 0 | 0 | 0 | 0 |
| Settled (standby) | 0 | 0 | 0 | 0 |

### Pin states during SLEEP under fw_22 (current production)

| Step | PA2 | PB7 | PC15 | PF0 |
|---|---:|---:|---:|---:|
| Before (active) | 1 | 1 | 1 | 1 |
| `spdif_subsystem_init` NOP | 1 | 1 | 1 | 1 |
| `0x800c48c` NOP | 1 | 1 | 1 | 1 |
| After PF0 LOW | 1 | 1 | 1 | 0 |
| After I²C1 shutdown | 1 | 1 | 1 | 0 |
| PC15 LOW NOP | 1 | 1 | 1 | 0 |
| Settled (fw_22 standby) | **1** | **1** | **1** | **0** |

→ DSP IC stays *powered* (PB7 HIGH), held in reset (PF0 LOW). This matches the observed behavior where the DSP is "responsive" / draws current during standby.

### Pin states during SLEEP under fw_33 (proposed: keep only Toslink alive)

| Step | PA2 | PB7 | PC15 | PF0 |
|---|---:|---:|---:|---:|
| Before (active) | 1 | 1 | 1 | 1 |
| `spdif_subsystem_init` NOP | 1 | 1 | 1 | 1 |
| `0x800c48c` (restored, PB7 LOW) | 1 | **0** | 1 | 1 |
| After PF0 LOW | 1 | 0 | 1 | 0 |
| After I²C1 shutdown | 1 | 0 | 1 | 0 |
| PC15 LOW (restored) | 1 | 0 | **0** | 0 |
| Settled (fw_33 standby) | **1** | **0** | **0** | **0** |

→ Toslink rail stays up (PA2 HIGH) for wake-on-SPDIF, but DSP/amp powered down (PB7 LOW, PC15 LOW). Pending bench verification (does Toslink really only need PA2, or do PB7/PC15 also contribute?).

---

## Important sub-functions

| Address | Role |
|---|---|
| `0x08011500` | `spdif_subsystem_init` — drives PA2 (HIGH in wake, LOW in sleep). The Goal #2 work showed PA2 is the Toslink-rail master. |
| `0x0800C48C` → `0x0800C9A0` | Drives PB7 (HIGH in wake, LOW in sleep). Suspect: DSP-IC power enable. |
| `0x0800F61C` | I²C1 init (EEPROM bus on PB8/PB9). Called only during WAKE. |
| `0x0800F2B8` | I²C1 deinit (PB8/PB9 → Analog). Called only during SLEEP. |
| `0x0800C4EC` | `dsp_init_dispatcher` — holds DSP in reset, releases it, uploads the 30 KB DSP firmware blob via I²C2, runs post-init register writes. |
| `0x0800D65E` | `GPIO_WriteBit(GPIOx, pinmask, val)` — the HAL wrapper used for PA2 / PB7 / PC15 / PF0 writes. |
| `0x0800D334` | `osDelay_ms` — RTX5 osDelay wrapper, called with 50 ms (wake) and 200 ms (sleep). |
| `0x0800A8DC` | volume apply (or fade-to-mute when passed 0) |
| `0x0800A648` | bass apply |
| `0x0800A664` | source apply / DSP routing setup |
| `0x0800B330` | source=1 (AUX) specific pre-shutdown (called only during SLEEP if source==1) |

---

## Why DSP appears "responsive" in standby (the task #59 puzzle)

In **stock firmware**, all four pins (PA2/PB7/PC15/PF0) go LOW during sleep, so the DSP IC's power input is removed and the chip draws ~0 mA.

In **fw_22**, three of those LOW writes are NOPed (PA2/PB7/PC15) to keep the Toslink rail alive for wake-on-SPDIF. The unintended side effect: **PB7 stays HIGH**, so the DSP IC's power rail stays on. PF0 LOW still asserts the DSP's hardware reset, which halts the DSP CPU — but the chip itself remains powered (idle current draw, internal voltage references still on, possibly leakage to other rails).

**fw_33** restores the PB7 LOW and PC15 LOW writes (only PA2 stays NOPed), on the hypothesis that PA2 alone is the Toslink-rail master. Pending bench verification.
