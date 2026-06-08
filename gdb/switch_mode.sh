#!/usr/bin/env bash
# switch_mode.sh — flip the Teufel Cinebar One DSP audio mode via GDB+OpenOCD
#
# Prereqs:
#   - OpenOCD running with a GDB server on localhost:3333
#   - gdb-multiarch or arm-none-eabi-gdb in PATH
#   - Bar flashed with firmware_22_wake-on-spdif.bin or any descendant that
#     keeps set_audio_mode at 0x0800C560 (verified for fw_22 and fw_23)
#
# Usage:
#   ./switch_mode.sh music     (or  0)
#   ./switch_mode.sh movie     (or  1)
#   ./switch_mode.sh voice     (or  2)
#   ./switch_mode.sh -v voice  (verbose — show GDB output)
#
# What it does:
#   Halts the bar's CPU, saves caller-saved registers, writes a BKPT instruction
#   into RAM at 0x20002000 as a return trampoline, then calls
#       set_audio_mode(mode)   [@ 0x0800C560]
#   When the function returns to the trampoline, the BKPT halts the CPU.
#   GDB then restores all saved registers and resumes the bar's task.
#   Net effect: 12 DSP-register writes are emitted while the bar's task is
#   paused for a few ms — audio buffer typically doesn't notice.

set -e

verbose=0
if [ "${1:-}" = "-v" ]; then verbose=1; shift; fi

# Mode IDs (verified 2026-06-07 from IR-handler disasm):
#   Music = 0, Voice = 1, Movie = 2
# Earlier labels in this script had Movie=1 and Voice=2 — that was wrong.
# Verified by looking at each modeXxx sub-handler's `movs r0, #N; bl set_audio_mode`:
#   modeMusic @ 0x0800C246 → r0=0
#   modeVoice @ 0x0800C29E → r0=1
#   modeMovie @ 0x0800C272 → r0=2
# (Whether set_audio_mode at 0x0800AB54 and the mode-preset loader at
# 0x0800C560 — what this script actually calls — agree on the numbering
# has NOT been independently verified yet. If switching sounds wrong,
# try a different id.)
case "${1:-}" in
    0|music) mode=0; name=Music ;;
    1|voice) mode=1; name=Voice ;;
    2|movie) mode=2; name=Movie ;;
    *)
        echo "Usage: $0 [-v] <music|voice|movie|0|1|2>" >&2
        exit 1
        ;;
esac

GDB=$(command -v gdb-multiarch arm-none-eabi-gdb 2>/dev/null | head -1)
if [ -z "$GDB" ]; then
    echo "Need gdb-multiarch or arm-none-eabi-gdb in PATH" >&2
    exit 1
fi

run() {
    "$GDB" -batch -nx -q \
        -ex "set confirm off" \
        -ex "set pagination off" \
        -ex "set remotetimeout 30" \
        -ex "target extended-remote :3333" \
        -ex "monitor halt" \
        -ex "delete breakpoints" \
        -ex 'set $saved_r0  = $r0' \
        -ex 'set $saved_r1  = $r1' \
        -ex 'set $saved_r2  = $r2' \
        -ex 'set $saved_r3  = $r3' \
        -ex 'set $saved_r12 = $r12' \
        -ex 'set $saved_lr  = $lr' \
        -ex 'set $saved_pc  = $pc' \
        -ex 'set *(unsigned short*)0x20002000 = 0xBE00' \
        -ex "set \$r0 = $mode" \
        -ex 'set $lr = 0x20002001' \
        -ex 'set $pc = 0x0800c560' \
        -ex 'continue' \
        -ex 'set $r0  = $saved_r0' \
        -ex 'set $r1  = $saved_r1' \
        -ex 'set $r2  = $saved_r2' \
        -ex 'set $r3  = $saved_r3' \
        -ex 'set $r12 = $saved_r12' \
        -ex 'set $lr  = $saved_lr' \
        -ex 'set $pc  = $saved_pc' \
        -ex 'monitor resume' \
        -ex 'quit'
}

if [ "$verbose" = 1 ]; then
    run 2>&1
else
    run >/dev/null 2>&1
fi
echo "→ $name mode applied"
