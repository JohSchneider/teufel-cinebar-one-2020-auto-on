# IR command mapping — Teufel Cinebar One

## TL;DR — verified end-to-end

Every IR remote button posts to the command queue via **`notify(13, packed_value)`** where `packed_value` is a 32-bit word with this layout:

```
   byte 3   byte 2   byte 1     byte 0
  +--------+--------+----------+-----------+
  | 0x00   | 0x00   | press_tag | button_id |
  +--------+--------+----------+-----------+
```

- `button_id`: 1–14, identifies which IR button (table at `0x080116A0`)
- `press_tag`: `2` = normal/first press, `4` / `6` / `8` / `11` / `12` = various hold-state encodings (set inside the IR-decoder at `0x0800FE00+`)

POWER is verified via ring-buffer capture: pressing the Arduino's IR-power code resulted in `notify(13, 0x00000201)` (button_id=1, press_tag=2).

## Complete button-id table

The IR-decoder's lookup table at `0x080116A0` (14 entries × 8 bytes) stores `(0xFD, bit_reverse(~NEC_cmd), 0, 0, button_id_u32)`. After decoding the bit-reverse:

| id | LIRC name | LIRC NEC code | NEC cmd byte | normal-press notify value |
|---:|---|---|---:|---:|
| 1 | power | `0x40BFB847` | `0xB8` | **`notify(13, 0x0201)`** ★ verified (ring buffer + GDB-inject toggles bar) |
| 2 | mute | `0x40BF7887` | `0x78` | **`notify(13, 0x0202)`** ★ verified (GDB-inject mutes audio) |
| 3 | hdmiIn | `0x40BF20DF` | `0x20` | `notify(13, 0x0203)` |
| 4 | btIn | `0x40BF40BF` | `0x40` | `notify(13, 0x0204)` |
| 5 | auxIn | `0x40BF609F` | `0x60` | `notify(13, 0x0205)` |
| 6 | optIn | `0x40BFC03F` | `0xC0` | `notify(13, 0x0206)` |
| 7 | bassUp | `0x40BFD02F` | `0xD0` | `notify(13, 0x0207)` |
| 8 | bassDown | `0x40BF50AF` | `0x50` | `notify(13, 0x0208)` |
| 9 | volUp | `0x40BF18E7` | `0x18` | `notify(13, 0x0209)` |
| 10 | volDown | `0x40BF629D` | `0x62` | `notify(13, 0x020A)` |
| 11 | modeExtend (stereo widening) | `0x40BF708F` | `0x70` | `notify(13, 0x020B)` |
| 12 | modeMusic | `0x40BF10EF` | `0x10` | `notify(13, 0x020C)` |
| 13 | modeMovie | `0x40BF02FD` | `0x02` | `notify(13, 0x020D)` |
| 14 | modeVoice | `0x40BFA45B` | `0xA4` | `notify(13, 0x020E)` |

## How we found it

1. **fw_29** instrumented `notify()` with a 4-byte trampoline (`ldr r2, [pc, #imm]; bx r2` + repurposed literal at `0x0800BC10`) that writes channel/value to RAM at `0x20003E00` before tail-calling notify+4. Firing Arduino IR-power → captured `notify(13, 0x00000201)`.
2. **Static trace** found the IR-decoder at `0x0800FE00+`: a 14-iteration loop comparing received NEC bytes to a table at `*(0x0800FEA8)` = `0x080116A0`.
3. The table's "key" byte is **bit-reverse of the NEC inverted-cmd byte** — e.g., power's NEC cmd `0xB8` → inverted `0x47` → bit-reversed `0xE2` is what's stored. All 14 table entries decode correctly.

## What `cmd_id=13` actually does (corrected)

The dispatch chain for `cmd_id=13` is:

