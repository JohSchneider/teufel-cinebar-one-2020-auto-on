# IR command mapping — Teufel Cinebar One

Static-RE-derived mapping of the bar's command-dispatcher (jump table at `0x0800BCE6`) to the 14 IR remote buttons documented in `teufel_remote.lircd.conf` (and confirmed against the printed manual).

## Architecture recap

The bar has a dedicated **command-dispatch task** at `0x0800BCAC` (a separate RTX5 thread from `event_loop_thread`). The IR decoder (location not yet found — see task #58 status) builds messages of the form `{cmd_id, value}` and posts them via `notify(channel, value)` to the queue this task drains.

Inside the task:
```
0x0800BCD2:  bl osMessageQueueGet         ; wait for command msg
0x0800BCDA:  ldr r1, [sp, #4]              ; r1 = msg ptr
0x0800BCDC:  ldrb r0, [r1, #0]             ; r0 = cmd_id (msg.byte[0])
0x0800BCDE:  ldr r5, [r1, #4]              ; r5 = msg.word[1] (sub_param)
0x0800BCE2:  bl 0x80108e2                   ; dispatch via inline jump table @ 0x0800BCE6
```

Case 5–9 all redirect to `0x0800BD78` (no-op exit) — reserved/unused IDs.

## LED color → source (from the manual)

This gives us a **visual confirmation oracle** for the source-select sub-indices: fire each `src_*` via `simulate_ir.sh`, watch the LED color, match.

| Color | Meaning |
|---|---|
| Red | Standby |
| **Green** | **AUX IN** selected |
| **White** | **HDMI** selected |
| **Purple** | **OPTICAL** selected |
| **Blue** | **Bluetooth** selected |
| Blue, slow pulsing | Waiting for BT connection |
| Blue, fast blinking | Waiting for BT pairing |
| Orange | Playing Dolby audio |
| Cyan, fast blinking | Waiting for wireless subwoofer connection |

## All 14 IR codes (from lircd.conf, NEC 32-bit)

| Name | NEC code | cmd_id | sub-param | Confidence |
|---|---|---:|---:|---|
| **power** | `0x40BFB847` | **2** | 0 | ★★★ verified live |
| optIn (Optical) | `0x40BFC03F` | 4 | ? (one of 0-3) | ★★ verified-pattern (4-way + 4 LED literals at `0x800C0B0..0xBC`) |
| auxIn (AUX) | `0x40BF609F` | 4 | ? | ★★ |
| hdmiIn (HDMI) | `0x40BF20DF` | 4 | ? | ★★ |
| btIn (Bluetooth) | `0x40BF40BF` | 4 | ? | ★★ |
| modeMusic | `0x40BF10EF` | 1 | ? (one of 1-4) | ★★ verified-pattern (sub-dispatch on `r5∈{1,2,3,4}` matches 4 modes ★ INCLUDING modeExtend) |
| modeMovie | `0x40BF02FD` | 1 | ? | ★★ |
| modeVoice | `0x40BFA45B` | 1 | ? | ★★ |
| **modeExtend** (stereo widening) | `0x40BF708F` | 1 | ? | ★★ NEW — was missed before; 4-mode dispatch now makes perfect sense |
| **mute** | `0x40BF7887` | 0 OR 10 OR 13? | ? | ★ candidate (cmd_id=0 simple LED change is mute-like; cmd_id=13 single-action also plausible) |
| volUp | `0x40BF18E7` | 11 or similar | ? | ★ short-branch handler region (0x0800BEE2-BF0A) |
| volDown | `0x40BF629D` | 12 or similar | ? | ★ |
| bassUp | `0x40BFD02F` | 13 or 10 | ? | ★ |
| bassDown | `0x40BF50AF` | 14 or 10 | ? | ★ |

**To pin down with certainty**: use `gdb/simulate_ir.sh` from your local machine to fire each candidate `(cmd_id, sub)` pair and observe the bar's response (LED color, audible mode change, volume). The LED-color table above maps each source unambiguously.

## Unmapped cmd_ids (probably non-IR)

| cmd_id | Handler | Likely role |
|---:|---|---|
| 0 | `0x0800BD0E` | small LED-change at `0x800c0d0` — possibly **mute** OR a UART/BT status command |
| 3 | `0x0800BDEE` | loads 16-byte struct from `0x800C0D4` (3 fn-ptrs + `0xBB8`=3000 ms delay) — probably a multi-step UART/BT-only command (factory reset, sleep timer) |
| 10 | `0x0800BE7A` | r5∈[0,7] + tick-delta long-press check — possibly **vol or bass with hold-to-repeat** OR a UART/BT preset selector |
| 15 | `0x0800BEDA` | branches to no-op exit |

Cases 5–9 are all `b 0x800c466` (immediate function return).

## State-struct readers (used by case handlers)

These accessors at `0x200025DC` were the key to mapping case behaviors:

| Address | Returns |
|---|---|
| `0x0800A9A8` | `state[+3]` = source (vEEPROM key `0x1111`) |
| `0x0800A9B4` | `state[+2]` |
| `0x0800A9C0` | `state[+0]` = power state (1=standby, 2=active) |
| `0x0800A9CC` | `state[+4]` (vEEPROM key `0x4444`) |
| `0x0800A9D8` | `state[+1]` = volume (vEEPROM key `0x2222`) |

## Chassis controls (not via IR)

The bar has **exactly one tactile chassis button: SUB PAIRING** (5-sec hold). This is read independently from a GPIO; it does NOT route through `notify()`/dispatch. The "long-press" pattern in cmd_id=10 is therefore NOT this — it's likely a remote hold/repeat for vol or bass.

Two BT modules are present: a generic one for phone audio (the `btIn` source) and a proprietary one for the wireless subwoofer (the chassis-button pairing target). The cyan-fast-blinking LED indicates waiting-for-sub-pairing.

## Verifying / completing the mapping — use `gdb/simulate_ir.sh`

```bash
./gdb/simulate_ir.sh power                # power toggle (★★★ verified)
./gdb/simulate_ir.sh src_opt              # bar LED should turn PURPLE (OPTICAL)
./gdb/simulate_ir.sh src_aux              # bar LED should turn GREEN (AUX)
./gdb/simulate_ir.sh src_hdmi             # bar LED should turn WHITE (HDMI)
./gdb/simulate_ir.sh src_bt               # bar LED should turn BLUE (Bluetooth)

./gdb/simulate_ir.sh mode_music           # audio change (subtle) — Music mode
./gdb/simulate_ir.sh mode_movie           # audio change — Movie mode
./gdb/simulate_ir.sh mode_voice           # audio change — Voice mode
./gdb/simulate_ir.sh mode_extend          # audio change — stereo widening (NEW)

./gdb/simulate_ir.sh raw 0 0              # try cmd_id 0 — mute?
./gdb/simulate_ir.sh raw 10 1             # try cmd_id 10 — vol/bass?
./gdb/simulate_ir.sh raw 11 1             # try cmd_id 11
# ...etc for raw 12, 13, 14
```

The expected results above were checked against the manual's LED color table; each match either CONFIRMS the sub-index → button assignment or REVEALS that the order is different. Update this doc as you discover.
