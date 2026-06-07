# Teufel Cinebar One — Reverse-Engineered Symbols

Consolidated reference of every named function, variable, and structure we
identified during the RE work. Use as a Ghidra label sheet, GDB cheat-sheet,
or just as a map for future work.

Target:  **STM32F072CBT6** (Cortex-M0, 128 KB flash, 16 KB RAM, LQFP48)
Image:   `/tmp/firmware/firmware_01_original-dump.bin`, load at `0x08000000`, size `0x20000`
Build:   Keil RTX V5.2.3 (CMSIS-RTOS)

Confidence legend:
- ★★★ = confirmed by direct observation (live debug, or unambiguous static signal)
- ★★  = strong indirect evidence (multiple callers, expected call shape)
- ★   = inferred from context, plausible but not verified

---

## Boot / Reset / C runtime

| Address       | Conf | Symbol                            | Notes                                          |
| ------------- | ---- | --------------------------------- | ---------------------------------------------- |
| `0x08000000`  | ★★★  | `g_vector_table`                  | Cortex-M0 vector table, 48 entries (192 B)     |
| `0x080000D4`  | ★★★  | `Reset_Handler`                   | Entry: `LDR R0,=SystemInit; BLX R0; LDR R0,=__main; BX R0` |
| `0x080000C0`  | ★★   | `__main`                          | C runtime init (calls scatterload-like at `0x080001AC`) |
| `0x080001AC`  | ★★   | `__scatterload`                   | Copies `.data` initializers from flash to RAM  |
| `0x08002EA0`  | ★★★  | `SystemInit`                      | RCC/clock setup; called from Reset_Handler     |
| `0x080039D4`  | ★★★  | `main`                            | Hardware init phase; calls GPIO setup, module inits, then ends |
| `0x08010A52`  | ★★★  | `app_main`                        | (Entry at `0x08010A54`, no PUSH — runs to bkpt at end.) Does `osKernelInitialize`, creates threads, enables EXTIs, calls `osKernelStart` |
| `0x08010AA2`  | ★★★  | `app_main_kernel_start_site`      | The `bl` to `osKernelStart` wrapper inside app_main |
| `0x080000E6`  | ★★★  | `Default_Handler`                 | Infinite-loop trap (`b .`) used by all unused IRQ vectors |

### Vector table — known non-default entries

```
0x00  SP_init     = 0x20001CE8
0x04  Reset       = 0x080000D4
0x08  NMI         = 0x08002400
0x0C  HardFault   = 0x080020D8
0x2C  SVCall      = 0x08002DB4   ; RTX5 SVC dispatcher
0x38  PendSV      = 0x080027C4   ; RTX5 context switch
0x3C  SysTick     = 0x08002E34   ; RTX5 / firmware tick
0xBC  USB         = 0x08003988   ; (only application IRQ wired to a real handler)
0x40-0xB8         = 0x080000E6   ; all other IRQs → infinite-loop trap
```

---

## RTX5 RTOS

| Address       | Conf | Symbol                              | Notes                                       |
| ------------- | ---- | ----------------------------------- | ------------------------------------------- |
| `0x20002538`  | ★★★  | `osRtxInfo`                         | RTX5 kernel state struct. `state[8] = kernel state byte` (set to `2 = osKernelRunning` by osKernelStart at `0x08009A7C`). **Heavy write traffic** — do NOT watchpoint! |
| `0x08008C48`  | ★★★  | `osKernelGetState` (wrapper)        | SVC-or-direct dispatch wrapper. Reads `osRtxInfo.state` (byte at +8) |
| `0x08008C78`  | ★★   | `osKernelInitialize` (wrapper)      | Same SVC pattern; called from app_main if state==0 |
| `0x08008C9C`  | ★★   | `osKernelStart` (wrapper)           | SVC wrapper; never returns                  |
| `0x08009A40`  | ★★★  | `svcRtxKernelStart` (impl)          | Inside: sets CONTROL, then `state[8] = 2`   |
| `0x08009854`  | ★★   | `svcRtxKernelGetState` (impl)       | Pointed to by SVC dispatch (from R7 = `0x9855`) |
| `0x08009840`  | ★★   | `svcRtxKernelInitialize` (impl)     | Pointed to by SVC dispatch                  |
| `0x080097CC`  | ★★   | `osTimerNew` (wrapper)              | RTX5 timer creation                         |
| `0x080097A8`  | ★★   | `osTimerIsRunning`                  |                                             |
| `0x080097F0`  | ★★   | `osTimerStart`                      |                                             |
| `0x08009818`  | ★★   | `osTimerStop`                       |                                             |
| `0x08009784`  | ★★   | `osThreadNew` (wrapper)             | (Earlier mis-labeled as MessageQueueNew — corrected during RE.) |
| `0x08008CC0`  | ★    | `osMemoryPoolAlloc` (wrapper)       | Used inside `notify()`                      |
| `0x08008D74`  | ★★   | `osMessageQueueGet` (wrapper)       | Used by the event-loop thread               |
| `0x08008E10`  | ★★   | `osMessageQueuePut` (wrapper)       | Used inside `notify()`                      |
| `0x0800E1C4`  | ★★   | `osThreadNew_alt1`                  | Different create wrapper (used by thread creator) |
| `0x0800DFDC`  | ★★   | `osThreadNew_alt2`                  | Another create wrapper                       |
| `0x0800DEBC`  | ★★   | `osEventFlagsNew?`                  | Yet another RTX create wrapper              |
| `0x0800DE88`  | ★★   | `NVIC_SetPriority` (wrapper)        |                                             |
| `0x0800DE74`  | ★★★  | `__NVIC_EnableIRQ`                  | Standard CMSIS function (one of two copies in firmware) |
| `0x08000DF0`  | ★★★  | `__NVIC_EnableIRQ_v2`               | Second copy (different module)              |

