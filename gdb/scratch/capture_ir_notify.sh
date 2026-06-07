#!/usr/bin/env bash
# capture_ir_notify.sh — locate the IR decoder by catching the notify(channel=2)
# call chain when you press IR-power. Run locally (NOT via SSH) so halts are
# microseconds.
#
# Usage:
#   ./capture_ir_notify.sh [timeout_seconds]   (default 30)
#
# Pre-req: OpenOCD GDB server on localhost:3333, bar in fw_22 or fw_23.
#
# What it does: arms a CONDITIONAL hardware breakpoint at notify() (0x0800BBDC)
# that fires only when r0==2 (i.e., notify for the power-button channel). Other
# notify calls (LED updates etc) halt the CPU briefly to check the condition
# but don't trigger any GDB processing — locally this overhead is small enough
# that the bar's IR decoder still works. When the r0==2 hit happens, the bp
# captures full state, self-deletes, and the bar runs normally.

set -e
duration=${1:-30}

GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
[ -z "$GDB" ] && { echo "Need gdb-multiarch or arm-none-eabi-gdb in PATH" >&2; exit 1; }

CAPTURE=$(mktemp /tmp/cap_notify.XXXXXX)
CLEANUP=$(mktemp /tmp/cleanup.XXXXXX)

cat > "$CAPTURE" <<'EOF'
set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints
break *0x0800BBDC if $r0 == 2
commands
silent
printf "\n========== IR-POWER notify CAPTURED ==========\n"
printf "  channel = %d\n", $r0
printf "  value   = 0x%08X (%d)\n", $r1, $r1
printf "  lr (caller return) = 0x%08X\n", $lr
printf "  sp = 0x%08X\n", $sp
printf "\n  Caller disasm (lr-48 .. lr):\n"
x/12i $lr-48
printf "\n  Stack (sp .. sp+63):\n"
x/16wx $sp
printf "\n  Deleting bp, continuing...\n"
delete breakpoints
continue
end
monitor resume
continue
EOF

cat > "$CLEANUP" <<'EOF'
set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints
monitor resume
quit
EOF

trap '"$GDB" -batch -x "$CLEANUP" >/dev/null 2>&1 || true; rm -f "$CAPTURE" "$CLEANUP"' EXIT

echo "=== IR-power capture armed; window ${duration}s ==="
echo "↓↓↓  press IR-power ONCE during the window  ↓↓↓"
{ timeout --signal=INT --kill-after=10 "${duration}" "$GDB" -batch -x "$CAPTURE" 2>&1 || true; }
echo "=== Window closed. Cleaning up... ==="
