set confirm off
set pagination off
set remotetimeout 30
target extended-remote :3333
monitor halt
delete breakpoints

printf "\nBar state:\n"
printf "  PC = 0x%08X\n", $pc
printf "  state[0] = %d  (1=standby, 2=active)\n", *(unsigned char*)0x200025DC

# Check PA1 (IR input pin) GPIOA->IDR bit 1
# GPIOA_IDR = 0x48000010
printf "  GPIOA IDR = 0x%08X (PA1 = bit 1 = %d)\n", *(unsigned int*)0x48000010, (*(unsigned int*)0x48000010 >> 1) & 1

monitor resume
quit