### RTX5 named objects (from flash strings @ `0x0801E5B0`+)

| Name                | Attr struct addr | Notes                            |
| ------------------- | ---------------- | -------------------------------- |
| `"Mutex I2C System"` | `~0x08011690`   | Protects I²C bus access          |
| `"LED Timer"`       | `0x08011710`     | osTimerAttr_t (16B); callback at `0x08010068` |
| `"Mutex vEEPROM"`   | `0x08011E38`     | Protects vEEPROM emulation       |
| `"CEC RX"`          | string at `0x0801E5E0` | HDMI-CEC receive thread/event |
| `"CEC TX"`          | string at `0x0801E5E8` | HDMI-CEC transmit             |

---

## Application state machine

### Functions

| Address       | Conf | Symbol                            | Signature / notes                           |
| ------------- | ---- | --------------------------------- | ------------------------------------------- |
| `0x0800A740`  | ★★★  | `transition_state`                | `uint8_t transition_state(uint8_t action)`. **The power-toggle dispatch.** action=2 from current=1 → intermediate state 3, settles at state 2 (active); action=1 from current=2 → intermediate state 4, settles at state 1 (standby). Does GPIO writes, vEEPROM persist, DSP control. Called only from `0x0800AD12`. |
| `0x0801041C`  | ★★★  | `is_audio_active`                 | `uint8_t is_audio_active(void)` — reads `(GPIOA->IDR >> 3) & 1` via the GPIO-read helper at `0x0800D654`. The firmware reads PA3, but **PA3 is dead-wired in this firmware** (bench truth table 2026-06-06: PA3 reads LOW in all 6 active/standby × audio scenarios). So `is_audio_active()` always returns 0. Actual SPDIF activity is on **PA4**, which the firmware doesn't read. The auto_standby_check silent path (which requires return=1) therefore never fires; auto-standby triggers via a different mechanism. |
| `0x08011524`  | ★★★  | `auto_standby_check`              | `uint8_t auto_standby_check(void)`. Tracks tick-since-last-mode-change. Calls `is_audio_active` + `osKernelGetTickCount`. State at RAM `0x20002504`: `[+0]=return code (0/1/2/4), [+1]=last mode, [+8]=last change tick`. Returns 2 when mode==1 (silent) sustained for `> 0x3E8 = 1000 RTX5 ticks (≈1 second)`. The outer timeout (the "couple of minutes" the user observed) is somewhere upstream that probably counts these 1-second pulses. |
| `0x0800D66C`  | ★★★  | `osKernelGetTickCount`            | Returns `osRtxInfo[12]` (RTX5 millisecond tick) |
| `0x0800D654`  | ★★★  | `GPIO_ReadPins`                   | `uint32_t GPIO_ReadPins(GPIO_TypeDef *port, uint32_t pin_mask)` — reads input register, returns `(IDR & mask)` non-zero if any masked bit is set. |
| `0x0800D65E`  | ★★★  | `GPIO_WriteBit`                   | (corrected — used by transition_state for audio-rail writes) |
| `0x0800A760`  | ★★★  | `transition_state.set_state_3`    | The `strb r0, [r4, #0]` that writes `state[0]=3`. (Watchpoint target — confirmed live.) |
| `0x0800A802`  | ★★★  | `transition_state.set_state_4`    | Mirror: writes `state[0]=4` in the other path |
| `0x0800ACA4`  | ★★★  | `event_loop_thread`               | Main UI/event-handling RTX thread. Entry passed to `osThreadNew` at file `0x10262`. Reads queue, dispatches via transition_state, notifies via `notify()`. |
| `0x0800ACA8`  | ★★★  | `event_loop_thread.init1`         | `bl 0x0800A5C4` |
| `0x0800ACAC`  | ★★★  | `event_loop_thread.init2_BL`      | `bl 0x0800AE78` — **this is the BL we hijack for Goal #1 patch** |
| `0x0800ACBC`  | ★★   | `event_loop_thread.queue_get`     | `bl osMessageQueueGet` — blocks the thread on its inbox |
| `0x0800AD12`  | ★★★  | `event_loop_thread.call_transition` | The one BL site to `transition_state`     |
| `0x0800AD16`  | ★★★  | `event_loop_thread.cache_retval`  | `strb r0, [r4, #0]` — caches return value somewhere |
| `0x0800AD1C`  | ★★★  | `event_loop_thread.call_notify`   | `bl 0x0800BBDC` — **the notify call we needed in Goal #1** |
| `0x0800BBDC`  | ★★★  | `notify`                          | `int notify(uint8_t channel, uint32_t value)`. Allocs from pool, fills `{channel byte, value u32}`, posts to a queue. Many callers (event handlers throughout). |
| `0x080115F8`  | ★★★  | `vEEPROM_set_default`             | `int vEEPROM_set_default(uint16_t key, uint16_t value)`. If key not yet persisted, writes default. |
| `0x080115F8`  | ★★   | (callee from app_main with args 0xFF00/49 and 0xFF01/5100) — sets default volume/timeout values |
| `0x0800CDFC`  | ★★   | `vEEPROM_read`                    | Internal vEEPROM read                       |
| `0x0800CEBC`  | ★★   | `vEEPROM_write`                   | Internal vEEPROM write                      |
| `0x0801164C`  | ★★   | `vEEPROM_module_init`             | Creates `"Mutex vEEPROM"`, calls sub-init   |
| `0x08008EB8`  | ★★   | `osMutexNew` (wrapper)            | Called from vEEPROM_module_init             |
| `0x0800CF94`  | ★★★  | `FLASH_PageErase`                 | `void FLASH_PageErase(uint32_t page_addr)`. Generic flash page erase; takes page address in R0. |
| `0x0800D340`  | ★★★  | `vEEPROM_erase_loop`              | Iterates over vEEPROM pages, calls FLASH_PageErase per page. Page size = 2048 (`1<<11`). |

