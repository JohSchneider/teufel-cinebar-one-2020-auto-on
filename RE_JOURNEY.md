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

---

## Phase 8 — full protocol RE: the USB-MSC firmware-upload

With the bootloader / application split clear, the picture of the bar's USB MSC mode snapped into focus. The bootloader has its own SCSI dispatcher, FAT12 emulator, and a hidden firmware-update protocol.

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
