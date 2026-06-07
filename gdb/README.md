# GDB / OpenOCD recipes for the Teufel Cinebar One

Consolidated live-debug tooling for the Cinebar One firmware-RE project.

## Files in this directory

| File | Purpose |
|---|---|
| `README.md` | This file: prerequisites, helper-script usage, recipes |
| `switch_mode.sh` | Wrapper to switch the bar's audio mode via GDB (Music/Movie/Voice) live |
| `trace_modes.gdb` | GDB command file to capture full DSP-write trace per mode |
| `read_ir_log.sh` | Dump the fw_24 IR-notify ring buffer at `0x20003C00` (use after IR-button press) |
| `scratch/` | Disposable ad-hoc test scripts including the deprecated `capture_ir_notify.sh` (safe to delete) |

## Prerequisites

- ST-Link connected to bar's SWD pads
- OpenOCD installed and running:
  ```
  openocd -f interface/stlink.cfg -f target/stm32f0x.cfg
  ```
- `gdb-multiarch` or `arm-none-eabi-gdb` in PATH
- `arm-none-eabi-objcopy` (for ELF building — see Step 0)
- Bar flashed with a known firmware (see `/tmp/firmware/FIRMWARE_VARIANTS.md`)

Cortex-M0 debug limits to keep in mind:
- 4 hardware breakpoints (FPB) — flash addresses only, NOT RAM
- 2 hardware data watchpoints (DWT) — exceeding falls back to slow software single-stepping

## Step 0 — Build a usable ELF (recommended)

Without an ELF, GDB still works but shows everything as raw hex. With one,
`disas <addr>` and many other commands become useful.

```bash
arm-none-eabi-objcopy \
    -I binary \
    -O elf32-littlearm \
    -B arm \
    --rename-section .data=.text,alloc,readonly,code,contents \
    --change-section-address .data=0x08000000 \
    firmware_01_original-dump.bin firmware_01_original-dump.elf
```

Sanity-check:

```
arm-none-eabi-gdb firmware_01_original-dump.elf
(gdb) target remote :3333
(gdb) info files          # expect section at 0x08000000 - 0x08020000
(gdb) x/4wx 0x08000000    # expect: 0x20001ce8 0x080000d5 0x08002401 0x080020d9
```

Note: `objcopy` produces a *relocatable* ELF; GDB's `call` command still won't
work because there's no entry point. For function-call use (Recipe F), see
the `switch_mode.sh` manual-register approach.

---

## Helper script: `switch_mode.sh`

