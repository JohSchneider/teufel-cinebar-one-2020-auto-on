set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\n=== Bar state right now ===\n"
printf "PC = 0x%08X  (0x08010ab6 = idle loop, 0x0800f15c-area = HardFault)\n", $pc
printf "state[0] = %d\n", *(unsigned char*)0x200025DC

# If HardFaulted, reset.
# We'll check PC and use shell echo to indicate.
printf "\nIf PC is in 0x0800F15X (HardFault), please POWER-CYCLE the bar (unplug AC, replug).\n"
printf "If PC is in 0x08010AB6 (idle), bar is alive.\n"

monitor resume
quit