```
notify(13, v)  →  command_dispatch_thread queue
              →  helper@0x080108E2: r3=13, byte_at_LR-1=0x14 (LIMIT),
                  reads inline[14]=0xFB → target = 0x0800BEDC
              →  0x0800BEDC: b.n 0x0800BF54   (IR case body)
              →  0x0800BF54: extracts (byte0, byte1, byte2) from value, then
                  bl 0x080108E2 again — sub-dispatch on byte0 = button_id
              →  per-button sub-handler at one of:
                    sub  1 (power)    → 0x0800BF90   (toggle state via post_event_type0)
                    sub  2            → 0x0800BFB0
                    sub  3            → 0x0800BFD6   (post_event_type3(3))
                    sub  4 (4-way)    → 0x0800C000
                    sub  5            → 0x0800C054   (post_event_type3(0))
                    sub  6            → 0x0800C07E
                    sub  7            → 0x0800C0F4
                    sub  8            → 0x0800C14C
                    sub 9–14          → 0x0800C13E..0x0800C148 cluster
```

**There is no source gate on the main IR path** — vol/bass/mode/mute go straight to their own per-button handlers regardless of source. (My earlier "source-gated at 0x0800C32C" reading was a byte-counting error in the dispatch table: the inline table has five `0x49` no-op bytes in a row, not four. cmd_id=13 actually reads `0xFB` and routes to `0x0800BEDC`, not `0xFA` at `0x0800BEDA`.)

The `0x0800BF8E → 0x0800C32C` chain that DOES read state[+3] is the **fallback exit** taken when the sub=1 power-toggle handler sees state[0] in an unexpected transitional value (not 1 or 2 — e.g., 4 = "going-to-standby"). It's a defensive path, not the main one.

## Sub-handler fingerprints (per button)

Once cmd_id=13 → 0x0800BF54 → sub-dispatch[button_id], each button reaches a specific handler:

| button | id | sub-handler |
|---|---:|---|
| power | 1 | 0x0800BF90 — read state[0]; post_event_type0(1) if active, (2) if standby |
| mute | 2 | 0x0800BFB0 — checks byte1 ∈ {2, 11} |
| hdmiIn | 3 | 0x0800BFD6 — `post_event_type3(3)` (source-set?) |
| btIn | 4 | 0x0800C000 — sub-sub-dispatch on byte1 ∈ {2, 4, 8} |
| auxIn | 5 | 0x0800C054 — `post_event_type3(0)` |
| optIn | 6 | 0x0800C07E — `post_event_type3(?)` |
| bassUp | 7 | 0x0800C0F4 — checks byte1 ∈ {2, 11, 12} |
| bassDown | 8 | 0x0800C14C — checks byte1 ∈ {2, 11, 12} |
| volUp | 9..14 | cluster at 0x0800C13E..0x0800C148 (likely vol/mode) |

(Mapping of LIRC button → sub-id derived from the IR-decoder's lookup table at `0x080116A0`: lookup index in that table directly becomes value byte 0 = button_id. The first 6 sub-handlers' addresses are read from the static disasm.)

## Press-tag (value byte 1) semantics

The IR-decoder at `0x0800FE3E–0x0800FE83` sets the press-tag based on press duration / repeat state:

| tag | observed from disasm |
|---:|---|
| 2 | normal / first press (`movs r0, #2` at 0x0800FE3E) — what we captured |
| 4 | timer-based variant (set at 0x0800FE66 if r4 < 0x3E8 ms threshold met) |
| 6 | timer-based variant (set at 0x0800FE70) |
| 8 | timer-based variant (set at 0x0800FE7C) |
| 11 | repeat-while-held (set at 0x0800FE4C if previous-cmd matches AND elapsed < 0x3E8) |
| 12 | terminal/release marker (default fallthrough at 0x0800FE80) |

Most simulator usage should use **tag=2** for "single press."

## Patch state (firmware_29 series)

To capture IR without HardFaulting the bar:

- `firmware_25_nop-ir-power-post.bin`: NOPs `bl post_event_type0` at `0x0800BFAA` (would-be standby trigger from sub=1 of an older / unused dispatch path).
- `firmware_29_notify-trap-v2.bin`: fw_25 + the notify-trampoline (single-slot log at `0x20003E00`/`0x20003E04`).

## Chassis controls (not via IR)

The bar has **one tactile chassis button: SUB PAIRING** (5-sec hold). Independent GPIO read; does NOT route through `notify()`. Cyan-fast-blinking LED is the visible state.

Two BT modules: generic (`btIn` source) and proprietary (wireless subwoofer = SUB PAIRING).
