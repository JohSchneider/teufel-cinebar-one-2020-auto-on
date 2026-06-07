#!/usr/bin/env bash
# read_ir_log.sh — dump the IR-log ring buffer captured by fw_24
#
# Usage: ./read_ir_log.sh
#   Halts the bar briefly, reads idx + all 64 entries from 0x20003C00,
#   pretty-prints non-empty entries, resumes the bar.
#
# fw_24 layout:
#   0x20003C00 : u32 idx (writes 0..63 then wraps)
#   0x20003C04 + i*8 : u32 channel, u32 lr  — for i = 0..63

set -e
GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
[ -z "$GDB" ] && { echo "Need gdb-multiarch or arm-none-eabi-gdb" >&2; exit 1; }

TMP=$(mktemp)
cat > "$TMP" <<'EOF'
set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt

printf "==== IR-log buffer dump ====\n"
printf "idx (raw) = %u\n", *(unsigned*)0x20003C00

# 64 entries, 8 bytes each = 128 words after the idx
# Print as channel + lr columns
set $i = 0
while $i < 64
  set $entry = (unsigned*)(0x20003C04 + $i * 8)
  set $ch  = $entry[0]
  set $lr  = $entry[1]
  if $ch != 0xffffffff
    printf "  [%2d]  channel=%-6u  lr=0x%08X\n", $i, $ch, $lr
  end
  set $i = $i + 1
end

printf "==== end ====\n"
monitor resume
quit
EOF

"$GDB" -batch -x "$TMP" 2>&1 | grep -v "^warning:\|^0x\|^\[" || true
rm -f "$TMP"
