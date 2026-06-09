# Reverse-engineering a Teufel Cinebar One — a journey writeup

Two days of poking at a Teufel Cinebar One soundbar's STM32F072 firmware, told as a tutorial. Audience: someone comfortable with embedded software (GDB, OpenOCD, STM32 toolchain) but new to reverse-engineering. The story isn't linear — we hit dead ends, followed red herrings, and learned hard lessons. Those are kept in: they're the most useful part.

**What we ended up with:**
- A firmware that auto-on's at AC restore and wakes from SPDIF (the original goal)
- A complete map of GPIOs, DSP control protocol, IR codes, and the bootloader's hidden USB-MSC firmware-update path
- A way to upload firmware to the bar **without** opening the case — by pressing any TV remote button at power-on

**Tools used throughout:**
- ST-Link v2 clone (the cheap blue ones, ~$2)
- A multimeter
- An OpenOCD + arm-none-eabi-gdb installation
- objdump (`arm-none-eabi-objdump`) for disassembly
- Python for binary patching
- Optional but useful: a Saleae Logic clone, an Arduino with an IR LED for testing without the real remote, a TV remote

**No oscilloscope was used.** All the timing-sensitive observations were either from disassembly + a multimeter, or via GDB pausing the chip.

---

## Phase 0 — get a clean dump

Before anything else, dump the flash. ST-Link clipped to the bar's SWD pads:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "init; reset halt; flash read_bank 0 firmware_01_original-dump.bin; exit"
```

128 KB later you have everything: vector table, code, data, vEEPROM. **Save the dump and don't touch it.** Every patch goes through a Python script that reads the original and writes a patched copy — never modify the dump in place.

While you're at it, check the readout protection level:

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "init; stm32f0x options_read 0; exit"
```

You want to see RDP=AA (= no protection). If it's AB or CC, the chip refuses to expose flash and you're done before you started.

Sanity check the dump:

```bash
# First word = initial SP, must point into RAM (0x20000000-0x20020000 for F072)
xxd firmware_01_original-dump.bin | head -1
# Second word (offset 4) = Reset_Handler address — should be in flash (0x08000000+)
```

If both look reasonable, you have a real dump.

---

## Phase 1 — first static look

Disassemble the whole thing as ARMv6-M Thumb:

```bash
arm-none-eabi-objdump -D -b binary -m arm -M force-thumb \
    --adjust-vma=0x08000000 firmware_01_original-dump.bin > disasm.txt
```

This produces a giant text file but `grep` makes it tractable. A few first grep targets:

```bash
# All push instructions = function entries
grep -nE '\bpush\b' disasm.txt | head

# Find what addresses are referenced from elsewhere — useful for function pointers
strings -tx firmware_01_original-dump.bin | head -50

# Find peripheral base addresses as literals (uses Python for proper LE search)
python3 -c "
import struct
d = open('firmware_01_original-dump.bin','rb').read()
for name, addr in (('RCC', 0x40021000), ('GPIOA', 0x48000000),
                   ('USB',  0x40005C00), ('I2C1', 0x40005400)):
    pat = struct.pack('<I', addr)
    refs = []
    pos = 0
    while True:
        i = d.find(pat, pos)
        if i < 0: break
        refs.append(i)
        pos = i + 1
    print(f'{name} ({addr:#x}): {len(refs)} refs')
"
```

The PERIPHERAL LITERAL search is gold — every time the firmware uses GPIOA, it has to load the literal 0x48000000 from a constant pool. Finding those refs gives you the "GPIO touch points."

Now build a **pinmap**: scan every `HAL_GPIO_Init` call, decode the args (Pin/Mode/Pull/Speed/AF), and dump a table. We did this with a Python regex over the disasm. The output:

```
PA0   Input no-pull       — Service mode trigger (later: not really)
PA1   Input VeryHigh      — IR receiver
PA5   AF1                 — TIM2/SPI? (later: CEC config side path)
PB6/PB7   I²C1 (DSP)
PB8/PB9   I²C1 alt
PB10/PB11 I²C2 (EEPROM/CEC)
PC15  Output_PP           — !! later: this is THE Toslink rail master
PF0   Output_PP           — DSP reset (active low)
```

Use the datasheet alternate-function table to translate AF numbers. Don't trust the pin labels — the firmware uses the pins for something specific that may not match the schematic-style label.

**Find the kernel/RTOS.** Strings dump revealed `"RTX V5.2.3"`, named mutex strings (`"Mutex I2C System"`, `"LED Timer"`), `osThreadNew`, `osMessageQueueGet`, etc. Now we know:
- It's Keil RTX5 (CMSIS-RTOS2)
- The CMSIS SVCall pattern: `svc #0` → kernel SVC dispatcher → impl function pointer
- Threads, queues, mutexes, timers — all the standard primitives

Finding RTX threads is the most important map: each thread is its own state machine, and most of the application logic lives inside one or two threads.

---

## Phase 2 — make a first change

The smallest possible useful change: make the bar boot directly into active mode instead of into factory standby. This proves you can patch + flash.

The bar's "active" state is stored as a byte at a state struct. Finding it required:
1. Reading the disasm of the LED palette area (since LED color depends on state)
2. Tracing back from a `request_led_change` call to find which state byte determines color
3. Finding the byte that's set to `1` (= standby) at init, somewhere in `state_struct_init`

