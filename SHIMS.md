# Cinebar One — Patch Shims

Patches sit in flash patch space (`0x0801E800`–`0x0801EFFF`, ~6 KB available)
plus a few in-place detours over original function bodies. The shims either
return via `pop {pc}` or tail-call the original target.

| # | Shim | Address | Size | Used by | Hook | Purpose |
|---|------|---------|------|---------|------|---------|
| 1 | Autoboot-to-active | `0x0801E800` | 22 bytes | fw_05, fw_08, fw_12, fw_22, fw_23, fw_24 | `bl 0x0800AE78` @ `0x0800ACAC` redirected | On boot, drive bar to active state and broadcast LED change |
| 2 | Wake-on-SPDIF wrapper | `0x0801E820` | 84 bytes | fw_22, fw_23, fw_24 | `bl 0x08008D74` (osMessageQueueGet) @ `0x0800ACBC` redirected | In standby idle, detect fiber-lights-up transition and post wake event |
| 3 | Force-mode wrapper | `0x0801E880` | 24 bytes | fw_23, fw_24 | both `bl transition_state` sites redirected (`0x0801E808`, `0x0800AD12`) | After every `→active` transition, call `set_audio_mode(N)` to override the DSP blob default |
| 4 | Notify-logging shim | `0x0801E8C0` | 56 bytes | fw_24 only | notify() prologue overwritten in-place at `0x0800BBDC` (detour to shim) | Log every `notify(channel, value)` call's `(channel, caller_lr)` to RAM ring buffer at `0x20003C00` |

Patch space is 4-byte aligned and ends well before flash limit. Plenty of room for additional shims if needed.

---

## Shim 1 — Autoboot-to-active  (`0x0801E800`, 22 bytes)

**Purpose**: When the bar boots, drive it directly into the active state (purple LED, audio output enabled) without waiting for an IR-on press. This is Goal #1.

**How it's hooked**: At `0x0800ACAC`, the BL site that originally called `0x0800AE78` (the original "init 2" function that reads various vEEPROM-stored config bytes into the state struct) is redirected to `0x0801E800`:

```
0x0800ACAC:  bl 0x0800AE78  →  bl 0x0801E800
```

In hex, the BL bytes change from `00 f0 e4 f8` to `13 f0 a8 fd`. The 4-byte BL encodes a PC-relative offset of `+0x13B50` to reach our shim.

**Where the BL sits**: inside `event_loop_thread` (which starts at `0x0800ACA4`). On every kernel start, event_loop_thread runs after `osKernelStart`, calls `0x0800A5C4` (system init), then this BL (formerly "init 2"). After this BL returns, event_loop enters its message-pump loop. So our shim runs **exactly once at startup**, on the event_loop thread context — guaranteed after `osKernelStart`, before any user input is processed.

**Annotated assembly**:

```
0x0801E800:  b5 00          push  {lr}                        ; save return → caller
0x0801E802:  f7 ec fb 39    bl    0x0800AE78                  ; original "init 2" — preserve
                                                              ;   reads various vEEPROM bytes
                                                              ;   into g_system_state. We must
                                                              ;   not skip this — the rest of
                                                              ;   event_loop relies on those bytes.
0x0801E806:  20 02          movs  r0, #2                      ; action = 2 (= "wake/active entry")
0x0801E808:  f7 eb ff 9a    bl    0x0800A740                  ; transition_state(2)
                                                              ;   runs path 1: state[0]=3,
                                                              ;   spdif_init, GPIO setup,
                                                              ;   DSP boot, vEEPROM persist,
                                                              ;   PA2 HIGH, finally state[0]=2.
                                                              ;   Returns: new state[0] = 2.
0x0801E80C:  46 01          mov   r1, r0                      ; r1 = retval (= 2)
0x0801E80E:  20 00          movs  r0, #0                      ; r0 = notify channel 0
0x0801E810:  f7 ed f9 e4    bl    0x0800BBDC                  ; notify(0, retval)
                                                              ;   broadcasts new state to all
                                                              ;   subscribers — most importantly
                                                              ;   the LED thread, which updates
                                                              ;   the LED to purple ("active").
0x0801E814:  bd 00          pop   {pc}                        ; return to caller (event_loop)
```

