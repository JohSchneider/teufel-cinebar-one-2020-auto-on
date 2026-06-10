# Cinebar One (2020) — teardown & re-assembly walkthrough

Companion gallery for the [main README](../README.md). The photos are from my own teardown when I opened the bar to fix its dead PMIC and to do the firmware reverse-engineering. They're rough phone shots, not a service manual, but they're enough to show the order of operations if you're opening yours up.

If you only need the firmware mod and don't need to crack the case, the cleanest update path is the **USB-MSC firmware update** described in [`MSC_PROTOCOL.md`](../MSC_PROTOCOL.md) — that one needs no disassembly at all.

If you do need to get inside (dead PMIC, broken connector, curious teardown), here's the rough re-assembly sequence.

---

## 0. Identify which revision you have

Before anything else, confirm you have the **2020** model. The 2021 revision has a hardware "AUTO ON" switch on the back and looks similar but isn't pin-compatible:

| 2020 | 2021 |
|---|---|
| ![](cinebar-one-2020_connections.png) | ![](cinebar-one-2021_connections.png) |

See the main README for the differences and what each port does.

---

## 1. Removing the housing — screw locations

The case comes apart in **two stages**: first the outermost shell separates from the inner frame that holds the speakers, then a second pair of deeply-buried screws frees the PCB stack from that shell.

**Stage 1 — the first 9 screws** (`screw-locations_1.jpg`). These hold the outermost case onto the front frame. Once they're all out, the outer shell lifts off and exposes the speaker-holding frame and the rear PCB stack.

![](screw-locations_1.jpg)

**Stage 2 — two deeply-buried screws** (`screw-locations_2.jpg`). These sit recessed inside the case and are *not* visible until the first stage is done. They anchor the PCB stack (STM32 baseboard + DSP daughter board) to the outer shell. With these out, the PCB stack lifts free.

![](screw-locations_2.jpg)

Keep the two sets sorted — they aren't all the same length, and the deep pair in particular is easy to lose track of.

---

## 2. What you should have once everything's apart

This is roughly the state after a full disassembly. Lots of small screws — keep them sorted (the bar uses at least three different lengths). The two PCBs (baseboard with STM32 + daughter board with DSP) come out as a pair, connected by their two pin sockets.

![](re-assembly_IMG_4274.jpg)

---

## 3. The two PCBs and the front PCB

The big rear PCB pair (STM32 baseboard + DSP daughter board) sits in the back half of the housing. There's also a small **front PCB** that carries the status LED and the IR receiver, connected to the baseboard via a 6-pin ribbon. The two are independent and you can lift the front PCB out separately.

![](re-assembly_IMG_4277.jpg)

(The left object in the photo is the front PCB + its plastic mount; the right object is the rear PCB pair. The white ribbon between them is the 6-pin cable mapped in [`symbols.md`](../symbols.md) → "Front-panel ribbon cable".)

---

## 4. Empty housings on the bench

Left: the front of the enclosure with the speaker chambers, drivers held in place. Right: the bottom of the chassis (where the rear PCBs install). The center photo shows the rear PCB assembly being slid in.

![](re-assembly_IMG_4282.jpg)

If you're doing the PMIC bypass, this is the moment to do it — easier to solder before everything goes back together.

---

## 5. PCBs back in, foam damping on top

The acoustic foam isn't optional: the bar uses it to keep the various speaker chambers acoustically separated. Re-fit it to roughly the contours it came out of — the impressions in the foam from its first install are a good guide.

| Foam over the PCBs | Detail of the central capacitor cluster |
|---|---|
| ![](re-assembly_IMG_4285.jpg) | ![](re-assembly_IMG_4288.jpg) |

The capacitor cluster in the right-hand photo is the audio rail / amplifier section on the daughter board — the 470 µF / 25 V parts visible there are the ones that the dead-PMIC replacement bodge feeds.

---

## 6. Internal view from the back, before closing up

Half-closed angle showing how the foam and PCBs sit relative to the speaker chambers. Verify nothing's pinched and that the ribbon cable to the front PCB still has slack to route freely.

![](re-assembly_IMG_4284.jpg)

---

## 7. Driver side — what's actually doing the sound

Four equally-sized full-range drivers across the front, all on red-surround mounts. The drivers stay seated in the front frame through the whole re-assembly — you only see them while the outer shell is still off.

| Top-down through the open back | Side / end view | Front view through the frame |
|---|---|---|
| ![](re-assembly_IMG_4290.jpg) | ![](re-assembly_IMG_4292.jpg) | ![](re-assembly_IMG_4293.jpg) |

---

## 8. Perforated-metal grille back on

The grille is a single perforated-metal wrap-around piece. It clips around the front frame; the corner detail below shows the inside of the wrap meeting the bar's edge.

| Corner of the grille | Bar with grille fully on |
|---|---|
| ![](re-assembly_IMG_4276.jpg) | ![](re-assembly_IMG_4275.jpg) |

---

## Annotated baseboard reference

For RE work specifically (rather than re-assembly), the annotated component map is the more useful thing to look at:

![](base-board_annotated.svg)

See the main README's "Hardware" section for what each annotated block does electrically.