After ~30 minutes of grep+read, we found:

```
0x08010220  state_struct_init:
0x08010224    MOVS R1, #1
0x08010226    STRB R1, [R0, #0]     ; state[0] = 1 (= standby at boot)
```

Change `#1` to `#2` (= active state). The Thumb instruction `MOVS R1, #1` is `0x2101`. `MOVS R1, #2` is `0x2102`. **One-byte change**: file offset 0x10224 from `01` to `02`.

But wait — just changing the state byte doesn't actually power up the audio rail. There's a state-machine *transition* function that does that. So we also need to TRIGGER the transition at boot.

The right approach turned out to be different: leave the init value at 1, and post a `notify(channel=0, value=4)` event from `app_main` so the event loop runs `transition_state(2)`. That involves a shim function.

**Lesson learned:** "find the state byte and flip it" is rarely enough. The state byte's *transitions* trigger side effects. Patch the trigger, not the state.

After the shim was in place: bar boots, plays audio immediately. First win!

```bash
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg \
        -c "program firmware_05_autoboot-active-on-power.bin verify reset exit 0x08000000"
```

If something goes wrong (HardFault on boot), you can always reflash the original dump — the bootloader is in chip's system memory ROM and isn't touched by our writes.

### Sidebar: a tempting but wrong "fix" (fw_24)

To prevent IR-power presses from triggering a transition we couldn't observe cleanly, we briefly built `firmware_24_nop-transition-state.bin` — a one-byte patch that turned the entire `transition_state` function into `bx lr` (immediate return). Boot HardFault. **Why:** `transition_state(2)` is also called *during boot init* to bring the bar from standby to active. NOP'ing it leaves the DSP and audio rail uninitialized, and the first byte the bar's normal main loop reads from a peripheral that's not powered yet... HardFault.

**Lesson:** before you NOP a function, search every caller. If any caller runs at boot or during init, you can't NOP the function — you need a more surgical patch (e.g., NOP the specific call site that's bothering you).

---

## Phase 3 — live debugging primer

For anything beyond simple text patches, you need live debugging.

```bash
# Terminal 1: start the OpenOCD server, leave it running
openocd -f interface/stlink.cfg -f target/stm32f0x.cfg
```

OpenOCD listens on three ports: 3333 (GDB), 4444 (TCL/telnet command interface), 6666 (the deprecated TCL command interface). **Both 3333 and 4444 are useful** — sometimes one works better than the other.

```bash
# Terminal 2 — connect with GDB
arm-none-eabi-gdb
(gdb) target extended-remote :3333
(gdb) monitor halt
(gdb) info reg
```

Or for one-shot scripts, use `-batch -ex`:

```bash
gdb-multiarch -batch \
  -ex 'set confirm off' \
  -ex 'target extended-remote :3333' \
  -ex 'monitor halt' \
  -ex 'printf "PC=0x%x  APB1ENR=0x%08x\n", $pc, *(unsigned int*)0x4002101c' \
  -ex 'monitor resume' \
  -ex 'detach' -ex 'quit'
```

This is the workhorse: halt, peek at memory or registers, resume. We used it hundreds of times.

**Watch out for:** GDB caches register values. After `monitor halt`/`monitor resume`, sometimes `$pc` shows a stale value. Use `flushregs` (`maintenance flush register-cache` in newer GDBs) to force re-read.

For commands that don't go through GDB cleanly, use the TCL interface directly:

```bash
# One-shot commands via netcat to OpenOCD's TCL/telnet port
( echo "halt"
  echo "mdw 0x20000150 8"     # dump 8 words from RAM 0x20000150
  echo "mww 0x4002101c 0x800000"  # write 0x800000 to RCC_APB1ENR
  echo "bp 0x08003ca6 2 hw"   # set hardware BP at code address
  echo "resume"
  echo "exit"
) | nc -q 1 127.0.0.1 4444
```

This bypasses GDB's bookkeeping and goes straight to OpenOCD's hardware-level commands. Useful when GDB's HBP implementation breaks (we found it does, occasionally).

---

## Phase 4 — live GPIO bisection

A persistent puzzle: which GPIO actually kills the audio rail in standby?

Static analysis pointed at three pins (PA2, PB7, PC15) all going LOW during the standby transition. We had patched all three to test, but that left the bar's DSP powered in standby (red LED) — clearly the wrong fix.

The bench answer needed real-time GPIO toggling. Here's the trick:

```gdb
# Halt the bar in active state
monitor halt

# Drive PC15 LOW via BSRR (atomic, no register read-modify-write needed)
set *(unsigned int*)0x48000818 = (1 << 31)   ; GPIOC BSRR with reset bit for pin 15
monitor resume
```

With the multimeter on the Toslink Vcc rail: ~3.0V → 0.8V. **PC15 alone drops it.** Repeat for PA2 and PB7:

```gdb
set *(unsigned int*)0x48000018 = (1 << 18)   ; PA2 → LOW
set *(unsigned int*)0x48000418 = (1 << 23)   ; PB7 → LOW
```

PA2 LOW alone: **no effect** on Toslink. PB7 LOW alone: audio stops but Toslink rail intact (= DSP rail kill, not Toslink rail).