### DSP control (Renesas D2-92634-LR via I²C2 — PB10/PB11 AF1)

| Address       | Conf | Symbol                            | Signature / notes |
| ------------- | ---- | --------------------------------- | ----------------- |
| `0x0800C4EC`  | ★★★  | `dsp_init_dispatcher`             | Called from `transition_state(2)`. Holds DSP reset (PF0=LOW), waits, releases, uploads the 30 KB DSP firmware blob via `0x0800CA70`, then post-init wait. Doesn't call `write_dsp_register` directly. |
| `0x0800C560`  | ★★★  | `set_audio_mode`                  | `void set_audio_mode(uint8_t mode)`. Dispatches `r0 ∈ {0=Music, 1=Movie, 2=Voice}`, writes 12 DSP registers `0x2E–0x39`. See `dsp_protocol.md` for the per-mode value matrix. Only callers in stock firmware: the source-switch handler at `0x0800A664`. fw_23's wrapper at `0x0801E880` adds it after every `→active` transition. |
| `0x0800C5F4`  | ★★    | per-mode preset constants         | Two 4-byte words: `0x00800001` (the "enable" magic) and `0x00A56208` (the Voice-mode coefficient). Loaded by `set_audio_mode`. |
| `0x0800C744`  | ★★    | master-output-gain loader         | At boot, reads a value from vEEPROM via `0x0800CF54`, writes it (via `write_dsp_register`) to DSP regs `0xE4–0xE7`. Bench-traced value = `0xFFFFFB` (= -5 in 24-bit signed). Candidate for "patch the amp headroom" experiment (task #60). |
| `0x0800C7A0`  | ★★★  | bass-or-limiter writer            | Clamps r0 to `[-14, 0]`, persists to vEEPROM, writes to DSP regs `0x0F` and `0xE9`. Called only from event-6 handler (`0x0800A858`) with payload-dependent values {-3, 0, 2}. Either bass-cut or limiter — disambiguation pending. |
| `0x0800CA70`  | ★★★  | `dsp_blob_uploader`               | `int dsp_blob_uploader(void *buf, size_t len)`. Wrapper for `HAL_I2C_Mem_Write` to DSP slave `0x88` (= 7-bit `0x44`), memory address 0, 16-bit address size. Uploads the 30,661-byte blob at flash `0x08011E48`. |
| `0x0800CAA0`  | ★★★  | `write_dsp_register`              | `int write_dsp_register(uint32_t reg_24b, uint32_t val_24b)`. Builds a 6-byte buffer (3-byte BE addr + 3-byte BE value) and calls `0x0800FBC4` (mutex-guarded I²C TX). DSP runtime slave addr = `0xB2` (= 7-bit `0x59`). **56 call sites** in stock firmware. |
| `0x0800FBC4`  | ★★    | `i2c2_mutex_tx`                   | Generic mutex-guarded I²C2 write. Pushes I²C2 mutex handle, calls `HAL_I2C_Master_Transmit @ 0x0800D93C`. |

### State-struct readers (4 small accessors at 0x0800A9A8 onwards)

Tiny one-shot bx-lr functions; each loads a literal struct ptr and reads one byte. They're called frequently from the command-dispatcher's case handlers, so identifying them was the key to mapping IR cmd_ids.

| Address | Returns | vEEPROM key (if any) |
|---|---|---|
| `0x0800A9A8` | `state[+3]` = source select | 0x1111 |
| `0x0800A9B4` | `state[+2]` | — |
| `0x0800A9C0` | `state[+0]` = power state (1=standby, 2=active, 3/4=transitioning) | — |
| `0x0800A9CC` | `state[+4]` | 0x4444 |
| `0x0800A9D8` | `state[+1]` = volume | 0x2222 |

### Notify → command-dispatch path

`notify(channel, value)` queues `{channel byte, value u32}` messages onto a queue stored at `*(g_notify_struct+12) = *(0x200023C8)`. Two consumers:

| Consumer | Address | Role |
|---|---|---|
| `event_loop_thread` | `0x0800ACA4` | (main; reads from a DIFFERENT queue) |
| `command_dispatch_thread` | `0x0800BCAC` | Reads notify-queue messages, dispatches by `msg.byte[0]` (= channel) via inline jump table at `0x0800BCE2`. IR events arrive here. |

The IR-decoder calls `notify(cmd_id, value)` with the cmd_id encoding which button was pressed. **The complete IR-to-cmd_id map has been recovered via static disasm of the command-dispatcher's case handlers** — see `IR_CODES.md`. Headline: Power = cmd_id 2 (★ verified live), 4 sources = cmd_id 4 with sub-param 0–3, 3 modes = cmd_id 1 with sub-param 1–3, vol/bass = cmd_ids 11–14.

### Key hardware-pin mappings (★ verified)

| Pin | Role | Read/written by |
| --- | ---- | --------------- |
| **PA3** | Reads always LOW (dead-wired in this firmware) | `is_audio_active()` @ `0x0801041C` reads it but always returns 0; bench truth table confirmed |
| **PA4** | ★ Actual SPDIF data carrier (firmware doesn't read it) | Reads HIGH (toggling at biphase rate) only in active+plugged+playing; LOW elsewhere |
| **PC15** | Audio rail enable (HIGH = active, LOW = standby) | `transition_state` writes via `GPIO_WriteBit(GPIOC, 0x8000, val)` at `0x0800A776` (HIGH) and `0x0800A836` (LOW) |
| **PF0** | DSP reset (active LOW: LOW = held in reset) | `transition_state` writes via `GPIO_WriteBit(GPIOF, 0x0001, val)` at `0x0800A76C`/`0x0800A828` (LOW) and `0x0800A7F0` (HIGH) |
| **PB11** | I²C2 SDA (AF1) — DSP control bus | configured by `HAL_GPIO_Init` call at `0x0800F068` |
| **PA1** | (?) IR receiver — VeryHigh speed Input | configured by `HAL_GPIO_Init` call at `0x0800B456`; not yet hardware-verified |

### transition_state side-effect map

Path 1 (going active, action=2, current=1):
1. `state[0] = 3` (intermediate)
2. `bl 0x08011500` → `spdif_subsystem_init` (writes PA2=LOW, reconfigs PA2/PA3, resets cached SPDIF state)
3. `GPIO_WriteBit(GPIOF, 0x0001, 0)` — PF0 LOW: assert DSP reset
4. `GPIO_WriteBit(GPIOC, 0x8000, 1)` — PC15 HIGH: audio rail ON
5. 50 ms delay (`bl 0x0800D334`)
6. RCC bit 21 write to enable some peripheral clock
7. Module inits: `bl 0x0800F61C`, `bl 0x0800C4EC`, `bl 0x0800B350`, `bl 0x0800C4E8`
8. `vEEPROM_set_default(...)` — persist state choice
9. Sub-state transitions: `bl 0x0800A8DC(0)`, `bl 0x0800C494(1)`, `bl 0x0800C6B8`
10. More sub-state updates using state struct fields [+4], [+5], [+6], [+7]
11. `GPIO_WriteBit(GPIOF, 0x0001, 1)` — PF0 HIGH: release DSP reset
12. `bl 0x08011508` (finalize)
13. Return 2; settle: `state[0] = 2`

(Note: although path 1 calls spdif_init which writes PA2=LOW, some later step must set PA2=HIGH for active operation — confirmed by ODR snapshot showing PA2=HIGH in active state. The PA2-HIGH write hasn't been located in the disasm yet; the BSRR breakpoint to catch it during the active-entry transition is a future investigation.)

Path 2 (going standby, action=1, current=2):
1. `state[0] = 4` (intermediate)
2. `bl 0x0800A8DC(0)` (sub-state reset)
3. Conditional `bl 0x0800B330` if `state[3] == 1`
4. 200 ms delay (`bl 0x08008C20(200)`)
5. **`bl 0x08011500` → `spdif_subsystem_init` — PA2 LOW: Toslink buffer OFF**  ← BL NOP'd in firmware_08 ★ THE ACTUAL RAIL KILLER
6. `bl 0x0800C48C` → PB7 LOW chain (auxiliary, not the rail) — BL NOP'd in firmware_07+
7. `GPIO_WriteBit(GPIOF, 0x0001, 0)` — PF0 LOW: assert DSP reset
8. `bl 0x0800F2B8` (I²C1 shutdown: reconfigures PB8/PB9 to Analog)
9. `GPIO_WriteBit(GPIOC, 0x8000, 0)` — PC15 LOW: auxiliary signal — BL NOP'd in firmware_06+
10. `state[0] = 1` (final standby)

### Recipe D capture (2026-06-05) — empirical proof of rail killer

GDB code breakpoint at `0x0800d666` (the BRR-write inside `GPIO_WriteBit`) logged every clear-LOW call during IR-off transition:
```
BRR-write: port=0x48000000 mask=0x0004 lr=0x080103e1   ← ★ PA2 LOW (NEW finding)
BRR-write: port=0x48000400 mask=0x0080 lr=0x0800c9ad   ← PB7 LOW (known)
BRR-write: port=0x48001400 mask=0x0001 lr=0x0800a82d   ← PF0 LOW (DSP reset)
BRR-write: port=0x48000800 mask=0x8000 lr=0x0800a83b   ← PC15 LOW (known)
```

ODR snapshots confirm PA2 transition (pre→post):
- `GPIOA->ODR`: `0x84` → `0x80` (bit 2 cleared: PA2 went HIGH→LOW)
- `GPIOB->ODR`: `0x4085` → `0x4005` (bit 7 cleared: PB7 went HIGH→LOW)
- `GPIOC->ODR`: `0x8000` → `0x0` (bit 15 cleared: PC15 went HIGH→LOW)
- `GPIOF->ODR`: `0x1` → `0x0` (PF0 went HIGH→LOW)

### Auto-standby trigger flow (event-loop thread)

```
event_loop_thread @ 0x0800ACA4
  ├── osMessageQueueGet(timeout=25)              [bl @ 0x0800ACBC]
  ├── (timeout fallthrough):
  │   ├── if state[0] == 2 (active):
  │   │   ├── bl auto_standby_check @ 0x0800ACCA  [returns 0/1/2/4]
  │   │   └── if return code triggers standby:
  │   │       └── bl post_event_type7(0)         [bl @ 0x0800ACE4]
  │   └── loop back
  └── (message received):
      ├── notify(0, 4)                           [bl @ 0x0800AD0A]
      ├── transition_state(msg.byte[4])          [bl @ 0x0800AD12]
      └── notify(0, retval)                      [bl @ 0x0800AD1C]
```

The exact path from `post_event_type7(0)` to `transition_state(1)` involves
re-entry into the event_loop's message-processing path with a type-7 message
that the dispatcher eventually translates to action=1. We have the entry
point identified but haven't fully traced the type-7→action-1 mapping.

### Event-loop queue posters

The event-loop reads its queue at `*(g_event_loop_struct+4) = *(0x200023A4)`.
Eight functions post messages to this queue — each tagged with a distinct
`byte[0]` "channel" / event type:

| Address       | Conf | Symbol                       | Posts `{byte[0]=?, byte[4]=action}`  | Callers |
| ------------- | ---- | ---------------------------- | ------------------------------------ | ------- |
| `0x0800A9E4`  | ★★★  | `post_event_type6`           | `{0=6, 4=action}`                    | 1 (from 0x0800AA56) |
| `0x0800AA60`  | ★★★  | `post_event_type3`           | `{0=3, 4=action}`                    | 14 callers |
| `0x0800AABC`  | ★★★  | `post_event_type2`           | `{0=2, 4=0}`                         | 1 (from 0x0800BFCC) |
| `0x0800AB00`  | ★★★  | `post_event_type0`           | `{0=0, 4=action}` ← IR-toggle path   | **15 callers** — most-used poster |
| `0x0800AB54`  | ★★★  | `post_event_type5`           | `{0=5, 4=action}`                    | 1 (from 0x0800C2BC) |
| `0x0800ABA0`  | ★★★  | `post_event_type4`           | `{0=4, 4=0}`                         | 1 (from 0x0800C232) |
| `0x0800ABE4`  | ★★★  | `post_event_type7`           | `{0=7, 4=0 if arg=0, 1 if arg≠0}`    | 1 (from 0x0800ACE4) — auto-standby path |
| `0x0800AC38`  | ★★★  | `post_event_type1`           | `{0=1, 4=60}`                        | 1 (from 0x0800AC9A) |

`notify(channel, value)` at `0x0800BBDC` posts to a DIFFERENT queue (the
notify/broadcast queue at `*(g_notify_struct+12) = *(0x200023C8)`), so it's
NOT one of these posters. The state-change broadcasts that update the LED
display go through notify; the action commands to the event-loop go through
these 8 posters.

### LED subsystem

| Address       | Conf | Symbol                            | Notes                                       |
| ------------- | ---- | --------------------------------- | ------------------------------------------- |
| `0x0801002C`  | ★★★  | `set_led_animation`               | `void set_led_animation(void *anim_buf)`. Stops LED Timer, configures new animation, restarts timer. Called only from `0x08010524`. |
| `0x08010500`  | ★★★  | `request_led_change`              | `void request_led_change(void *anim, uint8_t priority, uint8_t immediate)`. Priority-based filter; calls set_led_animation only if priority allows. |
| `0x08010068`  | ★★★  | `led_timer_callback`              | RTX timer callback for LED animation (registered as `0x08010069` Thumb in LED Timer attr struct) |
| `0x08010220`  | ★★★  | `state_struct_init`               | Initializes global state struct at `0x200025DC`: byte[0]=1 (standby), byte[1]=10, byte[8]=8, plus creates 3 RTX message queues |
| `0x08010224`  | ★★★  | `state_struct_init.initial_state` | `MOVS R1, #1` — sets initial `state[0] = 1` (alternative simple-patch site for goal #1) |
| `0x08011920`  | ★★★  | `led_color_palette`               | RGB color palette, 3 bytes per entry. Index 0 = (255,0,0) red = standby; Index 9 = (255,0,255) purple = active |

### GPIO / peripheral wrappers

| Address       | Conf | Symbol                            | Notes                                       |
| ------------- | ---- | --------------------------------- | ------------------------------------------- |
| `0x0800D4FC`  | ★★★  | `HAL_GPIO_Init`                   | Standard ST HAL GPIO init. `void HAL_GPIO_Init(GPIO_TypeDef *GPIOx, GPIO_InitTypeDef *init)` — 33 call sites in firmware |
| `0x0800D65E`  | ★★   | `GPIO_write_bit`                  | Helper used by transition_state for audio-rail GPIO writes |
| `0x0800F160`  | ★★★  | `enable_app_irqs`                 | Enables NVIC IRQs for EXTI0_1, EXTI2_3, EXTI4_15 (priorities 1, 2, 2). Called once from app_main at `0x08010A68`. |
| `0x08010530`  | ★★★  | `create_app_threads`              | Creates 3 threads via osThreadNew_alt1/alt2 and `0x800DEBC`. Called once from app_main at `0x08010A64`. |
| `0x080102F4`  | ★★   | `create_rtx_obj_1`                | Creates an RTX object, stored at `0x20002434`. Called from app_main. |
| `0x080102BC`  | ★★   | `create_rtx_obj_2`                | Creates two RTX objects at `0x2000243C` and `0x20002440`. |
| `0x08010278`  | ★★   | `create_rtx_queue_group`          | Creates 3 RTX queues at `0x200023BC+8/12/16`. |
| `0x08010220`  | ★★   | `init_state_and_queues`           | Initializes state struct + 3 RTX queues + creates event-loop thread (entry `0x0800ACA5`) via osThreadNew at `0x08010262` |

---

## RAM addresses (state, structs)

| Address      | Conf | Size  | Symbol                          | Notes                                       |
| ------------ | ---- | ----- | ------------------------------- | ------------------------------------------- |
| `0x200025DC` | ★★★  | ~100B | `g_system_state`                | Main app state struct. **`state[0]` = power state byte** (1=standby stable, 2=active stable, 3=transitioning to active intermediate, 4=transitioning to standby intermediate). 26 LDR refs, 34 write sites — heavily used. Initialized by `state_struct_init` at `0x08010220`. |
| `0x20002504` | ★★★  | ~16B  | `g_audio_activity_tracker`      | State for `auto_standby_check`: byte[0]=last decision, byte[1]=last mode, word[8]=last-change tick |
| `0x20002538` | ★★★  | ~200B | `osRtxInfo`                     | RTX5 kernel info struct. `state[8] = osKernelState`. **DO NOT watchpoint** — context-switch writes constantly. |
| `0x200024E0` | ★★★  | ~16B  | `g_led_state`                   | LED state struct. `[+12] = LED Timer ID`. Init writes at `0x0801004A`-`0x08010052`. |
| `0x200026AC` | ★★★  | ~16B  | `g_led_anim_state`              | LED animation state. `[+0]` = anim active flag, `[+4]` = anim buffer ptr, `[+8]` = frame counter. Read by `led_timer_callback`. |
| `0x200023A0` | ★★   | ?     | `g_message_queues_a`            | Holds RTX queue/object IDs at offsets +4, +8 (from create_rtx_queue_group / state_struct_init) |
| `0x200023BC` | ★★   | ?     | `g_message_queues_b`            | Holds RTX queue/object IDs at offsets +8, +12, +16 |
| `0x20002434` | ★★   | ?     | `g_rtx_obj_1`                   | RTX object ID stored here                  |
| `0x2000243C` | ★★   | ?     | `g_rtx_obj_2`                   | (and +4 = `0x20002440`)                    |
| `0x200024CC` | ★★   | ?     | (heavily-trafficked, unidentified) | 16 write sites — possibly USB-related state |
| `0x200024FC` | ★★   | 4B    | `g_vEEPROM_mutex_id`            | Mutex ID stored by vEEPROM_module_init     |
| `0x200025F0` | ★★   | ?     | (heavily-trafficked, unidentified) | 21 LDR refs                                 |
| `0x20002610` | ★★   | ?     | (heavily-trafficked, unidentified) | 14 LDR refs                                 |
| `0x20002818` | ★★   | ?     | (unidentified)                  | 8 LDR refs                                  |
| `0x1FFFF7AC` | ★★★  | 12B   | `STM32_UniqueID`                | STM32 96-bit factory device unique ID. Candidate source for runtime USB iSerialNumber. |

---

## Flash data structures

| Address       | Conf | Size      | Symbol                       | Notes                                         |
| ------------- | ---- | --------- | ---------------------------- | --------------------------------------------- |
| `0x0801E5B0`+ | ★★★  | varies    | `RTX_object_names`           | ASCII strings for named RTX objects           |
| `0x08003F8E`  | ★★★  | 18B       | `g_usb_device_descriptor`    | Static USB descriptor template. **Variable fields overridden at runtime** (idProduct, bcdDevice, iManufacturer differ from what's actually sent — runtime source unknown but is NOT in firmware as a literal) |
| `0x08003F7A`  | ★★★  | 16B       | `g_hex_lookup_table`         | `"0123456789ABCDEF"` — used for byte→hex conversion (probably in serial number generation) |
| `0x08007000`  | ★★★  | 2 KB      | `vEEPROM_page_A`             | vEEPROM emulation page 1. Starts with `00 00 ff ff` = AN4061 VALID_PAGE marker |
| `0x08007800`  | ★★★  | 2 KB      | `vEEPROM_page_B`             | vEEPROM emulation page 2 (currently erased = inactive) |
| `0x0800CB74`  | ★★★  | 12B       | `vEEPROM_constants`          | `{0x08007000, 0x08007800, 0x0000EEEE}` — page addrs + RECEIVE_DATA marker |
| `0x08011920`  | ★★★  | 48B+      | `led_color_palette`          | RGB color palette (see LED section above)     |
| `0x0801E800`+ | ★★★  | 6.2 KB    | `g_patch_space`              | Confirmed unused / erased / safe for patches  |
| `0x015620`–`0x01C1F0` (file) | ★★ | ~27 KB | `dsp_firmware_blob` | High-entropy (~7.2 bits/byte) — almost certainly compressed/encrypted Renesas DSP firmware uploaded via I²C at boot |

---

## Hardware peripheral usage

### Used peripherals (literal references)

| Peripheral | Base addr      | LDR refs | Notes                                              |
| ---------- | -------------- | -------- | -------------------------------------------------- |
| TIM14      | `0x40002000`   | 1        | Used (purpose not fully traced)                    |
| TIM1       | `0x40012C00`   | 6        | PWM-capable                                        |
| TIM2       | `0x40000000`   | 0 lit / instr ref | PA5 has AF1 = TIM2_CH1_ETR — possibly audio control PWM |
| TIM3       | `0x40000400`   | 2        | General-purpose                                    |
| TIM16      | `0x40014400`   | 7        | General-purpose                                    |
| TIM6       | `0x40001000`   | 2        | General-purpose                                    |
| EXTI       | `0x40010400`   | 7        | EXTI0_1, EXTI2_3, EXTI4_15 enabled in NVIC (handlers point to default trap — they may never fire) |
| SYSCFG     | `0x40010000`   | 4        | EXTI source select                                 |
| RCC        | `0x40021000`   | many     | Clock gating                                       |
| PWR        | `0x40007000`   | 9        | Low-power mode control                             |
| I2C1       | `0x40005400`   | 1        | One use                                            |
| I2C2       | `0x40005800`   | 2        | **DSP communication bus** (also `0x40005828` = I2C2_TXDR for byte send) |
| FLASH      | `0x40022000`   | many     | Self-flash code uses FLASH_KEYR magic constants    |
| USB        | `0x40005C00`   | (none direct) | Used only via real ISR at vector slot 31 = `0x08003988` |

### Unused peripherals

SPI1, SPI2/I2S, DAC, USART (1-4), CAN are NOT referenced (or are referenced only as instruction byte coincidences). The STM32 acts purely as a system controller / I²C master.

### GPIO usage (computed bases, summary)

Full table in `/tmp/firmware/pinmap.txt`. Key pins:

| Pin   | Mode          | Function (best guess)             |
| ----- | ------------- | --------------------------------- |
| PA0   | Input         | Button on bar                     |
| PA1   | Input VeryHigh | **IR receiver** (best candidate based on speed setting) |
| **PA2** | **Output_PP**   | **★ SPDIF buffer / Toslink load-switch ENABLE.** Driven HIGH in active state (3V on Toslink Vcc), LOW in standby (0.8V leakage). Set LOW by `spdif_subsystem_init` at `0x080103dc`. Empirically confirmed via Recipe D ODR snapshots. |
| **PA3** | **Input**     | Reads always LOW (dead-wired). `is_audio_active()` at `0x0801041C` reads this but the result is meaningless. The SOT-23-5 chip with single trace to PA3 doesn't reach PA3 with usable signal in this firmware's configuration. |
| **PA4** | UNCONFIGURED  | ★ Actual SPDIF data carrier (toggles at ~5 MHz biphase rate when audio playing). Firmware doesn't configure it (sits in reset-default input mode) but the Toslink module drives it. firmware_17 polls this via direct IDR read. |
| PA5   | AF_OD AF1     | TIM2_CH1_ETR — possibly audio mute/control PWM |
| PA8   | Output_OD PU  |                                   |
| **PB7** | **Output_PP** | Auxiliary, NOT the audio rail despite earlier hypothesis. Pulsed LOW→HIGH during active entry (reset-pulse pattern). NOP'd in firmware_07/08 with no observable effect on Toslink Vcc. |
| PB11  | AF_OD AF1     | **I2C2_SDA** (the DSP bus)        |
| PB12  | Output_OD PU  |                                   |
| PB14  | Output_PP     |                                   |
| **PC15** | **Output_PP** | Auxiliary signal. Goes HIGH in active, LOW in standby. NOT the Toslink rail gate (firmware_06 confirmed). Possibly drives an indicator or related rail. |
| **PF0** | **Output_PP** | **★ DSP reset (active LOW).** Held LOW in standby (DSP held in reset). Goes HIGH ~50ms after rail-up during active entry. |

---

## Hardware (off-chip)

| Component                  | Identifier               | Notes                                       |
| -------------------------- | ------------------------ | ------------------------------------------- |
| MCU                        | STM32F072CBT6 LQFP48     | 128 KB flash, 16 KB RAM                     |
| SPDIF receiver             | 3-pin Toslink module     | Output → **PA4 directly** (carries raw biphase data). PA4 is the actual SPDIF data line that toggles with audio activity. |
| SPDIF buffer               | SOT-23-5 marked `Z045`/`Z04S` | Located next to Toslink module per user inspection. Single trace to PA3. Apparently non-functional in current firmware config (PA3 always reads LOW) — likely needs an enable signal not provided. |
| DSP                        | Renesas D2-92634-LR      | Has integrated SPDIFRX0/1. Talks to STM32 via I²C2. Firmware blob uploaded from STM32 flash at boot. |
| Bluetooth                  | CSR/Qualcomm A64215      | A2DP receive; labelled SPI debug header on daughter board |
| Wireless subwoofer link    | SWA12-TX (FCC NKR-SWA12) | Proprietary 2.4 GHz audio link to sub       |
| Audio rail control         | **PA2 (★ identified 2026-06-05)** | STM32-gated via PA2 → SOT-23-5 buffer/load-switch enable. Active=HIGH (Toslink Vcc ≈ 3.0V), standby=LOW (Toslink Vcc ≈ 0.8V leakage). Identified via Recipe D GDB breakpoint in `GPIO_WriteBit` BRR path. |

---

## RE workflow artifacts

These files in `/tmp/firmware/` capture the state of the work:

| File                          | Contents                                                  |
| ----------------------------- | --------------------------------------------------------- |
| `firmware_01_original-dump.bin`              | Original 128 KB flash dump (load at `0x08000000`)         |
| `firmware_05_autoboot-active-on-power.bin`          | **Working Goal #1 patch** (24 bytes differ from baseline) |
| `firmware_03_redirect-shim-noop.bin`          | NO-OP diagnostic patch (verified shim mechanism)          |
| `firmware_04_autoboot-partial-no-notify.bin`          | Earlier attempt (audio on, LED stuck red)                 |
| `disasm.txt`                  | Full Thumb disassembly via objdump                        |
| `optionbyts.txt`              | Option-byte dump (confirms RDP=AA)                        |
| `pinmap.txt`                  | GPIO pin assignments + app_main boot sequence             |
| `goal1_candidates.txt`        | Pre-GDB candidate analysis                                |
| `gdb/README.md`               | GDB / OpenOCD live-debug recipes + helper-script docs     |
| `gdb/switch_mode.sh`          | Local script to switch audio mode (Music/Movie/Voice)     |
| `gdb/trace_modes.gdb`         | GDB script: capture all DSP writes for Music/Movie/Voice  |
| `IR_CODES.md`                 | Complete IR-button → cmd_id mapping (static-RE derived)   |
| `dsp_protocol.md`             | DSP control protocol + vEEPROM + register map             |
| `mylog.txt`                   | User's GDB session log (the breakthrough)                 |
| `teufel_remote.lircd.conf`    | LIRC config with IR codes (NEC protocol)                  |
| `SOLUTION.md`                 | Goal #1 patch documentation                               |
| `symbols.md`                  | (this file)                                               |
| `plan_diy.md`                 | Earlier DIY (Ghidra-based) plan                           |