**Why the calls and arguments are exactly these**: this shim mirrors what happens during a normal IR-on press. The IR handler thread eventually posts a message with action=2; event_loop picks it up, calls `transition_state(2)` followed by `notify(0, retval)`. By doing those two calls ourselves at the right moment in boot, we make the bar behave as if the user pressed IR-on at AC restore — same code paths, same final state.

**Why we couldn't skip the original `bl 0x0800AE78`**: when fw_04 (earlier attempt) called `transition_state(2)` without first running `0x0800AE78`, the bar booted with audio on but LED stuck red. The vEEPROM reads inside `0x0800AE78` populate state struct fields that the LED-color decision logic reads. Skipping them leaves those fields zeroed, and the LED stays at whatever initial color.

**Stack discipline**: only `lr` is saved/restored. The three BLs are all standard AAPCS calls and preserve `r4-r11` themselves. Total stack delta inside the shim: 4 bytes (the saved lr). The shim is **leaf-safe** in the sense that we never use callee-saved registers we haven't saved.

**One-shot or recurring?** One-shot. After this BL returns, event_loop_thread continues into its message-pump loop and never re-enters this BL site. The bar can later cycle through active↔standby via IR or auto-standby, all driven by the normal state machine.

---

## Shim 2 — Wake-on-SPDIF wrapper  (`0x0801E820`, 84 bytes)

**Purpose**: When the bar is in standby (`state[0]==1`), detect when the Toslink fiber transitions from dark to lit (audio resumes) and post a wake event. This is Goal #2 Step 2.

**How it's hooked**: At `0x0800ACBC`, the BL to `osMessageQueueGet` (the call event_loop makes at the top of every loop iteration to poll for messages) is redirected to `0x0801E820`:

```
0x0800ACBC:  bl 0x08008D74  →  bl 0x0801E820
```

Bytes change from `f7 fe f8 5a` to `13 f0 b0 fd`. The shim acts as a **transparent wrapper** around `osMessageQueueGet` — it does its own work first, then calls the real `osMessageQueueGet`, then returns its result to event_loop. From event_loop's perspective, nothing has changed.

**Where the BL sits**: at the top of `event_loop_thread`'s message-pump loop (loop top is `0x0800ACB4`). Every iteration in **all** states (active, standby, intermediate) reaches this BL. With the bar idle in standby, the loop iterates every `osMessageQueueGet` timeout = 25 ticks = **25 ms**.

**State variable**: we store one byte at `0x20002506` (= autostandby_struct + 2). This is the "silence_seen" flag: 1 = shim saw fiber-dark in a recent poll; 0 = haven't seen silence since last wake or boot. Offset +2 of the autostandby struct is unused by all other firmware code (verified by grep).

**Annotated assembly**:

```
                          ;; Entry — preserve osMessageQueueGet's args + lr
0x0801E820:  b5 ff        push  {r0, r1, r2, r3, r4, r5, r6, r7, lr}
                          ; Saves osMessageQueueGet's args (r0-r3) so we can call
                          ; it with them intact later. Also saves callee-saved
                          ; r4-r7 (we use them as scratch) and the return address.

                          ;; Quick exit if not in standby — keeps active-state cost low
0x0801E822:  4c 11        ldr   r4, [pc, #68]                ; r4 = &g_system_state (0x200025DC)
0x0801E824:  78 20        ldrb  r0, [r4, #0]                  ; r0 = state[0]
0x0801E826:  28 01        cmp   r0, #1
0x0801E828:  d1 1a        bne   wrap_call                     ; not standby → straight to osMessageQueueGet
                          ; If state[0] != 1, the wake mechanism doesn't apply.
                          ; In active state (state[0]==2), auto_standby_check
                          ; handles things via its own BL further down in
                          ; event_loop. In intermediate states (3/4), do nothing.

                          ;; Standby path — sample PA4 16 times in a tight loop
0x0801E82A:  4d 10        ldr   r5, [pc, #64]                ; r5 = &g_auto_standby_state (0x20002504)
0x0801E82C:  4e 10        ldr   r6, [pc, #64]                ; r6 = &GPIOA->IDR (0x48000010)
0x0801E82E:  22 10        movs  r2, #16                       ; r2 = PA4 mask (1<<4 = 0x10)
0x0801E830:  68 33        ldr   r3, [r6, #0]                  ; first sample
0x0801E832:  40 13        ands  r3, r2                        ; r3 = first PA4 (0 or 0x10)
0x0801E834:  24 00        movs  r4, #0                        ; r4 = toggled flag
0x0801E836:  21 0F        movs  r1, #15                       ; r1 = 15 more samples to take

poll_loop:
0x0801E838:  68 30        ldr   r0, [r6, #0]                  ; next sample
0x0801E83A:  40 10        ands  r0, r2                        ; r0 = next PA4 (0 or 0x10)
0x0801E83C:  42 98        cmp   r0, r3
0x0801E83E:  d0 00        beq   next_iter                     ; same as first → still monotone
0x0801E840:  24 01        movs  r4, #1                        ; differed → set toggled flag
next_iter:
0x0801E842:  39 01        subs  r1, #1
0x0801E844:  d1 f8        bne   poll_loop                     ; loop until r1 = 0

                          ;; Why 16 samples? At ~5 MHz biphase data rate, even
                          ;; very fast successive IDR reads catch enough toggles.
                          ;; The 16-sample window is short enough that timing
                          ;; overhead is negligible (<10 µs even with bus latency)
                          ;; and long enough to debounce against the occasional
                          ;; noise glitch that earlier truth tables showed (e.g.,
                          ;; one "42/100" reading during a stable muted state).

                          ;; Branch on the result
0x0801E846:  2c 00        cmp   r4, #0
0x0801E848:  d1 02        bne   saw_toggling                  ; fiber lit with data

monotone_path:
                          ;; Fiber dark (cable unplugged OR source muted).
                          ;; Mark that we've seen silence so a later transition
                          ;; back to toggling counts as fresh audio.
0x0801E84A:  20 01        movs  r0, #1
0x0801E84C:  70 a8        strb  r0, [r5, #2]                  ; silence_seen = 1
0x0801E84E:  e0 07        b     wrap_call

saw_toggling:
                          ;; Fiber is lit and carrying data. The question is
                          ;; whether this is "fresh audio" (after silence) or
                          ;; "we IR-offed while audio was still playing" (in
                          ;; which case the user explicitly chose standby and
                          ;; we should NOT wake).
0x0801E850:  78 a8        ldrb  r0, [r5, #2]                  ; r0 = silence_seen
0x0801E852:  28 00        cmp   r0, #0
0x0801E854:  d0 04        beq   wrap_call                     ; never saw silence → no wake
                          ; This is the gate that fixes fw_14's wake-loop bug.

                          ;; Silence_seen was 1 AND PA4 is toggling now =
                          ;; silence→audio transition. Time to wake the bar.
0x0801E856:  20 00        movs  r0, #0
0x0801E858:  70 a8        strb  r0, [r5, #2]                  ; reset silence_seen
0x0801E85A:  20 02        movs  r0, #2                        ; action = 2 (wake)
0x0801E85C:  f7 ec f9 50  bl    0x0800AB00                    ; post_event_type0(2)
                          ; Posts a {type=0, action=2} message to event_loop's
                          ; queue. Next iteration of event_loop (right after
                          ; we return to it), osMessageQueueGet will receive
                          ; this message, and event_loop will dispatch it as
                          ; transition_state(2) → bar wakes to active.

wrap_call:
                          ;; Whatever path we took, now we need to call the
                          ;; real osMessageQueueGet on event_loop's behalf.
                          ;; Restore the original args (r0-r3), call it, return.
0x0801E860:  bc ff        pop   {r0, r1, r2, r3, r4, r5, r6, r7}
                          ; r0-r3 restored to original osMessageQueueGet args.
                          ; lr left on the stack (will be popped at the end).

0x0801E862:  f7 ea fa 87  bl    0x08008D74                    ; the real osMessageQueueGet
                          ; This blocks for up to 25 ticks (25 ms) or returns
                          ; immediately if a message is in the queue. If we
                          ; just posted a wake event above, this call will
                          ; receive it now, and event_loop will see the
                          ; familiar r0 = 0 (success) path and dispatch it.

0x0801E866:  bd 00        pop   {pc}                          ; return to event_loop
                          ; pops the lr from the stack into PC.

                          ;; Literal pool (4-byte aligned)
0x0801E868:  dc 25 00 20  .word 0x200025DC                    ; g_system_state
0x0801E86C:  04 25 00 20  .word 0x20002504                    ; g_auto_standby_state
0x0801E870:  10 00 00 48  .word 0x48000010                    ; &GPIOA->IDR
```

