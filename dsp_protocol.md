# DSP control protocol — Renesas D2-92634-LR on Teufel Cinebar One

All findings reverse-engineered statically from `/tmp/firmware/firmware_01_baseline.bin`
(disasm: `/tmp/firmware/disasm.txt`). No bench captures — RE leverages the host firmware's I²C protocol implementation. Last updated 2026-06-06.

## Architecture overview

| Property | Value |
|---|---|
| Host MCU bus | I²C2, pins PB10 (SCL) / PB11 (SDA), AF1 |
| Mutex | "Mutex I2C System" |
| HAL transmit fn | `HAL_I2C_Master_Transmit @ 0x0800D93C` |
| **Two DSP slave addresses** | `0x88` (= 7-bit `0x44`) for boot-time blob upload, `0xB2` (= 7-bit `0x59`) for runtime register access |
| Boot blob upload | `HAL_I2C_Mem_Write(0x88, MemAddr=0, MemAddSize=2, buf=0x08011E48, size=0x79C5=30661 bytes, timeout=5000ms)` |
| Runtime register access | `write_dsp_register(reg_24b, value_24b)` — 6-byte buffer = 3-byte BE address + 3-byte BE value |

## DSP boot blob (corrected)

| | Value |
|---|---|
| Flash start | `0x08011E48` (= file offset `0x11E48`) |
| Size | `0x79C5` = 31173 bytes ≈ **30.4 KB** |
| End | file offset `0x1980D` |
| Upload destination | DSP memory address `0` (16-bit) via slave `0x88` |

(The first agent's "27.6 KB blob at 0x15620–0x01C1F0" identified the highest-entropy *part* of the blob. The actual upload range is wider — there's lower-entropy material before and after.)

## Runtime register-writer: `write_dsp_register` @ `0x0800CAA0`

```
push {r2, r3, r4, lr}
lsrs r3, r0, #16; strb r3, [sp+0]        ; buf[0] = (reg >> 16) & 0xFF
lsrs r3, r0, #8;  strb r3, [sp+1]        ; buf[1] = (reg >> 8)
                  strb r0, [sp+2]        ; buf[2] = reg & 0xFF
lsrs r0, r1, #16; strb r0, [sp+3]        ; buf[3] = (val >> 16)
lsrs r0, r1, #8;  strb r0, [sp+4]        ; buf[4] = (val >> 8)
                  strb r1, [sp+5]        ; buf[5] = val & 0xFF
movs r2, #6                              ; len = 6
mov  r1, sp                              ; buf ptr
movs r0, #0xB2                           ; i2c slave addr (8-bit form)
bl   0x0800FBC4                          ; mutex-guarded I²C wrapper
```

Signature: `r0 = reg (24-bit)`, `r1 = value (24-bit)`. 56 call sites in flash.

## Per-mode preset bank: registers `0x2E – 0x39`

Loader: `set_audio_mode(mode_id)` @ `0x0800C560`. Dispatches `r0 ∈ {0, 1, 2}` → Music / Movie / Voice. Two literal constants drive the per-mode "enable" toggles: `0x00800001` (≈ -1.0 in Q23 — looks like a "filter enable" flag) and `0x00A56208` (Voice-only coefficient).

| Reg | Music | Movie | Voice | Interpretation guess |
|---|---|---|---|---|
| 0x2E | 0x800001 | 0 | 0x800001 | filter A enable (off in Movie only) |
| 0x2F | 0 | 0 | 0xA56208 | filter B coefficient (Voice-specific) |
| 0x30 | 0 | 0 | 0xA56208 | filter B coefficient (Voice-specific) |
| 0x31 | 0 | 0 | 0x800001 | filter C enable (Voice only) |
| 0x32 | 0 | 0 | 0 | reserved/unused |
| 0x33 | 0 | 0x800001 | 0 | filter D enable (Movie only — likely surround/spatial) |
| 0x34 | 0x800001 | 0 | 0x800001 | mirror of 0x2E (L/R channel?) |
| 0x35 | 0 | 0 | 0xA56208 | mirror of 0x2F |
| 0x36 | 0 | 0 | 0xA56208 | mirror of 0x30 |
| 0x37 | 0 | 0 | 0x800001 | mirror of 0x31 |
| 0x38 | 0 | 0 | 0 | mirror of 0x32 |
| 0x39 | 0 | 0x800001 | 0 | mirror of 0x33 |

Reads cleanly as: **Music = filter A on. Movie = filter D on (surround). Voice = filters A + B + C on.**

## Source-switch → auto-mode mapping (from `0x0800A664`)

