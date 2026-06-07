#!/usr/bin/env bash
# status.sh — read the bar's live RAM state + vEEPROM via OpenOCD/GDB.
#
# Prereqs:
#   - OpenOCD running with GDB server on localhost:3333
#   - gdb-multiarch or arm-none-eabi-gdb in PATH
#   - Python 3
#
# Usage:
#   ./status.sh           -- print RAM state + vEEPROM latest-per-ID
#   ./status.sh -v        -- also show the last 8 vEEPROM writes (change log)
#   ./status.sh --raw     -- raw hex dump of the active page

set -e

verbose=0
raw=0
case "${1:-}" in
    -v|--verbose) verbose=1 ;;
    --raw) raw=1 ;;
esac

GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
[ -z "$GDB" ] && { echo "Need gdb-multiarch or arm-none-eabi-gdb in PATH" >&2; exit 1; }

DUMP=/tmp/firmware_status_veeprom.bin

# --- Halt, read RAM, dump vEEPROM, resume ---
"$GDB" -batch -nx -q \
    -ex "set confirm off" -ex "set pagination off" \
    -ex "set remotetimeout 15" \
    -ex "target extended-remote :3333" \
    -ex "monitor halt" \
    -ex 'printf "__RAM__\n"' \
    -ex 'printf "pc=0x%08X\n", $pc' \
    -ex 'printf "power=%d\n", *(unsigned char*)0x200025DC' \
    -ex 'printf "volume=%d\n", *(unsigned char*)0x200025DD' \
    -ex 'printf "state2=%d\n", *(unsigned char*)0x200025DE' \
    -ex 'printf "source=%d\n", *(unsigned char*)0x200025DF' \
    -ex 'printf "modeExt=%d\n", *(unsigned char*)0x200025E0' \
    -ex 'printf "state5=%d\n", *(unsigned char*)0x200025E1' \
    -ex 'printf "bass=%d\n", (signed char)*(unsigned char*)0x200025E2' \
    -ex 'printf "state7=%d\n", *(unsigned char*)0x200025E3' \
    -ex "dump binary memory $DUMP 0x08007000 0x08007800" \
    -ex "monitor resume" \
    -ex 'quit' 2>/dev/null | tee /tmp/firmware_status_ram.txt > /dev/null

# Parse the RAM values from the GDB output
get() { grep "^$1=" /tmp/firmware_status_ram.txt | head -1 | cut -d= -f2; }
PC=$(get pc)
POWER=$(get power)
VOL=$(get volume)
S2=$(get state2)
SRC=$(get source)
EXT=$(get modeExt)
S5=$(get state5)
BASS=$(get bass)
S7=$(get state7)

power_lbl="?"; [ "$POWER" = "1" ] && power_lbl="standby"; [ "$POWER" = "2" ] && power_lbl="active"
ext_lbl="?"; [ "$EXT" = "0" ] && ext_lbl="off"; [ "$EXT" = "1" ] && ext_lbl="on"

# Format
cat <<EOF
─── RAM state ───────────────────────────────
  PC         $PC
  power      $POWER  ($power_lbl)
  volume     $VOL / 60
  source     $SRC
  modeExtend $EXT  ($ext_lbl)
  bass       $BASS  (signed -8..+8)
  state[+2]  $S2     state[+5]  $S5     state[+7]  $S7
EOF

# Decode vEEPROM via Python
python3 - "$DUMP" "$verbose" "$raw" <<'PY'
import sys, struct
data = open(sys.argv[1], 'rb').read()
verbose = sys.argv[2] == '1'
raw = sys.argv[3] == '1'

if raw:
    import subprocess
    print("\n─── vEEPROM raw hex (page 1 first 0x130 bytes) ─────")
    subprocess.run(["xxd", "-l", "0x130", sys.argv[1]])
    sys.exit(0)

fields = {0x1111:"power", 0x2222:"volume", 0x3333:"bass",
          0x4444:"modeExtend", 0x5555:"audio_mode", 0x6666:"?",
          0xFF00:"(meta sequence)", 0xFF01:"(meta)",
          0xFF02:"(meta)", 0xFF03:"(meta)"}

for page_idx, page_off in [(1, 0), (2, 0x400)]:
    latest = {}
    entries = []
    for off in range(4, 0x400, 4):
        val, id_ = struct.unpack_from("<HH", data, page_off + off)
        if id_ == 0xFFFF and val == 0xFFFF:
            free_at = off
            break
        entries.append((off, val, id_))
        latest[id_] = (val, off)
    else:
        free_at = 0x400

    if page_idx == 2 and not entries:
        print(f"\n─── vEEPROM page 2 (0x08007400) ───────────────────")
        print(f"  blank (no rotation yet)")
        continue

    print(f"\n─── vEEPROM page {page_idx} (0x0800{0x7000+page_off:04X}) ────────────")
    print(f"  {len(entries)} entries, next free @ +0x{free_at:03X}")
    if verbose:
        print(f"  Last 8 writes:")
        for off, val, id_ in entries[-8:]:
            name = fields.get(id_, "")
            print(f"    @+0x{off:03X}  val={val:>5}  id=0x{id_:04X}  {name}")
    print(f"  Latest per ID:")
    for id_ in [0x1111, 0x2222, 0x3333, 0x4444, 0x5555, 0x6666]:
        if id_ in latest:
            val, off = latest[id_]
            name = fields.get(id_, "?")
            mark = ""
            # cross-check vs RAM where mapping is known
            print(f"    0x{id_:04X} {name:<10} = {val:<5} (@+0x{off:03X}){mark}")
PY