Switches the bar's audio mode live, without reflashing. Usage on your local
machine (where OpenOCD's GDB server runs on `:3333`):

```bash
./switch_mode.sh music      # filter A only
./switch_mode.sh movie      # filter D only (surround)
./switch_mode.sh voice      # filters A + B + C + Voice coefficient
./switch_mode.sh -v voice   # verbose (show GDB output)
```

What it does: halts the bar's CPU, saves caller-saved registers, writes a
BKPT instruction to RAM at `0x20002000` as a return trampoline, calls
`set_audio_mode(mode)` @ `0x0800C560`, then restores registers and resumes.
The whole cycle is ~1 second locally (much longer over SSH-forwarded ports).

Works for any firmware variant that retains `set_audio_mode` at its standard
address (verified for `fw_22` and `fw_23`).

---

## Recipe A — IR toggle capture (✓ used for Goal #1)

Used to identify `transition_state()`, the notify-broadcast call, and the
state struct at `0x200025DC`. Result: `firmware_05_autoboot-active-on-power.bin`.

```
(gdb) target remote :3333
(gdb) monitor reset halt
(gdb) watch *(unsigned char *)0x200025DC      # main state struct byte 0
(gdb) info watchpoints                        # confirm "hw watchpoint"
(gdb) continue
```

Trigger IR (Arduino IR-trigger or remote). On each watchpoint fire:

```
(gdb) bt
(gdb) info reg
(gdb) x/8i $pc-16
```

**Cautions:**
- Do NOT watch `0x20002538` (RTX5 kernel struct — context-switch writes flood it)
- Use `unsigned char/short/int`, not `uint8_t` (no type info without ELF)

---

## Recipe B — Auto-standby trigger capture (✓ Goal #2 Step 1)

Used to find what causes the bar to enter standby. Watchpoint on
`*(unsigned char *)0x200025DC` while bar is active, then stop SPDIF audio
and wait. When the watchpoint fires:

```
(gdb) bt                  # ★ the function chain leading to standby
(gdb) info reg
(gdb) x/16wx $sp
(gdb) x/8i $pc-16
```

Expected cascade:
- Frame #0: address near `0x0800A800` — `strb` that writes `state[0] = 4`
- Frame #1: address near `0x0800AD12` — `BL transition_state`
- Frame #2+: the thread that posted the standby event

**Result confirmed**: the 15-min auto-standby is driven by a hardware
hysteresis chip (the SOT-23-5 next to Toslink), via `PA3` carrier-detect.
See `/tmp/firmware/GOAL2.md` for the full story.

---

## Recipe C — SPDIF pin verification (✓ done)

Hardware probe (no GDB needed) to confirm which STM32 pin carries the SPDIF
activity signal. Logic analyzer on STM32 pins:

- **Pin 13 = PA3** — clean HIGH-when-playing / LOW-when-silent (SOT-23-5
  buffer doing biphase decode for us)
- **Pin 14 = PA4** — raw biphase data (~5.6 MHz at 44.1 kHz audio)

The bar's firmware polls **PA3** via `is_audio_active()` @ `0x0801041C`.
Our wake-on-SPDIF (`fw_22`) polls **PA4** directly for faster wake response.

---

## Recipe D — Find the Toslink-rail-killer (✓ done, fw_12)

Used to identify all GPIO writes that drop the Toslink-driving rail in standby.
Pattern: break on the BRR-write inside `GPIO_WriteBit` and log every
(port, mask, lr) tuple during an active→standby transition.

```
(gdb) break *0x0800d666
(gdb) commands
> silent
> printf "BRR-write: port=0x%08x mask=0x%04x lr=0x%08x\n", $r0, $r1, $lr
> bt 6
> continue
> end
```

**Result**: `firmware_12_autoboot-active-rail-on.bin` NOPs PA2/PB7/PC15 LOW
writes, keeping the rail at 3 V in standby. See `SHIMS.md`.

**Note (2026-06-07)**: live observation showed the DSP also accepts I²C
writes in standby — the rail-keep-on patches may be over-engineered. Task
#59 covers this investigation.

---

## Recipe E — Diagnose `firmware_10` boot-rail-up failure (📜 historical)

Used during fw_10 → fw_12 development to find which post-shim GPIO writes
were dropping PA2 back to LOW. Pattern: breakpoint at the end of the autoboot
shim, then watch for BRR writes targeting `port=GPIOA mask=0x04`. Resulted
in identifying PA2 as a separate rail control alongside PB7/PC15.

Now mostly historical; preserved in case similar GPIO-mode investigations come up.

---

## Recipe F — DSP register write trace (★ used in current DSP-tuning work)

The bar writes DSP config registers via `write_dsp_register` @ `0x0800CAA0`.
To capture every write live:

```
(gdb) target extended-remote :3333
(gdb) monitor halt
(gdb) break *0x0800CAA0
(gdb) commands
> silent
> printf "DSP: reg=0x%02X val=0x%06X\n", $r0, $r1
> continue
> end
(gdb) monitor resume
```

Power-cycle (or trigger IR-on/off) — each write logs one line. Used to
confirm the bar's stock boot-time DSP config:

| Reg | Value | Likely role |
|---|---|---|
| `0xE4–0xE7` | `0xFFFFFB` (=-5) | Master output gain bank (4 channels) |
| `0x54, 0x55` | `0xFFFFFB` (=-5) | Paired |
| `0xB9` | `0x038E7A` | Unique config constant |
| `0x3A, 0x3B` | `0xFFFFFF` (=-1) | Output trim/offset |

For per-mode trace (calls `set_audio_mode(0)` then `(1)` then `(2)`):
see `trace_modes.gdb` in this directory. Bar must already be running fw_22
or fw_23 (or any binary that has `set_audio_mode` at `0x0800C560`).

---

## Recipe H — IR-decoder hunt via `notify()` logging shim (fw_24)

**Why**: dynamic GDB breakpoints at `notify()` (0x0800BBDC) disrupt the IR decoder's ~70 ms NEC frame timing — bp halts cause missed pulses → IR receive fails → bar HardFaults eventually. The fix: instrument the firmware itself with a logging shim that records `(channel, caller_lr)` to a ring buffer in RAM. No GDB halts during runtime. See `SHIMS.md` (Shim 4) for details.

**Usage**:

```bash
# 1. Flash fw_24 (extends fw_23 with the logging shim)
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
  -c 'program firmware_24_ir-logging.bin verify reset exit 0x08000000'

# 2. (Optional) Reset the log index so only fresh entries appear:
gdb-multiarch -batch -ex 'set confirm off' -ex 'set remotetimeout 30' \
  -ex 'target extended-remote :3333' -ex 'monitor halt' \
  -ex 'set *(unsigned*)0x20003C00 = 0' \
  -ex 'monitor resume' -ex 'quit' >/dev/null 2>&1

# 3. Press IR-power once. Bar responds normally — the shim runs inline
#    on each notify() call without halting.

# 4. Dump the ring buffer:
./read_ir_log.sh
```

**Reading the output**: entries with `channel=2` are the IR-power button. The `lr` field is the return address right after the `bl notify` instruction in the IR-decoder function; subtract 4 to find the BL site itself. Disassemble the surrounding function to find the NEC-code-to-channel lookup table.

Other channels seen in the wild:
- 0, 1 — state transitions (from `event_loop_thread`)
- 9, 14 — LED animation updates (called often during boot)
- 11, 12, 13, 15–19 — various sub-state transitions
- 2–8 — IR remote button channels (the ones we want)

---

## Recipe G — Live mode switch via `set_audio_mode` (★ active)

Implemented as `switch_mode.sh`. The interactive equivalent for paste-by-hand:

```
(gdb) target extended-remote :3333
(gdb) monitor halt
(gdb) set $sr0=$r0
(gdb) set $sr1=$r1
(gdb) set $sr2=$r2
(gdb) set $sr3=$r3
(gdb) set $sr12=$r12
(gdb) set $slr=$lr
(gdb) set $spc=$pc
(gdb) set *(unsigned short*)0x20002000 = 0xBE00
(gdb) set $r0=2                          # 0=Music 1=Movie 2=Voice
(gdb) set $lr=0x20002001
(gdb) set $pc=0x0800c560
(gdb) continue
                                          # SIGTRAP at 0x20002000 — BKPT halted
(gdb) set $r0=$sr0
(gdb) set $r1=$sr1
(gdb) set $r2=$sr2
(gdb) set $r3=$sr3
(gdb) set $r12=$sr12
(gdb) set $lr=$slr
(gdb) set $pc=$spc
(gdb) monitor resume
```

**Why a RAM trampoline?** Cortex-M0's FPB only matches flash addresses, so
we can't set a hardware breakpoint in RAM. The BKPT *instruction* at
`0x20002000` halts the CPU when executed regardless of FPB. We set LR to
`0x20002001` (BKPT addr + Thumb bit) so the function returns to it.

**Why save r0–r3, r12?** AAPCS: `set_audio_mode` may clobber these. r4–r11
are preserved by the function itself.

**Why save & restore pc, lr?** We're hijacking the CPU mid-execution of
some other task. After our call, we restore PC to the original instruction
so the task continues as if nothing happened.

---

## Reference tables

### Cortex-M0 peripheral registers (STM32F072)

| Address | Purpose |
|---|---|
| `0x40005400` | I2C1 base |
| `0x40005800` | I2C2 base (DSP bus — PB10=SCL, PB11=SDA AF1) |
| `0x40005828` | I2C2_TXDR |
| `0x40010400` | EXTI base |
| `0x40010000` | SYSCFG base (EXTICR) |
| `0x40021000` | RCC base |
| `0x40007000` | PWR base (low-power mode control) |
| `0x48000000` | GPIOA base |
| `0x48000010` | GPIOA_IDR (★ bit 3 = PA3 SPDIF carrier, bit 4 = PA4 SPDIF data) |
| `0x48000014` | GPIOA_ODR |
| `0x48000018` | GPIOA_BSRR (set bits) |
| `0x48000028` | GPIOA_BRR (clear bits) |
| `0x48000400` | GPIOB base |
| `0x48000800` | GPIOC base (PC15 = ★ audio rail enable) |
| `0x48001400` | GPIOF base (PF0 = ★ DSP reset, active LOW) |

### Key firmware addresses

| Address | Symbol |
|---|---|
| `0x080000d4` | Reset_Handler |
| `0x080000e7` | Default_Handler (`b .` — all other IRQ vectors point here) |
| `0x08008c48` | osKernelGetState wrapper |
| `0x08008d74` | osMessageQueueGet wrapper |
| `0x08008e10` | osMessageQueuePut wrapper |
| `0x0800a740` | **transition_state(action)** |
| `0x0800a760` | state[0]=3 write (active-entry transition) |
| `0x0800a802` | state[0]=4 write (standby-entry transition) |
| `0x0800a836` | `bl` PC15-LOW (NOP'd in fw_06+) |
| `0x0800a776` | `bl` PC15-HIGH (active-entry rail-on) |
| `0x0800a76c` | `bl` PF0-LOW (DSP reset) |
| `0x0800a7f0` | `bl` PF0-HIGH (DSP release, ~50 ms after rail-on) |
| `0x0800aca4` | event_loop_thread entry |
| `0x0800acca` | `bl` auto_standby_check |
| `0x0800ace4` | `bl` post_event_type7 (auto-standby trigger) |
| `0x0800ad12` | event-loop `BL transition_state` (★ redirected to wrapper in fw_23) |
| `0x0800bbdc` | notify(channel, value) |
| `0x0800c4ec` | DSP init dispatcher (called from transition_state(2)) |
| `0x0800c560` | **set_audio_mode(mode)** |
| `0x0800c5f4` | per-mode preset table (literals) |
| `0x0800caa0` | **write_dsp_register(reg_24b, val_24b)** |
| `0x0800fbc4` | Mutex-guarded I²C wrapper (calls HAL_I2C_Master_Transmit) |
| `0x0800f15c` | **BKPT** in HardFault handler (used as return trampoline target) |
| `0x0801041c` | `is_audio_active` (reads PA3) |
| `0x08011524` | auto_standby_check |
| `0x08011e48` | DSP boot blob (30,661 bytes) |
| `0x0801E800` | fw_22 shim 1 (autoboot-active) |
| `0x0801E820` | fw_22 shim 2 (wake-on-SPDIF) |
| `0x0801E880` | fw_23 set_audio_mode wrapper |

### Key RAM addresses

| Address | Purpose |
|---|---|
| `0x20002538` | osRtxInfo (RTX5 kernel) — ⚠ DO NOT WATCH |
| `0x20002504` | g_auto_standby_state |
| `0x200023A0` | g_event_loop_struct |
| `0x200024FC` | g_vEEPROM_mutex_id |
| `0x200025DC` | **g_system_state** (state[0] = power state byte) |
| `0x200025DD` | state[+1] = volume (key 0x2222) |
| `0x200025DF` | state[+3] = source (key 0x1111) |
| `0x200025E0` | state[+4] = key 0x4444 |
| `0x200025E2` | state[+6] = signed int8 (key 0x3333) |

### state[0] values (power state)

| Value | Meaning |
|---|---|
| 1 | Standby (stable, red LED) |
| 2 | Active (stable, purple LED) |
| 3 | Transitioning to active (intermediate) |
| 4 | Transitioning to standby (intermediate) |

---

## Quick troubleshooting

**"No symbol table is loaded"** — use `unsigned char/short/int`, not `uint8_t`. Or build the ELF (Step 0).

**"watchpoint" without "hw" prefix** — GDB fell back to software watchpoints (single-stepping):
```
(gdb) set can-use-hw-watchpoints 1
(gdb) delete
(gdb) watch ...
```

**Watchpoint never fires** — variable isn't where you think, OR the trigger isn't happening. Fallback to code breakpoint at the expected writer site.

**Bar reboots/freezes** — too many watchpoints (software fallback) or halted mid-transaction. Recover:
```
(gdb) monitor reset halt
(gdb) monitor reset run
```

**"target not halted" when continuing** — bar was already running. `^C` then continue.

**"Entry point address is not known"** when using `call` — GDB needs an entry point for inferior calls; relocatable ELFs don't have one. Workaround: manual register manipulation (Recipe G / switch_mode.sh).

**"Cannot insert hardware breakpoint: Remote failure reply: 0E"** — Cortex-M0 FPB doesn't support RAM addresses. Use the BKPT-in-RAM trampoline pattern (Recipe G) instead.

**TCL error `can't read "varname": no such variable`** — your GDB is routing `set $var = ...` to OpenOCD's TCL interpreter inside `define` macros. Workaround: use `-ex "set ..."` command-line args (which work directly), or interactive commands at the prompt.