When IR sends a source-change event, the bar AUTOMATICALLY sets a corresponding audio mode:

| Source ID | Likely source | Audio mode applied | Routing constant |
|---|---|---|---|
| 0 | Optical (default) | Music | 0x810000 |
| 1 | AUX | Movie | 0x800000 |
| 2 | HDMI | Voice | 0x810000 + extras |
| 3 | BT | Voice | 0x800000 + extras |

(Source-ID-to-physical-input correspondence not yet verified — placement is inferred.)

## Event-loop dispatch table @ `0x0800ACA4`

Inline jump table at `0x0800ACF4` (10 bytes, 1 byte per case). Each case index = `msg->type[0]`:

| Type | Handler | Likely event | DSP-write functions called |
|---|---|---|---|
| 0 | 0x800ad06 | (error/invalid) | — |
| 1 | 0x800a740 | **power / transition_state** | (state machine, no direct DSP) |
| 2 | 0x800a8dc | ? (mode-set?) | — |
| 3 | 0x800a71c | auto-standby request | — |
| 4 | 0x800a664 | **source switch** | calls set_audio_mode |
| 5 | 0x800a8a4 | ? (volume / EQ commit?) | 0x800c804 (regs 0x70-0x77) + 0x800c88c (0x3E/0x41/0x46/0x49) |
| 6 | 0x800a858 | **bass +/-** ★ | 0x800c7a0 (regs 0x0F + 0xE9) |
| 7 | 0x800a648 | ? (mute?) | — |
| 8 | 0x800a8c8 | ? (mode-set?) | 0x800c88c (0x3E/0x41/0x46/0x49) |

## Full DSP register map (every write site found in firmware)

| Reg | Width | Writer fn | Source of value | Crackle relevance |
|---|---|---|---|---|
| 0x00 | 24-bit | 0x0800C6B8 | literal at 0x800c6c4 | low |
| 0x02 | 24-bit | 0x0800C554 | constant `0` | low |
| 0x0F | 24-bit | **0x0800C7A0** | clamped to `[-14, 0]` from EEPROM | ★★ HIGH — see "Bass / limiter candidate" below |
| 0x2A | 24-bit | 0x0800C8C8, 0x0800C934 | `0` or literal | medium (boot-init only) |
| 0x2D | 24-bit | 0x0800C8D2, 0x0800C93E | literal at 0x800c94c/0x800c958 | medium |
| 0x2E – 0x39 | 24-bit | 0x0800C560 (set_audio_mode) | per-mode table (see above) | low (these are mode-toggles) |
| 0x3A | 24-bit | called by boot @ 0x800c4a4 | computed at boot (negated) | medium |
| 0x3B | 24-bit | called by boot @ 0x800c4a4 | computed at boot (negated, +1) | medium |
| 0x3C | 24-bit | 0x0800C5FC | one of {0x0000D7A3, 0x00009D36} | ★ likely a 4-band EQ filter |
| 0x3E | 24-bit | 0x0800C88C | `2` or literal at 0x800c948 | medium (called from vol or EQ event) |
| 0x40 | 24-bit | 0x0800C5FC | as 0x3C | ★ |
| 0x41 | 24-bit | 0x0800C88C | as 0x3E | medium |
| 0x42 | 24-bit | site near 0x800c90c | `2` | medium |
| 0x44 | 24-bit | 0x0800C5FC | as 0x3C | ★ |
| 0x46 | 24-bit | 0x0800C88C | as 0x3E | medium |
| 0x48 | 24-bit | 0x0800C5FC | as 0x3C | ★ |
| 0x49 | 24-bit | 0x0800C88C | as 0x3E | medium |
| 0x4A | 24-bit | site near 0x800c920 | literal | medium |
| 0x54 | 24-bit | 0x800c6f0 | literal | medium |
| 0x55 | 24-bit | 0x800c700 | literal | medium |
| 0x6D | 24-bit | **0x0800C640** | arg (r0) — possibly **volume** | ★ |
| 0x6E | 24-bit | 0x0800C640 (= 0x6D + 1) | arg (r1) — paired with 0x6D | ★ |
| 0x70 – 0x77 | 24-bit each | **0x0800C804** | 8 regs each from one of 4 literals at 0x800c888 indexed by r5 | ★★ probably **stereo/source routing matrix** — 4 options × 8 regs |
| 0xB9 | 24-bit | 0x800c734 | computed | low |
| 0xE4 – 0xE7 | 24-bit each | **0x0800C744** | all 4 from same value (EEPROM-loaded) | ★ likely **output gain bank** (master volume?) |
| 0xE9 | 24-bit | **0x0800C7A0** (paired with 0x0F) | clamped to [-14, 0] | ★★ HIGH (see below) |

