set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "PC = 0x%08X  state[0] = %d\n", $pc, *(unsigned char*)0x200025DC
printf "(want PC near 0x08010AB6 idle; bad if 0x0800F15X HardFault)\n"
monitor resume
quit