So PC15 is **the** Toslink rail master. The earlier patch (NOP all three) was over-conservative.

**Lesson:** when static analysis groups multiple suspects, **bisect via GDB-driven register writes** while measuring on the bench. The conclusion was a single byte change (NOP only one of the three writes), and behavior I could verify.

### Sidebar: the sequential-confound dead end (fw_06/07/08/22)

How we got to "NOP all three" in the first place:
- **fw_06**: NOP'd PC15-LOW write only. Toslink Vcc still dropped in standby. (= didn't work.)
- **fw_07**: + NOP PB7-LOW. Still dropped. (= didn't work.)
- **fw_08**: + NOP PA2-LOW. Rail stays up! (= "works"... or so we thought.)
- **fw_22**: same three NOPs, plus wake-on-SPDIF logic.

We declared victory and shipped fw_22 as our productive firmware for weeks.

What actually happened: between each test, the bar was REFLASHED and POWER-CYCLED. Each new firmware INITIALIZES the rail (PC15 HIGH, PB7 HIGH, PA2 HIGH) at boot. After fw_06 → reflash → boot → at boot, PC15 is already HIGH; standby-LOW gets NOP'd. But there's NO subsequent active-entry that re-sets PC15 (because nothing reset it). So we couldn't tell which of the three writes was THE one — we'd cumulatively patched them all.

The right test was the live GDB-driven bisection: keep the bar running, drive ONE pin LOW, measure. We did this only once we noticed the bar's DSP was still warm in standby (red LED, current draw way higher than expected) — months after declaring victory.

**Lesson:** if you patch-flash-reboot-test in sequence, each test starts from a different state. Use live GDB to manipulate ONE variable at a time without reboots between observations.

### Sidebar: pins that are connected but don't do anything (PA3)

The firmware contains a function `is_audio_active()` at `0x0801041C` that reads PA3 and returns its value. From a static read, that's "PA3 = SPDIF activity detect." From the bench:

```bash
# Bench truth table for PA3 across all states:
gdb-multiarch -batch \
  -ex 'target extended-remote :3333' -ex 'monitor halt' \
  -ex 'printf "GPIOA IDR = 0x%08x  (PA3 = bit 3)\n", *(unsigned int*)0x48000010' \
  -ex 'monitor resume' -ex 'detach' -ex 'quit'
# Active+playing:  GPIOA IDR = ...e3 (bit 3 = 0)
# Active+silent:   GPIOA IDR = ...e3 (bit 3 = 0)
# Standby:         GPIOA IDR = ...e3 (bit 3 = 0)
# All 6 scenarios: PA3 = 0
```

PA3 reads LOW in every scenario. The actual SPDIF data appears on PA4 (which the firmware *doesn't* read). Whatever's between the Toslink module and PA3 (we found a SOT-23-5 chip marked `Z045` near the receiver) doesn't carry usable signal in this firmware's configuration — probably missing a control signal we couldn't identify.

**Lesson:** just because the firmware reads a pin doesn't mean the pin is meaningfully connected. **Verify with a bench truth table** across the states where the pin should differ. If it doesn't differ, the firmware is reading a dead wire.

---

## Phase 5 — the RAM trampoline trick (dynamic capture of opaque APIs)

The IR-decoder calls some kind of `notify(channel, value)` function. We needed to know which `(channel, value)` pairs correspond to which button presses, but each press calls `notify()` with hundreds of intermediate calls. Polling the call doesn't help — we miss everything between halts.

**The trick:** patch the `notify()` function to log its args to a RAM ring buffer before doing its actual work. Then read the ring buffer after each button press.

The ring buffer is just a static RAM slot we choose:

```
0x20003E00  ring head index (1 byte)
0x20003E04  ring base — 16 entries × 8 bytes = (channel, value) pairs
```

The patch:

```asm
; Original first instruction of notify(): push {r2, r3, r4, r5, lr}
; We REPLACE it with: bl trampoline
; Then trampoline:

trampoline:
    push {r0, r1, lr}        ; save args
    ; compute &ring[head]
    ldr  r2, [pc, #literal]   ; r2 = 0x20003E00 (ring head ptr)
    ldrb r3, [r2]              ; r3 = head index
    add  r3, r3, #1
    and  r3, r3, #0x0F         ; ring of 16
    strb r3, [r2]              ; update head
    ; store (channel, value) at ring[old_head]
    ldr  r2, [pc, #literal]   ; r2 = 0x20003E04 (ring base)
    lsl  r3, r3, #3
    add  r2, r2, r3
    str  r0, [r2]              ; channel
    str  r1, [r2, #4]          ; value
    pop  {r0, r1, lr}          ; restore args
    ; tail-call back to notify() body
    push {r2, r3, r4, r5, lr}  ; what we displaced
    b    notify_body+2         ; b.n skipping the first inst we replaced
```

Two big gotchas we hit:
- **Cortex-M0 doesn't have `B.W` (the 32-bit unconditional branch).** Only `BL` is 32-bit. For long jumps, use `ldr r3, [pc, #imm]; bx r3`.
- **Stack balance is fragile.** Push/pop must match exactly. We had several HardFaults before getting it right.

### Sidebar: the B.W disaster (fw_26 / fw_27 / fw_28)

It took THREE failed firmwares before we found the B.W issue:

- **fw_26** (`nop-and-ring-log`): full ring-buffer trampoline. Boot HardFault.
- **fw_27** (`simple-notify-log`): simplified — just store args, no ring. Boot HardFault.
- **fw_28** (`passthrough-tramp`): pass-through with NO logging at all — just displace + jump back. **Still HardFault.**

That's the diagnostic moment: fw_28 didn't add any work, but it still crashed. So the problem was in the **redirect mechanism itself**, not the logging code.

The smoking gun: I'd written `b.w` (`0xF000 0xBE60`) for the unconditional jump back to `notify_body+2`. On ARMv7-M (Cortex-M3+), that encodes a valid 32-bit unconditional branch. On ARMv6-M (Cortex-M0/M0+), `0xF000 0xBExx` is an **UNDEFINED** instruction → HardFault on first execution.

The fix in fw_29:

```asm
; WRONG (ARMv7-M only):
b.w  notify_body+2

; RIGHT (ARMv6-M compatible):
ldr  r2, [pc, #0x30]   ; load target literal
bx   r2                 ; branch (clobbers a caller-saved reg)
```

Add a literal `0x0800BBDF` (= `notify_body+2` with Thumb bit set) somewhere reachable by `pc-relative load`. Use a caller-saved register (r0-r3, r12) for the temporary.

**Lesson:** know your ISA variant. On Cortex-M0, the only valid 4-byte Thumb-2 instructions are: `BL`, `MRS`, `MSR`, `ISB`, `DSB`, `DMB`. **No** `B.W`, no `LDR.W`, no `MOV.W`. The `disasm.txt` from objdump WILL show some `b.w` instructions in the firmware — those are bytes that happen to disassemble that way, **not** valid code paths (or they'd HardFault).

### Sidebar: the off-by-one that cost a day (the LIMIT byte)

After getting fw_29 working, we mapped out the IR ring buffer. Every press pushed (channel=12, value=...) to the queue. But pressing "power" gave `notify(12, 0x0201)` — and our static decode of cmd_id=12's dispatch said byte `0x02` of `value` selects a sub-handler... which was "no-op."

The user pushed back: "but pressing power DOES turn the bar off, so this can't be a no-op handler!"

The dispatch helper at `0x080108E2` reads a byte table inlined right after the BL site. The convention I'd guessed was: byte[0] = first case offset, byte[1] = second case offset, etc. So I counted four 0x49 bytes after the dispatch BL → cmd_id=12 → 5th entry → no-op handler.

The user's pushback forced a careful re-read. The actual convention: **the first byte of the inline table is the LIMIT (= max valid index), and the case offsets start at byte 1.** So:
- LIMIT byte = 4 (i.e., valid cmd_id range 0..4)
- byte[1] = handler for cmd_id 0
- byte[2] = handler for cmd_id 1
- ...
- byte[5] = handler for cmd_id 4

Five 0x49 bytes, not four. We'd off-by-one'd the entire IR mapping.

After fixing: `notify(12, 0x0201)` → cmd_id sub-dispatch → power-toggle handler at `0x0800BF90`. Everything else fell into place.

**Lesson:** if your model says "this should do nothing" but the user observes it DOES something, your model is wrong. **Re-verify byte counts** and bit positions; off-by-one is the most common error in this kind of work. And: **listen to the user with the device in their hands.** The pushback IS the data.

Once it worked: press a button, halt, dump `0x20003E00..3E80`:

```bash
gdb-multiarch -batch \
  -ex 'target extended-remote :3333' -ex 'monitor halt' \
  -ex 'printf "head=%d\n", *(unsigned char*)0x20003E00' \
  -ex 'x /16xb 0x20003E04' \
  -ex 'monitor resume' -ex 'detach' -ex 'quit'
```

Each `(channel, value)` pair tells us which `notify()` call fired. Pressing "power" → entries `(13, 0x0201)`. Pressing "mute" → `(13, 0x0202)`. With the full map of pairs to actions, we had every IR code.

**Lesson:** when you can't follow a call statically (too many call sites, too much state), patch the function to log its args to RAM, then read RAM after the user interaction. Way faster than reading more disasm.

---

## Phase 6 — when nothing makes sense, set telltales

Late in the journey, we built a shim that was supposed to set USBEN at boot. The bar booted normally, but `RCC_APB1ENR` showed bit 23 was still 0. Was our shim not being called?

GDB's hardware breakpoints **just didn't work** at this point (OpenOCD's FPB management bug). We needed another way to prove the shim ran.

Solution: **add a telltale RAM write**. Modify the shim to write `0xDEADBEEF` to some RAM address at the very start. Then halt + read that RAM:

```python
# In our shim builder script:
shim = [
    PUSH(r0, r1, r2, lr),
    LDR(r0, =0x20003FFC),       # telltale address
    LDR(r1, =0xDEADBEEF),
    STR(r1, [r0]),                # write telltale
    # ... the actual work ...
]
```

After flashing + boot:

```bash
gdb-multiarch -batch -ex 'target extended-remote :3333' \
  -ex 'monitor halt' \
  -ex 'printf "Telltale = 0x%08x\n", *(unsigned int*)0x20003FFC' \
  -ex 'monitor resume' -ex 'detach' -ex 'quit'
```

Telltale = 0xDEADBEEF → shim ran. Telltale = junk → never reached. **No HBP needed.**

This single technique unblocked a stuck investigation that the broken HBP path couldn't.

**Lesson:** when your debugger fights you, side-step it. A telltale RAM write is harder to ignore than a missed breakpoint.

---

## Phase 7 — recognize the architecture, twice

We made a major error early on: we thought `0x080039D4` was the application's `main()`. Symbols.md called it that. It was wrong.

We discovered the truth only when our patched code at `0x08003AD0` never executed. Eventually we set BPs at `main()` entry, then at SystemInit, then at Reset_Handler — **none fired**. The chip booted normally but never hit any of those addresses.

That triggered a careful re-read of `0x080039D4`. About 50 instructions later, we found:

```
0x08003A92    bl  0x08002DB8     ; boot_jump_to_app
```

Decoded:

```
0x08002DB8:
    push {r3-r6}
    ldr  r1, [pc, #...]       ; r1 = 0x08008000 (= literal)
    ldr  r0, [r1, #0]          ; r0 = app SP
    ; validate r0 & 0x2FFE0000 == 0x20000000
    msr MSP, r0                ; set MSP to app SP
    ; copy 48 entries × 4 = vector table from 0x08008000 to 0x20000000
    ; remap VTOR
    ; (later: bx to app reset vector)
```

This is the **bootloader-to-app jump**. The literal `0x08008000` is the app vector table base. **The bar has a multi-stage boot**: a 32 KB bootloader at `0x08000000-0x08007FFF`, then a 96 KB application at `0x08008000-0x0801FFFF`.

Everything we'd been reverse-engineering was the application. The bootloader was a separate beast we'd never touched.

**How to recognize a bootloader you didn't expect:**
- The reset handler is small (a few BLs and a BX).
- One of those BX's takes a literal that's nowhere near the start of flash — that's the app's entry.
- `msr MSP, ...` is rare in application code. It strongly suggests a stage transition.
- Look for `SCB->VTOR` writes (offset 8 from `0xE000ED00`) — those are vector-table relocations.

The lesson cost us about half a day. Worth it — once we understood the split, the rest of the MSC investigation came together fast.

### Sidebar: the PA15 mux-SEL hypothesis (live-tested wrong)

When chasing the USB mux SEL pin, the user noticed a trace from the suspected mux IC going "towards PA15." We built a quick GDB script to drive PA15 LOW via open-drain output:

```gdb
monitor halt
# Configure PA15 as output open-drain, drive LOW
set *(unsigned int*)0x48000018 = (1 << 31)   ; BSRR reset bit for PA15
set *(unsigned int*)0x48000004 = (*(unsigned int*)0x48000004) | (1 << 15)   ; OTYPER bit = OD
set *(unsigned int*)0x48000000 = (*(unsigned int*)0x48000000 & ~(0x3 << 30)) | (0x1 << 30)   ; MODER = output
monitor resume
```

Watched dmesg + lsusb: zero change. Mux didn't flip.

Static check: PA15 is never read, written, or configured by any firmware code we could find. The IDR reads HIGH idle (pulled HIGH by something external). It's a connection to the daughter board, but its function on the daughter side is unknown.

The user then methodically probed each PCB test pad with a multimeter while attempting USB enumeration → discovered the actual mux SEL is at testpad **T211**, completely independent of any STM32 GPIO. (Later: when MSC mode is active, T211 reads 3 V automatically. Either there's an STM32 pin we still missed, or — more likely — the USB mux IC auto-switches on D+ pull-up presence and T211 is just a mux-status output that happens to expose the routing.)

**Lesson:** PCB trace observations through a closed case are fuzzy. Test the hypothesis with a live GDB-driven write before committing to a theory. And: an STM32 GPIO that's "never accessed by firmware" really IS dead from the firmware's perspective — don't try to make it fit a narrative.

---

## Phase 8 — full protocol RE: the USB-MSC firmware-upload

With the bootloader / application split clear, the picture of the bar's USB MSC mode snapped into focus. The bootloader has its own SCSI dispatcher, FAT12 emulator, and a hidden firmware-update protocol.

### Sidebar: the CEC red herring (~2 days)

Before we cracked MSC, we spent two full days chasing a different "service mode" hypothesis: the **PA0+EEPROM handshake in the application** at `0x0800E928` / `0x0800ED10`.

The static evidence was compelling:
- An RTX thread polling PA0 for LOW
- An I²C transaction at slave address `0xA0` (= classic 24Cxx EEPROM)
- Validation of returned bytes (`[0]==2, [1]==3, [2]∈valid_range`)
- A USB MSC device descriptor in flash (PID `0x0004`, "TEUFEL CINEBAR COMPACT" inquiry string)
- A FAT12 image baked into flash

The story we told ourselves: "PA0 LOW + EEPROM contents → bar boots into USB MSC firmware-update mode." We even built a test firmware (`fw_36`) that bypassed both the PA0 read and the EEPROM check, expecting MSC to enumerate.

It didn't. Instead:
- Thread state confirmed the "service mode entered" branch (`state[+9] = 1`)
- `RCC_APB1ENR` showed bits 22 (I²C2EN) and 30 (CECEN) added — but NOT bit 23 (USBEN)
- USB peripheral remained dormant
- No MSC enumeration

We went down deep into chasing "why isn't USBEN being set?" and built fw_37 (a shim that force-enables USBEN). Still no MSC.

Eventually we traced the I²C2 EEPROM handshake → the type-2 handler at `0x08003C80` (in this app's path) → the CEC peripheral init at `0x0800EE9C` which:
- Enables CECEN (`RCC_APB1ENR` bit 30)
- Configures PA5 as AF1 (the CEC line)
- Sets up a CEC handle struct at `0x200026F8`
- Enables NVIC IRQ 30 = **CEC_CAN_IRQn**

`service_inner(r0=5)` was a **CEC operation**, not a USB operation. The whole PA0+EEPROM chain is for **HDMI-CEC factory test**, not USB MSC.

The real MSC entry mechanism was in the BOOTLOADER, which we hadn't touched yet (and didn't even know existed until phase 7's "main() isn't what we thought it was" discovery).

**Lesson:** strong static evidence can still be evidence for the WRONG thing. The USB MSC scaffold in this firmware exists because the bootloader has its own copy of MSC class code (descriptors, FAT12 image, SCSI handlers). When grep'ing for "USB MSC" in the binary, you'll find that scaffold — but it's compiled into the BOOTLOADER, not used by the app. The app has the *appearance* of USB MSC (descriptors, strings) only because they're duplicated/shared across boundaries.

When you find "X service mode" code that DOES things but doesn't achieve the goal, ask: **what other mode does it look like?** In our case, the "service mode" was real — just for CEC, not USB. The opcodes our dispatch handler recognized (0x36 `<Standby>`, 0x44 `<User Control Pressed>`, 0x82 `<Active Source>`, etc.) are textbook HDMI-CEC consumer opcodes. Once that pattern clicked, the entire app's service mode mapped to factory test, not firmware update.

### The reframe

After accepting CEC ≠ MSC, the question became: **does this bar have ANY USB MSC at all?**

The bootloader literal `0x40005C00` (= USB peripheral base) appears exactly once in the bootloader code at `0x080032B0`. Following that single reference led to:
- USB descriptor with PID `0x0004` baked at `0x08003F8E`
- FAT12 image with "TEUFEL CBO" label
- A SCSI dispatcher that recognizes WRITE(10), READ(10), INQUIRY, etc.
- A bootloader main `0x080039D4` that READS PA1 (not PA0) and either jumps to the app or enters the MSC code path

That last point is the key — **the bootloader's MSC entry is on PA1, not PA0**. PA1 is the IR receiver. Holding any TV remote button at boot pulses PA1 LOW (38 kHz IR carrier) and triggers MSC mode. No firmware modification needed.

---

**Discovery sequence:**

1. **Find the SCSI dispatcher** — look for `cmp r6, #0x2A` (= SCSI WRITE(10) opcode). One hit in the bootloader region.
2. **Trace WRITE handler** — it dispatches via function pointers in a table. We needed runtime state to find that table.
3. **Set a BP at WRITE entry** via OpenOCD's `bp` (TCL, not GDB):

   ```bash
   ( echo "halt"
     echo "bp 0x08002CA6 2 hw"   # WRITE(10) handler entry
     echo "resume"
     echo "exit"
   ) | nc -q 1 127.0.0.1 4444
   ```

4. **Trigger the WRITE** by `cp`'ing a file to the MSC volume on the host.
5. **Halt + read state struct:**

   ```bash
   ( echo "halt"
     echo "reg"
     echo "mdw 0x20000410 16"   # state struct
     echo "mdw 0x20000130 8"    # function pointer table
   ) | nc -q 1 127.0.0.1 4444
   ```

   This revealed the storage backend function table at RAM `0x20000130`. The flash addresses there (`0x08000234` for READ, `0x0800025C` for WRITE) led directly to the protocol logic.

6. **Decode the protocol from the WRITE backend disassembly:**

   ```
   WRITE(sector >= 5):
     if state[+12] == -1 (initial):
       parse header:
         type   = data[0]
         val1   = BE32 of data[1..4]
         val2   = BE32 of data[5..8]    ; stored but never read by any handler
       state[+12] = val1
       if type == 2:
         call type2_handler(val1)
         → validates length ≤ 0x18000, 4-byte aligned
         → flash_unlock + flash_erase 48 pages at 0x08008000
       if type == 0:
         call type0_handler
         → SCB->AIRCR = SYSRESETREQ → chip reset
     else if state.mode == 2 (= WRITE in progress):
       chunk_write(data, length=512)
       → for each 4-byte word: HAL_FLASH_Program(WORD, 0x08008000+offset, word)
       → on length reached: state.mode = 3 (DONE)
   ```

   No CRC, no magic. The "checksum slot" (bytes 5-8 of the header) is stored but unread.

7. **Build the upload file:**

   ```python
   import struct
   header = bytearray(512)
   header[0]   = 0x02                                     # type 2 = BEGIN_UPDATE
   header[1:5] = struct.pack(">I", 0x18000)              # BE32 length = 96 KB
   header[5:9] = struct.pack(">I", 0)                    # unused
   payload = open("firmware_34.bin","rb").read()[0x8000:0x20000]  # app region
   with open("upload.bin","wb") as f:
       f.write(bytes(header) + payload)
   # Total: 98816 bytes
   ```

8. **Verify it works end-to-end** by building a *self-identifying* test pattern (each 4-byte word = BE32 of its destination flash address), uploading, then reading flash via SWD:

   ```
   Flash 0x08008000 → reads 0x08008000 (BE32) ✓
   Flash 0x0801FFFC → reads 0x0801FFFC (BE32) ✓
   ```

   Every single one of the 24,576 words matched.

9. **The reset trigger** — write a 1-byte file containing `0x00`. Bootloader sees type-0 → SYSRESETREQ → bar reboots into the freshly-uploaded firmware.

**Entry without firmware modification:** the bootloader reads PA1 (= IR receiver line) at `0x08003A6C`. If PA1 is LOW at that read, the bootloader skips the app-validity check and goes straight to MSC. PA1 idles HIGH but pulses LOW under a 38 kHz IR signal — **so holding any TV remote button at power-on triggers MSC mode**. No tools, no patches, no opening the case.

### Sidebar: the "0x30 fill" mystery

Early in MSC investigation we wrote a small test file to the MSC volume:

```bash
echo "test1234" > /media/.../Teufel\ CBO/small.txt
```

Read it back — 9 bytes of `'0'` (= 0x30 ASCII).

That was confusing. Did the bootloader transform our data? Was it a buffer initialization side effect? Was the FS corrupt?

Hours later, we found the `msc_read_backend` at `0x08000234`:

```
read(sector, dst, length):
  if sector < 5:
    memcpy(dst, FAT12_IMAGE_RAM + sector*512, length*512)
  else:
    memset(dst, 0x30, length*512)
```

That's where the `0x30` comes from. For sectors >= 5 (= the data area, where user files live), the bootloader doesn't actually store anything — read always returns ASCII `'0'` fill. **Writes** to those sectors go to the firmware-update state machine, not to any persistent file storage.

This explained:
- Why `version.txt` read OK (it's at cluster 2 = sector 4, < 5 → real RAM read)
- Why user-created files read as 9 (or 17 or whatever) ASCII zeros (= 0x30 fill, truncated to file length by FAT)
- Why directory entries DO persist across power-cycle (= sector 3, < 5 → real RAM, plus the bootloader writes the FAT12 RAM image back somewhere persistent... maybe)

**Lesson:** when read-back differs from write, the storage medium is doing something. Look for the actual READ implementation, not just the WRITE. The asymmetry is often the whole story.

### Sidebar: the broken HBP — when GDB lies

Late in Phase 7-8 we hit a really nasty bug: `hbreak` reported success in GDB ("Hardware assisted breakpoint 1 at 0x08002CA6") but the breakpoint never fired. We spent hours setting BPs at functions we knew were called — `main` entry, `osKernelGetTickCount` (called 1000× per second), the bootloader main. Nothing fired.

Diagnostic that pinned it: read the FPB (Flash Patch & Breakpoint) hardware registers directly:

```bash
gdb-multiarch -batch -ex 'target extended-remote :3333' \
  -ex 'monitor halt' \
  -ex 'printf "FP_CTRL  = 0x%08x  (bit 0 = enable)\n", *(unsigned int*)0xE0002000' \
  -ex 'printf "FP_COMP0 = 0x%08x  (address + enable bit)\n", *(unsigned int*)0xE0002008' \
  -ex 'monitor resume' -ex 'detach' -ex 'quit'
```

`FP_CTRL = 0x41` (bit 0 = enabled, bits 7:4 = 4 comparators available) but `FP_COMP0 = 0` — GDB had told us the BP was set, but **OpenOCD never actually wrote the comparator register**. Some bug in the GDB ↔ OpenOCD FPB handoff.

Workaround: use OpenOCD's TCL command interface directly, bypassing GDB:

```bash
( echo "halt"
  echo "bp 0x08002CA6 2 hw"     ; OpenOCD-native HBP install
  echo "bp"                       ; list to confirm
  echo "resume"
  echo "exit"
) | nc -q 1 127.0.0.1 4444
```

This wrote `FP_COMP0` directly. Breakpoints fired immediately.

**Lesson:** when a debugger feature fails silently, **read the hardware state directly** to confirm. Don't trust the debugger's bookkeeping if behavior contradicts it. And: have a fallback (TCL, telltale RAM writes, manual register pokes) for when the primary path breaks.

### Sidebar: the one-shot self-destruct (fw_38's design flaw)

fw_38 was our experimental "force MSC mode" build. It had three patches:
- 1-byte at `0x03A89`: flip `bne` to unconditional `b` (forces "skip app, enter MSC" path in bootloader)
- 4 bytes at `0x03AD0`: BL retarget pointing to a shim in the app region
- 32-byte shim at `0x0801E880`: sets USBEN before calling the original USB init

Live-tested: MSC enumerated, full 96 KB upload validated. 

Then we triggered the type-0 reset and the bar HardFaulted. Why?

**The shim was in the APP region.** The type-2 handler erases the entire 96 KB app region (`0x08008000-0x0801FFFF`) before programming new content. Our shim at `0x0801E880` is INSIDE that region. When the upload starts, the erase wipes the shim.

After the upload + reset:
- Bootloader runs main
- The `bne→b` patch (in BOOTLOADER region, survived) forces "skip app"
- `bl 0x08003AD0` → patched BL → jumps to `0x0801E880` 
- `0x0801E880` now contains `0xFFFFFFFF` (or whatever app content was uploaded, not our shim)
- CPU executes `0xFFFF` → UNDEFINED → HardFault

The bar is bricked until SWD-reflashed. **One-shot self-destruct** by design.

The fix would be `fw_39` with the shim in the bootloader region (`0x080040D8` has 12 KB of free space) — but we didn't bother building it because we'd already validated the protocol AND we'd discovered the PA1-LOW gesture which needs no firmware modification at all.

**Lesson:** when you place patch shims, **map their flash regions vs what your own code might erase**. The MSC-update path erases its own app region — any patches that need to survive across an MSC update need to live in the immutable bootloader region.

---

## Anatomy of a dead end

We hit ~12 dead ends documented above. Two patterns recurred:

**Pattern 1: the convincing-but-wrong story.** Strong static evidence supports a hypothesis. You build a patch around the hypothesis. The patch doesn't deliver the expected behavior — instead it does *something else* that's also evidence for the hypothesis (we set USBEN! we got a state machine progressing!). You spend another day chasing why the "next step" of the hypothesis isn't happening, when the hypothesis itself is wrong. Examples in this journey:
- fw_36 (PA0+EEPROM bypass — turned out to be CEC, not MSC)
- The PA15 mux-SEL hypothesis (PCB trace observation that didn't match)
- The "single state byte = the answer" fix in Phase 2

**Pattern 2: the sequential confound.** You patch-flash-reboot-test in sequence. Each test starts from a fresh state. By the third or fourth test, you've cumulatively patched multiple things and can't isolate which one is doing the work. Example:
- fw_06 → fw_07 → fw_08 → fw_22 (NOP'd three pins one at a time, ended up with all three NOP'd, no idea which one mattered)

**Defense against both:**
- Whenever possible, **manipulate one variable at a time via live GDB**, not via patch-flash-reboot.
- Whenever a model predicts X and observes "X happened but the further consequences didn't" — re-check the prediction. The model might be partially right (X did happen) but wrong about what X *means*.
- Listen for the user's pushback. "But pressing power IS turning off the bar" is more reliable than "but my disassembly says the dispatch goes to a no-op."

The dead ends in `gdb/scratch/` and `scratch/build_fw26-33.py` are kept on disk *deliberately*. Each one is a "I tried this and it didn't work for these specific reasons" datapoint. Future-you (or your colleagues) will be glad of them.

---

## What I learned (for next time)

**About working productively:**
- Keep a running notes file (we used `symbols.md`, `FIRMWARE_VARIANTS.md`, etc.) and update it as you go. Dates matter — "verified live 2026-06-08" is much more useful six months later than "verified live."
- Every patched binary should have a unique name. We used `firmware_NN_kebab-description.bin` and a `build_fwNN.py` script per variant, never editing in place. This made rollback trivial.
- **Don't share copyrighted firmware.** The `patcher/` directory holds scripts that take the user's own dump and produce the patched copy, so the patches themselves are shareable without redistributing Teufel's code.

**About debugging:**
- `ldr Rd, [pc, #imm]` literal loads tell you what addresses code is touching — easier to grep than disassembly.
- Hardware breakpoints aren't always reliable. Have a backup plan (telltale RAM writes, watchpoints, manual FPB pokes).
- Cortex-M0 has only `BL` as 32-bit Thumb-2; no `B.W`. Bit me twice.
- The reset behavior of SRAM is "undefined" but in practice **persists across warm resets** on STM32F0. Telltales survive `SYSRESETREQ`.

**About scope:**
- Pushback from the user (the *real* user, the one with the bar in their hands) is invaluable. "EEPROM holds CEC opcodes makes no sense" was right — and pushed us to reconsider an entire interpretation.
- The mux/T211 puzzle had three wrong hypotheses before we landed on "the bootloader is a separate world." Don't get attached to your model.
- A dead end is still data. Twenty-four `gdb/scratch/` files later, we know exactly what doesn't work.

---

## Cross-references

For the deep details of each topic:

- `MSC_PROTOCOL.md` — the firmware-upload protocol (the final story arc above)
- `CEC_PROTOCOL.md` — the bar's CEC subsystem (which we mistook for the MSC entry for two days)
- `USB_MODES.md` — preserved-as-was record of our false starts on the PA0+EEPROM hypothesis
- `FIRMWARE_VARIANTS.md` — every binary we built, with status (productive / dead-end)
- `symbols.md` — every function and RAM address we identified, with confidence levels
- `IR_CODES.md` — the complete remote-button → cmd_id mapping
- `dsp_protocol.md` — the DSP register map and per-mode preset table

And in code:
- `build_fw34.py` / `build_fw35.py` — productive firmware builders
- `build_msc_upload.py` — produce a MSC upload file from a 128 KB firmware image
- `patcher/build_fw*_from_dump.py` — shareable patcher scripts (no redistributable firmware)
- `gdb/scratch/` — every dead-end probe, in case the technique is useful for the next puzzle
