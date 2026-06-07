set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== Bar state in RAM ===\n"
printf "  PC = 0x%08X\n", $pc
printf "  state[0] power      = %d  (1=stby, 2=active)\n", *(unsigned char*)0x200025DC
printf "  state[+1] volume    = %d  (0..60)\n", *(unsigned char*)0x200025DD
printf "  state[+3] source    = %d\n", *(unsigned char*)0x200025DF
printf "  state[+4] modeExt   = %d  (0=off, 1=on)\n", *(unsigned char*)0x200025E0
printf "  state[+6] bass      = %d  (signed -8..+8)\n", (signed char)*(unsigned char*)0x200025E2

printf "\n=== Live vEEPROM page 1 latest values ===\n"
printf "(reading first 0x130 bytes from 0x08007000)\n"
monitor resume
quit