**Stack discipline**: 9 words (36 bytes) saved at entry, 9 words popped at exit (8 in `pop {r0-r7}`, 1 in `pop {pc}`). Between the two pops, `bl osMessageQueueGet` clobbers `lr` but leaves the stack untouched, so the saved lr is still where `pop {pc}` expects it. Net stack delta of the shim: zero (as expected for a non-leaf function).

**Why wrap `osMessageQueueGet` and not `auto_standby_check`?** Earlier attempts (fw_14, fw_15, fw_16, fw_18) hijacked the BL to `auto_standby_check` at `0x0800ACCA`. To reach that BL in standby state, those attempts had to NOP a BNE at `0x0800ACC8` that originally redirected the flow back to the loop top for non-active states. NOPping the BNE caused a downstream side effect (the post-shim periodic-timer code, including a `state[8]=10` write and conditional BLs, was now running in standby) that triggered an error LED chain. Wrapping `osMessageQueueGet` instead lets us run our wake check on **every** loop iteration in **every** state, with no BNE NOPs and no exposure of the post-shim code in standby. The BNE stays intact, and the post-shim code keeps its original behavior of running only in active state.

**Why this design avoids the wake-loop**: the `silence_seen` gate (state byte at `0x20002506`). Without that gate, a level-triggered "PA4 toggling → wake" would re-wake the bar immediately every time the user IR-off'd while the SPDIF source was still playing. The gate requires us to observe a silent period first, so an explicit IR-off-with-audio-still-playing results in `silence_seen` staying at 0 → no wake. Only after the source actually goes quiet (mute, unplug, TV off) does the next "fiber lights up" event qualify as a wake trigger.

**Why polling and not EXTI**: PA4 toggles at SPDIF biphase rate (~5 MHz for 44.1 kHz audio). Enabling EXTI line 4 with PA4 as source would generate IRQs at that rate, saturating the Cortex-M0. Polling 16 samples once per 25 ms loop iteration is the right scale for this signal.

---

## Shim 3 — Force-mode wrapper  (`0x0801E880`, 24 bytes)

**Purpose**: After every `→active` transition (cold boot, IR-on-from-standby, wake-on-SPDIF), call `set_audio_mode(N)` to override whatever audio mode the DSP blob defaults to. Used for A/B audio-mode testing (Music/Movie/Voice). Forced mode is encoded in a single byte of the wrapper — buildable as fw_23/24/25 via `build_fw_force-mode.py` (mode 0/1/2 respectively).

**How it's hooked**: There are exactly **two** `bl transition_state` call sites in the firmware:
- `0x0801E808` — inside Shim 1 (autoboot path)
- `0x0800AD12` — inside the event-loop dispatch (IR-on and wake-on-SPDIF path)

Both are redirected from `transition_state @ 0x0800A740` to this wrapper at `0x0801E880`. The wrapper calls the original, then conditionally calls `set_audio_mode(N)` only if the transition action was `2` (active), avoiding the I²C call during `→standby`.

