#!/usr/bin/env bash
# simulate_ir.sh — simulate an IR-remote button press by calling notify(cmd_id, value)
# directly from GDB, bypassing the IR decoder entirely.
#
# Works against any fw_22+ binary (notify() is unchanged across them, and we use
# the same BKPT-trampoline trick as switch_mode.sh — no firmware modification needed).
#
# The bar's command-dispatch task picks up the message naturally and routes it through
# the same case handlers an IR press would. Listen to the bar's response to confirm
# the cmd_id ↔ button mapping in IR_CODES.md.
#
# Usage:
#   ./simulate_ir.sh <button>
#   ./simulate_ir.sh raw <cmd_id> [value]    -- send notify(cmd_id, value) directly
#
# Buttons (confidence ★ = strong inference / ★★★ = verified live):
#   power                              cmd_id=2,  value=0      ★★★ verified
#   src_opt | src_aux | src_hdmi | src_bt   cmd_id=4, value=0/1/2/3   ★★
#   mode_music | mode_movie | mode_voice    cmd_id=1, value=1/2/3     ★
#   vol_up | vol_down                  cmd_id=11/12, value=1    ★ (uncertain)
#   bass_up | bass_down                cmd_id=13/14, value=1    ★ (uncertain)

set -e

case "${1:-}" in
    power)        cmd=2;  val=0;  desc="Power toggle  (★★★ verified)" ;;
    # 4 sources — LED color confirms (Opt=Purple, AUX=Green, HDMI=White, BT=Blue)
    src_opt)      cmd=4;  val=0;  desc="Source Optical → expect Purple LED" ;;
    src_aux)      cmd=4;  val=1;  desc="Source AUX     → expect Green LED" ;;
    src_hdmi)     cmd=4;  val=2;  desc="Source HDMI    → expect White LED" ;;
    src_bt)       cmd=4;  val=3;  desc="Source BT      → expect Blue LED" ;;
    # 4 modes (the 4-way sub-dispatch in case 1)
    mode_music)   cmd=1;  val=1;  desc="Mode Music     (★★ inferred)" ;;
    mode_movie)   cmd=1;  val=2;  desc="Mode Movie     (★★ inferred)" ;;
    mode_voice)   cmd=1;  val=3;  desc="Mode Voice     (★★ inferred)" ;;
    mode_extend)  cmd=1;  val=4;  desc="Mode Extend (stereo widening) (★★ inferred — NEW)" ;;
    # Uncertain — try and listen
    mute)         cmd=0;  val=0;  desc="Mute? (★ candidate — cmd_id 0 also possible)" ;;
    vol_up)       cmd=11; val=1;  desc="Vol+  (★  guess — listen)" ;;
    vol_down)     cmd=12; val=1;  desc="Vol-  (★  guess)" ;;
    bass_up)      cmd=13; val=1;  desc="Bass+ (★  guess)" ;;
    bass_down)    cmd=14; val=1;  desc="Bass- (★  guess)" ;;
    raw)
        cmd="${2:?need cmd_id}"
        val="${3:-0}"
        desc="raw cmd_id=$cmd value=$val"
        ;;
    *)
        cat <<EOF >&2
Usage: $0 <button>

Verified / strong-inference:
  power                                       -- toggle bar standby/active
  src_opt | src_aux | src_hdmi | src_bt     -- pick source (LED color confirms!)
  mode_music | mode_movie | mode_voice | mode_extend  -- pick audio mode (4 modes)

Guesswork (listen / observe to confirm):
  mute
  vol_up | vol_down
  bass_up | bass_down

Experimental:
  raw <cmd_id> [value]                        -- post notify(cmd_id, value) directly

Examples:
  $0 power                                     -- toggle (verified)
  $0 src_hdmi                                  -- LED should turn White
  $0 src_aux                                   -- LED should turn Green
  $0 mode_extend                               -- stereo widening (newly added)
  $0 raw 10 1                                  -- try cmd_id 10 with value 1
  $0 raw 3 0                                   -- try unmapped cmd_id 3
EOF
        exit 1
        ;;
esac

GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
[ -z "$GDB" ] && { echo "Need gdb-multiarch or arm-none-eabi-gdb in PATH" >&2; exit 1; }

# notify(channel=r0, value=r1) — entry at 0x0800BBDC in fw_22+ binaries.
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
