# Teufel Cinebar One — HDMI-CEC subsystem

This document captures the CEC implementation in the STM32 firmware: thread structure, opcode dispatcher, message format, and how it relates to the PA0-LOW service mode.

## Architecture: two distinct CEC roles

The STM32 firmware contains TWO unrelated CEC code paths that share some structure but are activated differently:

1. **Normal-mode CEC handler** — a dedicated RTX thread spawned at boot, polling a "CEC RX" message queue every 50 ms and dispatching CEC opcodes. The CEC peripheral itself (`0x40007800`) is **not initialized** in normal mode — messages must arrive via a different path, most likely forwarded from the DSP daughter board (which has the physical HDMI-ARC connection) over I²C1.
2. **Service-mode CEC peripheral init** — `cec_peripheral_init @ 0x0800EE9C` brings the STM32's own CEC peripheral up. Called only from the PA0-LOW service-mode chain at `0x0800F132`. Activates CECEN, configures the peripheral, enables NVIC IRQ 30 (which currently points to `Default_Handler`, suggesting polled use).

Why two paths: normal user CEC (turn off TV → bar sleeps) routes through the DSP, where the HDMI receiver IC physically lives. The STM32's CEC peripheral is reserved for factory test mode, where a test station can talk to the STM32 directly.

## CEC handler thread (normal-mode)

Created at boot by `create_rtx_obj_2 @ 0x080102BC` via `osThreadNew(0x0800B7FD, NULL, NULL)`. The thread's body:

```
0x0800B7FC  CEC handler thread entry:
  bl  0x08010358   ; create CEC RX/TX message queues (one-shot)
loop:
  bl  0x0800EB04   ; CEC RX dispatcher — pops a message and acts on it
  bl  0x0800EDF0   ; CEC TX poller — sends pending outgoing messages
  movs r0, #50
  bl  osDelay      ; sleep 50 ms
  b   loop
```

So the thread runs in normal operation at ~20 Hz. If no message is in the RX queue, the dispatcher early-exits and the thread loops harmlessly.

### CEC RX/TX message queues

Created by `0x08010358`:

```
osMessageQueueNew(count=10, msg_size=18, attr=&CEC_RX_attr) → 0x2000251C
osMessageQueueNew(count=10, msg_size=18, attr=&CEC_TX_attr) → 0x20002520
```

| Field | Location | Notes |
|---|---|---|
| CEC RX queue handle | RAM `0x2000251C` | written by queue creator |
| CEC TX queue handle | RAM `0x20002520` | |
| CEC RX attr | flash `0x0801E478` | name only set ("CEC RX" at `0x0801E5E0`) |
| CEC TX attr | flash `0x0801E490` | name "CEC TX" at `0x0801E5E8` |

Each queue holds up to 10 messages of 18 bytes each.

## Message format (18 bytes per slot)

Reverse-engineered from the message constructors at `0x0800B810`, `0x0800B844`, `0x0800B87E`:

| Byte | Field | Notes |
|---|---|---|
| 0 | `(initiator << 4) \| follower` | combined CEC source/dest addrs |
| 1 | opcode | CEC opcode byte |
| 2..15 | parameters | opcode-specific payload |
| 16 | message-type tag | 1/2/3 — distinguishes which constructor built it |
| 17 | valid flag | 0 = empty / discard, non-zero = valid |

The RX dispatcher at `0x0800EB04` reads byte 17 first; if zero, it exits without dispatching. So the queue can hold valid + invalid messages and the consumer filters.

## CEC RX dispatcher — full opcode table

Function `0x0800EB04` dispatches on `r2 = buf[1]` (the opcode byte). Found 23 explicit comparison branches:

| Opcode | CEC name (spec) | Direction | Branch in disasm |
|--------|-----------------|-----------|------------------|
| `0x00` | (Feature Abort / broadcast?) | various | `0x0800EBCC` |
| `0x36` | `<Standby>` | TV → audio | `0x0800EC3A` |
| `0x44` | `<User Control Pressed>` | TV → audio | `0x0800EC06` |
| `0x45` | `<User Control Released>` | TV → audio | `0x0800EC22` |
| `0x46` | `<Give OSD Name>` | TV → audio | `0x0800EBF0` |
| `0x70` | `<System Audio Mode Request>` | TV → amp | `0x0800EC08` |
| `0x71` | `<Give Audio Status>` | TV → amp | `0x0800EBDE` |
| `0x72` | `<Set System Audio Mode>` | TV → amp | (small branch) |
| `0x7D` | `<Give System Audio Mode Status>` | TV → amp | `0x0800EBFC` |
| `0x82` | `<Active Source>` | broadcast | `0x0800EB9E` |
| `0x83` | `<Give Physical Address>` | broadcast | `0x0800EBF6` |
| `0x84` | `<Report Physical Address>` | broadcast | `0x0800EC24` |
| `0x87` | `<Device Vendor ID>` | broadcast | `0x0800EBB4` |
| `0x8C` | `<Give Device Vendor ID>` | TV → device | (branch) |
| `0x8F` | `<Give Device Power Status>` | TV → device | (branch) |
| `0x90` | `<Report Power Status>` | various | (branch) |
| `0x9E` | `<CEC Version>` | response | (branch) |
| `0x9F` | `<Get CEC Version>` | TV → device | (branch) |
| `0xA0` | `<Vendor Command with ID>` | vendor-specific | `0x0800EC52` |
| `0xA4` | `<Set Audio Rate>` | TV → amp | (branch) |
| `0xC1` | `<Set OSD String>` | response (display on TV) | (branch) |
| `0xC2` | `<Set OSD Name>` | (probably Teufel-specific) | (branch) |
| `0xC3` | `<Routing Change>` | broadcast (HDMI source change) | (branch) |
| `0xC4` | `<Routing Information>` | broadcast | (branch) |

This is a near-complete consumer-CEC implementation: standby, remote-control passthrough, OSD name reporting, audio mode negotiation, source routing, vendor commands.

## Message constructors

| Address | Constructs message with opcode | Used for |
|---|---|---|
| `0x0800B810` | `0x9E` `<CEC Version>` with param `0x05` (= CEC v1.4) | response to `<Get CEC Version>` |
| `0x0800B844` | `0x87` `<Device Vendor ID>` with 24-bit vendor ID | response to `<Give Device Vendor ID>` |
| `0x0800B87E` | `0x00` (broadcast/feature abort) with params | various |

