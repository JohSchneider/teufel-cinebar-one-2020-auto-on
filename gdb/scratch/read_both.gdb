set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== RAM state ===\n"
printf "  power      = %d  (1=stby, 2=active)\n", *(unsigned char*)0x200025DC
printf "  volume     = %d  / 60\n", *(unsigned char*)0x200025DD
printf "  state[+2]  = %d\n", *(unsigned char*)0x200025DE
printf "  source     = %d\n", *(unsigned char*)0x200025DF
printf "  modeExt    = %d  (0=off, 1=on)\n", *(unsigned char*)0x200025E0
printf "  state[+5]  = %d\n", *(unsigned char*)0x200025E1
printf "  bass       = %d  (signed -8..+8)\n", (signed char)*(unsigned char*)0x200025E2
printf "  state[+7]  = %d\n", *(unsigned char*)0x200025E3

dump binary memory /tmp/firmware/veeprom_live3.bin 0x08007000 0x08007800
monitor resume
quit