**Wrapper disassembly**:
```
0x0801E880: push  {r4, r5, lr}            ; b5 30
0x0801E882: mov   r4, r0                   ; 46 04   ; r4 = action (preserved across BL)
0x0801E884: bl    0x0800A740               ; eb f7 5c ff  transition_state(action)
0x0801E888: mov   r5, r0                   ; 46 05   ; r5 = retval
0x0801E88A: cmp   r4, #2                   ; 2c 02
0x0801E88C: bne.n  skip                    ; d1 01
0x0801E88E: movs  r0, #N                   ; 20 NN   ; ★ MODE BYTE (0/1/2)
0x0801E890: bl    0x0800C560               ; ed f7 66 fe  set_audio_mode(N)
                                            ; skip:
0x0801E894: mov   r0, r5                   ; 46 28   ; restore retval
0x0801E896: pop   {r4, r5, pc}             ; bd 30
```

**Key fact**: byte at flash file-offset `0x1E88E` is the mode immediate. Patch that single byte to `0x00` for Music, `0x01` for Movie, `0x02` for Voice — no other changes needed to switch a built variant.

**Side-tool**: `gdb/switch_mode.sh` switches modes live via GDB without reflashing — it just halts the bar, manually invokes `set_audio_mode(N)` via register manipulation + a BKPT trampoline at RAM `0x20002000`, and resumes. Doesn't depend on Shim 3 being present (works against any fw_22+ binary).

---

## Shim 4 — Notify-logging shim  (`0x0801E8C0`, 56 bytes)

**Purpose**: Capture every `notify(channel, value)` call into a RAM ring buffer for offline analysis. Used to locate the IR decoder by finding which call site posts `notify(channel=2, ...)` for the IR-power button. Operating principle: no GDB breakpoints, no CPU halts — the shim runs inline as a function-call overhead added to notify, so the bar's timing is undisturbed (IR decoder works normally).

**How it's hooked**: notify's first 4 instructions (8 bytes at `0x0800BBDC`) are overwritten with an in-place detour:
```
0x0800BBDC: ldr   r3, [pc, #0]              ; 4b 00
0x0800BBDE: bx    r3                         ; 47 18
0x0800BBE0: .word 0x0801E8C1                ; (= Shim 4 addr | Thumb bit)
```

The `ldr`+`bx` sequence preserves LR (unlike a BL would), so when Shim 4 chains to `notify+8`, the original caller_return is still in LR for the eventual `pop {pc}` to use.

