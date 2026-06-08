set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt
printf "\n=== Bar state ===\n"
printf "  state[0] = %d  (1=stby, 2=active)\n", *(unsigned char*)0x200025DC

printf "\n=== Standby GPIO outputs ===\n"
printf "  PA2 (Toslink rail) = %d  (★ MUST stay 1)\n", ((*(unsigned int*)0x48000014) >> 2) & 1
printf "  PB7 (DSP power?)   = %d  (★ should now be 0 in standby)\n", ((*(unsigned int*)0x48000414) >> 7) & 1
printf "  PC15 (aux/amp?)    = %d  (★ should now be 0 in standby)\n", ((*(unsigned int*)0x48000814) >> 15) & 1
printf "  PF0 (DSP reset)    = %d  (was 0 in fw_22 standby, expected unchanged)\n", (*(unsigned int*)0x48001414) & 1
monitor resume
quit
