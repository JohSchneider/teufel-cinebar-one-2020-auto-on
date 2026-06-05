# Goal #1 — Teufel Cinebar One Auto-On at AC Power

## Status: ✅ COMPLETE

Patched firmware: `firmware_05_autoboot-active-on-power.bin`

## What the patch does

The Teufel Cinebar One normally boots into standby (red LED) and waits for IR
remote / button input to wake. This patch makes the bar transition into the
active state automatically at boot, while preserving the original IR remote
behavior.

## How it works

The firmware runs an event-loop thread (function at `0x0800ACA4`) that
processes button/IR/state events. On a real "power on" IR press, the thread:

1. Receives a message from its queue
2. Calls `transition_state(2)` at `0x0800A740` — does GPIO writes, DSP wake,
   vEEPROM persistence, etc.
3. Calls `notify(0, return_value)` at `0x0800BBDC` — broadcasts the state
   change to other threads (LED display, etc.)

The patch hijacks the thread's `bl 0x0800AE78` instruction (its 2nd init call,
at flash address `0x0800ACAC`) and redirects to a 22-byte shim in unused
patch flash. The shim:

1. Runs the original `bl 0x0800AE78` (preserves thread init)
2. Calls `transition_state(2)` (the same call IR-power would make)
3. Calls `notify(0, return_value)` (the same notify IR-power would do)
4. Returns to the thread, which then enters its normal queue-wait loop

Net result: bar boots straight to active state. IR toggle continues to work
in both directions afterward.

## Patch bytes

Apply to `firmware_01_original-dump.bin` (verified extraction with RDP=AA):

### Patch 1 — 22-byte shim at flash `0x0801E800` (file offset `0x1E800`)

```
00 b5 ec f7 39 fb 02 20 eb f7 9a ff 01 46 00 20 ed f7 e4 f9 00 bd
```

Disassembly:
```
  +0   00 b5                push   {lr}            ; save thread return
  +2   ec f7 39 fb          bl     0x0800AE78      ; original init 2
  +6   02 20                movs   r0, #2
  +8   eb f7 9a ff          bl     0x0800A740      ; transition_state(2)
  +C   01 46                mov    r1, r0          ; r1 = return value
  +E   00 20                movs   r0, #0          ; r0 = channel 0
 +10   ed f7 e4 f9          bl     0x0800BBDC      ; notify(0, retval)
 +14   00 bd                pop    {pc}            ; return to thread
```

### Patch 2 — 4-byte BL redirect at flash `0x0800ACAC` (file offset `0x0ACAC`)

```
was:  00 f0 e4 f8     bl   0x0800AE78
now:  13 f0 a8 fd     bl   0x0801E800   (= our shim)
```

## How to apply

```bash
cp firmware_01_original-dump.bin firmware_05_autoboot-active-on-power.bin

# Patch 1: shim at 0x1E800
printf '\x00\xb5\xec\xf7\x39\xfb\x02\x20\xeb\xf7\x9a\xff\x01\x46\x00\x20\xed\xf7\xe4\xf9\x00\xbd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x1E800)) conv=notrunc

# Patch 2: thread BL redirect at 0x0ACAC
printf '\x13\xf0\xa8\xfd' | \
    dd of=firmware_05_autoboot-active-on-power.bin bs=1 seek=$((0x0ACAC)) conv=notrunc

# Flash via SWD
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_05_autoboot-active-on-power.bin verify reset exit 0x08000000"
```

## Verification (post-flash)

- Cold boot the bar (pull AC, restore AC):
  - LED transitions to **purple** without any IR/button input
  - After DSP boot delay (~few seconds), audio plays from active source
- IR remote power command still works:
  - Press → bar goes to red/standby
  - Press → bar goes back to purple/active
- All other IR commands (volume, source, etc.) work as normal

## Rollback

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
    -c "program firmware_01_original-dump.bin verify reset exit 0x08000000"
```

## Key reverse-engineering anchors

These addresses were the critical static-RE / live-debug findings that
unlocked the patch:

| Address      | Role                                                 |
| ------------ | ---------------------------------------------------- |
| `0x0800A740` | `transition_state(action)` — main state-change func  |
| `0x0800ACA4` | Event-loop thread entry                              |
| `0x0800AE78` | Thread's 2nd init call (we redirect via this BL)     |
| `0x0800BBDC` | `notify(channel, value)` — state-change broadcast    |
| `0x200025DC` | Global system state struct (state[0] = current power state) |
| `0x0801E800` | Unused flash, used as patch space                    |

The live-debug session (`mylog.txt`) showed `state[0]=3` being written at
`0x0800A760` when IR-power was triggered. That was the moment the patch
strategy crystallized.

## What's still open (Goal #2)

The user's secondary goal was auto-on-when-SPDIF-audio-appears. With Goal #1
making the bar always-on at AC, Goal #2 is functionally redundant unless the
user wants the bar to standby normally and only wake on SPDIF input (saving
power vs always-on). If pursued later, the path is:

1. Keep the audio rail powered in standby (find which GPIO gates it — likely
   on GPIOF or GPIOC based on r5/r7 in `transition_state`)
2. Configure EXTI4 on PA4 as a STOP-mode wake source (already wired in HW)
3. In the EXTI handler, post a queue message that the event loop will
   process as a "power on" event