All three call `0x0800EDC4` which forwards the message to the I²C or CEC transport (via mutex'd HAL call).

## CEC peripheral init (service-mode only)

`cec_peripheral_init @ 0x0800EE9C`:

| Step | Address | Action |
|---|---|---|
| 1 | `0x0800EEA0+` | Enable GPIOA clock (RCC_AHBENR bit 17) |
| 2 | `0x0800EEB4+` | `HAL_GPIO_Init(GPIOA, pin=PA5, mode=AF_PP, AF=1, speed=VeryHigh)` |
| 3 | `0x0800EED0+` | `RCC_APB1ENR \|= (1 << 30)` (CECEN) via `lsls r0, r4, #18` where `r4=0x40021000` → `0x40000000` exactly |
| 4 | `0x0800EEDE+` | Toggle `RCC_APB1RSTR` bit 30 — CEC peripheral reset |
| 5 | `0x0800EEEA+` | Initialize CEC HandleTypeDef at `0x200026F8`: `[+0]=0x40007800` (CEC base), `[+4]=0` (own addr?), `[+8]=8`, `[+12]=16`, `[+36]=15` (broadcast LA?), `[+40]=state+0x88` (RX buffer) |
| 6 | `0x0800EF0E` | `HAL_CEC_helper_1(handle)` @ `0x0800D064` |
| 7 | `0x0800EF14` | `HAL_CEC_helper_2(handle)` @ `0x0800D1EC` |
| 8 | `0x0800EF1E` | `NVIC_SetPriority(IRQ_CEC_CAN=30, 1)` |
| 9 | `0x0800EF24` | `NVIC_EnableIRQ(IRQ_CEC_CAN=30)` |

**Caveat**: the static vector table slot for IRQ 30 points to `Default_Handler` (the trap loop), so any actual CEC interrupt would HardFault the bar. Either the peripheral is configured to never generate interrupts (CEC_CFGR2 interrupt enables stay clear), or `SCB->VTOR` is reassigned at runtime to a relocated table that has a real handler.

## EEPROM record-dispatch format

Reverse-engineered from the handshake's validation walk at `0x0800ED58-0x0800ED7C`. The EEPROM at I²C2 address `0x50` is expected to return a buffer with this layout:

```
+0x00 :  0x02              ← magic byte 1
+0x01 :  0x03              ← magic byte 2
+0x02 :  count_byte         ← must be non-zero AND not 4
+0x03 :  (padding/unused)
+0x04 :  record 0 starts:
         [byte 0] = type[7:5] | length[4:0]  (3-bit type + 5-bit length)
         [byte 1 .. byte length] = record data (up to 31 bytes)
+0x04+L0+1 : record 1 starts (same format)
   ...
end-of-walk : either `type == 3` matched, or position > 0x80 + count_byte
```

The walk algorithm:

```c
int r1 = 4;
int limit = buf[2] + 0x80;     // upper-bound check
while (true) {
    uint8_t b = buf[r1];
    int type = b >> 5;           // top 3 bits
    int length = b & 0x1F;       // bottom 5 bits
    if (type == 3) break;        // found target record
    if (r1 > limit) break;       // walked off the end
    r1 += length + 1;
}
// SUCCESS path:
output_halfword = (buf[r1 + 5] << 8) | buf[r1 + 4];
output_halfword = rev16(output_halfword);  // byte-swap
*caller_ptr = output_halfword;
return 0;
```

So the firmware extracts a 16-bit value from data bytes 4-5 of the type-3 record. Given the CEC context, **best guess**: this is the **CEC Physical Address (PA)**, a 16-bit value of the form `0xXXXX` describing where the bar lives on the HDMI tree (e.g., `0x1000` = HDMI input 1, port 0).

Other record types (0/1/2/4+) are presumably:
- CEC Logical Address (1 byte)
- Vendor ID (3 bytes, used in opcodes `0x87` `<Device Vendor ID>` and `0xA0` `<Vendor Command with ID>`)
- OSD Name (variable-length string)
- Other config

But this is conjecture — the actual encoding requires either a populated EEPROM (which doesn't exist on this bar) or a different Teufel product's firmware variant to cross-reference.

## Status summary

| Claim | Status |
|---|---|
| CEC handler thread is spawned at boot | ✓ static |
| Thread polls RX/TX queues every 50ms | ✓ static |
| Thread has 23 standard CEC opcodes wired | ✓ static (decoded above) |
| CEC peripheral is initialized only in service mode | ✓ static (only caller of `0x0800EE9C` is in service path) |
| In normal mode, CEC messages must arrive from somewhere | ✓ inferred — most likely DSP forwards them over I²C1 |
| CEC handler thread fires in normal operation | ✗ NOT YET verified live (SWD dropped during last test) |
| EEPROM record format guess (type/length) | ✓ static decoded; **content** is speculation |
| Type-3 record holds CEC Physical Address (16-bit) | ✗ guess, unverified |

## Open questions

- **Where do CEC RX messages come from in normal operation?** Most likely the DSP daughter board (which has HDMI-ARC physical access) decodes CEC and forwards messages to the STM32 over I²C1 — but the receive path on the STM32 side hasn't been traced. Worth instrumenting an `osMessageQueuePut(RX_handle, ...)` watchpoint live to see who pushes.
- **What does the type-3 EEPROM record actually contain?** Without a real EEPROM, can only guess. Cross-referencing other Teufel firmware revisions (if any leaked / dumped from a Cinebar Lux or similar) might disambiguate.
- **Does CEC actually work end-to-end if you connect the bar to a TV via HDMI-ARC?** Worth a bench test: plug TV HDMI-ARC into the bar, observe whether bar standby-triggers when TV turns off (would prove the CEC `<Standby>` path is functional).