## Bass / limiter / volume candidate analysis

### Register pair `0x0F` + `0xE9` (function `0x0800C7A0`)

Strongest candidate for the crackle culprit. The function:
- Reads a signed input value (`r0`)
- Clamps to `[-14, 0]` (i.e., values 0 down to -14)
- Stores to vEEPROM
- Writes the same value to both DSP registers `0x0F` and `0xE9`

Two interpretations:
1. **Bass control** — the bar's bass+/- adjusts bass over 15 steps from neutral (0) to -14. The bar can only **cut**, not boost — design choice to avoid driver damage. (Common in entry-level soundbars.) If this is bass, the crackle isn't here.
2. **Limiter threshold** — `[-14, 0] dB FS` is textbook limiter threshold range. Writing 0 = limiter just barely engaged; -14 = limiter clamps everything above -14 dB. If the EEPROM-stored value sits near 0, the limiter is *too lenient* → loud transients pass through unattenuated → DAC/amp clipping → crackle.

Without the IR remote, we can't easily tell which interpretation is right just by static RE. **Patch test idea**: in `0x0800C7A0`, force a hard-coded value (e.g., -4) regardless of EEPROM. Listen to a crackle-prone track:
- If crackle reduces → it was a too-permissive limiter, fixed.
- If sound becomes obviously bass-light → it's the bass control, restore to 0.

### Register pair `0x6D` + `0x6E` (function `0x0800C640`)

Likely the **volume control** — takes two args, writes them to consecutive registers. Spaced from the limiter regs by enough that this is a separate effect.

### Register bank `0xE4 – 0xE7` (function `0x0800C744`)

4 registers all written from the same single value loaded from EEPROM. Looks like a **master output-gain bank** (one gain per channel — center, left, right, sub?). Set once at boot from EEPROM.

### Register bank `0x70 – 0x77` (function `0x0800C804`)

8 registers, each gets one of **4 literals at `0x800c888`** based on `r5` (incoming arg). Pattern matches a **routing matrix** (4 sources × 8 routing entries each? or 8 outputs × 4 modes?). Worth dumping the constants.

### Register bank `0x3C`, `0x40`, `0x44`, `0x48` (function `0x0800C5FC`)

4 registers, each takes one of 2 literals: `0x0000D7A3` (~55203 → Q23 ≈ 0.00658) or `0x00009D36` (~40246 → Q23 ≈ 0.0048). Looks like a **2-state biquad filter coefficient bank** — possibly the "Night mode" or "Voice enhancement" filter.

## vEEPROM (persistent settings)

vEEPROM lives at flash pages **`0x08007000`** (active in this dump) and **`0x08007800`** (erased backup). Two-page swap layout — Page 0 currently holds all writes.

### Key registry @ `0x08003FA0`

| Offset | Key | Used for |
|---|---|---|
| 0x3FA0 | 0x1111 | source select |
| 0x3FA2 | 0x2222 | volume |
| 0x3FA4 | 0x3333 | ★ signed-int8 setting — see below |
| 0x3FA6 | 0x4444 | binary toggle (mute? night?) |
| 0x3FA8 | 0x5555 | reserved (always 0 in dump) |
| 0x3FAA | 0x6666 | reserved (16-bit halfword in struct, always 0) |
| 0x3FAC | 0xFF00..0xFF03 | metadata: 0x31 (~49), 0x13EC (~5100), 0x0101, 0x0000 — counters/markers |

### Loader fn `0x0800AE78`, saver fn `0x0800AF08`

Loader reads each key in turn (via `ee_read_variable @ 0x080115C0`) and stores into a state struct at `0x200025DC`:

| Key | RAM offset | Type |
|---|---|---|
| 0x2222 (vol) | `[+1]` | u8 |
| 0x1111 (source) | `[+3]` | u8 |
| 0x4444 | `[+4]` | u8 |
| 0x5555 | `[+5]` | u8 |
| 0x3333 | `[+6]` | **int8 (signed)** — saver uses `ldrsb` |
| 0x6666 | `[+16]` | u16 (halfword) |

### Current stored values (from this dump)

Latest-write-wins parse of all 4-byte entries at file offset `0x7014–0x70CB`:

| Key | Latest val | History (early → late) | Interpretation |
|---|---|---|---|
| 0x1111 | **2** | 1,0,1,2,1,3,0,1,2,0,2,3,2,1,2 | source select; revised mapping based on user's actual usage: **0=HDMI-ARC, 1=AUX, 2=Optical/Toslink ★, 3=BT** (sources 0 and 2 share `0x810000` SPDIF-enable prefix in the handler — both are digital SPDIF inputs into the same receiver chain on the PCB) |
| 0x2222 | **11** | 10,60,43,60,42,60,23,18,19,18,16,14,13,11,9,11 | volume in 0–60 step range — currently low (11 ≈ 18%) |
| 0x3333 | **5** | 0,8,5,2,5,8,5 | ★ signed int8 — semantics unclear (see analysis below) |
| 0x4444 | **1** | 1,0,1,0,1 | binary toggle (mute? night mode?) |
| 0x5555 | 0 | (init only) | unused |
| 0x6666 | 0 | (init only) | unused |

### What is key 0x3333?

This is the most interesting setting because it's the **only signed int8** and it lives at struct offset `+6` — which is consumed by 8+ readers including the limiter writer at `0x0800C7A0` (the function that writes DSP regs `0x0F` and `0xE9` with range `[-14, 0]`).

But there's a complication: the **event-6 IR handler** (`0x0800A858`) writes struct[+6] with values from {0, 5, -6} based on payload — yet the vEEPROM history shows {0, 2, 5, 8}. The values 2 and 8 don't come from IR; they must come from the **UART/BT command parser** at `0x0800BCEC` (which also calls saver `0x0800AF08`). So the bar accepts external commands (Bluetooth SPP? debug UART?) that can set this byte to richer values than IR alone.

Three coexisting hypotheses for key 0x3333:
1. **Audio mode** (Music/Movie/Voice + Night) — but 4 distinct positive values 0/2/5/8 suggests more like 4 modes
2. **Night mode level** — 0 = off, higher = more aggressive compression
3. **Bass cut step** — signed, 0 = neutral, negative = boosted (which the EEPROM hasn't seen yet)

Without bench access we can't easily disambiguate. But the link `struct[+6]` → `0x0800C7A0` → DSP regs `0x0F + 0xE9` is concrete: **whatever key 0x3333 represents, changing it would change the DSP's behavior on those two registers**.



Top 3 crackle-test candidates in priority order:

1. **`0x0F` + `0xE9` via `0x0800C7A0`** — patch the clamp upper bound from 0 to e.g. `-4`. Listen test. If limiter, crackle reduces. If bass, bass becomes lighter.
2. **`0xE4 – 0xE7` master gain via `0x0800C744`** — patch the loaded value to a few dB lower. Reduces output level globally. If amp-side clipping, crackle reduces. Side effect: overall lower volume (so re-check at higher volume).
3. **`0x70 – 0x77` matrix via `0x0800C804`** — only worth probing if (1) and (2) don't help; modifying without semantics is risky.

## Risks recap

- Patches affect a 24-bit signed value space. Always change by 1-2 units at a time.
- All patches are local to `firmware_22_wake-on-spdif.bin`; reverting is just a reflash.
- DO NOT change registers in the boot blob (file offset 0x11E48-0x1980D) — that's DSP-internal code; we don't understand it.

## ★ Bench-verified finding (2026-06-07): host firmware never writes DSP registers during wake

GDB breakpoint at `0x0800CAA0` (`write_dsp_register`) was set during fw_22 active runtime. User then IR-cycled (off → on). **Breakpoint did not fire.** Walking the wake path:

- IR-on → event type 1, payload=2 → `transition_state(2)` @ `0x0800A740`
- `transition_state(2)` → `0x0800C4EC` (DSP init dispatcher)
- `0x0800C4EC` only chains: pre-init, DSP reset pulse, **bulk blob upload via `0x0800CA70`** (not via `write_dsp_register`), and a post-init wait

**The bar re-uploads the 30 KB DSP blob on every wake and lets the DSP run with whatever defaults the blob has.** The host does NOT write per-register DSP config except in response to explicit IR-triggered handlers (source switch → `set_audio_mode`, vol/bass +/-, etc.). With source/mode buttons unavailable, the bar runs purely on blob defaults — i.e., whatever audio mode is baked into the blob, regardless of EEPROM source selection.

Implication for **fw_23**: the injected `set_audio_mode(0)` call in the wrapper will be the **first** `write_dsp_register` activity on every wake — 12 writes (regs `0x2E – 0x39`) for the Music preset. This makes fw_23 trivially testable via the same GDB breakpoint: silent under fw_22, fires 12 times under fw_23.

Recon 1 (RAM state dump) also confirmed: state struct at `0x200025DC` exactly matches the EEPROM-derived values (vol=11, source=2, key3=5, key4=1, key5=0, key6=0). Loader at `0x0800AE78` works as documented.
