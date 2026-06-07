set confirm off
set pagination off
set remotetimeout 15
target extended-remote :3333
monitor halt

printf "\n=== Bar state ===\n"
printf "  PC = 0x%08X  state[0] = %d (need PC=0x08010AB6 idle, state=2 active)\n", $pc, *(unsigned char*)0x200025DC

printf "\n=== Log slot at 0x20003E00 ===\n"
printf "  channel byte = %d\n", *(unsigned char*)0x20003E00
printf "  value word   = 0x%08X\n", *(unsigned int*)0x20003E04

monitor resume
quit