**Shim 4 disassembly** (replicates notify's first 4 instructions, then logs, then tail-jumps to `notify+8`):
```
0x0801E8C0: push  {r3, r4, r5, r6, r7, lr}  ; b5 f8   ; original push
0x0801E8C2: ldr   r4, [pc, #40]              ; 4c 0a   ; r4 = 0x200023BC (g_notify_struct)
0x0801E8C4: mov   r5, r1                     ; 46 0d   ; (original mov r5, r1)
0x0801E8C6: mov   r6, r0                     ; 46 06   ; (original mov r6, r0)
;; --- logging start ---
0x0801E8C8: ldr   r0, [pc, #36]              ; 48 09   ; r0 = 0x20003C00 (log buf)
0x0801E8CA: ldr   r1, [r0, #0]               ; 68 01   ; r1 = idx
0x0801E8CC: cmp   r1, #63                    ; 29 3F
0x0801E8CE: bls.n  no_wrap                   ; d9 01
0x0801E8D0: movs  r1, #0                     ; 21 00   ; wrap idx
                                              ; no_wrap:
0x0801E8D2: lsls  r2, r1, #3                 ; 00 ca   ; r2 = idx*8
0x0801E8D4: adds  r2, #4                     ; 32 04   ; r2 = idx*8 + 4
0x0801E8D6: add   r2, r0                     ; 44 02   ; r2 = buf + idx*8 + 4
0x0801E8D8: str   r6, [r2, #0]               ; 60 16   ; entry.channel = r6
0x0801E8DA: mov   r3, lr                     ; 46 73   ; r3 = caller_return
0x0801E8DC: str   r3, [r2, #4]               ; 60 53   ; entry.lr = r3
0x0801E8DE: adds  r1, #1                     ; 31 01   ; idx++
0x0801E8E0: str   r1, [r0, #0]               ; 60 01   ; save idx
;; --- logging end; tail-jump ---
0x0801E8E2: mov   r0, r6                     ; 46 30   ; restore r0 = channel
0x0801E8E4: mov   r1, r5                     ; 46 29   ; restore r1 = value
0x0801E8E6: ldr   r2, [pc, #16]              ; 4a 04   ; r2 = notify+8 thumb addr
0x0801E8E8: bx    r2                         ; 47 10   ; jump (LR untouched)
;; literal pool:
0x0801E8EC: .word 0x200023BC                 ; g_notify_struct (orig ldr r4 target value)
0x0801E8F0: .word 0x20003C00                 ; log buffer base
0x0801E8F4: .word 0x0800BBE5                 ; notify+8 with Thumb bit
```

**RAM ring buffer** at `0x20003C00`:
- offset 0: `u32 idx` (write pointer, wraps at 64; bounded by `cmp #63; bls; movs r1, #0`)
- offset 4 + i*8: `u32 channel; u32 caller_lr` for entry i ∈ [0, 64)

Total RAM used: 4 + 64×8 = **516 bytes**. Buffer is in the high RAM region (STM32F072CBT6 has 16 KB ending at `0x20004000`); 516 bytes at `0x20003C00` ends at `0x20003E04` — within RAM, and the user has not reported issues with stack collision at this address.

**Idx initialization**: not explicitly zeroed; if the RAM happens to hold a value > 63 at boot, the first call's bound check resets idx to 0. So the buffer is self-healing on cold boot.

**Reader**: `gdb/read_ir_log.sh` halts the bar briefly, reads idx + all 64 entries, and pretty-prints non-empty ones. The bar continues normally afterward.

---

## Patch space layout (cumulative, fw_24)

```
0x0801E800 ┌──────────────────────────────────────────┐
           │ Shim 1: Autoboot-to-active                │ 22 bytes (fw_05+)
0x0801E816 ├──────────────────────────────────────────┤
           │ 0xFF padding (10 bytes)                   │
0x0801E820 ├──────────────────────────────────────────┤
           │ Shim 2: Wake-on-SPDIF wrapper             │ 84 bytes (fw_22+)
0x0801E874 ├──────────────────────────────────────────┤
           │ 0xFF padding (12 bytes)                   │
0x0801E880 ├──────────────────────────────────────────┤
           │ Shim 3: Force-mode wrapper                │ 24 bytes (fw_23+)
0x0801E898 ├──────────────────────────────────────────┤
           │ 0xFF padding (40 bytes)                   │
0x0801E8C0 ├──────────────────────────────────────────┤
           │ Shim 4: Notify-logging shim               │ 56 bytes (fw_24)
0x0801E8F8 ├──────────────────────────────────────────┤
           │ 0xFF padding (rest, ~5.7 KB)              │
0x0801FFFF └──────────────────────────────────────────┘
```

When the user's `firmware_02_swd-write-test.bin` wrote `DEADBEEF` at `0x1FF00` to verify SWD write/read, it landed within this region (the patch space starts at `0x1E800`). That test confirmed both that we can write here and that the bar still works after a flash — it's also our rollback verification target (re-flash baseline → `0x1FF00` reverts to `0xFFFFFFFF`).

## RAM usage by all shims

| Address | Bytes | Description | Set by |
|---------|------:|-------------|--------|
| `0x20002506` | 1 | `silence_seen` flag (1 = silence observed in standby; 0 = haven't seen silence yet) | Shim 2 |
| `0x20002000` | 2 | BKPT trampoline used by `switch_mode.sh` (NOT firmware-resident; written by GDB only) | gdb/switch_mode.sh |
| `0x20003C00` | 516 | IR log: `u32 idx` + 64 entries × `(u32 channel, u32 caller_lr)` | Shim 4 |
