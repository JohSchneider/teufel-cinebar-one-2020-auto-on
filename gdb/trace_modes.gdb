set confirm off
set pagination off
set remotetimeout 120
target extended-remote localhost:3333
monitor halt
printf "=== Saving register state ===\n"
set $saved_r0  = $r0
set $saved_r1  = $r1
set $saved_r2  = $r2
set $saved_r3  = $r3
set $saved_r12 = $r12
set $saved_lr  = $lr
set $saved_pc  = $pc

# Trampoline
set *(unsigned short*)0x20002000 = 0xBE00

# Breakpoint that captures every write_dsp_register call
break *0x0800CAA0
commands 1
silent
printf "  reg=0x%02X (%3d)  val=0x%06X (%d)\n", $r0, $r0, $r1, $r1
continue
end

printf "\n=== MODE 0 (Music) — set_audio_mode(0) ===\n"
set $r0 = 0
set $lr = 0x20002001
set $pc = 0x0800c560
continue

printf "\n=== MODE 1 (Movie) — set_audio_mode(1) ===\n"
set $r0 = 1
set $lr = 0x20002001
set $pc = 0x0800c560
continue

printf "\n=== MODE 2 (Voice) — set_audio_mode(2) ===\n"
set $r0 = 2
set $lr = 0x20002001
set $pc = 0x0800c560
continue

printf "\n=== All three traces done. Bar left in Voice mode. ===\n"

delete breakpoints
set $r0  = $saved_r0
set $r1  = $saved_r1
set $r2  = $saved_r2
set $r3  = $saved_r3
set $r12 = $saved_r12
set $lr  = $saved_lr
set $pc  = $saved_pc
monitor resume
printf "Bar resumed with Voice mode applied.\n"
quit
