#!/usr/bin/env bash
# simulate_ir.sh — simulate any IR-remote button via notify(13, packed).
#
# Complete mapping recovered from the IR-decoder lookup table at 0x080116A0
# and verified end-to-end for IR-power via fw_29's notify-trampoline.
#
# All IR buttons dispatch through cmd_id=13 with a packed value:
#     packed = (press_tag << 8) | button_id
# press_tag = 2 for a normal single press; 4/6/8/11/12 for various hold states.
#
# Usage:
#   ./simulate_ir.sh <button>          -- e.g. power, mute, volUp
#   ./simulate_ir.sh raw <cmd> <val>   -- arbitrary
#
# CAVEAT: cmd_id=13's handler at 0x0800C348 exits when source != 1. With the
# bar on source=2 (Toslink) the dispatched IR button is a no-op past the
# initial state check. To see effects of injected presses, switch the bar
# to source=1 first (mechanism not yet known via GDB).

set -e

# button_id table (matches the firmware's table at 0x080116A0)
declare -A BUTTON=(
    [power]=1     [mute]=2       [hdmiIn]=3     [btIn]=4
    [auxIn]=5     [optIn]=6      [bassUp]=7     [bassDown]=8
    [volUp]=9     [volDown]=10   [modeExtend]=11
    [modeMusic]=12 [modeMovie]=13 [modeVoice]=14
)

case "${1:-}" in
    raw)
        cmd="${2:?need cmd_id}"
        val="${3:-0}"
        desc="raw notify(cmd_id=$cmd, value=$val)"
        ;;
    "")
        cat <<EOF >&2
Usage: $0 <button>
       $0 raw <cmd_id> <value>

Buttons (id passed as value byte 0, tag=2 as byte 1):
EOF
        for name in power mute hdmiIn btIn auxIn optIn bassUp bassDown \
                   volUp volDown modeExtend modeMusic modeMovie modeVoice; do
            printf "  %-12s  notify(13, 0x02%02X)\n" "$name" "${BUTTON[$name]}" >&2
        done
        echo "" >&2
        echo "Or: $0 raw 13 0x0201  (= power, explicit)" >&2
        exit 1
        ;;
    *)
        name="$1"
        id="${BUTTON[$name]:-}"
        if [ -z "$id" ]; then
            echo "Unknown button: $name. Try one of: ${!BUTTON[*]}" >&2
            exit 1
        fi
        cmd=13
        # press_tag = 2 (normal single press), byte 0 = button_id
        val=$(( (2 << 8) | id ))
        desc=$(printf "%s  notify(13, 0x%04X)  (button_id=%d, tag=2)" "$name" "$val" "$id")
        ;;
esac

GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
[ -z "$GDB" ] && { echo "Need gdb-multiarch or arm-none-eabi-gdb in PATH" >&2; exit 1; }

NOTIFY_ADDR=0x0800BBDC

"$GDB" -batch -nx -q \
    -ex "set confirm off" -ex "set pagination off" \
    -ex "set remotetimeout 30" \
    -ex "target extended-remote :3333" \
    -ex "monitor halt" -ex "delete breakpoints" \
    -ex 'set $sr0  = $r0' \
    -ex 'set $sr1  = $r1' \
    -ex 'set $sr2  = $r2' \
    -ex 'set $sr3  = $r3' \
    -ex 'set $sr12 = $r12' \
    -ex 'set $slr  = $lr' \
    -ex 'set $spc  = $pc' \
    -ex 'set *(unsigned short*)0x20002000 = 0xBE00' \
    -ex "set \$r0 = $cmd" \
    -ex "set \$r1 = $val" \
    -ex 'set $lr = 0x20002001' \
    -ex "set \$pc = $NOTIFY_ADDR" \
    -ex 'continue' \
    -ex 'set $r0  = $sr0' \
    -ex 'set $r1  = $sr1' \
    -ex 'set $r2  = $sr2' \
    -ex 'set $r3  = $sr3' \
    -ex 'set $r12 = $sr12' \
    -ex 'set $lr  = $slr' \
    -ex 'set $pc  = $spc' \
    -ex 'monitor resume' \
    -ex 'quit' >/dev/null 2>&1

echo "→ $desc"
